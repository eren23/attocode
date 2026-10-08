"""Score the finished Loc-Bench V1 run; every instance stays in n.

A clone or base-commit failure (a "miss" marker) scores 0 in every arm. An instance
with no marker was not run and also scores 0, so score only after the shards finish.
A Jev answer that fell back keeps the lexical order, as the product does.
"""
import json
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("LOCBENCH_DIR", Path.home() / "locbench560")).resolve()
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from eval.metrics import compute_acc_at_k, compute_mrr, compute_recall_at_k  # noqa: E402

# The 42 instances of the earlier title-pack check.
DEV = set(yaml.safe_load((REPO / "packages/code-intel/evals/locbench_title_pack.yaml").read_text())["repos"])


def metrics(files: list[str], gold: set[str]) -> dict:
    return {"acc1": compute_acc_at_k(files, gold, 1), "acc5": compute_acc_at_k(files, gold, 5),
            "acc10": compute_acc_at_k(files, gold, 10), "strict5": float(gold <= set(files[:5])),
            "r5": compute_recall_at_k(files, gold, 5), "mrr5": compute_mrr(files, gold, 5),
            "pool24": compute_recall_at_k(files, gold, 24), "pool48": compute_recall_at_k(files, gold, 48)}


def ci(values: list[float], draws: int = 10000) -> list[float]:
    rng = random.Random(0)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def cluster_ci(values: dict[str, list[float]], draws: int = 10000) -> list[float]:
    """Resample source repositories, not instances: one repository can hold 26 instances."""
    rng, groups = random.Random(0), list(values.values())
    means = []
    for _ in range(draws):
        picked = [v for group in rng.choices(groups, k=len(groups)) for v in group]
        means.append(statistics.mean(picked))
    means.sort()
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def load() -> tuple[dict, Counter, dict]:
    rows = json.loads((ROOT / "all.json").read_text())
    per = defaultdict(dict)  # arm -> instance -> metrics
    status, latency = Counter(), defaultdict(list)
    for r in rows:
        iid, gold = r["instance_id"], {f.split(":")[0] for f in r["edit_functions"]}
        done = ROOT / "done" / f"{iid}.json"
        marker = json.loads(done.read_text()) if done.exists() else {"miss": "not run"}
        status[marker.get("miss", "ok")] += 1
        pool = ROOT / "pools" / f"{iid}.json"
        cases = {}
        if "miss" not in marker and pool.exists():
            for q in json.loads(pool.read_text())["repos"][0]["queries"]:
                cases[q["intent"]] = {"lexical": q["arms"]["prior"]["files"]}
            for name in ("jev24", "jev48"):
                trial = ROOT / "trials" / f"{iid}-{name}.json"
                for c in json.loads(trial.read_text())["cases"] if trial.exists() else []:
                    intent = "full" if c["query"] == r["problem_statement"] else "title"
                    cases.setdefault(intent, {})[name] = c["ranked_files"]
                    status[f"{name}:{c['fallback_reason'] or 'ok'}"] += 1
                    latency[name].append(c["inference_ms"])
        cases.setdefault("title", cases.get("full", {}))  # 10 one-line issues: the title is the issue
        for intent in ("full", "title"):
            for arm in ("lexical", "jev24", "jev48"):
                if intent == "title" and arm == "jev48":
                    continue
                files = cases.get(intent, {}).get(arm, [])
                per[f"{arm}-{intent}"][iid] = {**metrics(files, gold), "category": r["category"], "dev": iid in DEV,
                                               "repo": r["repo"], "pool": len(cases.get(intent, {}).get("lexical", []))}
    return per, status, latency


def summary(per: dict, keep=lambda m: True) -> dict:
    out = {}
    for arm, items in per.items():
        rows = [m for m in items.values() if keep(m)]
        out[arm] = {"n": len(rows)} | {k: round(statistics.mean(m[k] for m in rows), 4)
                                       for k in ("acc1", "acc5", "acc10", "strict5", "r5", "mrr5", "pool24", "pool48")}
        out[arm]["acc5_ci"] = ci([m["acc5"] for m in rows])
    return out


if __name__ == "__main__":
    per, status, latency = load()
    report = {"status": dict(status), "all": summary(per),
              "latency_ms": {k: {"median": statistics.median(v), "p95": sorted(v)[int(0.95 * len(v))]} for k, v in latency.items() if v},
              "dev42": summary(per, lambda m: m["dev"]),
              "by_category": {c: summary(per, lambda m, c=c: m["category"] == c)
                              for c in sorted({m["category"] for m in per["lexical-full"].values()})}}
    paired = {}
    for arm in ("jev24-full", "jev48-full", "jev24-title"):
        base = "lexical-" + arm.split("-")[1]
        deltas = [per[arm][i]["acc5"] - per[base][i]["acc5"] for i in per[arm]]
        by_repo = defaultdict(list)
        for i, d in zip(per[arm], deltas, strict=True):
            by_repo[per[arm][i]["repo"]].append(d)
        paired[f"{arm} vs {base}"] = {"wins": sum(d > 0 for d in deltas), "losses": sum(d < 0 for d in deltas),
                                      "acc5_delta_ci": ci(deltas), "acc5_delta_repo_ci": cluster_ci(by_repo)}
    report["paired_acc5"] = paired
    for arm, items in per.items():
        by_repo = defaultdict(list)
        for m in items.values():
            by_repo[m["repo"]].append(m["acc5"])
        report["all"][arm]["acc5_repo_ci"] = cluster_ci(by_repo)
    report["pool_sizes"] = {intent: {"empty": sum(m["pool"] == 0 for m in per[f"lexical-{intent}"].values()),
                                     "under_5": sum(0 < m["pool"] < 5 for m in per[f"lexical-{intent}"].values()),
                                     "under_24": sum(m["pool"] < 24 for m in per[f"lexical-{intent}"].values())}
                            for intent in ("full", "title")}
    (ROOT / "scores.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({"status": report["status"], "paired": paired, "pool_sizes": report["pool_sizes"],
                      "all": {k: {m: v[m] for m in ("n", "acc1", "acc5", "acc10", "acc5_ci", "acc5_repo_ci", "mrr5")}
                              for k, v in report["all"].items()}}, indent=1))
