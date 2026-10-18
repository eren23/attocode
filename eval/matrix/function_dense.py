"""On the pod: function-level CodeRankEmbed on Loc-Bench V1, as in SweRank Table 2 (74.29 / 80.36).

Usage, on a GPU pod: python eval/matrix/function_dense.py WORK CODE CACHE INSTANCES [ZIP]

WORK holds the vectors and the results, CODE is a checkout of this repository, CACHE holds the
snapshots of the eval.matrix.run snapshot stage, INSTANCES is a run folder instances.jsonl, and ZIP is
the SweRank datasets.zip (Google Drive file 1pjWkpEfFRAts5hkcCGFSoBW1HiQQTsTo). The packages:
sentence-transformers 3.4.1, transformers 4.51.3, einops.

Arms (one embedding of each unique document text serves both):
  zip   the SweRank corpora: datasets.zip folders loc-bench-function_<instance id>.
  ours  the CoRNStack unit rule (get_patch_info.find_py_or_non_dict_with_path over
        get_repo_structure.parse_python_file) on our snapshots in CACHE, with the method text of the zip.
Model: nomic-ai/CodeRankEmbed at the eval.matrix.dense revision, bf16, CLS, 1,024 tokens, no normalize.
Score: dot product, in fp32 and in bf16 (BEIR multiplies the bf16 vectors). The top 100 functions give
the files in first-occurrence order (refactored_eval_localization.extract_file_path).
"""
import ast
import hashlib
import json
import re
import sys
import time
import warnings
import zipfile
import zlib
from pathlib import Path

import numpy as np

PREFIX = "Represent this query for searching relevant code: "
SEQ, BATCH, TOP_FUNCTIONS, DEPTH = 1024, 128, 100, 200
PART = 100_000  # texts per saved part of vectors


def log(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


def units(path, source, pytest):
    """The documents of one file: {id: text}. The rule of CoRNStack find_py_or_non_dict_with_path."""
    name = path.rsplit("/", 1)[-1]
    if not path.endswith(".py") or "test" in name.lower() or ("test" in path.lower() and not pytest):
        return {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # invalid escapes in old sources
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return {}
    lines, docs, methods = source.splitlines(), {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    text = lines[n.lineno - 1:n.end_lineno]
                    key = f"{path}/{node.name}/{n.name}"
                    # The zip text: a newline after the class line, and the def line without its indent.
                    docs[key] = (f"{key}\nclass {node.name}:\n" + "\n".join([text[0].lstrip(), *text[1:]])).strip()
                    methods.add(n.name)
        elif isinstance(node, ast.FunctionDef) and node.name not in methods:
            key = f"{path}/{node.name}"
            docs[key] = (f"{key}\n" + "\n".join(lines[node.lineno - 1:node.end_lineno])).strip()
    return docs


def ours(args):
    """The documents of one instance from its snapshot, or None without a snapshot."""
    cache, inst = args
    from eval.matrix import run
    path = run._tree_file(cache, inst["repo"], inst["base_commit"])
    tree = json.loads(path.read_text()) if path.exists() else {"error": "no snapshot"}
    if "error" in tree:
        return None
    docs = {}
    for path, mode, oid, size in tree["entries"]:
        if mode == "120000" or not path.endswith(".py") or not run._stored([path, mode, oid, size]):
            continue
        data = zlib.decompress(run._blob_file(cache, oid).read_bytes())
        docs.update(units(path, data.decode(errors="replace"), inst["id"].split("/", 1)[1].startswith("pytest-dev__")))
    return docs


def from_zip(archive, names, iid):
    base = names.get(f"loc-bench-function_{iid}")
    if base is None:
        return None, None, None
    docs = {}
    with archive.open(base + "corpus.jsonl") as f:
        for line in f:
            d = json.loads(line)
            docs[d["_id"]] = (d.get("title", "") + " " + d["text"]).strip()
    with archive.open(base + "queries.jsonl") as f:
        query = json.loads(f.readline())["text"]
    gold = []
    with archive.open(base + "qrels/test.tsv") as f:
        for i, line in enumerate(f.read().decode().splitlines()):
            if i == 0 and line.startswith("query-id"):
                continue
            func = line.split("\t")[1]
            fn = func.split(".py")[0] + ".py"
            if fn not in gold:
                gold.append(fn)
    return docs, query, gold


def files_of(ids):
    out = []
    for i in ids:
        m = re.match(r"(.+\.py)(/.*)?", i)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def acc(files, gold, k):
    return len(set(files[:k]) & set(gold)) >= min(len(gold), k)


def main():
    work, code, cache, insts_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    sys.path[:0] = [code, f"{code}/packages/code-intel/src"]
    zpath = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    work.mkdir(parents=True, exist_ok=True)
    insts = [json.loads(line) for line in insts_path.read_text().splitlines()
             if line.startswith('{"id": "locbench/')]
    log(f"{len(insts)} instances")
    archive = zipfile.ZipFile(zpath) if zpath and zpath.exists() else None
    names = {}
    if archive:
        for n in archive.namelist():
            m = re.search(r"(?:^|/)(loc-bench-function_[^/]+)/corpus\.jsonl$", n)
            if m:
                names[m.group(1)] = n[:-len("corpus.jsonl")]
        log(f"zip: {len(names)} loc-bench folders")
    texts, index = [], {}
    from multiprocessing import Pool
    with Pool(16) as pool:  # ponytail: 16 of 64 CPUs; the retrieve run uses the others
        built = pool.map(ours, [(cache, inst) for inst in insts], chunksize=4)
    log("our corpora built")

    def ids_of(docs):
        rows = []
        for text in docs.values():
            if text not in index:
                index[text] = len(texts)
                texts.append(text)
            rows.append(index[text])
        return rows

    arms = {"zip": {}, "ours": {}}
    for n, inst in enumerate(insts):
        iid = inst["id"].split("/", 1)[1]
        query = inst["queries"]["full"]
        if archive:
            docs, zquery, zgold = from_zip(archive, names, iid)
            if docs is not None:
                arms["zip"][iid] = {"keys": list(docs), "rows": ids_of(docs), "gold": zgold,
                                    "query_same": zquery == query, "query": zquery}
        docs = built[n]
        if docs is not None:
            arms["ours"][iid] = {"keys": list(docs), "rows": ids_of(docs), "gold": inst["gold"], "query": query}
        if n % 50 == 0:
            log(f"corpus {n}: {len(texts)} unique texts")
    log(f"corpus done: zip {len(arms['zip'])}, ours {len(arms['ours'])} instances, {len(texts)} unique texts, "
        f"{sum(len(a['rows']) for arm in arms.values() for a in arm.values())} documents")

    import torch
    from sentence_transformers import SentenceTransformer

    from eval.matrix import dense
    model = SentenceTransformer(dense.MODEL, revision=dense.MODEL_REVISION, trust_remote_code=True, device="cuda")
    model = model.to(torch.bfloat16)
    model.max_seq_length = SEQ
    parts = []
    started = time.time()
    for start in range(0, len(texts), PART):
        part = work / f"vec-{start // PART:04d}.npy"
        digest = hashlib.sha256("\0".join(texts[start:start + PART]).encode()).hexdigest()[:16]
        if part.exists() and (work / f"{part.stem}.sha").read_text() == digest:
            parts.append(np.load(part))
            continue
        vec = model.encode(texts[start:start + PART], batch_size=BATCH, convert_to_tensor=True)
        vec = vec.float().cpu().numpy()
        np.save(part, vec)
        (work / f"{part.stem}.sha").write_text(digest)
        parts.append(vec)
        done = start + len(vec)
        log(f"embedded {done}/{len(texts)} ({done / (time.time() - started):.0f}/s)")
    vecs = torch.from_numpy(np.concatenate(parts)).cuda()

    queries = sorted({a["query"] for arm in arms.values() for a in arm.values()})
    qvec = {}
    for variant, prefix in (("prefix", PREFIX), ("noprefix", "")):
        enc = model.encode([prefix + q for q in queries], batch_size=16, convert_to_tensor=True).float()
        qvec[variant] = dict(zip(queries, enc, strict=True))
    out, summary = {}, {}
    for arm, rows in arms.items():
        for variant in qvec:
            for dtype in ("fp32", "bf16"):
                cell = f"{arm}.{variant}.{dtype}"
                res, hits = {}, {5: 0, 10: 0}
                for iid, a in rows.items():
                    m, q = vecs[a["rows"]], qvec[variant][a["query"]]
                    if dtype == "bf16":
                        scores = (m.to(torch.bfloat16) @ q.to(torch.bfloat16)).float()
                    else:
                        scores = m @ q
                    order = torch.argsort(scores, descending=True, stable=True).tolist()
                    ranked = [a["keys"][i] for i in order]
                    top = files_of(ranked[:TOP_FUNCTIONS])
                    res[iid] = {"files100": top, "files": files_of(ranked)[:DEPTH], "docs": len(ranked)}
                    for k in hits:
                        hits[k] += acc(top, a["gold"], k)
                summary[cell] = {"n": len(rows), **{f"acc@{k}": round(100 * v / max(len(rows), 1), 2)
                                                    for k, v in hits.items()},
                                 **{f"hits@{k}": v for k, v in hits.items()}}
                out[cell] = res
                log(f"{cell}: {summary[cell]}")
    if arms["zip"]:
        summary["checks"] = {
            "zip_query_equals_problem_statement": sum(a["query_same"] for a in arms["zip"].values()),
            "zip_gold_equals_edit_files": sum(sorted(a["gold"]) == sorted(arms["ours"].get(i, {}).get("gold", []))
                                              for i, a in arms["zip"].items()),
            "doc_counts": {i: [len(a["keys"]), len(arms["ours"].get(i, {}).get("keys", []))]
                           for i, a in arms["zip"].items()},
            "id_overlap": {i: len(set(a["keys"]) & set(arms["ours"].get(i, {}).get("keys", [])))
                           for i, a in arms["zip"].items()},
            "text_overlap": {i: len(set(a["rows"]) & set(arms["ours"].get(i, {}).get("rows", [])))
                             for i, a in arms["zip"].items()},
        }
    summary["texts"], summary["embed_seconds"] = len(texts), round(time.time() - started)
    (work / "fn-results.json").write_text(json.dumps(out))
    (work / "fn-summary.json").write_text(json.dumps(summary, indent=1))
    log("end")


if __name__ == "__main__":
    main()
