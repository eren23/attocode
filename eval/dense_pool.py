"""Eval-only dense retrieval arm: CodeRankEmbed files, fused with a frozen lexical pool.

Reads an ``eval.ranking_pair`` pool JSON, embeds each repository's tracked text
files in fixed line windows at the pool's pinned revision, and writes:

- ``<out>-dense.json``: a trial-shaped result whose ranking is dense-only;
- ``<out>-fused.json``: a ranking_pair-shaped pool whose ``prior`` order is the
  reciprocal-rank fusion of lexical and dense file orders, so
  ``eval.model_rerank_trial`` can rerank it unchanged.

Nothing is written into the repositories. Embeddings are cached per revision.

Example:
    .venv/bin/python -m eval.dense_pool --pool pool.json --out /path/run --cache /path/cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path

import numpy as np

MODEL = "nomic-ai/CodeRankEmbed"
# Its remote modeling code lives in the same repository, so this revision pins the code too.
MODEL_REVISION = "3c4b60807d71f79b43f3c4363786d9493691f8b1"
QUERY_PREFIX = "Represent this query for searching relevant code: "
WINDOW, MAX_CHUNKS_PER_FILE, MAX_BYTES, MAX_CHARS = 40, 40, 300_000, 1500
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".jar", ".gz", ".woff",
                 ".woff2", ".ttf", ".eot", ".svg", ".lock", ".bin", ".so", ".dylib", ".a", ".o"}
RRF_K = 60


def _chunks(root: Path, revision: str) -> list[tuple[str, str]]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    current = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
    if current != revision:
        raise ValueError(f"Repository revision changed: {root}")
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                      capture_output=True, text=True, check=True).stdout.strip():
        raise ValueError(f"Tracked source files changed: {root}")
    rows = []
    for name in listed.decode().split("\0"):
        path = root / name
        if not name or path.suffix.lower() in SKIP_SUFFIXES or name.endswith(".min.js"):
            continue
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        lines = data.decode(errors="replace").splitlines()
        for start in range(0, max(len(lines), 1), WINDOW)[:MAX_CHUNKS_PER_FILE]:
            body = "\n".join(lines[start:start + WINDOW])
            rows.append((name, f"File: {name}\n{body}"[:MAX_CHARS]))
    return rows


def _index(model, root: Path, revision: str, cache: Path) -> tuple[list[str], np.ndarray]:
    stem = cache / f"{root.name}-{revision[:12]}-{MODEL_REVISION[:12]}"
    if stem.with_suffix(".npy").is_file():
        return json.loads(stem.with_suffix(".json").read_text()), np.load(stem.with_suffix(".npy"))
    rows = _chunks(root, revision)
    started = time.perf_counter()
    vectors = model.encode([text for _name, text in rows], batch_size=32, normalize_embeddings=True,
                           show_progress_bar=False, convert_to_numpy=True)
    print(json.dumps({"repo": root.name, "chunks": len(rows),
                      "embed_s": round(time.perf_counter() - started, 1)}), flush=True)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(stem.with_suffix(".npy"), vectors)
    stem.with_suffix(".json").write_text(json.dumps([name for name, _text in rows]))
    return [name for name, _text in rows], vectors


def _dense_files(model, query: str, names: list[str], vectors: np.ndarray, depth: int) -> list[str]:
    q = model.encode([QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True)[0]
    order = np.argsort(-(vectors @ q))
    files: list[str] = []
    for index in order:
        if names[index] not in files:
            files.append(names[index])
            if len(files) == depth:
                break
    return files


def _rrf(*orders: list[str], depth: int) -> list[str]:
    scores: dict[str, float] = {}
    for order in orders:
        for rank, path in enumerate(order):
            scores[path] = scores.get(path, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda path: (-scores[path], path))[:depth]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Output prefix")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    from sentence_transformers import SentenceTransformer

    pool_bytes = args.pool.read_bytes()
    pool = json.loads(pool_bytes)
    model = SentenceTransformer(MODEL, revision=MODEL_REVISION, trust_remote_code=True, device=args.device)
    model.max_seq_length = 512  # ponytail: ~1500-char windows fit; 8192 only adds padding cost
    dense_cases, fused_cases, fused = [], [], {**pool, "comparison": f"lexical+{MODEL} RRF k={RRF_K}", "repos": []}
    for repo in pool["repos"]:
        root = Path(repo["source"]).resolve()
        names, vectors = _index(model, root, repo["source_revision"], args.cache)
        fused_queries = []
        for case in repo["queries"]:
            lexical = case["arms"]["prior"]["files"]
            started = time.perf_counter()
            dense = _dense_files(model, case["query"], names, vectors, len(lexical))
            ms = round((time.perf_counter() - started) * 1000, 1)
            dense_cases.append({"repo": repo["repo"], "query": case["query"], "ranked_files": dense,
                                "inference_ms": ms, "failures": 0})
            merged = _rrf(lexical, dense, depth=len(lexical))
            fused_cases.append({"repo": repo["repo"], "query": case["query"], "ranked_files": merged,
                                "inference_ms": ms, "failures": 0})
            fused_queries.append({**case, "arms": {**case["arms"], "prior": {"files": merged}}})
        fused["repos"].append({**repo, "queries": fused_queries})
    latencies = sorted(row["inference_ms"] for row in dense_cases)
    pool_sha = hashlib.sha256(pool_bytes).hexdigest()
    dense = {"model": MODEL, "model_revision": MODEL_REVISION, "pool": str(args.pool), "pool_sha256": pool_sha, "cases": dense_cases,
             "summary": {"median_inference_ms": statistics.median(latencies),
                         "p95_inference_ms": latencies[int(0.95 * len(latencies)) - 1],
                         "failures": 0}}
    Path(f"{args.out}-dense.json").write_text(json.dumps(dense, indent=2) + "\n")
    rank = {**dense, "model": f"lexical+{MODEL} RRF", "cases": fused_cases}
    Path(f"{args.out}-fusedrank.json").write_text(json.dumps(rank, indent=2) + "\n")
    Path(f"{args.out}-fused.json").write_text(json.dumps(fused, indent=2) + "\n")


if __name__ == "__main__":
    main()
