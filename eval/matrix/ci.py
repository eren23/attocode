"""CI ranking gate: the free first-stage cells on a fixed query set, compared with a baseline.

Search is deterministic, so a change in the first five files of a query comes from a code
change. The gate fails when, in one cell, the queries that lose Acc@5 (or R@5) outnumber the
queries that gain by the net loss of configs/ci.yaml, or when the mean MRR@5 drops by more
than its limit. A failed or missing result and a query set that differs from the baseline also
fail. The gate lists every query whose first five files changed. An intended ranking change
commits a new baseline in the same pull request.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

from eval.matrix import arms, run, stats
from eval.matrix.datasets import Instance

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "configs/ci.yaml"
INSTANCES = HERE / "configs/ci_instances.jsonl"
BASELINE = HERE / "ci_baseline.json"
TOP = 5  # the files that the baseline keeps per query: the window of Acc@5, R@5 and MRR@5


def instances() -> list[Instance]:
    return [Instance(**json.loads(line)) for line in INSTANCES.read_text().splitlines() if line.strip()]


def rows(cache: Path, insts: list[Instance], cells: list[str]) -> dict[str, dict]:
    """``id|variant|cell`` -> status and first files. A title that equals the issue is one query."""
    out = {}
    for inst in insts:
        first: dict[str, str] = {}
        for variant, query in inst.queries.items():
            first.setdefault(query, variant)
        for variant, cell, _key, result in run._entries(cache, inst, cells):
            if first[inst.queries[variant]] == variant:
                out[f"{inst.id}|{variant}|{cell}"] = {
                    "status": result["status"] if result else "missing",
                    "files": result["lists"].get(arms.CELLS[cell][1], [])[:TOP] if result else []}
    return out


def _cell(key: str) -> str:
    return key.rsplit("|", 2)[2]


def compare(insts: list[Instance], baseline: dict, now: dict[str, dict], cells: list[str],
            net_loss: int, mrr5_drop: float) -> tuple[list[str], bool]:
    """The report lines, and True when the gate fails."""
    gold = {inst.id: inst.gold for inst in insts}
    old = baseline["rows"]
    lines, failed = [], False
    bad = sorted(key for key, row in now.items() if row["status"] != "ok")
    if bad:
        failed = True
        lines += [f"{len(bad)} queries have no result:"] + [f"  {key}: {now[key]['status']}" for key in bad]
    if now.keys() != old.keys():
        failed = True
        lines += ["The query set differs from the baseline. Write the baseline again."]
        lines += [f"  not in the baseline: {key}" for key in sorted(now.keys() - old.keys())]
        lines += [f"  only in the baseline: {key}" for key in sorted(old.keys() - now.keys())]
    lines += ["", "| Cell | Queries | Acc@5 lost | Acc@5 gained | R@5 lost | R@5 gained "
              "| MRR@5 baseline | MRR@5 now | Result |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    changed = []
    for cell in cells:
        keys = sorted(key for key in now.keys() & old.keys() if _cell(key) == cell and now[key]["status"] == "ok")
        before = {key: stats.row_metrics(old[key], gold[key.rsplit("|", 2)[0]]) for key in keys}
        after = {key: stats.row_metrics(now[key]["files"], gold[key.rsplit("|", 2)[0]]) for key in keys}
        count = {(name, sign): sum((after[key][name] - before[key][name]) * sign > 0 for key in keys)
                 for name in ("acc5", "r5") for sign in (-1, 1)}
        mrr = [statistics.fmean([m[key]["mrr5"] for key in keys]) if keys else 0.0 for m in (before, after)]
        crossed = (count["acc5", -1] - count["acc5", 1] >= net_loss or count["r5", -1] - count["r5", 1] >= net_loss
                   or round(mrr[0] - mrr[1], 9) > mrr5_drop)
        failed |= crossed
        lines.append(f"| {cell} | {len(keys)} | {count['acc5', -1]} | {count['acc5', 1]} | {count['r5', -1]} "
                     f"| {count['r5', 1]} | {mrr[0]:.3f} | {mrr[1]:.3f} | {'FAIL' if crossed else 'pass'} |")
        for key in keys:
            if now[key]["files"] != old[key]:
                diff = ", ".join(f"{label} {before[key][name]:.2f} -> {after[key][name]:.2f}"
                                 for name, label in (("acc5", "Acc@5"), ("r5", "R@5"), ("mrr5", "MRR@5")))
                changed += [f"  {key}: {diff}", f"    baseline: {', '.join(old[key])}",
                            f"    now:      {', '.join(now[key]['files'])}"]
    lines += ["", f"{len(changed) // 3} queries changed their first five files" + (":" if changed else ".")] + changed
    return lines, failed


def gate(cache: Path, *, write: bool = False) -> int:
    """Run the gate, or write the baseline. Returns the exit code."""
    cfg = yaml.safe_load(CONFIG.read_text())
    cells, insts = cfg["cells"], instances()
    run.MIN_FREE = 2 * 2**30  # ponytail: the gate stores about 1 GB; the 25 GiB floor is for full runs
    run.snapshot(cache, insts)
    run.retrieve(cache, insts, cells)
    now = rows(cache, insts, cells)
    engine = arms.engine()
    if write:
        bad = sorted(key for key, row in now.items() if row["status"] != "ok")
        if bad:
            print(f"refused: {len(bad)} queries have no result, for example {bad[0]}")
            return 1
        BASELINE.write_text(json.dumps({"commit": run._commit(), "engine": engine, "cells": cells,
                                        "rows": {key: row["files"] for key, row in now.items()}},
                                       indent=1, sort_keys=True) + "\n")
        print(f"wrote {len(now)} rows to {BASELINE}")
        return 0
    if not BASELINE.exists():
        print(f"No baseline at {BASELINE.relative_to(run.REPO)}. Run `python -m eval.matrix.run ci "
              "--write-baseline` on Linux, or take the ranking-baseline artifact of the failed CI run. "
              "Then commit the file.")
        return 1
    baseline = json.loads(BASELINE.read_text())
    lines, failed = compare(insts, baseline, now, cells, **cfg["fail"])
    print(f"Ranking gate: {len({key.rsplit('|', 1)[0] for key in now})} queries. Baseline engine "
          f"{baseline['engine'][:12]} (commit {baseline['commit'][:12]}), this engine {engine[:12]}.")
    print("\n".join(lines))
    print("\nRanking gate failed. If the change is intended, commit the ranking-baseline artifact of this CI run "
          "as eval/matrix/ci_baseline.json." if failed else "\nRanking gate passed.")
    return int(failed)
