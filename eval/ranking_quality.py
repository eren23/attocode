"""Offline, judged evaluation of code-intel candidate recall and final ranking.

The input files are JSONL. A judgment row has ``repo``, ``query_id``, and
``grades`` mapping stable file/symbol IDs to 0 (unrelated), 1 (background),
2 (useful support), or 3 (direct implementation). Optional ``category``
supports task-type slices. A run row has the same repo/query_id, ordered
``candidates`` and ``ranked`` IDs, and complete-tool ``latency_ms``. Every
candidate and returned result must be judged; unjudged is not grade zero.

Example::

    python -m eval.ranking_quality --judgments labels.jsonl --run baseline.jsonl
    python -m eval.ranking_quality --judgments labels.jsonl --run baseline.jsonl \
        --compare-run proposed.jsonl --require-same-candidates

This evaluator never runs a model, indexes a repository, or downloads weights.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eval.metrics import compute_graded_ndcg

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

QueryKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Judgment:
    repo: str
    query_id: str
    grades: Mapping[str, int]
    category: str = ""

    @property
    def key(self) -> QueryKey:
        return self.repo, self.query_id


@dataclass(frozen=True, slots=True)
class Observation:
    repo: str
    query_id: str
    candidates: tuple[str, ...]
    ranked: tuple[str, ...]
    latency_ms: float

    @property
    def key(self) -> QueryKey:
        return self.repo, self.query_id


def _ids(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{label} must be a list of nonempty IDs")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} contains duplicate IDs")
    return tuple(value)


def _identity(row: Mapping[str, Any]) -> QueryKey:
    repo, query_id = row.get("repo"), row.get("query_id")
    if not isinstance(repo, str) or not repo or not isinstance(query_id, str) or not query_id:
        raise ValueError("repo and query_id must be nonempty strings")
    return repo, query_id


def load_judgments(path: str | Path) -> dict[QueryKey, Judgment]:
    """Load a complete, uniquely keyed relevance pool."""
    rows: dict[QueryKey, Judgment] = {}
    for row in _read_jsonl(path):
        repo, query_id = _identity(row)
        grades = row.get("grades")
        if not isinstance(grades, dict) or any(
            not isinstance(doc_id, str) or not doc_id
            or not isinstance(grade, int) or isinstance(grade, bool) or grade not in range(4)
            for doc_id, grade in grades.items()
        ):
            raise ValueError(f"{(repo, query_id)}: grades must map IDs to integers 0–3")
        category = row.get("category", "")
        if not isinstance(category, str):
            raise ValueError(f"{(repo, query_id)}: category must be a string")
        key = repo, query_id
        if key in rows:
            raise ValueError(f"duplicate judgment: {key}")
        rows[key] = Judgment(repo, query_id, grades, category)
    if not rows:
        raise ValueError("judgment file is empty")
    return rows


def load_run(path: str | Path) -> dict[QueryKey, Observation]:
    """Load a uniquely keyed retrieval/ranking run."""
    rows: dict[QueryKey, Observation] = {}
    for row in _read_jsonl(path):
        repo, query_id = _identity(row)
        key = repo, query_id
        candidates = _ids(row.get("candidates"), f"{key} candidates")
        ranked = _ids(row.get("ranked"), f"{key} ranked")
        if not set(ranked).issubset(candidates):
            raise ValueError(f"{key}: ranked IDs must appear in candidates")
        latency = row.get("latency_ms")
        if (not isinstance(latency, (int, float)) or isinstance(latency, bool)
                or not math.isfinite(latency) or latency < 0):
            raise ValueError(f"{key}: latency_ms must be a finite, nonnegative number")
        if key in rows:
            raise ValueError(f"duplicate run observation: {key}")
        rows[key] = Observation(repo, query_id, candidates, ranked, float(latency))
    if not rows:
        raise ValueError("run file is empty")
    return rows


def _read_jsonl(path: str | Path) -> Iterable[Mapping[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            yield row


def _percentile(values: list[float], proportion: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = proportion * (len(ordered) - 1)
    lower = math.floor(index)
    fraction = index - lower
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * fraction


def score_query(judgment: Judgment, observation: Observation) -> dict[str, Any]:
    """Score one fully judged output; absence from the pool is an error."""
    if judgment.key != observation.key:
        raise ValueError("judgment and observation query IDs differ")
    unjudged = (set(observation.candidates) | set(observation.ranked)) - judgment.grades.keys()
    if unjudged:
        raise ValueError(f"{judgment.key}: unjudged IDs: {sorted(unjudged)}")

    direct = {doc_id for doc_id, grade in judgment.grades.items() if grade == 3}
    answerable = bool(direct)
    top_50 = observation.candidates[:50]
    top_3 = observation.ranked[:3]
    top_5 = observation.ranked[:5]
    return {
        "repo": judgment.repo,
        "query_id": judgment.query_id,
        "category": judgment.category,
        "answerable": answerable,
        "candidate_direct_recall_at_50": (
            len(direct.intersection(top_50)) / len(direct) if answerable else None
        ),
        "direct_success_at_3": bool(direct.intersection(top_3)) if answerable else None,
        "graded_ndcg_at_5": (
            compute_graded_ndcg(list(top_5), judgment.grades, k=5) if answerable else None
        ),
        "irrelevant_fraction_top_5": (
            sum(judgment.grades[doc_id] == 0 for doc_id in top_5) / len(top_5)
            if top_5 else 0.0
        ),
        "no_answer_false_positive": bool(observation.ranked) if not answerable else None,
        "latency_ms": observation.latency_ms,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["answerable"]]
    no_answer = [row for row in rows if not row["answerable"]]
    latencies = [row["latency_ms"] for row in rows]

    def mean(values: Iterable[float]) -> float | None:
        collected = list(values)
        return statistics.mean(collected) if collected else None

    return {
        "queries": len(rows),
        "answerable_queries": len(answerable),
        "no_answer_queries": len(no_answer),
        "candidate_direct_recall_at_50": mean(
            row["candidate_direct_recall_at_50"] for row in answerable
        ),
        "direct_success_at_3": mean(float(row["direct_success_at_3"]) for row in answerable),
        "graded_ndcg_at_5": mean(row["graded_ndcg_at_5"] for row in answerable),
        "irrelevant_fraction_top_5": mean(row["irrelevant_fraction_top_5"] for row in rows),
        "no_answer_false_positive_rate": mean(
            float(row["no_answer_false_positive"]) for row in no_answer
        ),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def evaluate_run(
    judgments: Mapping[QueryKey, Judgment],
    observations: Mapping[QueryKey, Observation],
) -> dict[str, Any]:
    """Evaluate candidate recall and returned ranking for identical query sets."""
    if judgments.keys() != observations.keys():
        missing = sorted(judgments.keys() - observations.keys())
        extra = sorted(observations.keys() - judgments.keys())
        raise ValueError(f"run/judgment query mismatch: missing={missing}, extra={extra}")
    per_query = [score_query(judgments[key], observations[key]) for key in sorted(judgments)]
    by_repo = {
        repo: _aggregate([row for row in per_query if row["repo"] == repo])
        for repo in sorted({row["repo"] for row in per_query})
    }
    by_category = {
        category: _aggregate([row for row in per_query if row["category"] == category])
        for category in sorted({row["category"] for row in per_query if row["category"]})
    }
    return {
        "schema_version": 1,
        "overall": _aggregate(per_query),
        "by_repo": by_repo,
        "by_category": by_category,
        "per_query": per_query,
    }


def compare_runs(
    baseline: Mapping[str, Any], proposed: Mapping[str, Any],
    *, samples: int = 1000, seed: int = 0,
) -> dict[str, Any]:
    """Paired, repository-cluster bootstrap comparison of judged query scores.

    Repositories are resampled as intact clusters. For a single-repository
    corpus, queries are resampled so the interval is not spuriously zero-width.
    This is descriptive evidence, not a substitute for a frozen holdout.
    """
    if samples <= 0:
        raise ValueError("samples must be positive")
    a = {(r["repo"], r["query_id"]): r for r in baseline["per_query"]}
    b = {(r["repo"], r["query_id"]): r for r in proposed["per_query"]}
    if not a or a.keys() != b.keys():
        raise ValueError("paired comparison requires identical nonempty query sets")
    repos = sorted({key[0] for key in a})
    keys_by_repo = {repo: sorted(key for key in a if key[0] == repo) for repo in repos}
    metric_names = (
        "candidate_direct_recall_at_50", "direct_success_at_3", "graded_ndcg_at_5",
        "irrelevant_fraction_top_5", "no_answer_false_positive_rate",
        "latency_p50_ms", "latency_p95_ms",
    )

    def deltas(keys: list[QueryKey]) -> dict[str, float | None]:
        before = _aggregate([a[key] for key in keys])
        after = _aggregate([b[key] for key in keys])
        return {
            name: (after[name] - before[name]
                   if before[name] is not None and after[name] is not None else None)
            for name in metric_names
        }

    observed = deltas(sorted(a))
    draws: dict[str, list[float]] = {name: [] for name in metric_names}
    random_state = random.Random(seed)
    for _ in range(samples):
        if len(repos) == 1:
            pool = keys_by_repo[repos[0]]
            sampled = random_state.choices(pool, k=len(pool))
        else:
            sampled_repos = random_state.choices(repos, k=len(repos))
            sampled = [key for repo in sampled_repos for key in keys_by_repo[repo]]
        for name, delta in deltas(sampled).items():
            if delta is not None:
                draws[name].append(delta)
    return {
        "paired_queries": len(a),
        "cluster_repositories": len(repos),
        "bootstrap_samples": samples,
        "seed": seed,
        "delta_proposed_minus_baseline": observed,
        "ci95": {
            name: [_percentile(values, 0.025), _percentile(values, 0.975)]
            if values else None
            for name, values in draws.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments", required=True, help="Graded judgment JSONL")
    parser.add_argument("--run", required=True, help="Baseline or standalone run JSONL")
    parser.add_argument("--compare-run", help="Optional proposed run JSONL")
    parser.add_argument("--require-same-candidates", action="store_true",
                        help="Reject candidate changes in a reranker-only comparison")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", help="Optional output JSON path; stdout remains available")
    args = parser.parse_args()

    judgments = load_judgments(args.judgments)
    baseline_run = load_run(args.run)
    result: dict[str, Any] = {
        "judgments": str(args.judgments),
        "baseline_run": str(args.run),
        "baseline": evaluate_run(judgments, baseline_run),
    }
    if args.compare_run:
        proposed_run = load_run(args.compare_run)
        if args.require_same_candidates and (
            baseline_run.keys() != proposed_run.keys() or any(
                baseline_run[key].candidates != proposed_run[key].candidates
                for key in baseline_run
            )
        ):
            raise ValueError("reranker-only comparison requires identical ordered candidates")
        proposed = evaluate_run(judgments, proposed_run)
        result["proposed_run"] = str(args.compare_run)
        result["proposed"] = proposed
        result["comparison"] = compare_runs(
            result["baseline"], proposed, samples=args.bootstrap_samples, seed=args.seed,
        )

    output = json.dumps(result, indent=2)
    if args.json:
        Path(args.json).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
