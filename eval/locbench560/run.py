"""Loc-Bench V1 (czlll/Loc-Bench_V1 @ c44cf3b7, all 560) through attocode search and Jev.

Work files (clones, pools, trials) go to $LOCBENCH_DIR (default ~/locbench560).
One repository clone and one snapshot on disk at a time. Resumable: an instance
with a done marker is skipped. Jev sends source excerpts of these public
repositories to OpenRouter. Commands:
  run.py fetch              write all.json (needs `uv run --with datasets`)
  run.py prepare            write pack.yaml (full issue + title per instance)
  run.py shard I N          process repositories I, I+N, I+2N, ... (sorted by name)
  run.py only ID [ID ...]   process the given instances
  run.py credits            print OpenRouter total usage (USD), for the cost delta
  run.py q512 I N           shard I of N: Jev with the query cut to 512 characters (long issues only)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("LOCBENCH_DIR", Path.home() / "locbench560")).resolve()
REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
DATASET, REVISION = "czlll/Loc-Bench_V1", "c44cf3b74e07ca642cec841b471a9939907c12a7"
ENV = {**os.environ, "PYTHONPATH": "packages/code-intel/src"}


def title(statement: str) -> str:
    # Same rule as the 42-instance title pack.
    first = statement.strip().splitlines()[0].strip().strip("#").strip()
    return re.sub(r"^\[[^\]]+\]\s*", "", first)


def rows() -> list[dict]:
    return json.loads((ROOT / "all.json").read_text())


def fetch() -> None:
    from datasets import load_dataset

    data = load_dataset(DATASET, split="test", revision=REVISION)
    (ROOT / "all.json").write_text(json.dumps(list(data)))
    print(len(data), "instances")


def prepare() -> None:
    pack = {}
    for r in rows():
        gold = sorted({f.split(":")[0] for f in r["edit_functions"]})
        base = {"relevant_files": gold, "base_commit": r["base_commit"], "source_repo": r["repo"],
                "category": r["category"]}
        cases = [{"query": r["problem_statement"], "intent": "full", **base}]
        if title(r["problem_statement"]) != r["problem_statement"].strip():
            cases.append({"query": title(r["problem_statement"]), "intent": "title", **base})
        pack[r["instance_id"]] = cases
    (ROOT / "pack.yaml").write_text(
        "# Loc-Bench V1 @ c44cf3b7, all 560. Query: problem_statement verbatim (full) and its first line (title).\n"
        "# Gold: unique edit_functions files, as in LocAgent eval_metric.cal_metrics_w_dataset.\n"
        + yaml.safe_dump({"repos": pack}, sort_keys=False, allow_unicode=True, width=10**6))
    print(len(pack), "instances")


def run(cmd: list[str], log: Path, timeout: float, cwd: Path = REPO) -> bool:
    with log.open("a") as out:
        out.write(f"$ {' '.join(c[:200] for c in cmd)}\n")
        out.flush()
        try:
            return subprocess.run(cmd, cwd=cwd, env=ENV, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode == 0
        except subprocess.TimeoutExpired:
            out.write("TIMEOUT\n")
            return False


def cases(path: Path) -> int:
    """Rows in a trial output; 0 when the trial wrote nothing usable."""
    try:
        return len(json.loads(path.read_text())["cases"])
    except (OSError, ValueError, KeyError):
        return 0


def miss(iid: str, reason: str, done: str = "done") -> None:
    (ROOT / done / f"{iid}.json").write_text(json.dumps({"instance_id": iid, "miss": reason}))


def checkout(clone: Path, r: dict, log: Path) -> Path | None:
    """A worktree at the instance's base_commit, or None when the commit cannot be fetched."""
    wt, git = ROOT / "wt" / r["instance_id"], ["git", "-C", str(clone)]
    if not wt.exists() and not run([*git, "worktree", "add", "-q", "--detach", str(wt), r["base_commit"]], log, 1800):
        run([*git, "fetch", "-q", "origin", r["base_commit"]], log, 1800)
        if not run([*git, "worktree", "add", "-q", "--detach", str(wt), r["base_commit"]], log, 1800):
            return None
    run(["git", "-C", str(wt), "status", "--porcelain"], log, 600)  # first touch is slow in a blobless clone
    return wt


def jev(pool: Path, r: dict, prefix: str, log: Path) -> bool:
    """Jev over the first 24 files for every query and the first 48 for the full issue."""
    trial = [PY, "-m", "eval.model_rerank_trial", "--pool", str(pool), "--model", "jev-choice", "--allow-remote"]
    t24, t48 = ROOT / "trials" / f"{prefix}24.json", ROOT / "trials" / f"{prefix}48.json"
    ok = (run([*trial, "--max-candidates", "24", "--output", str(t24)], log, 3600)
          and cases(t24) == len(json.loads(pool.read_text())["repos"][0]["queries"]))
    return ok and (run([*trial, "--max-candidates", "48", "--select", f"{r['instance_id']}::{r['problem_statement']}",
                        "--output", str(t48)], log, 3600) and cases(t48) == 1)


def instance(clone: Path, r: dict) -> None:
    iid, log = r["instance_id"], ROOT / "logs" / f"{r['instance_id']}.log"
    if (ROOT / "done" / f"{iid}.json").exists():
        return
    started, git = time.time(), ["git", "-C", str(clone)]
    wt = checkout(clone, r, log)
    if wt is None:
        return miss(iid, "base_commit not available")
    pool = ROOT / "pools" / f"{iid}.json"
    ok = run([PY, "-m", "eval.ranking_pair", "--repos", f"{iid}={wt}", "--case-pack", str(ROOT / "pack.yaml"),
              "--top-k", "400", "--pool-files", "48", "--treatment", "default", "--timeout", "1200",
              "--json", str(pool)], log, 3600)
    if not ok or not pool.exists():
        run([*git, "worktree", "remove", "--force", str(wt)], log, 600)
        return miss(iid, "pool failed")
    ok = jev(pool, r, f"{iid}-jev", log)
    run([*git, "worktree", "remove", "--force", str(wt)], log, 600)
    if not ok:  # no done marker: the next run retries this instance
        with log.open("a") as out:
            out.write("TRIAL FAILED\n")
        return
    (ROOT / "done" / f"{iid}.json").write_text(json.dumps({"instance_id": iid, "seconds": round(time.time() - started)}))


def q512(clone: Path, r: dict) -> None:
    """Jev on the frozen pool with the query cut to 512 characters, as the product ranker sends it.

    Rebuilds the 48 candidate files at base_commit and checks that the excerpts hash
    the same as in the original trial, so only the query differs.
    """
    iid, log = r["instance_id"], ROOT / "logs" / f"{r['instance_id']}-q512.log"
    old = json.loads((ROOT / "trials" / f"{iid}-jev48.json").read_text())["cases"][0]
    pool = ROOT / "pools" / f"{iid}.json"
    wt = Path(json.loads(pool.read_text())["repos"][0]["source"])
    git = ["git", "-C", str(clone)]
    add = [*git, "worktree", "add", "-q", "--no-checkout", "--detach", str(wt), r["base_commit"]]
    if not wt.exists() and not run(add, log, 1800):
        run([*git, "fetch", "-q", "origin", r["base_commit"]], log, 1800)
        run(add, log, 1800)
    # Sparse checkout writes only the candidates and keeps `git status` clean for the trial.
    def patterns(paths):
        return ["/" + re.sub(r"([*?\[\\])", r"\\\1", path) for path in paths]

    run(["git", "-C", str(wt), "sparse-checkout", "set", "--no-cone", *patterns(old["baseline_files"])], log, 600)
    run(["git", "-C", str(wt), "read-tree", "-mu", "HEAD"], log, 1800)
    # A symlinked candidate also needs its target in the checkout.
    links = [os.path.relpath(os.path.realpath(wt / f), wt) for f in old["baseline_files"] if (wt / f).is_symlink()]
    if links:
        run(["git", "-C", str(wt), "sparse-checkout", "add", *patterns(links)], log, 1800)
    trial = [PY, "-m", "eval.model_rerank_trial", "--pool", str(pool), "--model", "jev-choice", "--allow-remote",
             "--select", f"{iid}::{r['problem_statement']}", "--max-query-chars", "512"]
    same = {}
    for n in (24, 48):
        out = ROOT / "trials-q512" / f"{iid}-jev{n}.json"
        if not (run([*trial, "--max-candidates", str(n), "--output", str(out)], log, 3600) and cases(out) == 1):
            run([*git, "worktree", "remove", "--force", str(wt)], log, 600)
            return
        before = old if n == 48 else next(c for c in json.loads((ROOT / "trials" / f"{iid}-jev24.json").read_text())["cases"]
                                          if c["query"] == old["query"])
        same[n] = json.loads(out.read_text())["cases"][0]["evidence_sha256"] == before["evidence_sha256"]
    run([*git, "worktree", "remove", "--force", str(wt)], log, 600)
    (ROOT / "done-q512" / f"{iid}.json").write_text(json.dumps({"instance_id": iid, "same_evidence": same}))


def process(selected: list[dict], step=instance, done: str = "done") -> None:
    by_repo = defaultdict(list)
    for r in selected:
        by_repo[r["repo"]].append(r)
    for repo, items in sorted(by_repo.items()):
        todo = [r for r in items if not (ROOT / done / f"{r['instance_id']}.json").exists()]
        if not todo:
            continue
        clone = ROOT / "repos" / repo.replace("/", "__")
        log = ROOT / "logs" / f"clone-{clone.name}.log"
        if not clone.exists() and not run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                                          f"https://github.com/{repo}.git", str(clone)], log, 3600, ROOT):
            for r in todo:
                miss(r["instance_id"], "clone failed", done)
            shutil.rmtree(clone, ignore_errors=True)
            continue
        for r in todo:
            step(clone, r)
            marker = ROOT / done / f"{r['instance_id']}.json"
            print(r["instance_id"], marker.read_text() if marker.exists() else "trial failed, will retry", flush=True)
        if all((ROOT / done / f"{r['instance_id']}.json").exists() for r in items):
            shutil.rmtree(clone, ignore_errors=True)  # ponytail: one clone at a time keeps disk under ~5 GB


def usage() -> None:
    import urllib.request

    from dotenv import dotenv_values
    key = os.environ.get("OPENROUTER_API_KEY") or dotenv_values(Path.home() / ".jev/env").get("OPENROUTER_API_KEY")
    request = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"})
    print(json.load(urllib.request.urlopen(request, timeout=30))["data"]["total_usage"])


if __name__ == "__main__":
    command, args = sys.argv[1], sys.argv[2:]
    for name in ("pools", "trials", "logs", "done", "repos", "wt", "trials-q512", "done-q512"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    if command == "fetch":
        fetch()
    elif command == "prepare":
        prepare()
    elif command == "credits":
        usage()
    elif command == "only":
        process([r for r in rows() if r["instance_id"] in set(args)])
    elif command == "shard":
        index, count = int(args[0]), int(args[1])
        repos = sorted({r["repo"] for r in rows()})[index::count]
        process([r for r in rows() if r["repo"] in repos])
    elif command == "q512":
        index, count = int(args[0]), int(args[1])
        long = [r for r in rows() if len(r["problem_statement"]) > 512]
        repos = sorted({r["repo"] for r in long})[index::count]
        process([r for r in long if r["repo"] in repos], step=q512, done="done-q512")
