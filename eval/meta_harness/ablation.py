"""Ablation study for Phase 1/2 algorithmic signals.

Measures the contribution of each signal by running evaluation with it
toggled off. Reports per-signal delta vs the full-signal baseline.

Signals tested:
- importance_weight (Phase 1a)
- nl_mode heuristic (Phase 1b) — requires embeddings
- rerank_confidence_threshold (Phase 1c) — requires embeddings
- frecency_weight (Phase 1d)
- dep_proximity_weight (Phase 2)

Usage:
    python -m eval.meta_harness.ablation --search-repos attocode,fastapi,redis
    python -m eval.meta_harness.ablation --signals importance,frecency
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
from eval.meta_harness.harness_config import HarnessConfig


# Signal → config override that disables it
ABLATIONS: dict[str, dict] = {
    "importance": {"importance_weight": 0.0},
    "frecency": {"frecency_weight": 0.0},
    "rerank": {"rerank_confidence_threshold": 0.0},
    "dep_proximity": {"dep_proximity_weight": 0.0},
}


@dataclass
class AblationResult:
    signal: str
    score: float
    delta: float
    search_score: float
    bench_score: float


async def run_ablation(
    search_repos: list[str] | None,
    bench_repos: list[str] | None,
    signals: list[str],
    no_split: bool,
) -> tuple[float, list[AblationResult]]:
    """Run baseline + each ablation.

    Returns (baseline_score, [AblationResult, ...]).
    """
    evaluator = CodeIntelBenchEvaluator(
        search_repos=search_repos,
        bench_repos=bench_repos,
        split="" if no_split else "eval",
    )

    import tempfile

    # 1. Full-signal baseline
    print("Evaluating baseline (all signals ON)...")
    baseline_cfg = HarnessConfig.default()
    with tempfile.TemporaryDirectory() as tmpdir:
        baseline_cfg.save_yaml(os.path.join(tmpdir, "harness_config.yaml"))
        baseline = await evaluator.evaluate(tmpdir)

    if not baseline.success:
        print(f"Baseline failed: {baseline.error}")
        return 0.0, []

    baseline_score = baseline.metric_value
    baseline_search = baseline.metrics.get("search_composite", 0) or 0
    baseline_bench = baseline.metrics.get("bench_composite", 0) or 0
    print(f"  Composite: {baseline_score:.4f} (search={baseline_search:.4f}, bench={baseline_bench:.4f})")

    # 2. Each ablation
    results: list[AblationResult] = []
    for signal in signals:
        if signal not in ABLATIONS:
            print(f"  Unknown signal '{signal}', skipping")
            continue

        overrides = ABLATIONS[signal]
        print(f"\nAblation: {signal} OFF ({overrides})...")

        # Build ablated config
        cfg_dict = baseline_cfg.to_dict()
        ctx_data = cfg_dict.pop("context", None)
        cfg_dict.update(overrides)
        if ctx_data:
            cfg_dict["context"] = ctx_data
        ablated = HarnessConfig.from_dict(cfg_dict)

        errors = ablated.validate()
        if errors:
            print(f"  Invalid config: {errors}")
            continue

        with tempfile.TemporaryDirectory() as tmpdir:
            ablated.save_yaml(os.path.join(tmpdir, "harness_config.yaml"))
            result = await evaluator.evaluate(tmpdir)

        if not result.success:
            print(f"  Failed: {result.error}")
            continue

        score = result.metric_value
        delta = score - baseline_score
        search = result.metrics.get("search_composite", 0) or 0
        bench = result.metrics.get("bench_composite", 0) or 0

        results.append(AblationResult(
            signal=signal,
            score=score,
            delta=delta,
            search_score=search,
            bench_score=bench,
        ))
        print(f"  Composite: {score:.4f} (delta={delta:+.4f}) search={search:.4f} bench={bench:.4f}")

    return baseline_score, results


def format_report(baseline: float, results: list[AblationResult]) -> str:
    """Format ablation results as a table.

    Interpretation: a negative delta means disabling the signal HURT the score,
    so the signal was contributing positively. Positive delta = signal was hurting.
    """
    lines = [
        "=" * 70,
        "ABLATION STUDY RESULTS",
        "=" * 70,
        f"Full-signal baseline: {baseline:.4f}",
        "",
        f"{'Signal':<20} {'Score':>8} {'Delta':>9} {'Contribution':>14}",
        f"{'-' * 20} {'-' * 8} {'-' * 9} {'-' * 14}",
    ]

    for r in sorted(results, key=lambda x: x.delta):
        contribution = -r.delta  # negate: negative delta means signal contributed positively
        sign = "+" if contribution > 0 else ""
        lines.append(
            f"{r.signal:<20} {r.score:>8.4f} {r.delta:>+9.4f} {sign}{contribution:>+13.4f}"
        )

    lines.extend([
        "",
        "Interpretation:",
        "  - Negative delta → signal was HELPING (removing it hurt the score)",
        "  - Positive delta → signal was HURTING (removing it improved the score)",
        "  - Near-zero delta → signal has no measurable effect on this eval set",
        "=" * 70,
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ablation study for Phase 1/2 algorithmic signals",
    )
    parser.add_argument("--search-repos", type=str, default=None)
    parser.add_argument("--bench-repos", type=str, default=None)
    parser.add_argument("--signals", type=str, default="importance,frecency,rerank,dep_proximity",
                        help="Comma-separated list of signals to ablate")
    parser.add_argument("--no-split", action="store_true", default=True)
    parser.add_argument("--output", type=str, help="Save results JSON")

    args = parser.parse_args()

    signals = [s.strip() for s in args.signals.split(",") if s.strip()]

    baseline, results = asyncio.run(run_ablation(
        search_repos=args.search_repos.split(",") if args.search_repos else None,
        bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
        signals=signals,
        no_split=args.no_split,
    ))

    print()
    print(format_report(baseline, results))

    if args.output:
        data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "baseline_score": baseline,
            "results": [
                {
                    "signal": r.signal,
                    "score": r.score,
                    "delta": r.delta,
                    "contribution": -r.delta,
                    "search_score": r.search_score,
                    "bench_score": r.bench_score,
                }
                for r in results
            ],
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to: {args.output}")


if __name__ == "__main__":
    main()
