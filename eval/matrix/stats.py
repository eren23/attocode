"""Metrics and paired comparisons for the eval matrix.

A row is one ranking: one (instance, variant, cell). ``score`` computes the metrics of each
row with ``eval.metrics`` and compares cells with baseline cells on the same instances.

The bootstrap and the sign-flip test resample source repositories (``Instance.repo``), not
instances. A dataset with fewer than 10 repositories gets descriptive output only: means,
wins and losses, and the bootstrap range, but no p-value and no MDE.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from statistics import NormalDist
from typing import TYPE_CHECKING

from eval.metrics import compute_acc_at_k, compute_graded_ndcg, compute_mrr, compute_recall_at_k

if TYPE_CHECKING:
    from eval.matrix.datasets import Instance

METRICS = {"acc1": "Acc@1", "acc5": "Acc@5", "acc10": "Acc@10", "r5": "R@5", "mrr5": "MRR@5",
           "gndcg5": "gNDCG@5", "ceil24": "Ceil@24", "ceil48": "Ceil@48"}
MIN_REPOS = 10  # fewer source repositories: descriptive output only
Z = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.8)  # two-sided 5% test, 80% power
EPS = 1e-9


def row_metrics(files: list[str], gold: list[str],
                grades: dict[str, int] | None = None) -> dict[str, float | None]:
    """LocAgent file Acc@k, R@5, MRR@5, Ceil@24 and Ceil@48, and graded NDCG@5 of one ranking.

    Ceil@k is 1 when every gold file is in the first k files. On a graded row, MRR@5 counts
    grade 2 and 3 files, and a metric is None while one of its first k files has no grade,
    because that file could be relevant.
    """
    relevant = set(gold)
    primary = relevant if grades is None else {path for path, grade in grades.items() if grade >= 2}

    def judged(k: int) -> bool:
        return grades is None or all(path in grades for path in files[:k])

    top5 = judged(5)
    return {
        "acc1": compute_acc_at_k(files, relevant, 1) if judged(1) else None,
        "acc5": compute_acc_at_k(files, relevant, 5) if top5 else None,
        "acc10": compute_acc_at_k(files, relevant, 10) if judged(10) else None,
        "r5": compute_recall_at_k(files, relevant, 5) if top5 else None,
        "mrr5": compute_mrr(files, primary, 5) if top5 else None,
        "gndcg5": compute_graded_ndcg(files, grades, 5) if grades is not None and top5 else None,
        "ceil24": float(relevant <= set(files[:24])),
        "ceil48": float(relevant <= set(files[:48])),
    }


def interval(groups: dict[str, list[float]], draws: int = 10_000,
             seed: int = 0) -> tuple[float, float] | None:
    """2.5th and 97.5th percentile of the mean over draws that resample whole repositories.

    None for one repository: the resamples of one cluster have no spread.
    """
    repos = sorted(groups)
    if len(repos) < 2:
        return None
    sums, counts = [math.fsum(groups[r]) for r in repos], [len(groups[r]) for r in repos]
    rng, picks, means = random.Random(seed), range(len(repos)), []
    for _ in range(draws):
        chosen = rng.choices(picks, k=len(repos))
        means.append(sum(sums[i] for i in chosen) / sum(counts[i] for i in chosen))
    cuts = statistics.quantiles(means, n=40, method="inclusive")
    return cuts[0], cuts[-1]


def sign_flip(groups: dict[str, list[float]], draws: int = 10_000, seed: int = 0) -> float:
    """Two-sided p-value for a mean paired difference of zero. A draw flips whole repositories."""
    sums = [math.fsum(groups[r]) for r in sorted(groups)]
    observed, rng = abs(math.fsum(sums)), random.Random(seed)
    hits = sum(abs(math.fsum(s if rng.random() < 0.5 else -s for s in sums)) >= observed - EPS
               for _ in range(draws))
    return (hits + 1) / (draws + 1)


def mde(groups: dict[str, list[float]]) -> tuple[float | None, float | None]:
    """Minimum detectable effect and design effect, MDE = Z * sqrt(p_disc / n) * sqrt(deff).

    Z is z(0.975) + z(0.8), for a two-sided 5% test with 80% power. p_disc is the mean squared
    paired difference: for a 0/1 metric, the share of discordant rows. deff is the variance of
    the total with repository clusters over the variance without them, from the differences
    minus their mean. It is at least 1. Both values are None when no row changes.
    """
    deltas = [d for ds in groups.values() for d in ds]
    n = len(deltas)
    second, mean = math.fsum(d * d for d in deltas), math.fsum(deltas) / n
    if not second:
        return None, None
    within = math.fsum((d - mean) ** 2 for d in deltas)
    clustered = math.fsum((math.fsum(ds) - len(ds) * mean) ** 2 for ds in groups.values())
    deff = max(1.0, clustered / within) if within else 1.0
    return Z * math.sqrt(second / n / n * deff), deff


def holm(pvalues: list[float | None]) -> list[float | None]:
    """Holm step-down adjusted p-values. A None (descriptive) entry stays None and does not count."""
    ranked = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    adjusted: list[float | None] = [None] * len(pvalues)
    running = 0.0
    for rank, (p, i) in enumerate(ranked):
        running = max(running, min(1.0, (len(ranked) - rank) * p))
        adjusted[i] = running
    return adjusted


def describe(pairs: list[tuple[str, str, float, float]]) -> dict:
    """Means and flipped instances of (instance id, repo, cell value, baseline value) rows."""
    cell = statistics.fmean(a for _i, _r, a, _b in pairs)
    baseline = statistics.fmean(b for _i, _r, _a, b in pairs)
    return {"n": len(pairs), "cell_mean": cell, "baseline_mean": baseline, "delta": cell - baseline,
            "wins": [iid for iid, _r, a, b in pairs if a > b + EPS],
            "losses": [iid for iid, _r, a, b in pairs if a < b - EPS]}


def paired(pairs: list[tuple[str, str, float, float]], draws: int = 10_000, seed: int = 0) -> dict:
    """``describe`` plus the repository bootstrap range of the difference, and with at least
    MIN_REPOS repositories the sign-flip p-value and the MDE."""
    groups = defaultdict(list)
    for _iid, repo, a, b in pairs:
        groups[repo].append(a - b)
    out = describe(pairs) | {"repos": len(groups), "ci": interval(groups, draws, seed),
                             "p": None, "mde": None, "deff": None}
    if len(groups) >= MIN_REPOS:
        out["p"] = sign_flip(groups, draws, seed)
        out["mde"], out["deff"] = mde(groups)
    return out


def primary_metric(instances: list[Instance]) -> str:
    return "gndcg5" if any(inst.grades is not None for inst in instances) else "acc5"


def score(instances: list[Instance], rows: list[dict], pairs: list[tuple[str, str]] = (), *,
          metrics: list[str] = (), partial: bool = False, draws: int = 10_000, seed: int = 0) -> dict:
    """Score the rows and compare each (cell, baseline) pair per dataset and query variant.

    A cell with rows on a dataset needs a row for every instance of that dataset, unless
    ``partial`` is true: a missing row is never a silent zero. A row that failed or fell back
    keeps the pool order, as the product does. The scorer counts these rows, and each
    comparison also gives the result without them.

    ``metrics`` replaces the primary metric of each dataset (gNDCG@5 for a graded dataset,
    else Acc@5) in the comparisons.
    """
    by_id = {inst.id: inst for inst in instances}
    per_dataset = defaultdict(list)
    for inst in instances:
        per_dataset[inst.dataset].append(inst)
    table: dict[tuple[str, str, str], dict] = defaultdict(dict)  # (cell, variant, dataset) -> id -> (row, metrics)
    for row in rows:
        inst = by_id[row["instance_id"]]
        if row["variant"] not in inst.queries:
            raise ValueError(f"{inst.id}: no {row['variant']!r} query")
        got = table[row["cell"], row["variant"], inst.dataset]
        if inst.id in got:
            raise ValueError(f"{inst.id}: two rows for {row['cell']}@{row['variant']}")
        got[inst.id] = row, row_metrics(row["files"], inst.gold, inst.grades)

    missing = []
    for (cell, variant, dataset), got in sorted(table.items()):
        expected = sum(variant in inst.queries for inst in per_dataset[dataset])
        if len(got) < expected:
            missing.append(f"{cell}@{variant} on {dataset}: {expected - len(got)} of {expected} "
                           "instances have no row")
    if missing and not partial:
        raise ValueError(". ".join(missing) + ". Pass --partial to score only the rows that exist.")

    summary: dict = {"partial": partial, "missing": missing, "cells": [], "comparisons": []}
    for (cell, variant, dataset), got in sorted(table.items()):
        primary = primary_metric(per_dataset[dataset])
        entry = {"cell": cell, "variant": variant, "dataset": dataset, "n": len(got), "primary": primary}
        for name in METRICS:
            values = [m[name] for _row, m in got.values() if m[name] is not None]
            entry[name] = statistics.fmean(values) if values else None
        groups = defaultdict(list)
        for iid, (_row, m) in got.items():
            if m[primary] is not None:
                groups[by_id[iid].repo].append(m[primary])
        latency = [row["latency_ms"] for row, _m in got.values() if row.get("latency_ms") is not None]
        cuts = statistics.quantiles(latency, n=20, method="inclusive") if len(latency) > 1 else None
        summary["cells"].append(entry | {
            "ci": interval(groups, draws, seed),
            "unjudged": sum(by_id[iid].grades is not None and m["gndcg5"] is None for iid, (_r, m) in got.items()),
            "status": dict(Counter(row["status"] for row, _m in got.values())),
            "p50_ms": cuts[9] if cuts else None, "p95_ms": cuts[18] if cuts else None})

    for cell, base in pairs:
        for (name, variant, dataset), got in sorted(table.items()):
            ref = table.get((base, variant, dataset))
            if name != cell or ref is None:
                continue
            for metric in metrics or [primary_metric(per_dataset[dataset])]:
                both = [((iid, by_id[iid].repo, m[metric], ref[iid][1][metric]),
                         row["status"] == "ok" and ref[iid][0]["status"] == "ok")
                        for iid, (row, m) in got.items()
                        if iid in ref and m[metric] is not None and ref[iid][1][metric] is not None]
                if not both:
                    continue
                result = paired([p for p, _ok in both], draws, seed)
                ok = [p for p, ok in both if ok]
                result["ok_only"] = describe(ok) if ok and len(ok) < len(both) else None
                summary["comparisons"].append({"cell": cell, "baseline": base, "variant": variant,
                                               "dataset": dataset, "metric": metric, **result})
    for comparison, p in zip(summary["comparisons"], holm([c["p"] for c in summary["comparisons"]]),
                             strict=True):
        comparison["p_holm"] = p
    return summary


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _range(ci: tuple[float, float] | None, sign: str = "") -> str:
    return "—" if ci is None else f"{ci[0]:{sign}.4f} to {ci[1]:{sign}.4f}"


def _native(iid: str) -> str:
    return iid.split("/", 1)[1]


def render(summary: dict, header: list[str]) -> str:
    """The markdown report of a ``score`` summary. ``header`` lines describe the inputs."""
    stamp = " (PARTIAL)" if summary["partial"] else ""
    lines = [f"# Matrix report{stamp}", "", *(f"- {line}" for line in header)]
    lines += [f"- Missing rows: {line}." for line in summary["missing"]]
    cells, datasets = summary["cells"], sorted({c["dataset"] for c in summary["cells"]})
    primary = {c["dataset"]: c["primary"] for c in cells}

    lines += ["", f"## Primary metric{stamp}", "",
              "Each value is the mean, with the 2.5th to 97.5th percentile of the mean over draws "
              "that resample source repositories.", "",
              "| Cell | " + " | ".join(f"{d}: {METRICS[primary[d]]}" for d in datasets) + " |",
              "|---|" + "---:|" * len(datasets)]
    found = {(c["cell"], c["variant"], c["dataset"]): c for c in cells}
    for cell, variant in sorted({(c["cell"], c["variant"]) for c in cells}):
        values = []
        for d in datasets:
            c = found.get((cell, variant, d))
            values.append("" if c is None else f"{_num(c[c['primary']])} ({_range(c['ci'])})")
        lines.append(f"| {cell}@{variant} | " + " | ".join(values) + " |")

    for dataset, variant in sorted({(c["dataset"], c["variant"]) for c in cells}):
        group = [c for c in cells if (c["dataset"], c["variant"]) == (dataset, variant)]
        graded = primary[dataset] == "gndcg5"
        names = [m for m in METRICS if graded or m != "gndcg5"]
        lines += ["", f"## {dataset}, {variant} query{stamp}", "",
                  "| Cell | n | " + " | ".join(METRICS[m] for m in names)
                  + (" | Unjudged" if graded else "") + " | Failed | p50 / p95 ms |",
                  "|---|" + "---:|" * (len(names) + 3 + graded)]
        for c in group:
            failed = ", ".join(f"{k} {s}" for s, k in sorted(c["status"].items()) if s != "ok") or "0"
            latency = "—" if c["p50_ms"] is None else f"{c['p50_ms']:.0f} / {c['p95_ms']:.0f}"
            lines.append(f"| {c['cell']} | {c['n']} | " + " | ".join(_num(c[m]) for m in names)
                         + (f" | {c['unjudged']}" if graded else "") + f" | {failed} | {latency} |")

    comparisons = summary["comparisons"]
    if comparisons:
        lines += ["", f"## Comparisons{stamp}", "",
                  "Δ is the cell minus the baseline on the same instances. The range of Δ is the "
                  "2.5th to 97.5th percentile over draws that resample source repositories. p is a "
                  "sign-flip permutation p-value over repositories, with the Holm correction over "
                  "the comparisons in this report. MDE is the smallest Δ that the test finds with "
                  f"80% power at 5%, and deff is the repository design effect. A dataset with fewer "
                  f"than {MIN_REPOS} repositories is descriptive: no p-value and no MDE. A failed "
                  "or fallback row keeps the pool order. The last column leaves out the instances "
                  "where a row failed.", "",
                  "| Cell | Baseline | Dataset | Metric | n (repos) | Baseline | Cell | Δ "
                  "| Wins / losses | Range of Δ | p (Holm) | MDE (deff) | Without failed rows |",
                  "|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|"]
        for c in comparisons:
            p = "descriptive" if c["repos"] < MIN_REPOS else _num(c["p_holm"])
            mde_text = "—" if c["mde"] is None else f"{c['mde']:.4f} ({c['deff']:.2f})"
            ok = c["ok_only"]
            without = "—" if ok is None else (f"{ok['baseline_mean']:.4f} → {ok['cell_mean']:.4f} "
                                              f"({len(ok['wins'])} / {len(ok['losses'])}, n {ok['n']})")
            lines.append(
                f"| {c['cell']}@{c['variant']} | {c['baseline']}@{c['variant']} | {c['dataset']} "
                f"| {METRICS[c['metric']]} | {c['n']} ({c['repos']}) | {c['baseline_mean']:.4f} "
                f"| {c['cell_mean']:.4f} | {c['delta']:+.4f} | {len(c['wins'])} / {len(c['losses'])} "
                f"| {_range(c['ci'], '+')} | {p} | {mde_text} | {without} |")
        lines += ["", f"## Flipped instances{stamp}"]
        for c in comparisons:
            lines += ["", f"{c['cell']}@{c['variant']} against {c['baseline']}@{c['variant']}, "
                          f"{c['dataset']}, {METRICS[c['metric']]}:", ""]
            for label in ("wins", "losses"):
                ids = ", ".join(_native(iid) for iid in sorted(c[label])) or "none"
                lines.append(f"- {label.capitalize()} ({len(c[label])}): {ids}")
    return "\n".join(lines) + "\n"
