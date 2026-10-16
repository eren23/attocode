"""Compare one explicit-test partition on frozen cached-source questions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import yaml
from attocode_intel._internal.integrations.context import semantic_search
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _expand_query,
)
from attocode_intel.focused_evidence import terms
from attocode_intel.test_ranking import is_test_path

from eval.quality import sources
from eval.quality.corpus import PACK, materialize
from eval.quality.runner import REPO, fingerprint


def baseline_partition(query, candidates):
    """Frozen default before this trial: short test requests preserve pool order."""
    if re.search(r"\btests?\b", query, re.IGNORECASE) and len(terms(query)) <= 20:
        return candidates
    return sorted(candidates, key=lambda row: is_test_path(row.file_path))


def candidate_partition(query, candidates):
    if re.search(r"\btests?\b", query, re.IGNORECASE) and len(terms(query)) <= 20:
        return sorted(candidates, key=lambda row: not is_test_path(row.file_path))
    return baseline_partition(query, candidates)


def decide(rows, expected_ids):
    if (len(rows) != 12 or len({r["id"] for r in rows}) != 12
            or {r["id"] for r in rows} != set(expected_ids)
            or sum(r["intent"] == "test" for r in rows) != 8
            or sum(r["intent"] == "production" for r in rows) != 4
            or any(not r["labels"] or set(r["arms"]) != {"baseline", "candidate"} for r in rows)):
        raise ValueError("Requires all twelve labeled pairs, eight tests and four controls")
    improvements, losses = [], []
    counts = {a: {"test_hit5": 0, "all_hit24": 0} for a in ("baseline", "candidate")}
    for row in rows:
        labels = set(row["labels"])
        b, c = (row["arms"][a]["files"] for a in ("baseline", "candidate"))
        if row["intent"] == "test" and not labels & set(b[:5]) and labels & set(c[:5]):
            improvements.append(row)
        if (labels & set(b[:5]) and not labels & set(c[:5])) or not labels & set(b) <= set(c):
            losses.append(row["id"])
        for arm in counts:
            files = row["arms"][arm]["files"]
            counts[arm]["test_hit5"] += row["intent"] == "test" and bool(labels & set(files[:5]))
            counts[arm]["all_hit24"] += bool(labels & set(files))
    timings = {a: max(r["arms"][a]["seconds"] for r in rows) for a in counts}
    checks = {
        "two_net_test_hits5": counts["candidate"]["test_hit5"] - counts["baseline"]["test_hit5"] >= 2,
        "two_improved_repositories": len({r["pack"] for r in improvements}) >= 2,
        "no_individual_losses": not losses,
        "production_controls_identical": all(r["arms"]["baseline"]["results"] == r["arms"]["candidate"]["results"]
                                             for r in rows if r["intent"] == "production"),
        "generation_identical": all(r["arms"]["baseline"]["stages"][stage] == r["arms"]["candidate"]["stages"][stage]
                                    for r in rows for stage in ("keyword", "body", "file_bm25", "chunk_fused")),
        "latency": timings["candidate"] <= max(1.5 * timings["baseline"], .05),
    }
    return {"passed": all(checks.values()), "checks": checks, "counts": counts, "p95_seconds": timings,
            "improved": [r["id"] for r in improvements], "losses": losses}


def snapshot(hits):
    return [{"file": h.file_path, "name": h.name, "kind": h.chunk_type, "score": h.score,
             "start_line": h.start_line, "end_line": h.end_line} for h in hits]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pack", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite observations")
    raw = args.questions.read_bytes()
    group = next(r for r in json.loads(raw)["repositories"] if r["pack"] == args.pack)
    questions = group["queries"]
    if len(questions) != 3:
        parser.error("Three questions per pack required")
    spec = next(r for r in yaml.safe_load(PACK.read_text())["repositories"] if r["id"] == args.pack)
    if spec["commit"] != group["commit"]:
        parser.error("Pinned source mismatch")
    os.environ["QUALITY_ALLOW_DOWNLOADS"] = "0"
    sources.MAX_PACK_BYTES = 64 * 1024**2
    identity = fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"])
    rows = []
    with tempfile.TemporaryDirectory(prefix="attocode-test-intent-") as tmp:
        root, cache = Path(tmp) / "source", Path(tmp) / "cache"
        root.mkdir()
        cache.mkdir()
        tree = materialize(spec, root, cache)
        mgr = SemanticSearchManager(str(root))
        try:
            mgr.search("warmup", top_k=24)
            if not mgr.wait_for_body_index(timeout=90):
                raise TimeoutError("Index warmup incomplete")
            for number, question in enumerate(questions):
                labels = {e["file"] for e in question["evidence"]}
                if not labels:
                    raise ValueError("Question has no labels")
                for evidence in question["evidence"]:
                    path = (root / evidence["file"]).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError("Label escapes pack")
                    content = path.read_bytes()
                    if (hashlib.sha256(content).hexdigest() != evidence["source_sha256"]
                            or evidence["quote"] not in content.decode()):
                        raise ValueError("Label source mismatch")
                arms, samples = {}, {"baseline": [], "candidate": []}
                for repeat in range(3):
                    order = ["baseline", "candidate"]
                    if (number + repeat) % 2:
                        order.reverse()
                    for arm in order:
                        partition = baseline_partition if arm == "baseline" else candidate_partition
                        trace = {}
                        started = time.perf_counter()
                        with patch.object(semantic_search, "demote_tests", partition):
                            hits = mgr.search_candidates(_expand_query(question["query"]), top_k=24, trace=trace)
                        samples[arm].append(time.perf_counter() - started)
                        result = snapshot(hits)
                        if arm in arms and arms[arm]["results"] != result:
                            raise RuntimeError("Unstable warmed results")
                        arms[arm] = {"results": result, "files": list(dict.fromkeys(h.file_path for h in hits)),
                                     "stages": trace}
                for arm in arms:
                    arms[arm].update(seconds=statistics.median(samples[arm]), samples_seconds=samples[arm])
                rows.append({"id": question["id"], "pack": args.pack, "query": question["query"], "intent": question["intent"],
                             "labels": sorted(labels), "arms": arms})
            index = mgr.candidate_diagnostics()
        finally:
            mgr.close()
    if identity != fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"]):
        raise RuntimeError("Implementation changed during comparison")
    result = {"pack": args.pack, "commit": spec["commit"], "tree": tree, "index": index,
              "queries": rows, "questions_sha256": hashlib.sha256(raw).hexdigest(),
              "source_sha256": identity, "cleanup_verified": not Path(tmp).exists()}
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
