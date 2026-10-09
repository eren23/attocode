"""Paired comparison of two finished Loc-Bench runs over the same 560 instances.

Usage: compare.py BEFORE_DIR AFTER_DIR [IDS_FILE]

Each row compares one arm of BEFORE with one arm of AFTER: the mean of both,
paired wins and losses, and the range of the change (repository-cluster
bootstrap, as in score.py). With IDS_FILE (one instance id per line), a second
table scores only those instances.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import score

# (arm in BEFORE, arm in AFTER, metric)
ROWS = [("lexical-full", "lexical-full", "acc5"), ("lexical-full", "lexical-full", "ceil48"),
        ("jev24-full", "jev24-full", "acc5"), ("jev48-full", "jev48-full", "acc5"),
        ("lexical-title", "lexical-title", "acc5"), ("jev24-title", "jev24-title", "acc5"),
        ("fused-full", "lexical-full", "acc5"), ("fused-full", "lexical-full", "ceil48"),
        ("fus48-full", "jev48-full", "acc5")]


def load(root: str) -> dict:
    score.ROOT = Path(root).expanduser().resolve()
    return score.load()[0]


def table(before: dict, after: dict, keep=None) -> list[dict]:
    out = []
    for arm_a, arm_b, metric in ROWS:
        ids = [i for i in before[arm_a] if keep is None or i in keep]
        a = [before[arm_a][i][metric] for i in ids]
        b = [after[arm_b][i][metric] for i in ids]
        by_repo = defaultdict(list)
        for i, x, y in zip(ids, a, b, strict=True):
            by_repo[before[arm_a][i]["repo"]].append(y - x)
        out.append({"before": arm_a, "after": arm_b, "metric": metric, "n": len(ids),
                    "mean_before": round(statistics.mean(a), 4), "mean_after": round(statistics.mean(b), 4),
                    "wins": sum(y > x for x, y in zip(a, b, strict=True)),
                    "losses": sum(y < x for x, y in zip(a, b, strict=True)),
                    "delta_repo_ci": score.cluster_ci(by_repo)})
    return out


if __name__ == "__main__":
    before, after = load(sys.argv[1]), load(sys.argv[2])
    report = {"all": table(before, after)}
    if len(sys.argv) > 3:
        report["subset"] = table(before, after, set(Path(sys.argv[3]).read_text().split()))
    print(json.dumps(report, indent=1))
