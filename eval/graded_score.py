"""Score frozen-pool rerank trials against graded, pooled judgments.

Inputs are a graded case pack (``relevant_files: {path: 0..3}``), the
``eval.ranking_pair`` pool JSON, and any number of ``eval.model_rerank_trial``
outputs. A metric is not scored while a first-five file is unjudged, so first
run with ``--unjudged`` to list every unjudged file in any arm's first five,
judge those without knowing which arm produced them, add the grades to the pack,
and rerun. A trial must come from the same pool file; pass a trial that ran on
another pool (a dense or fused pool) with ``--cross-pool-trial``.

Example:
    .venv/bin/python -m eval.graded_score --pack packages/code-intel/evals/graded_blind_pack.yaml \
      --pool pool.json --trial jev12=jev12.json --trial jev24=jev24.json --unjudged todo.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

import yaml

from eval.metrics import compute_graded_ndcg, compute_mrr, compute_recall_at_k

POOL_DEPTHS = (5, 12, 24, 48)


def _grades(pack: dict) -> dict[str, dict[str, int]]:
    return {f"{repo}::{case['query']}": (dict(case["relevant_files"])
                                          if isinstance(case["relevant_files"], dict)
                                          else dict.fromkeys(case["relevant_files"], 1))
            for repo, cases in pack["repos"].items() for case in cases}


def _metrics(files: list[str], grades: dict[str, int]) -> dict:
    primary = {path for path, grade in grades.items() if grade >= 2}
    relevant = {path for path, grade in grades.items() if grade >= 1}
    if not all(path in grades for path in files[:5]):
        return dict.fromkeys(("gndcg5", "mrr5_primary", "recall5"))  # an unjudged file could be primary
    return {
        "gndcg5": compute_graded_ndcg(files, grades, 5),
        "mrr5_primary": compute_mrr(files, primary, 5),
        "recall5": compute_recall_at_k(files, relevant, 5),
    }


def _bootstrap(deltas: dict[str, list[float]], draws: int = 10000) -> tuple[float, float]:
    """Repository-cluster percentile interval for the mean paired delta."""
    rng, repos = random.Random(0), sorted(deltas)
    means = []
    for _ in range(draws):
        sample = [d for repo in rng.choices(repos, k=len(repos)) for d in deltas[repo]]
        means.append(statistics.mean(sample))
    means.sort()
    return round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)


def score(pack: dict, pool: dict, trials: dict[str, dict], pool_sha256: str | None = None,
          cross_pool: frozenset[str] = frozenset()) -> dict:
    grades = _grades(pack)
    pool_rows = {f"{repo['repo']}::{case['query']}": (repo["repo"], case)
                 for repo in pool["repos"] for case in repo["queries"]}
    # Known-positive capture: judging stopped at each arm's first five, so this is not exhaustive recall.
    report: dict = {"known_primary_capture": {}, "arms": {}, "unjudged": defaultdict(set)}

    for depth in POOL_DEPTHS:
        hits = [compute_recall_at_k(case["arms"]["prior"]["files"],
                                    {p for p, g in grades[key].items() if g >= 2}, depth)
                for key, (_repo, case) in pool_rows.items()]
        report["known_primary_capture"][f"primary@{depth}"] = round(statistics.mean(hits), 4)

    rankings = {"baseline": {key: case["arms"]["prior"]["files"] for key, (_r, case) in pool_rows.items()}}
    latency = {}
    for name, trial in trials.items():
        if name not in cross_pool and trial["pool_sha256"] != pool_sha256:
            raise ValueError(f"{name}: trial ran on another pool; pass it as a cross-pool trial")
        keys = [f"{row['repo']}::{row['query']}" for row in trial["cases"]]
        if len(keys) != len(set(keys)) or not set(pool_rows) <= set(keys):
            raise ValueError(f"{name}: trial must hold every pool case exactly once")
        rankings[name] = {key: row["ranked_files"] for key, row in zip(keys, trial["cases"], strict=True)
                          if key in pool_rows}  # a cross-pool trial may cover more cases
        latency[name] = trial["summary"]
    for ranked in rankings.values():
        for key, files in ranked.items():
            for path in files[:5]:
                if path not in grades[key]:
                    report["unjudged"][key].add(path)

    base = {key: _metrics(files, grades[key]) for key, files in rankings["baseline"].items()}
    for name, ranked in rankings.items():
        rows = {key: _metrics(files, grades[key]) for key, files in ranked.items()}
        arm: dict = {"cases": len(rows)}
        for metric in ("gndcg5", "mrr5_primary", "recall5"):
            pairs = [(key, base[key][metric], row[metric]) for key, row in rows.items()
                     if row[metric] is not None and base[key][metric] is not None]
            if not pairs:
                arm[metric] = None
                continue
            deltas = defaultdict(list)
            for key, before, after in pairs:
                deltas[pool_rows[key][0]].append(after - before)
            arm[metric] = {
                "mean": round(statistics.mean(after for _k, _b, after in pairs), 4),
                "scored": len(pairs),
                "wins": sum(a > b + 1e-9 for _k, b, a in pairs),
                "losses": sum(a < b - 1e-9 for _k, b, a in pairs),
                "ci95_delta": _bootstrap(deltas) if name != "baseline" else None,
            }
        by_intent = defaultdict(list)
        for key, row in rows.items():
            if row["gndcg5"] is not None:
                by_intent[pool_rows[key][1].get("intent") or "unlabeled"].append(row["gndcg5"])
        arm["gndcg5_by_intent"] = {k: round(statistics.mean(v), 4) for k, v in sorted(by_intent.items())}
        if name in latency:
            arm["median_ms"] = latency[name]["median_inference_ms"]
            arm["p95_ms"] = latency[name]["p95_inference_ms"]
            arm["failures"] = latency[name]["failures"]
        report["arms"][name] = arm
    report["unjudged"] = {key: sorted(paths) for key, paths in sorted(report["unjudged"].items())}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--trial", action="append", default=[], help="name=trial.json; repeatable")
    parser.add_argument("--cross-pool-trial", action="append", default=[],
                        help="name=trial.json that ran on another pool of the same queries; repeatable")
    parser.add_argument("--unjudged", type=Path, help="Write unjudged first-five files, arm-blind")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    trials = {}
    for item in args.trial + args.cross_pool_trial:
        name, _, path = item.partition("=")
        trials[name] = json.loads(Path(path).read_text())
    cross = frozenset(item.partition("=")[0] for item in args.cross_pool_trial)
    pool_bytes = args.pool.read_bytes()
    report = score(yaml.safe_load(args.pack.read_text()), json.loads(pool_bytes), trials,
                   hashlib.sha256(pool_bytes).hexdigest(), cross)
    if args.unjudged:
        args.unjudged.write_text(yaml.safe_dump(report["unjudged"], sort_keys=True))
    summary = {k: v for k, v in report.items() if k != "unjudged"}
    summary["unjudged_files"] = sum(len(v) for v in report["unjudged"].values())
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
