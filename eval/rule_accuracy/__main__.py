"""CLI for rule accuracy benchmark.

Usage:
    python -m eval.rule_accuracy run                     # Run benchmark
    python -m eval.rule_accuracy run --update-baseline   # Run and save baseline
    python -m eval.rule_accuracy check                   # Check for regressions
    python -m eval.rule_accuracy report                  # Show last report

    # Where does confidence come from? Compare, at the product threshold:
    python -m eval.rule_accuracy run --scorer jev --min-confidence 0.5
    python -m eval.rule_accuracy run --bake-off          # all scorers, one table
"""

from __future__ import annotations

import argparse
import sys


def _print_comparison(corpus: str, runs: list[tuple[str, float]]) -> None:
    """Run each (scorer, threshold) pair and print one row per run."""
    import time

    from eval.rule_accuracy.calibration import compute_calibration
    from eval.rule_accuracy.runner import run_accuracy_benchmark

    print("| Scorer | Threshold | P | R | F1 | ECE | Findings | Seconds |")
    print("|--------|-----------|------|------|------|-------|----------|---------|")
    for scorer, threshold in runs:
        started = time.monotonic()
        try:
            result = run_accuracy_benchmark(corpus, min_confidence=threshold, scorer=scorer)
        except RuntimeError as exc:  # one scorer failing must not hide the others
            print(f"| {scorer} | {threshold:.1f} | — | — | — | — | — | did not run: {exc} |")
            continue
        elapsed = time.monotonic() - started
        o = result.overall
        ece = compute_calibration(result.scored).ece if result.scored else float("nan")
        print(
            f"| {scorer} | {threshold:.1f} | {o.precision:.2f} | {o.recall:.2f} | "
            f"{o.f1:.2f} | {ece:.4f} | {len(result.scored)} | {elapsed:.1f} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rule accuracy benchmark")
    sub = parser.add_subparsers(dest="command")

    # Run
    run_parser = sub.add_parser("run", help="Run accuracy benchmark")
    run_parser.add_argument("--update-baseline", action="store_true")
    run_parser.add_argument("--corpus", default="", help="Corpus directory")
    run_parser.add_argument("--min-confidence", type=float, default=0.0)
    run_parser.add_argument(
        "--scorer", default="constants", choices=["constants", "llm", "jev"],
        help="Where confidence comes from (default: constants, the shipped behaviour)",
    )
    run_parser.add_argument(
        "--sweep", action="store_true",
        help="Run thresholds 0.0/0.3/0.5/0.7/0.9 and print one row each",
    )
    run_parser.add_argument(
        "--bake-off", action="store_true",
        help="Run every scorer at --min-confidence and print one comparison table",
    )

    # Check regressions
    check_parser = sub.add_parser("check", help="Check for regressions")
    check_parser.add_argument("--baseline", default="", help="Baseline JSON path")
    check_parser.add_argument("--threshold", type=float, default=0.05)

    args = parser.parse_args()

    if args.command == "run":
        from eval.rule_accuracy.runner import run_accuracy_benchmark, CORPUS_DIR
        from eval.rule_accuracy.report import format_accuracy_report
        from eval.rule_accuracy.regression import save_baseline

        corpus = args.corpus or str(CORPUS_DIR)

        if args.bake_off:
            _print_comparison(
                corpus,
                [(s, args.min_confidence) for s in ("constants", "llm", "jev")],
            )
            return
        if args.sweep:
            _print_comparison(
                corpus,
                [(args.scorer, t) for t in (0.0, 0.3, 0.5, 0.7, 0.9)],
            )
            return

        result = run_accuracy_benchmark(
            corpus, min_confidence=args.min_confidence, scorer=args.scorer,
        )
        print(format_accuracy_report(result))

        if args.update_baseline:
            save_baseline(result)
            print("\nBaseline updated.")

    elif args.command == "check":
        from eval.rule_accuracy.runner import run_accuracy_benchmark, CORPUS_DIR
        from eval.rule_accuracy.regression import check_regression

        result = run_accuracy_benchmark(str(CORPUS_DIR))
        baseline_path = args.baseline or ""
        regressions = check_regression(
            result,
            **({"baseline_path": baseline_path} if baseline_path else {}),
            f1_threshold=args.threshold,
        )

        if regressions:
            print("REGRESSIONS DETECTED:\n")
            for r in regressions:
                print(f"  {r}")
            sys.exit(1)
        else:
            print("No regressions detected.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
