"""First-stage retrieval on Loc-Bench V1: file BM25 fused with the lexical pool.

Needs the run.py pools in $LOCBENCH_DIR. For each instance it ranks the Python files at
base_commit with BM25. The fused pool was fixed before any run: equal-weight RRF (k=60)
of the lexical and BM25 orders, 48 files. Jev then reranks the lexical pool and the
fused pool with the same excerpt rule. Python files only, as the published Loc-Bench
retrievers. Each Python file is also saved once under blobs/, keyed by its git blob id,
with the per-instance (path, blob) list in the pools2 file, so a dense arm can embed
the same snapshots later without git. Commands:
  first_stage.py shard I N          repositories I, I+N, ... (sorted by name)
  first_stage.py only ID [ID ...]
"""
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import run as base

sys.path.insert(0, str(base.REPO))
from attocode_intel.focused_evidence import STOP_WORDS  # noqa: E402

from eval.dense_pool import MAX_BYTES, _rrf  # noqa: E402

DEPTH, K1, B = 48, 1.2, 0.75
TOKENS: dict[str, Counter] = {}  # blob id -> term counts, for the current repository
_state = {"repo": None}


def tokens(text: str) -> list[str]:
    """The product's focused_evidence.terms rule, with counts kept for BM25."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 4 else w
            for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower()) if len(w) > 2 and w not in STOP_WORDS]


def bm25(query: str, docs: dict[str, Counter], lengths: dict[str, int]) -> list[str]:
    avgdl = sum(lengths.values()) / max(len(docs), 1) or 1.0
    terms = set(tokens(query))
    df = Counter(t for counts in docs.values() for t in terms if t in counts)
    idf = {t: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    scores = {}
    for path, counts in docs.items():
        norm = K1 * (1 - B + B * lengths[path] / avgdl)
        score = sum(w * counts[t] * (K1 + 1) / (counts[t] + norm) for t, w in idf.items() if t in counts)
        if score > 0:
            scores[path] = score
    return sorted(scores, key=lambda p: (-scores[p], p))[:DEPTH]


def python_files(wt: Path) -> list[tuple[str, str, str]]:
    listed = subprocess.run(["git", "-C", str(wt), "ls-files", "-s", "-z"], capture_output=True, check=True).stdout
    files = []
    for entry in filter(None, listed.split(b"\0")):
        meta, name = entry.split(b"\t", 1)
        mode, blob, _stage = meta.split()
        path = name.decode()
        if mode in (b"100644", b"100755") and path.endswith(".py") and (wt / path).stat().st_size <= MAX_BYTES:
            blob, data = blob.decode(), (wt / path).read_bytes()
            saved = base.ROOT / "blobs" / blob[:2] / blob
            if not saved.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(data)
            files.append((path, blob, data.decode(errors="replace")))
    return files


def step(clone: Path, r: dict) -> None:
    iid, log = r["instance_id"], base.ROOT / "logs" / f"{r['instance_id']}.stage.log"
    if (base.ROOT / "done2" / f"{iid}.json").exists():
        return
    if _state["repo"] != r["repo"]:  # ponytail: caches hold one repository; process() runs repos in order
        TOKENS.clear()
        _state["repo"] = r["repo"]
    started = time.time()
    wt = base.checkout(clone, r, log)
    if wt is None:
        return base.miss(iid, "base_commit not available", "done2")
    lexical_pool = base.ROOT / "pools" / f"{iid}.json"
    pool = json.loads(lexical_pool.read_text())
    files = python_files(wt)
    for _path, blob, text in files:
        if blob not in TOKENS:
            TOKENS[blob] = Counter(tokens(text))
    docs = {path: TOKENS[blob] for path, blob, _text in files}
    lengths = {path: sum(counts.values()) for path, counts in docs.items()}
    timing = {"files": len(files), "bm25_s": 0.0}
    queries = []
    for case in pool["repos"][0]["queries"]:
        lexical = case["arms"]["prior"]["files"]
        t0 = time.time()
        ranked_bm25 = bm25(case["query"], docs, lengths)
        timing["bm25_s"] += round(time.time() - t0, 2)
        fused = _rrf(lexical, ranked_bm25, depth=DEPTH)
        queries.append({**case, "arms": {"prior": {"files": fused}, "lexical": {"files": lexical},
                                         "bm25": {"files": ranked_bm25}}})
    fused_pool = base.ROOT / "pools2" / f"{iid}.json"
    fused_pool.write_text(json.dumps({**pool, "comparison": "RRF k=60 of lexical and BM25 (Python files)",
                                      "python_files": [[path, blob] for path, blob, _text in files],
                                      "repos": [{**pool["repos"][0], "queries": queries}]}))
    ok = base.jev(lexical_pool, r, f"{iid}-lex", log) and base.jev(fused_pool, r, f"{iid}-fus", log)
    base.run(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)], log, 600)
    if not ok:  # no done marker: the next run retries this instance
        with log.open("a") as out:
            out.write("TRIAL FAILED\n")
        return
    (base.ROOT / "done2" / f"{iid}.json").write_text(json.dumps(
        {"instance_id": iid, "seconds": round(time.time() - started), **timing}))


if __name__ == "__main__":
    command, args = sys.argv[1], sys.argv[2:]
    for name in ("pools2", "done2", "blobs", "trials", "logs", "repos", "wt"):
        (base.ROOT / name).mkdir(parents=True, exist_ok=True)
    rows = base.rows()
    if command == "only":
        selected = [r for r in rows if r["instance_id"] in set(args)]
    else:
        repos = sorted({r["repo"] for r in rows})[int(args[0])::int(args[1])]
        selected = [r for r in rows if r["repo"] in repos]
    base.process(selected, step, "done2")
