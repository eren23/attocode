"""Compare default page delivery on identical lexical pools from pinned local packs."""
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
from attocode_intel._internal.integrations.context import semantic_search as search
from attocode_intel.query_ranking import query_concepts, rerank_broad_candidates

from eval.quality import sources
from eval.quality.corpus import PACK, materialize


def baseline(query, candidates, top_k, file_filter=""):
    """Default delivery from main 112dab66; keep the historical fallback intact."""
    if top_k <= 0 or not candidates:
        return []
    if len(query_concepts(query)) < 2 or file_filter or re.search(r"\btests?\b", query, re.I):
        return candidates[:top_k]
    selected = []
    seen = set()
    for row in candidates:
        if row.file_path not in seen:
            selected.append(row)
            seen.add(row.file_path)
            if len(selected) == top_k:
                return selected
    return candidates[:top_k]


def compare(query, pool, depth, labels):
    """Record source-free chunk identities and both deliveries from one frozen pool."""
    firsts = list(dict.fromkeys(row.file_path for row in pool))
    index = {id(row): i for i, row in enumerate(pool)}
    identities = [
        {"file": row.file_path, "name": row.name, "kind": row.chunk_type,
         "start_line": row.start_line, "end_line": row.end_line, "score": row.score,
         "text_sha256": hashlib.sha256(row.text.encode()).hexdigest()}
        for row in pool
    ]
    arms = {}
    for name, deliver in (("baseline", baseline), ("candidate", rerank_broad_candidates)):
        timings = []
        for _ in range(101):
            start = time.perf_counter_ns()
            hits = deliver(query, pool, depth)
            timings.append((time.perf_counter_ns() - start) / 1e6)
        files = list(dict.fromkeys(row.file_path for row in hits))
        arms[name] = {
            "indices": [index[id(row)] for row in hits], "files": files,
            "labeled_ranks": {p: i + 1 for i, p in enumerate(files) if p in labels},
            "count": len(hits), "median_delivery_ms": statistics.median(timings),
        }
    old, new = arms["baseline"], arms["candidate"]
    checks = {
        "count": old["count"] == new["count"] == min(depth, len(pool)),
        "first_file": old["files"][:1] == new["files"][:1],
        "file_order": new["files"] == firsts[:depth],
        "distinct_prefix": [pool[i].file_path for i in new["indices"][:len(firsts)]]
        == firsts[:depth],
        "labels_at_five": (labels & set(old["files"][:5])) <= set(new["files"][:5]),
        "labels_at_depth": (labels & set(old["files"])) <= set(new["files"]),
        "delivery_latency": new["median_delivery_ms"] < 5,
    }
    return {"depth": depth, "pool": identities,
            "pool_sha256": hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest(),
            "unique_pool_files": len(firsts), "arms": arms, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite observed results")
    os.environ["QUALITY_ALLOW_DOWNLOADS"] = "0"
    os.environ["ATTOCODE_INTEL_BROAD_RERANK"] = "0"
    sources.MAX_PACK_BYTES = 64 * 1024**2
    spec = next(s for s in yaml.safe_load(PACK.read_text())["repositories"]
                if s["id"] == args.pack)
    questions = json.loads(args.questions.read_text())
    group = next(g for g in questions["repositories"] if g["pack"] == args.pack)
    if group["commit"] != spec["commit"]:
        raise ValueError("Question revision does not match source pack")
    observations = []
    with tempfile.TemporaryDirectory(prefix="attocode-deep-page-") as tmp:
        root, cache = Path(tmp) / "source", Path(tmp) / "cache"
        root.mkdir()
        cache.mkdir()
        tree = materialize(spec, root, cache)
        mgr = search.SemanticSearchManager(str(root))
        try:
            mgr.search("warmup", top_k=24)
            if not mgr.wait_for_body_index(timeout=90):
                raise TimeoutError("Candidate indexes did not become ready")
            for question in group["queries"]:
                labels = {e["file"] for e in question["evidence"]}
                for evidence in question["evidence"]:
                    path = (root / evidence["file"]).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError("Label escapes source pack")
                    raw = path.read_bytes()
                    if (hashlib.sha256(raw).hexdigest() != evidence["source_sha256"]
                            or evidence["quote"] not in raw.decode()):
                        raise ValueError("Pinned source label changed")
                for depth in questions["acceptance"]["depths"]:
                    captured = []

                    def capture(query, pool, top_k, file_filter="", _captured=captured):
                        if file_filter:
                            raise ValueError("This trial is unscoped")
                        _captured.append((query, list(pool), top_k))
                        return rerank_broad_candidates(query, pool, top_k)

                    start = time.perf_counter()
                    with patch.object(search, "rerank_broad_candidates", capture):
                        returned = mgr.search(question["query"], top_k=depth)
                    elapsed = time.perf_counter() - start
                    if len(captured) != 1:
                        raise ValueError("Expected one provider-free lexical pool")
                    query, pool, actual_depth = captured[0]
                    if actual_depth != depth:
                        raise ValueError("Unexpected candidate depth")
                    result = compare(query, pool, depth, labels)
                    if returned != rerank_broad_candidates(query, pool, depth):
                        raise ValueError("Search did not deliver the compared candidate")
                    observations.append({"id": question["id"], "query": question["query"],
                                         "expanded_query": query, "labels": sorted(labels),
                                         "search_seconds": elapsed, **result})
            diagnostics = mgr.candidate_diagnostics()
        finally:
            mgr.close()
    result = {"pack": args.pack, "commit": spec["commit"], "tree": tree,
              "questions_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
              "diagnostics": diagnostics, "observations": observations,
              "cleanup_verified": not Path(tmp).exists(),
              "passed": all(all(row["checks"].values()) for row in observations)}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit("Frozen acceptance checks failed")


if __name__ == "__main__":
    main()
