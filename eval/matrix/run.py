"""Eval matrix command line. Run it from the repository root.

  python -m eval.matrix.run import-legacy OUT [--locbench [PREFIX=]DIR ...] [--pack NAME=DIR ...]
      Convert the pools and trials of earlier runs into OUT/instances.jsonl and
      OUT/results.jsonl, with one row per (instance, query variant, cell).
  python -m eval.matrix.run ingest [OUT] [--config FILE]
      Read every dataset of the registry (default eval/matrix/configs/full.yaml), draw the
      core mix, and write OUT/instances.jsonl and OUT/ingest.md. Parquet files need pyarrow.
  python -m eval.matrix.run report OUT [--cells A,B] [--baseline CELL] [--pair CELL:BASELINE ...]
      [--metric NAME ...] [--ids FILE] [--partial] [--unjudged FILE] [--output FILE]
      Score OUT/results.jsonl against OUT/instances.jsonl and write OUT/report.md.
  python -m eval.matrix.run run OUT --stage snapshot|retrieve|rows [--arms A,B] [--ids FILE]
      [--dataset NAME] [--shard I/N] [--cache DIR] [--retry-failed]
      For the instances in OUT/instances.jsonl: save the files of each (repository, commit),
      run the first-stage arms on them, or write their rows to OUT/results.jsonl.
  python -m eval.matrix.run status OUT [--arms A,B] [--ids FILE] [--dataset NAME] [--cache DIR]
      Show the snapshot and retrieve coverage per dataset and cell.

A Loc-Bench folder is a run of eval/locbench560: all.json, pools/ (cell lexical, and cell
lexpy for its Python files), pools2/ (cells fused and bm25), trials/ (one cell per trial
name, such as jev24) and trials-q512/ (cells such as jev24_q512). PREFIX names the run in
its cells, as in body.jev24.

A case-pack folder holds frozen pools in the format of the deleted eval.ranking_pair
(pool.json is the lexical pool) and eval.model_rerank_trial outputs. The cell is the file
name.

The stages share a cache (default ~/Documents/AI/attocode-evals/matrix): trees/ lists the
files of each (repository, commit), blobs/ holds their contents by git blob id, and ret/
holds one result per (tree, arm family, family config, query). A file that exists is a
finished step, so a stopped shard continues where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zlib
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path, PurePosixPath

import yaml

from eval.matrix import arms, datasets, stats
from eval.matrix.datasets import Instance
from eval.meta_harness.splits import assign_split

REPO = Path(__file__).resolve().parents[2]
CORE_IDS = Path(__file__).resolve().parent / "core_ids.txt"
CACHE = Path.home() / "Documents/AI/attocode-evals/matrix"
# Read-only clone sources: case-pack repositories, then the Loc-Bench dev clones.
SOURCES = (Path.home() / "Documents/ai/benchmark-repos", Path.home() / "Documents/AI/attocode-evals/locbench/repos")
REMOTE = "https://github.com/{}.git"
PRODUCT = ("packages/code-intel/src",)  # the code that the engine hash covers
SNAPSHOT_VERSION = 1  # change it when the rule for saved files changes
MAX_BYTES = 1_000_000  # codebase_context.discover_files skips larger files
MIN_FREE = 25 * 2**30


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

    for folder, named in (("pools", {"prior": "lexical"}), ("pools2", {"prior": "fused", "bm25": "bm25"})):
        for path in sorted((root / folder).glob("*.json")):
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            for case in json.loads(raw)["repos"][0]["queries"]:
                lexical = case["arms"]["prior"]
                pools[path.stem].setdefault(sha, {})[case["query"]] = lexical["files"]
                for arm, cell in named.items():
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
        if isinstance(data, dict) and "repos" in data:  # a frozen lexical pool
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


def _instances(out: Path) -> list[Instance]:
    return [Instance(**json.loads(line)) for line in (out / "instances.jsonl").read_text().splitlines()]


def _select_ids(instances: list[Instance], ids: Path | None) -> list[Instance]:
    """The instances in an id file: full ids, or native ids as in the old Loc-Bench id files."""
    if ids is None:
        return instances
    keep = {line.strip() for line in ids.read_text().splitlines() if line.strip()}
    if not keep:
        raise SystemExit(f"{ids} has no instance ids")
    unmatched = keep - {name for inst in instances for name in (inst.id, inst.id.split("/", 1)[1])}
    if unmatched:
        raise SystemExit(f"{len(unmatched)} ids in {ids} match no instance, such as {min(unmatched)}")
    return [inst for inst in instances if inst.id in keep or inst.id.split("/", 1)[1] in keep]


def report(args: argparse.Namespace) -> None:
    instances = _instances(args.out)
    rows = [json.loads(line) for line in (args.out / "results.jsonl").read_text().splitlines()]
    unknown = {r["instance_id"] for r in rows} - {inst.id for inst in instances}
    if unknown:
        raise SystemExit(f"{len(unknown)} result instances are not in instances.jsonl, such as {min(unknown)}")
    instances = _select_ids(instances, args.ids)
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


def ingest(out: Path, config: Path, core_file: Path = CORE_IDS) -> None:
    """Read each registry dataset, draw the core mix, and write OUT/instances.jsonl and OUT/ingest.md.

    Downloads go to OUT/datasets. The first run writes core_file. A later run stops when its core
    mix differs from that file, because paid results are only comparable on the same core ids.
    """
    cfg = yaml.safe_load(config.read_text())
    run, store = cfg["run"], out / "datasets"
    found: dict[str, list[Instance]] = {}
    for name, entry in cfg["datasets"].items():
        found[name] = datasets.load(name, entry, store)
        kept = [inst for inst in found[name] if inst.gold]
        if kept and stats.primary_metric(kept) != entry["primary"]:
            raise SystemExit(f"{name}: the scorer uses {stats.primary_metric(kept)}, but the config says "
                             f"{entry['primary']}")
    instances = sorted((inst for insts in found.values() for inst in insts if inst.gold), key=lambda inst: inst.id)
    twice = [iid for iid, n in Counter(inst.id for inst in instances).items() if n > 1]
    if twice:
        raise SystemExit(f"{len(twice)} instance ids occur twice, such as {min(twice)}")
    core = datasets.core_mix(instances, seed=run["seed"])
    if not core_file.exists():
        core_file.write_text("".join(f"{iid}\n" for iid in core))
    elif core_file.read_text().splitlines() != core:
        raise SystemExit(f"The core mix differs from {core_file}, because a dataset or the sampler changed. "
                         "To draw a new core mix, delete the file. Then commit the new file.")
    tags = {"core": set(core), "noise50": set(datasets.noise50(core, seed=run["seed"]))}
    for inst in instances:
        inst.split = "holdout" if assign_split(inst.id, run["holdout"]) == "eval" else "dev"
        inst.tags = [tag for tag, ids in tags.items() if inst.id in ids]
    lca = cfg["datasets"].get("lca")
    lca_tests = sum(len(datasets.lca_gold(row)[1]) for row in datasets.read("lca", lca, store)) if lca else None
    out.mkdir(parents=True, exist_ok=True)
    (out / "instances.jsonl").write_text("".join(json.dumps(asdict(inst)) + "\n" for inst in instances))
    (out / "ingest.md").write_text(_ingest_report(config, cfg, store, found, instances, lca_tests))
    print(f"{len(instances)} instances, {len(core)} in the core mix: wrote {out / 'instances.jsonl'} and ingest.md")


def _ingest_report(config: Path, cfg: dict, store: Path, found: dict[str, list[Instance]],
                   instances: list[Instance], lca_tests: int | None) -> str:
    kept: dict[str, list[Instance]] = defaultdict(list)
    for inst in instances:
        kept[inst.dataset].append(inst)
    lines = ["# Eval matrix instances", "",
             f"Config: {config.name} (sha256 {_sha256(config)[:12]}). Commit: {_commit()}.",
             f"{len(instances):,} instances. Core mix: {sum('core' in i.tags for i in instances)} ids. "
             f"noise50: {sum('noise50' in i.tags for i in instances)} ids.", "",
             "| Dataset | Revision | Rows | Excluded | Instances | Repos | Holdout | Core | Languages |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, entry in cfg["datasets"].items():
        insts = kept[name]
        langs = ", ".join(f"{lang} {n}" for lang, n in sorted(Counter(i.language for i in insts).items()))
        lines.append(f"| {name} | {entry.get('revision', '')[:8] or 'pack'} | {len(found[name])} "
                     f"| {len(found[name]) - len(insts)} | {len(insts)} | {len({i.repo for i in insts})} "
                     f"| {sum(i.split == 'holdout' for i in insts)} | {sum('core' in i.tags for i in insts)} | {langs} |")
    lines += ["", "## Exclusions", "",
              "An instance is excluded when no gold file is in its base tree, for example when its patch "
              "only adds files. An LCA instance is also excluded when it changes only test files.", ""]
    lines += [f"- {name}: {', '.join(sorted(i.id for i in insts if not i.gold))}"
              for name, insts in found.items() if any(not i.gold for i in insts)] or ["- None."]
    if lca_tests is not None:
        lines += ["", f"LCA gold leaves out {lca_tests} changed test files (the frozen rule `datasets._is_test`)."]
    lines += ["", "## Gold files that search does not parse", "",
              "The path rules of the product file discovery (`codebase_context.py`). Skipped: search never "
              "reads the file. Text only: the product has no parser for the extension. Search then sees the "
              "path and text windows only, with no symbols and no whole-file BM25.", "",
              "| Dataset | Gold files | Skipped | Text only | Extensions |", "|---|---:|---:|---:|---|"]
    for name in cfg["datasets"]:
        cover, exts = Counter(), Counter()
        for path in (path for inst in kept[name] for path in inst.gold):
            kind = datasets.search_coverage(path)
            cover[kind] += 1
            if kind != "parsed":
                exts[f"{Path(path).suffix or Path(path).name} ({kind.replace('_', ' ')})"] += 1
        lines.append(f"| {name} | {sum(cover.values())} | {cover['skipped']} | {cover['text_only']} "
                     f"| {', '.join(f'{ext} {n}' for ext, n in exts.most_common())} |")
    lines += ["", "## Files", "", "| Dataset | File | sha256 |", "|---|---|---|"]
    for name, entry in cfg["datasets"].items():
        folder = store / f"{name}@{entry.get('revision')}"
        lines += [f"| {name} | {file} | {_sha256(folder / file)} |" for file in entry.get("files", [])]
    return "\n".join(lines) + "\n"


class _MissingFilesError(Exception):
    """A local clone does not have all the objects of a commit."""


def _write(path: Path, data: bytes) -> None:
    """Write a file in one step. A file that exists is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def _git(cwd: Path, *args: str, data: bytes | None = None) -> bytes:
    """Git without lazy fetches: a missing object in a local clone is an error, not a download."""
    return subprocess.run(["git", "-C", str(cwd), *args], input=data, capture_output=True, check=True,
                          env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}).stdout


def _refuse_dirty(repo: Path = REPO) -> str:
    """The commit of the product code. Results of uncommitted product code would not be reproducible."""
    changed = _git(repo, "status", "--porcelain", "--", *PRODUCT).decode().strip()
    if changed:
        raise SystemExit(f"commit the product changes first:\n{changed}")
    return _git(repo, "rev-parse", "HEAD").decode().strip()


def _tree_file(cache: Path, repo: str, commit: str) -> Path:
    return cache / "trees" / f"{repo.replace('/', '__')}@{commit or 'HEAD'}.json"


def _blob_file(cache: Path, oid: str) -> Path:
    return cache / "blobs" / oid[:2] / oid[2:]


def _ret_file(cache: Path, key: str) -> Path:
    return cache / "ret" / key[:2] / f"{key}.json"


def _key(tree: dict, family: str, query: str) -> str:
    """The cache key of a result: tree, arm family, family config and query."""
    ident = f"{tree['tree']}/v{tree['version']}" if "tree" in tree else f"failed:{tree['repo']}@{tree['requested']}"
    text = json.dumps({"tree": ident, "family": family, "config": arms.config(family), "query": query}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _stored(entry: list) -> bool:
    """A file that the product can index: a link, or a file of at most 1 MB that discovery does not skip."""
    from attocode_intel._internal.integrations.context.codebase_context import (
        SKIP_EXTENSIONS,
        SKIP_FILENAMES,
    )
    path, mode, _oid, size = entry
    name = PurePosixPath(path).name
    return mode == "120000" or (mode in ("100644", "100755") and 0 <= size <= MAX_BYTES
                                and PurePosixPath(name).suffix.lower() not in SKIP_EXTENSIONS
                                and name not in SKIP_FILENAMES)


def _read_tree(git_dir: Path, commit: str, cache: Path, *, remote: bool) -> dict:
    """List a commit and save the contents of its stored files.

    A remote clone omits blobs over 1 MB, so a missing blob there is a large file. A local
    clone must have every blob that the rule keeps.
    """
    sha = _git(git_dir, "rev-parse", "--verify", f"{commit or 'HEAD'}^{{commit}}").decode().strip()
    entries = []
    for record in _git(git_dir, "ls-tree", "-r", "-z", sha).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, _kind, oid = meta.decode().split()
            entries.append([os.fsdecode(path), mode, oid, 0])
    blobs = sorted({oid for _path, mode, oid, _size in entries if mode != "160000"})
    sizes = {}
    for line in _git(git_dir, "cat-file", "--batch-check", data="".join(o + "\n" for o in blobs).encode()).splitlines():
        oid, *rest = line.decode().split()
        sizes[oid] = int(rest[1]) if rest[0] == "blob" else -1  # -1: missing
    for entry in entries:
        entry[3] = sizes.get(entry[2], 0) if entry[1] != "160000" else 0
    if not remote and any(entry[3] < 0 and _stored([*entry[:3], 0]) for entry in entries):
        raise _MissingFilesError(f"{git_dir} does not have all files of {sha}")
    need = sorted({entry[2] for entry in entries if _stored(entry) and not _blob_file(cache, entry[2]).exists()})
    for start in range(0, len(need), 2000):
        out, pos = _git(git_dir, "cat-file", "--batch", data="".join(o + "\n" for o in need[start:start + 2000]).encode()), 0
        while pos < len(out):
            end = out.index(b"\n", pos)
            oid, _kind, size = out[pos:end].decode().split()
            _write(_blob_file(cache, oid), zlib.compress(out[end + 1:end + 1 + int(size)]))
            pos = end + 1 + int(size) + 1
    return {"commit": sha, "tree": _git(git_dir, "rev-parse", f"{sha}^{{tree}}").decode().strip(), "entries": entries}


def _local(repo: str, sources: tuple[Path, ...]) -> Path | None:
    """A local clone of a repository. A case-pack key names a benchmark repository."""
    if "/" not in repo:
        path = REPO if repo == "attocode" else sources[0] / repo
        return path if path.exists() else None
    for root in sources:
        path = root / repo.split("/")[1]
        try:
            url = _git(path, "remote", "get-url", "origin").decode().strip() if path.exists() else ""
        except subprocess.CalledProcessError:
            continue
        if url.removesuffix(".git").replace(":", "/").lower().endswith("github.com/" + repo.lower()):
            return path
    return None


def _remote(repo: str, tmp: Path) -> Path:
    """An empty partial clone that fetches files of at most 1 MB."""
    clone = tmp / "clone.git"
    if not clone.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(clone)], check=True)
        for key, value in (("core.repositoryformatversion", "1"), ("extensions.partialClone", "origin"),
                           ("remote.origin.url", REMOTE.format(repo)), ("remote.origin.promisor", "true"),
                           ("remote.origin.partialCloneFilter", f"blob:limit={MAX_BYTES + 1}")):
            _git(clone, "config", key, value)
    return clone


def _free(cache: Path) -> int:
    cache.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(cache).free


def _check_free(cache: Path) -> None:
    if _free(cache) < MIN_FREE:
        raise SystemExit(f"stopped: under {MIN_FREE / 2**30:.0f} GiB free on the disk of {cache}")


def snapshot(cache: Path, instances: list[Instance], sources: tuple[Path, ...] = SOURCES, *,
             retry_failed: bool = False) -> None:
    """Save the files of each (repository, commit), one clone at a time, and delete the clone."""
    wanted: dict[str, set[str]] = defaultdict(set)
    for inst in instances:
        wanted[inst.repo].add(inst.base_commit)

    def needed(path: Path) -> bool:
        return not path.exists() or (retry_failed and "error" in json.loads(path.read_text()))

    todo = {repo: sorted(c for c in commits if needed(_tree_file(cache, repo, c)))
            for repo, commits in sorted(wanted.items())}
    todo = {repo: commits for repo, commits in todo.items() if commits}
    count = sum(map(len, todo.values()))
    if not count:
        return
    trees = list((cache / "trees").glob("*.json"))
    per = (sum(f.stat().st_size for f in (cache / "blobs").rglob("*") if f.is_file()) / len(trees)
           if len(trees) >= 5 else 60 * 2**20)  # bytes per snapshot so far; dedup makes the next ones smaller
    projected, free = count * per + 2 * 2**30, _free(cache)  # plus one clone and one index
    print(f"snapshot: {count} to make, about {projected / 2**30:.1f} GiB; {free / 2**30:.1f} GiB free", flush=True)
    if free - projected < MIN_FREE:
        raise SystemExit(f"refused: the projection leaves under {MIN_FREE / 2**30:.0f} GiB free")
    for repo, commits in todo.items():
        local = _local(repo, sources)
        with tempfile.TemporaryDirectory(prefix=f"attocode-matrix-{os.getpid()}-") as tmp:
            clone = None
            for commit in commits:
                _check_free(cache)
                started, tree, source = time.time(), None, None
                if local is not None:
                    try:
                        tree, source = _read_tree(local, commit, cache, remote=False), str(local)
                    except (subprocess.CalledProcessError, _MissingFilesError):
                        tree = None
                if tree is None and "/" in repo and commit:
                    try:
                        clone = clone or _remote(repo, Path(tmp))
                        _git(clone, "fetch", "-q", "--depth", "1", f"--filter=blob:limit={MAX_BYTES + 1}",
                             "--no-tags", "origin", commit)
                        tree, source = _read_tree(clone, commit, cache, remote=True), REMOTE.format(repo)
                    except subprocess.CalledProcessError as error:
                        tree = {"error": f"git {error.cmd[3]}: {error.stderr.decode(errors='replace').strip()[:300]}"}
                tree = tree or {"error": "no local clone has this commit"}
                _write(_tree_file(cache, repo, commit), json.dumps(
                    {"repo": repo, "requested": commit, "source": source, "version": SNAPSHOT_VERSION, **tree}).encode())
                state = tree.get("error") or f"{sum(map(_stored, tree['entries']))} files"
                print(f"{repo}@{commit[:12] or 'HEAD'}: {state} ({time.time() - started:.0f} s)", flush=True)


def _materialize(cache: Path, tree: dict, root: Path) -> list[str]:
    """Write the stored files of a tree under root. Returns the regular files."""
    paths, links = [], []
    for entry in tree["entries"]:
        if not _stored(entry):
            continue
        path, mode, oid, _size = entry
        data = zlib.decompress(_blob_file(cache, oid).read_bytes())
        if mode == "120000":
            links.append((root / path, os.fsdecode(data)))
            continue
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
        paths.append(path)
    for target, destination in links:  # last, so that no file is written through a link
        target.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(target):
            os.symlink(destination, target)
    return paths


def retrieve(cache: Path, instances: list[Instance], cells: list[str], *, retry_failed: bool = False,
             repo: Path = REPO, timeout: float = 1800) -> None:
    """Run the first-stage families of the cells. One product index per snapshot serves all queries."""
    commit = _refuse_dirty(repo)
    families = sorted({arms.CELLS[cell][0] for cell in cells})
    groups: dict[tuple[str, str], list[Instance]] = defaultdict(list)
    for inst in instances:
        groups[inst.repo, inst.base_commit].append(inst)
    count = Counter()
    for (name, base), group in sorted(groups.items()):
        path = _tree_file(cache, name, base)
        if not path.exists():
            raise SystemExit(f"no snapshot of {name}@{base or 'HEAD'}: run --stage snapshot first")
        tree, jobs = json.loads(path.read_text()), {}
        for query in dict.fromkeys(q for inst in group for q in inst.queries.values()):
            for family in families:
                key = _key(tree, family, query)
                done = _ret_file(cache, key)
                if done.exists() and not (retry_failed and json.loads(done.read_text())["status"] != "ok"):
                    count["cached"] += 1
                    continue
                jobs[key] = (family, query)
        count["made"] += len(jobs)
        if not jobs:
            continue
        started, header = time.time(), {"tree": tree.get("tree"), "commit": commit}
        if "error" in tree:
            for key, (family, _query) in jobs.items():
                _write(_ret_file(cache, key), json.dumps({"status": "snapshot_failed", "error": tree["error"],
                                                          "lists": {}, "page": None, "ms": None, "family": family,
                                                          "config": arms.config(family), **header}).encode())
            continue
        _check_free(cache)
        root = Path(tempfile.mkdtemp(prefix=f"attocode-matrix-{os.getpid()}-"))
        snap = None
        try:
            snap = arms.Snapshot(root, _materialize(cache, tree, root), timeout)
            for key, (family, query) in sorted(jobs.items(), key=lambda item: (item[1][0], item[1][1])):
                try:
                    result = {"status": "ok", **arms.run(family, snap, query)}
                except arms.IndexFailedError as error:
                    result = {"status": "index_failed", "error": str(error), "lists": {}, "page": None, "ms": None}
                _write(_ret_file(cache, key), json.dumps(
                    {**result, "family": family, "config": arms.config(family), **header}).encode())
        finally:
            if snap is not None:
                snap.close()
            shutil.rmtree(root, ignore_errors=True)
        print(f"{name}@{base[:12] or 'HEAD'}: {len(jobs)} results, index {snap.index_s:.0f} s, "
              f"total {time.time() - started:.0f} s", flush=True)
    print(f"retrieve: {count['made']} results made, {count['cached']} from the cache")


def _entries(cache: Path, inst: Instance, cells: list[str]):
    """(variant, cell, key, result or None) for each query variant of an instance with a snapshot."""
    path = _tree_file(cache, inst.repo, inst.base_commit)
    if not path.exists():
        return
    tree = json.loads(path.read_text())
    for variant, query in inst.queries.items():
        for cell in cells:
            key = _key(tree, arms.CELLS[cell][0], query)
            done = _ret_file(cache, key)
            yield variant, cell, key, json.loads(done.read_text()) if done.exists() else None


def write_rows(out: Path, cache: Path, instances: list[Instance], cells: list[str]) -> None:
    """Replace the rows of these cells and instances in OUT/results.jsonl. A missing result has no row."""
    new, missing = {}, Counter()
    for inst in instances:
        for variant, cell, key, result in _entries(cache, inst, cells):
            if result is None:
                missing[cell] += 1
                continue
            new[inst.id, variant, cell] = {
                "instance_id": inst.id, "variant": variant, "cell": cell,
                "files": result["lists"].get(arms.CELLS[cell][1], []), "status": result["status"],
                "fallback_reason": result.get("error"), "latency_ms": result["ms"],
                "pool_sha256": key, "evidence_sha256": None}
    results = out / "results.jsonl"
    old = [json.loads(line) for line in results.read_text().splitlines()] if results.exists() else []
    rows = [r for r in old if (r["instance_id"], r["variant"], r["cell"]) not in new] + list(new.values())
    rows.sort(key=lambda r: (r["instance_id"], r["variant"], r["cell"]))
    _write(results, "".join(json.dumps(r) + "\n" for r in rows).encode())
    print(f"wrote {len(new)} rows to {results}" + "".join(f"; {cell}: {n} without a result"
                                                          for cell, n in sorted(missing.items())))


def status(cache: Path, instances: list[Instance], cells: list[str]) -> None:
    """Coverage per dataset: snapshots, then finished results per cell (failed ones in brackets)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for inst in instances:
        count = counts[inst.dataset]
        count["instances"] += 1
        path = _tree_file(cache, inst.repo, inst.base_commit)
        if path.exists():
            count["snapshots"] += 1
            count["snapshot errors"] += "error" in json.loads(path.read_text())
        for cell in cells:
            count[cell, "total"] += len(inst.queries)
        for _variant, cell, _key, result in _entries(cache, inst, cells):
            count[cell, "done"] += result is not None
            count[cell, "failed"] += result is not None and result["status"] != "ok"
    for dataset, count in sorted(counts.items()):
        print(f"{dataset}: {count['instances']} instances, {count['snapshots']} with a snapshot "
              f"({count['snapshot errors']} failed)")
        for cell in cells:
            print(f"  {cell}: {count[cell, 'done']}/{count[cell, 'total']} ({count[cell, 'failed']} failed)")


def stage(args: argparse.Namespace) -> None:
    instances = _select_ids(_instances(args.out), args.ids)
    if args.dataset:
        instances = [inst for inst in instances if inst.dataset == args.dataset]
    if getattr(args, "shard", None):
        index, count = map(int, args.shard.split("/"))
        repos = sorted({inst.repo for inst in instances})[index::count]
        instances = [inst for inst in instances if inst.repo in repos]
    cells = args.arms.split(",")
    unknown = [cell for cell in cells if cell not in arms.CELLS]
    if unknown:
        raise SystemExit(f"unknown arms {unknown}. Known arms: {', '.join(arms.CELLS)}")
    if args.command == "status":
        status(args.cache, instances, cells)
    elif args.stage == "snapshot":
        snapshot(args.cache, instances, retry_failed=args.retry_failed)
    elif args.stage == "retrieve":
        retrieve(args.cache, instances, cells, retry_failed=args.retry_failed)
    else:
        write_rows(args.out, args.cache, instances, cells)


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
    ingesting = commands.add_parser("ingest", help="read the registry datasets and write instances.jsonl")
    ingesting.add_argument("out", type=Path, nargs="?", default=Path.home() / "Documents/AI/attocode-evals/matrix")
    ingesting.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "configs/full.yaml")
    stages = commands.add_parser("run", help="snapshot repositories, run first-stage arms, or write their rows")
    coverage = commands.add_parser("status", help="show the snapshot and retrieve coverage")
    for sub in (stages, coverage):
        sub.add_argument("out", type=Path, help="the run folder, with instances.jsonl")
        sub.add_argument("--arms", default=",".join(arms.CELLS), help="comma-separated cells (default: all)")
        sub.add_argument("--ids", type=Path, help="only the instance ids in this file, one per line")
        sub.add_argument("--dataset", help="only the instances of this dataset")
        sub.add_argument("--cache", type=Path, default=CACHE, help=f"default: {CACHE}")
    stages.add_argument("--stage", required=True, choices=("snapshot", "retrieve", "rows"))
    stages.add_argument("--shard", default="0/1", help="I/N: repositories I, I+N, I+2N, ... in name order")
    stages.add_argument("--retry-failed", action="store_true", help="make failed snapshots and results again")
    args = parser.parse_args()
    if args.command == "import-legacy":
        unknown = [item for item in args.pack if item.partition("=")[0] not in datasets.PACKS]
        if unknown:
            parser.error(f"unknown pack in {unknown}. Known packs: {', '.join(datasets.PACKS)}")
        import_legacy(args.out, args.locbench, args.pack)
    elif args.command == "ingest":
        ingest(args.out, args.config)
    elif args.command in ("run", "status"):
        stage(args)
    else:
        report(args)


if __name__ == "__main__":
    main()
