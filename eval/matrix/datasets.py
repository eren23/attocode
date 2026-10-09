"""Instances of the eval matrix: one record shape for every dataset.

An instance id is ``dataset/native_id``. ``repo`` is the source repository. It is the
cluster unit of every bootstrap and permutation test, because instances of one
repository are not independent. ``split`` comes from a hash of the id, so a change to a
dataset does not move other instances between dev and holdout.

``load`` reads one dataset of ``configs/full.yaml``: Hugging Face files pinned to a commit,
or a case pack with a pinned commit per repository. ``core_mix`` draws the stratified core
sample that the paid arms run on.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import yaml

from eval.meta_harness.splits import assign_split

_EVALS = Path(__file__).resolve().parents[2] / "packages/code-intel/evals"
PACKS = {  # dataset name -> case pack
    "graded_blind": _EVALS / "graded_blind_pack.yaml",
    "locbench_title": _EVALS / "locbench_title_pack.yaml",
    "broad_dev": _EVALS / "broad_query_cases.yaml",
    "broad_external": _EVALS / "broad_query_external_cases.yaml",
    "broad_holdout": _EVALS / "broad_query_final_holdout.yaml",
}
# Dataset language names (PolyBench field, LCA config, Live file) -> one name per language.
LANGUAGES = {"py": "python", "python": "python", "java": "java", "kt": "kotlin", "js": "javascript",
             "javascript": "javascript", "ts": "typescript", "typescript": "typescript", "c": "c",
             "cpp": "cpp", "cs": "csharp", "go": "go", "rust": "rust"}
# Core-mix quota per dataset. None takes every instance.
CORE = {"locbench": 80, "lite": 40, "lca": 60, "polybench": 60, "live": 60,
        "graded_blind": None, "broad_dev": None, "broad_external": None, "broad_holdout": None}
_literal = ast.literal_eval  # LCA keeps changed_files as the repr of a Python list


@dataclass(slots=True)
class Instance:
    id: str
    repo: str
    base_commit: str
    language: str
    category: str
    created_at: str
    queries: dict[str, str]  # variant -> query
    gold: list[str]
    grades: dict[str, int] | None  # judged file -> grade 0 to 3, or None for binary gold
    split: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.split = self.split or ("holdout" if assign_split(self.id, 0.3) == "eval" else "dev")

    @property
    def dataset(self) -> str:
        return self.id.split("/", 1)[0]


def title(statement: str) -> str:
    """The first line of an issue, without heading marks and a leading [tag]."""
    first = statement.strip().splitlines()[0].strip().strip("#").strip()
    return re.sub(r"^\[[^\]]+\]\s*", "", first)


def _iso(value: int | str | datetime) -> str:
    """A time as ISO 8601 UTC: epoch milliseconds, an ISO string, or a datetime."""
    if isinstance(value, int):
        value = datetime.fromtimestamp(value / 1000, UTC)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value)
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instance(dataset: str, native: str, repo: str, commit: str, language: str, category: str,
              created: int | str | datetime, issue: str, gold: list[str]) -> Instance:
    short = title(issue)
    return Instance(
        id=f"{dataset}/{native}", repo=repo, base_commit=commit, language=language, category=category,
        created_at=_iso(created),
        # A one-line issue has no separate title: its title query is the issue.
        queries={"full": issue, "title": short if short and short != issue.strip() else issue},
        gold=gold, grades=None)


def _edit_files(row: dict) -> list[str]:
    return sorted({f.split(":")[0] for f in row["edit_functions"]})


def locbench(rows: list[dict]) -> list[Instance]:
    """Loc-Bench V1 rows (czlll/Loc-Bench_V1). Gold: the unique files of edit_functions, as LocAgent scores."""
    return [_instance("locbench", r["instance_id"], r["repo"], r["base_commit"], "python", r["category"],
                      int(r["created_at"]), r["problem_statement"], _edit_files(r)) for r in rows]


def lite(rows: list[dict]) -> list[Instance]:
    """SWE-bench Lite in the LocAgent copy (czlll/SWE-bench_Lite). Gold: the edit_functions files."""
    return [_instance("lite", r["instance_id"], r["repo"], r["base_commit"], "python", "", r["created_at"],
                      r["problem_statement"], _edit_files(r)) for r in rows]


def _is_test(path: str) -> bool:
    """A test file, by a frozen path rule. It is not the product rule, so gold does not move with the product.

    A test file is in a test, tests or __tests__ folder, or in a folder directly under src/ that ends in
    Test (androidTest, jvmTest, commonTest, integrationTest). Or its name is test_*.py, *_test.py,
    conftest.py, *Test.java, *Tests.java, *Test.kt or *Tests.kt. A testing/ folder is source (numpy.testing).
    """
    *folders, name = path.split("/")
    return (any(part in ("test", "tests", "__tests__") for part in folders)
            or any(parent == "src" and part.endswith("Test") for parent, part in pairwise(folders))
            or re.fullmatch(r"test_.*\.py|.*_test\.py|conftest\.py|.*Tests?\.(?:java|kt)", name) is not None)


def lca_gold(row: dict) -> tuple[list[str], list[str]]:
    """The gold files and the dropped test files of an LCA row.

    LCA lists changed test files in changed_files. Gold keeps the changed files that the diff has in the
    base tree (a renamed file by its old path), without test files. So LCA gold has the same meaning as
    the non-test patch of the other datasets.
    """
    changed = set(_literal(row["changed_files"]))
    files = list(dict.fromkeys(old for old, new in patch_files(row["diff"]) if old and (old in changed or new in changed)))
    return [path for path in files if not _is_test(path)], [path for path in files if _is_test(path)]


def lca(rows: list[dict]) -> list[Instance]:
    """Long Code Arena bug localization, one test file per language. The native id is owner__name-pull-issue.

    Gold: ``lca_gold``, the changed non-test files of the base tree. An instance that changes only test
    files has no gold, so ingest excludes it.
    """
    out = []
    for r in rows:
        owner, name, pull, issue = r["text_id"].split("/")
        # LCA keeps the pull request time at 10**6-second resolution: its millisecond timestamp column
        # holds epoch seconds / 1000. So 1970-01-01 00:23:39 is 1,419,000,000 s, 2014-12-19 (the pull
        # request is from 2014-12-29). A date can be up to 11.6 days early.
        seconds = (r["pull_create_at"] - datetime(1970, 1, 1)) // timedelta(microseconds=1)
        out.append(_instance("lca", f"{owner}__{name}-{pull}-{issue}", f"{owner}/{name}", r["base_sha"],
                             LANGUAGES[r["_file"].split("/")[0]], "", datetime.fromtimestamp(seconds, UTC),
                             f"{r['issue_title']}\n{r['issue_body'] or ''}".strip(), lca_gold(r)[0]))
    return out


def polybench(rows: list[dict]) -> list[Instance]:
    """SWE-PolyBench Verified. Gold: the base-tree files that the (non-test) patch changes."""
    return [_instance("polybench", r["instance_id"], r["repo"], r["base_commit"], LANGUAGES[r["language"].lower()],
                      r["task_category"], r["created_at"], r["problem_statement"], patch_gold(r["patch"]))
            for r in rows]


def live(rows: list[dict]) -> list[Instance]:
    """SWE-bench-Live MultiLang, one file per language. Gold: the base-tree files that the patch changes."""
    return [_instance("live", r["instance_id"], r["repo"], r["base_commit"],
                      LANGUAGES[Path(r["_file"]).name.split("-")[0]], "", r["created_at"], r["problem_statement"],
                      patch_gold(r["patch"])) for r in rows]


def _unquote(path: str) -> str:
    """A path as git prints it: in double quotes with C escapes when it has special characters."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    return path[1:-1].encode().decode("unicode_escape").encode("latin-1").decode("utf-8")


def _side(token: str) -> str | None:
    """The path of a ---, +++ or Binary token. None for /dev/null."""
    path = _unquote(token.split("\t")[0])  # a tab ends the path (a timestamp, or nothing)
    return None if path == "/dev/null" else re.sub(r"^[ab]/", "", path)


def _header(rest: str) -> tuple[str | None, str | None]:
    """Both paths of ``diff --git a/P b/P`` when they are the same path. A rename has its own lines."""
    if rest.startswith('"') and '" "' in rest:
        old, new = rest.split('" "', 1)
        return _side(old + '"'), _side('"' + new)
    half = (len(rest) - 1) // 2
    old, new = rest[:half], rest[half + 1:]
    return (old[2:], new[2:]) if old[:2] == "a/" and new[:2] == "b/" and old[2:] == new[2:] else (None, None)


def patch_files(patch: str) -> list[tuple[str | None, str | None]]:
    """(old path, new path) of each file in a git diff. None: the file does not exist on that side."""
    out = []
    for section in re.split(r"^diff --git ", patch, flags=re.M)[1:]:
        first, *lines = section.splitlines()
        old, new = _header(first)
        created = False
        for line in lines:
            if line.startswith("@@"):  # hunk lines can look like headers ("--- x" removes "-- x")
                break
            if line.startswith("--- "):
                old = _side(line[4:])
            elif line.startswith("+++ "):
                new = _side(line[4:])
            elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                kind, side, path = line.split(" ", 2)
                if side == "from":
                    old = _unquote(path)
                else:
                    new = _unquote(path)
                created = created or kind == "copy"  # a copy leaves its source unchanged
            elif line.startswith("new file mode"):
                created = True
            elif line.startswith("deleted file mode"):
                new = None
            elif match := re.match(r"Binary files (.+) and (.+) differ$", line):
                old, new = _side(match[1]), _side(match[2])
        out.append((None if created else old, new))
    return out


def patch_gold(patch: str) -> list[str]:
    """The base-tree files that a patch changes: modified and deleted files, and renamed files by old path.

    A new file is not gold: the base tree does not have it, so no search can return it.
    """
    return list(dict.fromkeys(old for old, _new in patch_files(patch) if old))


def search_coverage(path: str) -> str:
    """How product search treats a gold file, by the file discovery rules of codebase_context.

    "skipped": discovery never reads the file (a skipped name, extension or folder, or a hidden path).
    "text_only": the product has no parser for the extension, so search sees the path and text
    windows only, with no symbols and no whole-file BM25. "parsed": a file with a language.
    Size limits and .gitignore rules also skip files. They need the tree, so this check does not see them.
    """
    from attocode_intel._internal.integrations.context.codebase_context import (
        DEFAULT_IGNORES,
        EXTENSION_LANGUAGES,
        SKIP_EXTENSIONS,
        SKIP_FILENAMES,
    )

    *folders, name = path.split("/")
    ext = os.path.splitext(name)[1].lower()
    if (name.startswith(".") or name in SKIP_FILENAMES or ext in SKIP_EXTENSIONS
            or any(part in DEFAULT_IGNORES or part.startswith(".") for part in folders)):
        return "skipped"
    return "parsed" if ext in EXTENSION_LANGUAGES else "text_only"


def labels(relevant_files: list[str] | dict[str, int]) -> tuple[list[str], dict[str, int] | None]:
    """Gold files and grades of a case. A list is binary gold. A dict grades files 0 to 3 (0: judged irrelevant)."""
    if isinstance(relevant_files, dict):
        return [path for path, grade in relevant_files.items() if grade > 0], dict(relevant_files)
    return list(dict.fromkeys(relevant_files)), None


def case_pack(name: str, path: Path | None = None) -> list[Instance]:
    """Instances of a case pack, ``repos: {key: [{query, relevant_files, ...}]}``.

    The native id is ``key::query``. The cluster is the case's ``source_repo`` when it has one
    (a Loc-Bench pack, where each key is one instance), else the key.
    """
    out = []
    for key, cases in yaml.safe_load((path or PACKS[name]).read_text())["repos"].items():
        for case in cases:
            gold, grades = labels(case["relevant_files"])
            out.append(Instance(
                id=f"{name}/{key}::{case['query']}", repo=case.get("source_repo", key),
                base_commit=case.get("base_commit", ""), language="", category=case.get("intent", ""),
                created_at="", queries={"full": case["query"]}, gold=gold, grades=grades))
    return out


ADAPTERS = {"locbench": locbench, "lite": lite, "lca": lca, "polybench": polybench, "live": live}
_FIELDS = {  # the columns that each adapter reads. The files also hold large columns that it does not read.
    "locbench": ["instance_id", "repo", "base_commit", "category", "created_at", "problem_statement",
                 "edit_functions"],
    "lite": ["instance_id", "repo", "base_commit", "created_at", "problem_statement", "edit_functions"],
    "lca": ["text_id", "base_sha", "pull_create_at", "issue_title", "issue_body", "diff", "changed_files"],
    "polybench": None,  # a CSV file
    "live": ["instance_id", "repo", "base_commit", "created_at", "problem_statement", "patch"],
}


def read_rows(path: Path, columns: list[str] | None = None) -> list[dict]:
    """Rows of a parquet, CSV or JSON-lines file."""
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise SystemExit(f"{path.name} is a parquet file. Reading it needs pyarrow, so run ingest as: uv run "
                             "--no-project --python .venv/bin/python --with pyarrow python -m eval.matrix.run ingest"
                             ) from None
        return pq.read_table(path, columns=columns).to_pylist()
    if path.suffix == ".csv":
        csv.field_size_limit(sys.maxsize)
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with urllib.request.urlopen(url, timeout=300) as response, part.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    part.replace(path)


def read(name: str, entry: dict, store: Path) -> list[dict]:
    """The rows of a Hugging Face registry dataset, each with its file in ``_file``. A missing file is downloaded."""
    folder, rows = store / f"{name}@{entry['revision']}", []
    for file in entry["files"]:
        path = folder / file
        if not path.exists():
            _download(f"https://huggingface.co/datasets/{entry['hf']}/resolve/{entry['revision']}/{file}", path)
        rows += [{**row, "_file": file} for row in read_rows(path, _FIELDS[name])]
    return rows


def load(name: str, entry: dict, store: Path) -> list[Instance]:
    """The instances of one registry dataset. A missing Hugging Face file is downloaded to store first."""
    if name in PACKS:
        out = case_pack(name)
        for inst in out:  # a pack pins one commit and one language per repository
            inst.base_commit = inst.base_commit or entry["commits"][inst.repo]
            inst.language = entry["languages"][inst.repo]
        return out
    return ADAPTERS[name](read(name, entry, store))


def _rank(seed: int, salt: str, iid: str) -> str:
    return hashlib.sha256(f"{seed}:{salt}:{iid}".encode()).hexdigest()


def core_mix(instances: list[Instance], seed: int = 7, quotas: dict[str, int | None] = CORE) -> list[str]:
    """The core sample that the paid arms run on, as sorted ids.

    A dataset quota is split over its language x category strata in proportion to their size, by
    largest remainder. A stratum takes its instances in the order of a seeded hash of the id. A
    repository gives at most twice its even share of the quota (at least 2), so that a few large
    repositories do not dominate the repository bootstrap. Seats that this cap leaves empty go to
    the next instances of the dataset in hash order.
    """
    by_dataset: dict[str, list[Instance]] = defaultdict(list)
    for inst in sorted(instances, key=lambda inst: (_rank(seed, "core", inst.id), inst.id)):
        by_dataset[inst.dataset].append(inst)
    chosen: list[str] = []
    for name, quota in sorted(quotas.items()):
        pool = by_dataset.get(name, [])
        if quota is None or quota >= len(pool):
            chosen += [inst.id for inst in pool]
            continue
        cap = max(2, math.ceil(2 * quota / len({inst.repo for inst in pool})))
        strata: dict[tuple[str, str], list[Instance]] = defaultdict(list)
        for inst in pool:
            strata[inst.language, inst.category].append(inst)
        shares = {key: quota * len(members) / len(pool) for key, members in strata.items()}
        seats = {key: math.floor(share) for key, share in shares.items()}
        for key in sorted(shares, key=lambda key: (seats[key] - shares[key], key))[:quota - sum(seats.values())]:
            seats[key] += 1
        taken: dict[str, None] = {}
        per_repo: Counter[str] = Counter()
        for key, members in sorted(strata.items()):
            for inst in members:
                if seats[key] and per_repo[inst.repo] < cap:
                    taken[inst.id], seats[key] = None, seats[key] - 1
                    per_repo[inst.repo] += 1
        for inst in pool:
            if len(taken) < quota and inst.id not in taken and per_repo[inst.repo] < cap:
                taken[inst.id] = None
                per_repo[inst.repo] += 1
        if len(taken) < quota:
            raise ValueError(f"{name}: at most {cap} instances per repository fill {len(taken)} of {quota} core seats")
        chosen += taken
    return sorted(chosen)


def noise50(core: list[str], seed: int = 7) -> list[str]:
    """The 50 core ids with the lowest seeded hash: the fixed subset for repeats of stochastic arms."""
    return sorted(sorted(core, key=lambda iid: (_rank(seed, "noise50", iid), iid))[:50])
