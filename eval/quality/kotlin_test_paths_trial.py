"""Replay the frozen Kotlin path-classification comparison on cached OkHttp."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import yaml
from attocode_intel import query_ranking
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _expand_query,
)
from attocode_intel.test_ranking import is_test_path

from eval.quality import sources
from eval.quality.corpus import PACK, materialize
from eval.quality.runner import REPO, fingerprint


def baseline_is_test_path(path):
    """Frozen classifier from main fab7fe20, before Kotlin source-set recognition."""
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (any(p in {"test", "tests", "__tests__", "spec", "specs"} for p in parts)
            or any(p.endswith((".Tests", ".Test", ".UnitTests", ".IntegrationTests")) for p in parts[:-1])
            or name.startswith("test_") or ".test." in name or ".spec." in name
            or name.endswith(("_test.py", "_test.go", "Test.java", "Test.kt", "Tests.java", "Tests.kt",
                              "Test.cs", "Tests.cs", "_test.c", "_test.cc", "_test.cpp", "_unittest.cc")))


def snapshot(hits):
    return [{"file": h.file_path, "name": h.name, "kind": h.chunk_type, "score": h.score,
             "start_line": h.start_line, "end_line": h.end_line} for h in hits]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite observations")
    raw = args.questions.read_bytes()
    group, = json.loads(raw)["repositories"]
    questions = group["queries"]
    if (len(questions) != 6 or len({q["id"] for q in questions}) != 6
            or Counter(q["intent"] for q in questions) != {"production": 4, "test": 2}):
        parser.error("Requires four production questions and two test controls")
    spec = next(r for r in yaml.safe_load(PACK.read_text())["repositories"] if r["id"] == "okhttp")
    if group["pack"] != "okhttp" or spec["commit"] != group["commit"]:
        parser.error("Pinned source mismatch")
    os.environ["QUALITY_ALLOW_DOWNLOADS"] = "0"
    sources.MAX_PACK_BYTES = 64 * 1024**2
    identity = fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"])
    rows = []
    with tempfile.TemporaryDirectory(prefix="attocode-kotlin-paths-") as tmp:
        root, cache = Path(tmp) / "source", Path(tmp) / "cache"
        root.mkdir()
        cache.mkdir()
        tree = materialize(spec, root, cache)
        paths = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        changed = [p for p in paths if is_test_path(p) != baseline_is_test_path(p)]
        if any(baseline_is_test_path(p) for p in changed):
            raise RuntimeError("Existing test classification lost")
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
                        classifier = baseline_is_test_path if arm == "baseline" else is_test_path
                        trace = {}
                        started = time.perf_counter()
                        with patch.object(query_ranking, "is_test_path", classifier):
                            hits = mgr.search_candidates(_expand_query(question["query"]), top_k=24, trace=trace)
                        samples[arm].append(time.perf_counter() - started)
                        result = snapshot(hits)
                        if arm in arms and arms[arm]["results"] != result:
                            raise RuntimeError("Unstable warmed results")
                        arms[arm] = {"results": result, "files": list(dict.fromkeys(h.file_path for h in hits)),
                                     "stages": trace}
                for arm in arms:
                    arms[arm].update(seconds=statistics.median(samples[arm]), samples_seconds=samples[arm])
                rows.append({"id": question["id"], "query": question["query"], "intent": question["intent"],
                             "labels": sorted(labels), "arms": arms})
            index = mgr.candidate_diagnostics()
        finally:
            mgr.close()
    if identity != fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"]):
        raise RuntimeError("Implementation changed during comparison")
    checks = {
        "same_generation": all(r["arms"]["baseline"]["stages"][stage] == r["arms"]["candidate"]["stages"][stage]
                               for r in rows for stage in ("keyword", "body", "file_bm25", "chunk_fused")),
        "production_labels_preserved": all(set(r["labels"]) & set(r["arms"]["baseline"]["files"][:k])
                                           <= set(r["arms"]["candidate"]["files"][:k])
                                           for r in rows if r["intent"] == "production" for k in (5, 24)),
        "explicit_tests_unchanged": all(r["arms"]["baseline"]["results"] == r["arms"]["candidate"]["results"]
                                        for r in rows if r["intent"] == "test"),
    }
    # Six samples: nearest-rank p95 is the maximum per-query median.
    timings = {a: max(r["arms"][a]["seconds"] for r in rows) for a in ("baseline", "candidate")}
    checks["latency"] = timings["candidate"] <= max(1.5 * timings["baseline"], .05)
    result = {"pack": "okhttp", "commit": spec["commit"], "tree": tree, "index": index,
              "queries": rows, "checks": checks, "passed": all(checks.values()), "p95_seconds": timings,
              "new_test_paths": changed, "questions_sha256": hashlib.sha256(raw).hexdigest(),
              "source_sha256": identity, "cleanup_verified": not Path(tmp).exists()}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit("Comparison failed; observations retained")


if __name__ == "__main__":
    main()
