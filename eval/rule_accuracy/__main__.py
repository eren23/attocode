"""CLI for rule accuracy benchmark.

Usage:
    python -m eval.rule_accuracy run                     # Run benchmark
    python -m eval.rule_accuracy run --update-baseline   # Run and save baseline
    python -m eval.rule_accuracy check                   # Check for regressions
    python -m eval.rule_accuracy report                  # Show last report
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Rule accuracy benchmark")
    sub = parser.add_subparsers(dest="command")

    # Run
    run_parser = sub.add_parser("run", help="Run accuracy benchmark")
    run_parser.add_argument("--update-baseline", action="store_true")
    run_parser.add_argument("--corpus", default="", help="Corpus directory")
    run_parser.add_argument("--min-confidence", type=float, default=0.0)

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
        result = run_accuracy_benchmark(corpus, min_confidence=args.min_confidence)
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
