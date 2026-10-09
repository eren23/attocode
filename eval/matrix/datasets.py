"""Instances of the eval matrix: one record shape for every dataset.

An instance id is ``dataset/native_id``. ``repo`` is the source repository. It is the
cluster unit of every bootstrap and permutation test, because instances of one
repository are not independent. ``split`` comes from a hash of the id, so a change to a
dataset does not move other instances between dev and holdout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
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


def locbench(rows: list[dict]) -> list[Instance]:
    """Loc-Bench V1 rows (czlll/Loc-Bench_V1). Gold: the unique files of edit_functions, as LocAgent scores."""
    out = []
    for r in rows:
        issue, short = r["problem_statement"], title(r["problem_statement"])
        created = datetime.fromtimestamp(int(r["created_at"]) / 1000, UTC)
        out.append(Instance(
            id=f"locbench/{r['instance_id']}", repo=r["repo"], base_commit=r["base_commit"],
            language="python", category=r["category"], created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            # A one-line issue has no separate title: its title query is the issue.
            queries={"full": issue, "title": short if short != issue.strip() else issue},
            gold=sorted({f.split(":")[0] for f in r["edit_functions"]}), grades=None))
    return out


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
