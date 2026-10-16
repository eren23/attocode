"""Bounded comparison of one leading-navigation-phrase candidate; no product default."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _expand_query,
)
from attocode_intel.focused_evidence import task_terms

from eval.quality import sources
from eval.quality.corpus import PACK, materialize
from eval.quality.runner import REPO, fingerprint

_PREFIX = re.compile(r"^\s*(?:please\s+)?(?:trace|explain|show)\s+how\s+", re.I)


def normalize(query, file_filter=""):
    """Strip one explicit navigation prefix, preserving the remaining search text."""
    if file_filter or re.search(r"\btests?\b", query, re.I):
        return query
    remainder = _PREFIX.sub("", query, count=1)
    return remainder if task_terms(remainder)[0] else query


def summarize(rows, arm):
    values = [row["arms"][arm] for row in rows]
    return {
        "questions": len(rows),
        "any5": sum(bool(set(v["files"][:5]) & set(r["labels"]))
                    for r, v in zip(rows, values, strict=True)),
        "all5": sum(set(r["labels"]) <= set(v["files"][:5])
                    for r, v in zip(rows, values, strict=True)),
        "pairs5": sum(len(set(v["files"][:5]) & set(r["labels"]))
                      for r, v in zip(rows, values, strict=True)),
        "all24": sum(set(r["labels"]) <= set(v["files"])
                     for r, v in zip(rows, values, strict=True)),
        "pairs24": sum(len(set(v["files"]) & set(r["labels"]))
                       for r, v in zip(rows, values, strict=True)),
        "mean_recall5": statistics.mean(len(set(v["files"][:5]) & set(r["labels"]))
                                        / len(r["labels"])
                                        for r, v in zip(rows, values, strict=True)),
        "p95_seconds": sorted(v["seconds"] for v in values)[math.ceil(.95 * len(values)) - 1],
    }


def gate(rows, expected_ids):
    if (len(rows) != 12 or len({r["id"] for r in rows}) != 12
            or {r["id"] for r in rows} != set(expected_ids)
            or any(not r["labels"] or set(r["arms"]) != {"baseline", "candidate"}
                   for r in rows)):
        raise ValueError("Requires all twelve distinct labeled questions and both arms")
    before, after = (summarize(rows, a) for a in ("baseline", "candidate"))
    improved, losses5, losses24 = [], [], []
    for row in rows:
        labels = set(row["labels"])
        b, c = (row["arms"][a]["files"] for a in ("baseline", "candidate"))
        if len(labels & set(c[:5])) > len(labels & set(b[:5])):
            improved.append(row)
        if labels & set(b[:5]) and not labels & set(c[:5]):
            losses5.append(row["id"])
        if not labels & set(b) <= set(c):
            losses24.append(row["id"])
    checks = {
        "net_pairs5_at_least_two": after["pairs5"] - before["pairs5"] >= 2,
        "improved_queries_at_least_two": len(improved) >= 2,
        "improved_repositories_at_least_two": len({r["pack"] for r in improved}) >= 2,
        "no_any5_loss": not losses5,
        "no_label24_loss": not losses24,
        "recall5_not_decreased": after["mean_recall5"] >= before["mean_recall5"],
        "latency": after["p95_seconds"] <= max(1.5 * before["p95_seconds"], .05),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "baseline": before, "candidate": after,
            "improved": [r["id"] for r in improved], "any5_losses": losses5,
            "label24_losses": losses24}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite observations")
    raw = args.questions.read_bytes()
    group = next(r for r in json.loads(raw)["repositories"] if r["pack"] == args.pack)
    if len(group["queries"]) != 4:
        parser.error("Exactly four questions per pack required")
    spec = next(r for r in yaml.safe_load(PACK.read_text())["repositories"] if r["id"] == args.pack)
    if spec["commit"] != group["commit"]:
        parser.error("Pinned source revision mismatch")
    os.environ["QUALITY_ALLOW_DOWNLOADS"] = "0"
    sources.MAX_PACK_BYTES = 64 * 1024**2
    identity = fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"])
    rows = []
    with tempfile.TemporaryDirectory(prefix="attocode-prefix-") as tmp:
        root, cache = Path(tmp) / "source", Path(tmp) / "cache"
        root.mkdir()
        cache.mkdir()
        tree = materialize(spec, root, cache)
        mgr = SemanticSearchManager(str(root))
        try:
            mgr.search("warmup", top_k=24)
            if not mgr.wait_for_body_index(timeout=90):
                raise TimeoutError("Index warmup incomplete")
            for number, question in enumerate(group["queries"]):
                labels = {e["file"] for e in question["evidence"]}
                for evidence in question["evidence"]:
                    path = (root / evidence["file"]).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError("Label escapes pack")
                    content = path.read_bytes()
                    if (hashlib.sha256(content).hexdigest() != evidence["source_sha256"]
                            or evidence["quote"] not in content.decode()):
                        raise ValueError("Pinned label source mismatch")
                arms, samples = {}, {"baseline": [], "candidate": []}
                for repeat in range(3):
                    order = ["baseline", "candidate"]
                    if (repeat + number) % 2:
                        order.reverse()
                    for arm in order:
                        trace = {}
                        started = time.perf_counter()
                        query = question["query"] if arm == "baseline" else normalize(question["query"])
                        expanded = _expand_query(query)
                        hits = mgr.search_candidates(expanded, top_k=24, trace=trace)
                        paths = list(dict.fromkeys(h.file_path for h in hits))
                        samples[arm].append(time.perf_counter() - started)
                        if arm in arms and arms[arm]["files"] != paths:
                            raise RuntimeError("Unstable warmed ordering")
                        arms[arm] = {"query": query, "expanded_query": expanded,
                                     "files": paths, "stages": trace}
                for arm, result in arms.items():
                    result.update(seconds=statistics.median(samples[arm]), samples_seconds=samples[arm])
                rows.append({"id": question["id"], "pack": args.pack,
                             "query": question["query"], "labels": sorted(labels), "arms": arms})
            index = mgr.candidate_diagnostics()
        finally:
            mgr.close()
    if identity != fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"]):
        raise RuntimeError("Implementation changed during comparison")
    args.output.write_text(json.dumps({"pack": args.pack, "commit": spec["commit"],
                                      "tree": tree, "index": index, "queries": rows,
                                      "questions_sha256": hashlib.sha256(raw).hexdigest(),
                                      "source_sha256": identity, "cleanup_verified": not Path(tmp).exists()},
                                     indent=2) + "\n")


if __name__ == "__main__":
    main()
