"""Resumable body-budget sweep for the search-quality eval.

Runs `eval.search_quality --reindex` once per body-token budget, writing a
per-budget JSON + Markdown report, then prints a budget-vs-MRR comparison.
Resumable: a budget whose JSON already exists (and parsed cleanly) is skipped
unless --force is given. Each budget runs as a subprocess so a crash in one
(e.g. an OOM during a large-repo reindex) doesn't lose the others.

Usage:
    # default: BGE on the cratering repos, budgets 200/400/800
    uv run python -m eval.run_body_budget_sweep \
        --repos gh-cli redis pandas --model bge --budgets 200 400 800

    # full nomic sweep, all repos, incl. unbounded
    uv run python -m eval.run_body_budget_sweep \
        --model nomic-embed-text --budgets 200 400 800 100000

Outputs land in eval/sweep_out/ (gitignored scratch).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "eval" / "sweep_out"


def _json_path(budget: str) -> Path:
    return OUT_DIR / f"budget_{budget}.json"


def _report_path(budget: str) -> Path:
    return OUT_DIR / f"budget_{budget}.md"


def _already_done(budget: str) -> bool:
    p = _json_path(budget)
    if not p.is_file():
        return False
    try:
        json.loads(p.read_text())
        return True
    except Exception:
        return False


def _run_one_budget(budget: str, repos: list[str], model: str) -> dict | None:
    env = dict(os.environ)
    env["ATTOCODE_BODY_TOKEN_BUDGET"] = budget
    if model:
        env["ATTOCODE_EMBEDDING_MODEL"] = model

    # `search_quality --repo` takes a single repo, so run one subprocess per
    # requested repo (isolation: a crash in one repo doesn't lose the rest),
    # then aggregate their JSON here.
    runs: list[dict] = []
    for r in repos:
        rj = OUT_DIR / f"budget_{budget}__{r}.json"
        sub = [
            sys.executable, "-m", "eval.search_quality",
            "--repo", r, "--reindex", "--json", str(rj),
        ]
        print(f"  -> budget={budget} repo={r} (model={model or 'auto'})", flush=True)
        subprocess.run(sub, env=env, cwd=str(PROJECT_ROOT), check=False)
        if rj.is_file():
            try:
                runs.append(json.loads(rj.read_text()))
            except Exception:
                pass

    # Merge per-repo runs into one budget summary.
    repo_entries: list[dict] = []
    for run in runs:
        repo_entries.extend(run.get("repos", []))
    ok = [e for e in repo_entries if not e.get("error") and e.get("total_queries", 0) > 0]
    tq = sum(e["total_queries"] for e in ok)
    overall = {
        "avg_mrr": (sum(e["avg_mrr"] * e["total_queries"] for e in ok) / tq) if tq else 0.0,
        "avg_ndcg": (sum(e["avg_ndcg"] * e["total_queries"] for e in ok) / tq) if tq else 0.0,
        "total_queries": tq,
    }
    summary = {
        "budget": budget,
        "model": model or "auto",
        "overall": overall,
        "repos": repo_entries,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _json_path(budget).write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable body-budget sweep")
    parser.add_argument("--budgets", nargs="+", default=["200", "400", "800"])
    parser.add_argument(
        "--repos", nargs="+", default=["gh-cli", "redis", "pandas"],
        help="Repos to score (default: the cratering repos).",
    )
    parser.add_argument(
        "--model", default="bge",
        help="ATTOCODE_EMBEDDING_MODEL (bge=cached/fast, nomic-embed-text=code-trained).",
    )
    parser.add_argument("--force", action="store_true", help="Re-run done budgets.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from eval.search_quality import format_sweep_comparison

    runs: list[dict] = []
    for budget in args.budgets:
        if not args.force and _already_done(budget):
            print(f"[skip] budget={budget} already done ({_json_path(budget)})")
            runs.append(json.loads(_json_path(budget).read_text()))
            continue
        print(f"[run ] budget={budget} repos={args.repos} model={args.model}")
        summary = _run_one_budget(budget, args.repos, args.model)
        if summary:
            runs.append(summary)
            ov = summary["overall"]
            print(
                f"[done] budget={budget} MRR={ov['avg_mrr']:.3f} "
                f"NDCG={ov['avg_ndcg']:.3f} q={ov['total_queries']}"
            )

    # Comparison table (label = budget).
    table_runs = [{"label": r["budget"], "overall": r["overall"]} for r in runs]
    table = format_sweep_comparison(table_runs)
    (OUT_DIR / "comparison.md").write_text(table + "\n")
    print()
    print(table)
    print(f"\nv3 baseline overall MRR=0.453 NDCG=0.248 (target >= 0.55)")
    print(f"Comparison written to {OUT_DIR / 'comparison.md'}")


if __name__ == "__main__":
    main()
