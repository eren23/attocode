"""Eval matrix command line. Run it from the repository root.

  python -m eval.matrix.run import-legacy OUT [--locbench [PREFIX=]DIR ...] [--pack NAME=DIR ...]
      Convert the pools and trials of earlier runs into OUT/instances.jsonl and
      OUT/results.jsonl, with one row per (instance, query variant, cell).
  python -m eval.matrix.run report OUT [--cells A,B] [--baseline CELL] [--pair CELL:BASELINE ...]
      [--metric NAME ...] [--ids FILE] [--partial] [--unjudged FILE] [--output FILE]
      Score OUT/results.jsonl against OUT/instances.jsonl and write OUT/report.md.

A Loc-Bench folder is a run of eval/locbench560: all.json, pools/ (cell lexical, and cell
lexpy for its Python files), pools2/ (cells fused and bm25), trials/ (one cell per trial
name, such as jev24) and trials-q512/ (cells such as jev24_q512). PREFIX names the run in
its cells, as in body.jev24.

A case-pack folder holds eval.ranking_pair pools (pool.json is the lexical pool) and
eval.model_rerank_trial outputs. The cell is the file name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import yaml

from eval.matrix import datasets, stats
from eval.matrix.datasets import Instance

REPO = Path(__file__).resolve().parents[2]


def _pool_row(arm: dict, pool_sha256: str) -> dict:
    return {"files": arm["files"], "status": "ok", "fallback_reason": None, "latency_ms": arm.get("ms"),
            "pool_sha256": pool_sha256, "evidence_sha256": None}


def _trial_row(case: dict, pool: list[str], pool_sha256: str) -> dict:
    """A trial case as a row. A reranker reorders the first pool files, and the rest of the pool follows.

    A failed request keeps the pool order, as the product does. Its status says so.
    """
    files = case["ranked_files"]
    if "baseline_files" in case:  # a reranker. A first-stage output (dense) has no baseline.
        if sorted(files) != sorted(pool[:len(files)]):
            raise ValueError(f"{case['repo']}::{case['query'][:80]}: the ranking is not the first "
                             f"{len(files)} files of its pool")
        files = files + pool[len(files):]
    failed, reason = case.get("failures", 0), case.get("fallback_reason")
    return {"files": files, "status": "request_failed" if failed else "fallback" if reason else "ok",
            "fallback_reason": reason, "latency_ms": case.get("inference_ms"),
            "pool_sha256": pool_sha256, "evidence_sha256": case.get("evidence_sha256")}


def _locbench(root: Path, prefix: str) -> tuple[list[Instance], list[dict]]:
    instances = datasets.locbench(json.loads((root / "all.json").read_text()))
    by_native = {inst.id.split("/", 1)[1]: inst for inst in instances}
    pools: dict[str, dict[str, dict]] = defaultdict(dict)  # native id -> pool sha256 -> query -> files
    rows: dict[tuple[str, str, str], dict] = {}

    def add(inst: Instance, query: str, cell: str, row: dict) -> None:
        variant = "full" if query == inst.queries["full"] else "title"
        if query != inst.queries[variant]:
            raise ValueError(f"{inst.id}: the query is not the issue or its title: {query[:80]!r}")
        if (inst.id, variant, prefix + cell) in rows:
            raise ValueError(f"{inst.id}: two rows for {prefix + cell}@{variant}")
        rows[inst.id, variant, prefix + cell] = {"instance_id": inst.id, "variant": variant,
                                                 "cell": prefix + cell, **row}

    for folder, arms in (("pools", {"prior": "lexical"}), ("pools2", {"prior": "fused", "bm25": "bm25"})):
        for path in sorted((root / folder).glob("*.json")):
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            for case in json.loads(raw)["repos"][0]["queries"]:
                lexical = case["arms"]["prior"]
                pools[path.stem].setdefault(sha, {})[case["query"]] = lexical["files"]
                for arm, cell in arms.items():
                    add(by_native[path.stem], case["query"], cell, _pool_row(case["arms"][arm], sha))
                if folder == "pools":  # every gold file is a Python file
                    python = [f for f in lexical["files"] if f.endswith(".py")]
                    add(by_native[path.stem], case["query"], "lexpy", _pool_row({**lexical, "files": python}, sha))
    for folder in sorted(root.glob("trials*")):
        suffix = folder.name.removeprefix("trials").replace("-", "_")
        for path in sorted(folder.glob("*.json")):
            native, name = path.stem.rsplit("-", 1)
            trial = json.loads(path.read_text())
            pool = pools[native].get(trial["pool_sha256"])
            if pool is None:
                raise ValueError(f"{path}: the trial ran on a pool that is not in {root}")
            for case in trial["cases"]:
                add(by_native[native], case["query"], name + suffix,
                    _trial_row(case, pool[case["query"]], trial["pool_sha256"]))
    # A one-line issue has no separate title query, so its full rows are its title rows too.
    titled = {cell for _iid, variant, cell in rows if variant == "title"}
    for inst in instances:
        for cell in sorted(titled) if inst.queries["title"] == inst.queries["full"] else ():
            if (inst.id, "full", cell) in rows:
                rows[inst.id, "title", cell] = {**rows[inst.id, "full", cell], "variant": "title"}
    return instances, list(rows.values())


def _pack(name: str, root: Path) -> tuple[list[Instance], list[dict]]:
    instances = datasets.case_pack(name)
    known = {inst.id for inst in instances}
    pools: dict[str, dict[str, list[str]]] = {}  # pool sha256 -> instance id -> files
    rows: dict[tuple[str, str], dict] = {}
    trials = []

    def add(iid: str, cell: str, row: dict) -> None:
        if iid not in known:
            raise ValueError(f"{iid}: not in the {name} pack")
        if (iid, cell) in rows:
            raise ValueError(f"{iid}: two rows for {cell}")
        rows[iid, cell] = {"instance_id": iid, "variant": "full", "cell": cell, **row}

    for path in sorted(root.glob("*.json")):
        raw = path.read_bytes()
        data = json.loads(raw)
        if isinstance(data, dict) and "repos" in data:  # an eval.ranking_pair pool
            sha, cell = hashlib.sha256(raw).hexdigest(), "lexical" if path.stem == "pool" else path.stem
            pools[sha] = {}
            for repo in data["repos"]:
                for case in repo["queries"]:
                    iid = f"{name}/{repo['repo']}::{case['query']}"
                    pools[sha][iid] = case["arms"]["prior"]["files"]
                    add(iid, cell, _pool_row(case["arms"]["prior"], sha))
        elif isinstance(data, dict) and "cases" in data:  # a trial or dense output on one of the pools
            trials.append((path, data))
    for path, trial in trials:
        pool = pools.get(trial["pool_sha256"])
        if pool is None:
            raise ValueError(f"{path}: the trial ran on a pool that is not in {root}")
        for case in trial["cases"]:
            iid = f"{name}/{case['repo']}::{case['query']}"
            add(iid, path.stem, _trial_row(case, pool[iid], trial["pool_sha256"]))
    return instances, list(rows.values())


def import_legacy(out: Path, locbench: list[str], packs: list[str]) -> None:
    loaded = []
    for item in locbench:
        prefix, _, path = item.rpartition("=")
        loaded.append(_locbench(Path(path).expanduser(), f"{prefix}." if prefix else ""))
    for item in packs:
        name, _, path = item.partition("=")
        loaded.append(_pack(name, Path(path).expanduser()))
    instances: dict[str, Instance] = {}
    rows = []
    for found, more in loaded:
        for inst in found:
            if instances.setdefault(inst.id, inst) != inst:
                raise ValueError(f"{inst.id}: two inputs disagree on this instance")
        rows += more
    twice = [key for key, n in Counter((r["instance_id"], r["variant"], r["cell"]) for r in rows).items() if n > 1]
    if twice:
        raise ValueError(f"{len(twice)} rows come from two inputs, such as {twice[0]}. Give each run a prefix.")
    out.mkdir(parents=True, exist_ok=True)
    (out / "instances.jsonl").write_text("".join(json.dumps(asdict(inst)) + "\n" for inst in instances.values()))
    (out / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    counts = Counter((r["instance_id"].split("/")[0], r["cell"], r["variant"], r["status"]) for r in rows)
    for (dataset, cell, variant, status), n in sorted(counts.items()):
        print(f"{dataset}\t{cell}@{variant}\t{status}\t{n}")
    print(f"{len(instances)} instances and {len(rows)} rows in {out}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()
    return git("rev-parse", "HEAD") + (" with uncommitted changes" if git("status", "--porcelain", "-uno") else "")


def report(args: argparse.Namespace) -> None:
    instances = [Instance(**json.loads(line)) for line in (args.out / "instances.jsonl").read_text().splitlines()]
    rows = [json.loads(line) for line in (args.out / "results.jsonl").read_text().splitlines()]
    unknown = {r["instance_id"] for r in rows} - {inst.id for inst in instances}
    if unknown:
        raise SystemExit(f"{len(unknown)} result instances are not in instances.jsonl, such as {min(unknown)}")
    if args.ids:  # full ids, or native ids as in the old Loc-Bench id files
        keep = {line.strip() for line in args.ids.read_text().splitlines() if line.strip()}
        unmatched = keep - {name for inst in instances for name in (inst.id, inst.id.split("/", 1)[1])}
        if unmatched:
            raise SystemExit(f"{len(unmatched)} ids in {args.ids} match no instance, such as {min(unmatched)}")
        instances = [inst for inst in instances if inst.id in keep or inst.id.split("/", 1)[1] in keep]
    pairs = [tuple(item.split(":", 1)) for item in args.pair]
    cells = set(args.cells.split(",")) if args.cells else {r["cell"] for r in rows}
    if args.baseline:
        pairs = [(cell, args.baseline) for cell in sorted(cells - {args.baseline})] + pairs
    cells |= {cell for pair in pairs for cell in pair}
    absent = cells - {r["cell"] for r in rows}
    if absent:
        raise SystemExit(f"no rows for cells {sorted(absent)}")
    selected = {inst.id for inst in instances}
    rows = [r for r in rows if r["cell"] in cells and r["instance_id"] in selected]
    try:
        summary = stats.score(instances, rows, pairs, metrics=args.metric, partial=args.partial,
                              draws=args.draws, seed=args.seed)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    header = [f"Commit: {_commit()}",
              *(f"Input: {path} (sha256 {_sha256(path)[:12]})"
                for path in (args.out / "instances.jsonl", args.out / "results.jsonl")),
              f"Scored: {len(rows)} rows on {len(instances)} instances"
              + (f" from {args.ids}" if args.ids else "") + ".",
              f"Bootstrap and sign flips: {args.draws:,} draws each, seed {args.seed}."]
    output = args.output or args.out / "report.md"
    output.write_text(stats.render(summary, header))
    print(f"wrote {output}")
    if args.unjudged:  # arm-blind: the list does not say which cell returned a file
        grades = {inst.id: inst.grades for inst in instances if inst.grades is not None}
        todo = defaultdict(set)
        for r in rows:
            if r["instance_id"] in grades:
                todo[r["instance_id"]].update(p for p in r["files"][:5] if p not in grades[r["instance_id"]])
        args.unjudged.write_text(yaml.safe_dump({iid: sorted(paths) for iid, paths in sorted(todo.items()) if paths}))
        print(f"wrote {args.unjudged}: {sum(map(len, todo.values()))} unjudged files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    legacy = commands.add_parser("import-legacy", help="convert the pools and trials of earlier runs")
    legacy.add_argument("out", type=Path)
    legacy.add_argument("--locbench", action="append", default=[], metavar="[PREFIX=]DIR")
    legacy.add_argument("--pack", action="append", default=[], metavar="NAME=DIR",
                        help=f"NAME is one of {', '.join(datasets.PACKS)}")
    scoring = commands.add_parser("report", aliases=["score"], help="score the rows and write report.md")
    scoring.add_argument("out", type=Path)
    scoring.add_argument("--cells", help="comma-separated cells (default: all)")
    scoring.add_argument("--baseline", help="compare every other cell with this cell")
    scoring.add_argument("--pair", action="append", default=[], metavar="CELL:BASELINE")
    scoring.add_argument("--metric", action="append", default=[], choices=list(stats.METRICS),
                         help="compare on this metric (default: the primary metric of each dataset)")
    scoring.add_argument("--ids", type=Path, help="score only the instance ids in this file, one per line")
    scoring.add_argument("--partial", action="store_true",
                         help="score cells that miss rows, and stamp every table PARTIAL")
    scoring.add_argument("--unjudged", type=Path, help="write the unjudged first-five files of graded rows")
    scoring.add_argument("--output", type=Path, help="default: OUT/report.md")
    scoring.add_argument("--draws", type=int, default=10_000)
    scoring.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.command == "import-legacy":
        unknown = [item for item in args.pack if item.partition("=")[0] not in datasets.PACKS]
        if unknown:
            parser.error(f"unknown pack in {unknown}. Known packs: {', '.join(datasets.PACKS)}")
        import_legacy(args.out, args.locbench, args.pack)
    else:
        report(args)


if __name__ == "__main__":
    main()
