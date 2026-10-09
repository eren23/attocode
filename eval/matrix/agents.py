"""Agent localization report: a localize study, paired with native and joined with the matrix.

  python -m eval.matrix.agents STUDY --instances FILE [--matrix OUT] [--offline-cell product] [--output FILE]

STUDY is a ``study.py --mode localize`` folder after ``summary`` (runs.jsonl, manifest.json).
The task is the unit: the trials of a task are averaged first, then each setup is paired with
``native`` on the same tasks. The bootstrap and the sign-flip test resample the source
repositories of the matrix instances in FILE (an instances.jsonl). ``issue_only`` is the
contamination control: the report gives its scores but does not pair it. With --matrix, the
rows of one offline cell at variant full in OUT/results.jsonl are joined by instance id.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from eval.matrix import stats
from eval.metrics import compute_acc_at_k, compute_mrr

BASELINE, CONTROL = "native", "issue_only"
SCORES = ("acc1", "acc5", "recall10", "mrr5")
TOKENS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
# Paired metric -> (label, format of a mean, format of a difference). Cost pairs are logarithms:
# a mean shows as the geometric mean in USD and a difference as the geometric mean ratio.
PAIRED = {"acc5": ("Acc@5", "{:.3f}".format, "{:+.3f}".format),
          "cost": ("Cost (USD)", lambda v: f"{math.exp(v):.4f}", lambda v: f"×{math.exp(v):.3f}"),
          "seconds": ("Seconds", "{:.1f}".format, "{:+.1f}".format),
          "turns": ("Turns", "{:.1f}".format, "{:+.1f}".format)}
TARGETS = (0.10, 0.05)  # ΔAcc@5 values for the sample size table
AGENT_HIT = 0.5  # a task with a mean Acc@5 at or above this is an agent hit


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _num(value: float | None, digits: int = 3) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def _median(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def task_values(runs: list[dict]) -> dict[str, dict[str, dict]]:
    """setup -> instance id -> the trial means of one task.

    A failed run scores 0 and costs the most expensive run of its setup.
    """
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in runs:
        grouped[row["setup"]][row["instance_id"]].append(row)
    out: dict[str, dict[str, dict]] = {}
    for setup, tasks in grouped.items():
        worst = max((r["cost_usd"] for rows in tasks.values() for r in rows if r["cost_usd"] is not None),
                    default=None)
        out[setup] = {}
        for iid, rows in tasks.items():
            costs = [worst if r["failed"] else r["cost_usd"] for r in rows]
            out[setup][iid] = {
                **{key: _mean([0.0 if r["failed"] else r[key] for r in rows]) for key in SCORES},
                "seconds": _mean([r["seconds"] for r in rows]), "turns": _mean([r["turns"] for r in rows]),
                "cost": _mean(costs), "costs": costs, "runs": rows,
                "hits": [not r["failed"] and r["acc5"] == 1 for r in rows]}
    return out


def setup_row(tasks: dict[str, dict]) -> dict:
    """Scores as means over tasks; counts and medians over the runs of one setup."""
    runs = [r for task in tasks.values() for r in task["runs"]]
    return {"tasks": len(tasks), "runs": len(runs), "failures": sum(r["failed"] for r in runs),
            **{key: _mean([t[key] for t in tasks.values()]) for key in SCORES},
            "pass_any": _mean([any(t["hits"]) for t in tasks.values()]),
            "pass_all": _mean([all(t["hits"]) for t in tasks.values()]),
            "mcp": sum((r.get("mcp_calls") or 0) > 0 for r in runs),
            "warming": sum(r.get("mcp_warming_results") or 0 for r in runs),
            "seconds": _median([r["seconds"] for r in runs]), "turns": _median([r["turns"] for r in runs]),
            "tokens": [_median([(r.get("tokens") or {}).get(key) for r in runs]) for key in TOKENS],
            "cost": _median([c for t in tasks.values() for c in t["costs"]])}


def pairs(setup: dict[str, dict], native: dict[str, dict], key: str,
          repos: dict[str, str]) -> list[tuple[str, str, float, float]]:
    """(instance id, repository, setup value, native value) for the tasks that both setups ran.

    Cost pairs are logarithms, so the mean difference is the log of the geometric mean ratio.
    A task without a cost on one side has no cost pair.
    """
    out = []
    for iid in sorted(setup.keys() & native.keys()):
        a, b = setup[iid][key], native[iid][key]
        if key == "cost":
            if not (a and b):
                continue
            a, b = math.log(a), math.log(b)
        if a is not None and b is not None:
            out.append((iid, repos[iid], a, b))
    return out


def sizing(prs: list[tuple[str, str, float, float]]) -> dict:
    """Tasks for 80% power at a two-sided 5% level for each ΔAcc@5 in TARGETS.

    This is ``stats.mde`` solved for n: n = Z² × p_disc × deff / Δ². None when no task changes.
    """
    groups = defaultdict(list)
    for _iid, repo, a, b in prs:
        groups[repo].append(a - b)
    deltas = [d for ds in groups.values() for d in ds]
    p_disc = math.fsum(d * d for d in deltas) / len(deltas) if deltas else 0.0
    deff = stats.mde(groups)[1] if p_disc else None
    return {"n": len(deltas), "repos": len(groups), "p_disc": p_disc, "deff": deff,
            "needed": [math.ceil(stats.Z ** 2 * p_disc * deff / t ** 2) if deff else None for t in TARGETS]}


def offline(results: Path, cell: str, instances: dict[str, dict]) -> dict[str, dict]:
    """Instance id -> offline RR of the first gold file and offline hit@5, for one cell at variant full."""
    out = {}
    for row in _jsonl(results):
        iid = row["instance_id"]
        if row["cell"] != cell or row["variant"] != "full" or iid not in instances:
            continue
        if iid in out:
            raise SystemExit(f"{results}: two rows for {iid} in cell {cell}")
        gold, files = set(instances[iid]["gold"]), row["files"]
        out[iid] = {"rr": compute_mrr(files, gold, len(files)), "hit5": compute_acc_at_k(files, gold, 5) == 1}
    if not out:
        raise SystemExit(f"{results} has no rows of cell {cell} at variant full for these instances")
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation with average ranks for ties. None for fewer than 3 tasks or a constant side."""
    if len(x) < 3:
        return None
    try:
        return statistics.correlation(x, y, method="ranked")
    except statistics.StatisticsError:
        return None


def report(study: Path, instances_file: Path, matrix: Path | None = None, cell: str = "product",
           draws: int = 10_000, seed: int = 0) -> str:
    manifest = json.loads((study / "manifest.json").read_text())
    runs = _jsonl(study / "runs.jsonl")
    instances = {row["id"]: row for row in _jsonl(instances_file)}
    study_ids = sorted({r["instance_id"] for r in runs})
    unknown = [iid for iid in study_ids if iid not in instances]
    if unknown:
        raise SystemExit(f"{len(unknown)} study tasks have no instance in {instances_file}, such as {unknown[0]}")
    repos = {iid: inst["repo"] for iid, inst in instances.items()}
    values = task_values(runs)
    setups = [s for s in manifest["setups"] if s in values]
    lines = [
        "# Agent localization report", "",
        f"Study `{manifest['study_id'][:12]}`, model `{manifest['model']}`, config `{manifest['config_id']}`, "
        f"{manifest['trials']} trials for each task and setup" + (f", 1 for `{CONTROL}`" if CONTROL in setups else "")
        + f": {len(runs)} runs on {len(study_ids)} tasks from {len({repos[iid] for iid in study_ids})} "
        f"repositories. Instances: `{instances_file}`.", "",
        "The task is the unit: the report averages the trials of a task first. A range resamples "
        f"repositories ({draws:,} draws). With fewer than {stats.MIN_REPOS} repositories, a comparison is "
        "descriptive: it has no p-value and no MDE. A failed run scores 0, takes the timeout and costs "
        "the most expensive run of its setup.", "",
        "## Setups", "",
        "pass@k: the share of tasks with an Acc@5 hit in one or more trials. pass^k: in all trials. "
        "MCP adoption: the runs with one or more MCP calls.", "",
        "| Setup | Tasks | Runs | Failures | Acc@1 | Acc@5 | R@10 | MRR@5 | pass@k | pass^k | MCP adoption "
        "| Warming results | Median s | Median turns | Median tokens: input / cache write / cache read / output "
        "| Median cost (USD) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for setup in setups:
        s = setup_row(values[setup])
        tokens = " / ".join("–" if t is None else f"{t:,.0f}" for t in s["tokens"])
        lines.append(
            f"| {setup} | {s['tasks']} | {s['runs']} | {s['failures']} | {_num(s['acc1'])} | {_num(s['acc5'])} "
            f"| {_num(s['recall10'])} | {_num(s['mrr5'])} | {_num(s['pass_any'])} | {_num(s['pass_all'])} "
            f"| {s['mcp']} / {s['runs']} | {s['warming']} | {_num(s['seconds'], 1)} | {_num(s['turns'], 1)} "
            f"| {tokens} | {_num(s['cost'], 4)} |")
    lines += ["", "Prompt caching carries over between runs, so a cost depends on the run order: "
                  "compare the tokens by type with the cost."]

    compared = [s for s in setups if s not in (BASELINE, CONTROL)]
    lines += ["", f"## Paired with {BASELINE}", ""]
    if CONTROL in values:
        control = setup_row(values[CONTROL])
        lines += [f"`{CONTROL}` is the contamination control and has no tools. The report does not pair it: "
                  f"Acc@5 {_num(control['acc5'])} on {control['tasks']} tasks.", ""]
    if BASELINE not in values or not compared:
        lines.append(f"No comparison: the study needs `{BASELINE}` and one more setup with tools.")
    else:
        results = {}
        for key in PAIRED:
            found = {s: stats.paired(p, draws, seed) for s in compared
                     if (p := pairs(values[s], values[BASELINE], key, repos))}
            for s, p_holm in zip(found, stats.holm([r["p"] for r in found.values()]), strict=True):
                results[s, key] = found[s] | {"p_holm": p_holm}
        lines += ["Δ is the setup minus native on the same tasks. Cost is the geometric mean over tasks, "
                  "and its Δ is the geometric mean ratio of setup to native. p is a sign-flip p-value over "
                  "repositories, with the Holm correction over the setups of one metric. MDE is the smallest "
                  "Δ that the test finds with 80% power at 5%.", "",
                  "| Setup | Metric | Tasks (repos) | Native | Setup | Δ | Higher / lower | Range of Δ (95%) "
                  "| p (Holm) | MDE |", "|---|---|---:|---:|---:|---:|---:|---|---:|---:|"]
        for setup in compared:
            for key, (label, mean, diff) in PAIRED.items():
                r = results.get((setup, key))
                if r is None:
                    lines.append(f"| {setup} | {label} | 0 | – | – | – | – | – | – | – |")
                    continue
                ci = "–" if r["ci"] is None else f"{diff(r['ci'][0])} to {diff(r['ci'][1])}"
                p = "descriptive" if r["repos"] < stats.MIN_REPOS else _num(r["p_holm"], 4)
                mde = "–" if r["mde"] is None else diff(r["mde"]).lstrip("+")
                lines.append(f"| {setup} | {label} | {r['n']} ({r['repos']}) | {mean(r['baseline_mean'])} "
                             f"| {mean(r['cell_mean'])} | {diff(r['delta'])} | {len(r['wins'])} / "
                             f"{len(r['losses'])} | {ci} | {p} | {mde} |")

        lines += ["", "## Sample size", "",
                  "Tasks for 80% power at a two-sided 5% level, from the paired Acc@5 differences of this "
                  "study: n = Z² × p_disc × deff / Δ². p_disc is the mean squared difference and deff the "
                  "repository design effect. With few repositories, deff is a rough estimate.", "",
                  "| Setup | Tasks | Repos | p_disc | deff | "
                  + " | ".join(f"Tasks for ΔAcc@5 {t:.2f}" for t in TARGETS) + " |",
                  "|---|---:|---:|---:|---:|" + "---:|" * len(TARGETS)]
        for setup in compared:
            z = sizing(pairs(values[setup], values[BASELINE], "acc5", repos))
            lines.append(f"| {setup} | {z['n']} | {z['repos']} | {_num(z['p_disc'])} | {_num(z['deff'], 2)} | "
                         + " | ".join("–" if n is None else str(n) for n in z["needed"]) + " |")

    if matrix is not None:
        results_file = matrix / "results.jsonl"
        found = offline(results_file, cell, instances)
        missing = [iid for iid in study_ids if iid not in found]
        lines += ["", f"## Offline {cell} against the agents", "",
                  f"Offline rows: `{results_file}`, cell `{cell}`, variant full. {len(study_ids) - len(missing)} "
                  f"of {len(study_ids)} tasks have a row. A task without a row is not scored."
                  + (f" No row: {', '.join(missing[:5])}{' …' if len(missing) > 5 else ''}." if missing else ""),
                  "", "Offline RR is the reciprocal rank of the first gold file in the full offline list. An "
                  f"agent hit is a task with a mean Acc@5 of {AGENT_HIT} or more.", "",
                  "| Setup | Tasks | Spearman: offline RR, agent Acc@5 | Offline hit, agent hit "
                  "| Offline hit, agent miss | Offline miss, agent hit | Offline miss, agent miss |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for setup in setups:
            ids = [iid for iid in sorted(values[setup]) if iid in found]
            agent = [values[setup][iid]["acc5"] for iid in ids]
            table: dict[tuple[bool, bool], int] = defaultdict(int)
            for iid, acc in zip(ids, agent, strict=True):
                table[found[iid]["hit5"], acc >= AGENT_HIT] += 1
            rho = spearman([found[iid]["rr"] for iid in ids], agent)
            lines.append(f"| {setup} | {len(ids)} | {_num(rho)} | {table[True, True]} | {table[True, False]} "
                         f"| {table[False, True]} | {table[False, False]} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", type=Path)
    parser.add_argument("--instances", type=Path, required=True, help="matrix instances.jsonl")
    parser.add_argument("--matrix", type=Path, help="matrix run folder with results.jsonl")
    parser.add_argument("--offline-cell", default="product")
    parser.add_argument("--output", type=Path, help="default: STUDY/agent_report.md")
    args = parser.parse_args()
    output = args.output or args.study / "agent_report.md"
    output.write_text(report(args.study, args.instances, args.matrix, args.offline_cell))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
