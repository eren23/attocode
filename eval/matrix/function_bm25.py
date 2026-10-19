"""BM25 over function units and over 40-line windows of the same files, on Loc-Bench V1 (CPU only).

Usage: python eval/matrix/function_bm25.py WORK CODE CACHE INSTANCES [WORKERS]

The question: does the function unit help a lexical ranker as it helps CodeRankEmbed? Both arms use
the same files: the files of eval/matrix/function_dense.py that have at least one function unit.
  fn   one document for each function unit, with the SweRank text (id, class line, source).
  win  one document for each 40 lines of the same files, with "File: <path>" first.
Both arms use the product tokenizer and the product BM25 parameters. The ranked documents give the
files in the order of their first document, up to 200 files. WORK/fn-bm25.json gets the lists.
"""
import json
import math
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

DEPTH, WINDOW = 200, 40


def bm25(docs, query_terms, k1, b):
    """The document indexes by BM25 score, best first, ties by index. docs: (length, {term: tf})."""
    n = len(docs)
    avg = sum(length for length, _tf in docs) / max(n, 1) or 1.0
    df = Counter(term for _length, tf in docs for term in tf)
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in query_terms if df[t]}
    scores = []
    for i, (length, tf) in enumerate(docs):
        s = sum(idf[t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * length / avg)) for t in tf if t in idf)
        if s > 0:
            scores.append((-s, i))
    return [i for _s, i in sorted(scores)]


def windows(path, source):
    lines = source.splitlines()
    return [f"File: {path}\n" + "\n".join(lines[s:s + WINDOW]) for s in range(0, max(len(lines), 1), WINDOW)]


def instance(args):
    code, cache, inst = args
    sys.path[:0] = [code, f"{code}/packages/code-intel/src"]
    from attocode_intel._internal.integrations.context.semantic_search import (
        SearchScoringConfig,
        _tokenize,
    )

    from eval.matrix import run
    from eval.matrix.function_dense import files_of, units
    started = time.time()
    tree_path = run._tree_file(cache, inst["repo"], inst["base_commit"])
    tree = json.loads(tree_path.read_text()) if tree_path.exists() else {"error": "no snapshot"}
    if "error" in tree:
        return inst["id"], {"error": tree["error"]}
    query = set(_tokenize(inst["queries"]["full"]))
    pytest = inst["id"].split("/", 1)[1].startswith("pytest-dev__")

    def doc(text):
        tokens = _tokenize(text)
        return len(tokens), Counter(t for t in tokens if t in query)

    fn_keys, fn_docs, win_paths, win_docs = [], [], [], []
    for path, mode, oid, size in tree["entries"]:
        if mode == "120000" or not path.endswith(".py") or not run._stored([path, mode, oid, size]):
            continue
        source = zlib.decompress(run._blob_file(cache, oid).read_bytes()).decode(errors="replace")
        found = units(path, source, pytest)
        if not found:
            continue
        for key, text in found.items():
            fn_keys.append(key)
            fn_docs.append(doc(text))
        for text in windows(path, source):
            win_paths.append(path)
            win_docs.append(doc(text))
    cfg = SearchScoringConfig()
    fn = files_of([fn_keys[i] for i in bm25(fn_docs, query, cfg.bm25_k1, cfg.bm25_b)])[:DEPTH]
    win = list(dict.fromkeys(win_paths[i] for i in bm25(win_docs, query, cfg.bm25_k1, cfg.bm25_b)))[:DEPTH]
    return inst["id"], {"fn": fn, "win": win, "functions": len(fn_docs), "windows": len(win_docs),
                        "query_terms": len(query), "seconds": round(time.time() - started, 2)}


def main():
    work, code, cache, insts_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 16
    work.mkdir(parents=True, exist_ok=True)
    insts = [json.loads(line) for line in insts_path.read_text().splitlines() if line.startswith('{"id": "locbench/')]
    from multiprocessing import get_context
    started, out = time.time(), {}
    with get_context("spawn").Pool(workers) as pool:
        for n, (iid, result) in enumerate(pool.imap_unordered(instance, [(code, cache, i) for i in insts]), 1):
            out[iid] = result
            if n % 50 == 0:
                print(f"{time.strftime('%H:%M:%S')} {n}/{len(insts)} {time.time() - started:.0f}s", flush=True)
    (work / "fn-bm25.json").write_text(json.dumps(out))
    print(f"end: {len(out)} instances, {sum('error' in r for r in out.values())} errors, "
          f"{time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
