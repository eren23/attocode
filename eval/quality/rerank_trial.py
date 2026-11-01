"""Acceptance for the frozen hosted-rerank trial (designs/2026-11-hosted-rerank.json).

Reuses the paired MCP delivery comparison; the hosted gates replace its local
latency rule. Labels are authored and non-exhaustive, not agent outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from eval.quality.mcp_search import compare, worst_of

MODEL = "typesafe/jev-1.13"
PRICE_PER_CALL = .00075  # USD, design estimate; measured key usage is checked too
SPEND_LIMIT = 5.0
CONFIG_FALLBACKS = {"not_configured", "invalid_config", "remote_disabled", "missing_credential"}
SAMPLES = 3


def p95(values):
    values = sorted(values)
    return values[math.ceil(.95 * len(values)) - 1] if values else None


def decide(design_bytes, baseline_runs, candidate_runs, usage_before, usage_after):
    design = json.loads(design_bytes)
    packs = {g["pack"]: g["commit"] for g in design["repositories"]}
    digest = hashlib.sha256(design_bytes).hexdigest()
    runs = [*baseline_runs, *candidate_runs]
    if (sorted(r["pack"] for r in baseline_runs) != sorted(packs)
            or sorted(r["pack"] for r in candidate_runs) != sorted(packs)
            or {r["arm"] for r in baseline_runs} != {"baseline"}
            or {r["arm"] for r in candidate_runs} != {"candidate"}
            or any(r["questions_sha256"] != digest or r["commit"] != packs[r["pack"]] for r in runs)
            or len({(r["operator_sha256"], r["engine_sha256"]) for r in runs}) != 1
            or not all(r["samples_may_differ"] for r in candidate_runs)):
        raise ValueError("Observations do not match one frozen design, operator and engine")
    expected = [q["id"] for g in design["repositories"] for q in g["queries"]]
    baseline = [row for r in baseline_runs for row in r["queries"]]
    candidate = [row for r in candidate_runs for row in r["queries"]]
    result = compare(baseline, candidate, expected)
    del result["checks"]["latency"]  # replaced by the hosted latency gates below

    pages = [row["pages"][page] for row in candidate for page in ("5", "24", "scoped")]
    if any(len(p["samples"]) != SAMPLES or p["hits"] != worst_of(p["samples"]) for p in pages):
        raise ValueError("Each candidate page needs three samples scored worst of three")
    samples = [s for p in pages for s in p["samples"]]
    rankings = [d for s in samples for d in s["ranking_diagnostic"]]
    attempts = [d for d in rankings if "rerank_elapsed_ms" in d]
    fallbacks = [d for d in attempts if d.get("method") != "systemone_choice"]
    searches = [s["seconds"] for row in candidate for page in ("5", "24")
                for s in row["pages"][page]["samples"]]
    by_id = {row["id"]: row for row in candidate}
    net = dict.fromkeys(packs, 0)
    for old in baseline:
        net[old["pack"]] += (len(by_id[old["id"]]["pages"]["5"]["hits"]["files"])
                             - len(old["pages"]["5"]["hits"]["files"]))
    file_losses = {page: sum(len(x["labels"]) for x in result["individual_losses"]
                             if x["page"] == page and x["metric"] == "files") for page in ("5", "24")}
    posted = sum(r["rerank_calls"]["posted"] for r in candidate_runs)
    estimate = posted * PRICE_PER_CALL
    measured = usage_after["usage"] - usage_before["usage"]
    result["checks"].update(
        files_5_gain=sum(net.values()) >= 3 and sum(v > 0 for v in net.values()) >= 2,
        no_file_loss_24=file_losses["24"] == 0,
        at_most_one_file_loss_5=file_losses["5"] <= 1,
        hosted_ranker_used=bool(rankings) and all(
            d.get("provider") == "systemone" and d.get("model") == MODEL and d.get("remote") is True
            for d in rankings),
        no_config_fallback=not any(d.get("fallback_reason") in CONFIG_FALLBACKS for d in rankings),
        fallback_rate=bool(attempts) and len(fallbacks) <= .05 * len(attempts),
        rerank_p95=bool(attempts) and p95([d["rerank_elapsed_ms"] for d in attempts]) <= 1500,
        search_p95=p95(searches) <= 2.0,
        baseline_no_remote_calls=all(r["rerank_calls"] == {"posted": 0, "refused": 0} for r in baseline_runs),
        no_refused_calls=not any(r["rerank_calls"]["refused"] for r in candidate_runs),
        spend=estimate <= SPEND_LIMIT and 0 <= measured <= SPEND_LIMIT,
    )
    result["passed"] = all(result["checks"].values())
    result["hosted"] = {
        "files_5_net_by_pack": net, "file_label_losses": file_losses,
        "rankings": len(rankings), "attempts": len(attempts), "fallbacks": len(fallbacks),
        "fallback_reasons": dict(Counter(d.get("fallback_reason") for d in fallbacks)),
        "rerank_p95_ms": p95([d["rerank_elapsed_ms"] for d in attempts]),
        "search_p95_seconds": p95(searches), "posted_calls": posted,
        "estimated_usd": round(estimate, 6), "measured_usage_delta_usd": measured,
    }
    result["questions_sha256"] = digest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    for name in ("baseline", "candidate"):
        parser.add_argument(f"--{name}", type=Path, required=True, help="Directory of per-pack observations")
    parser.add_argument("--usage-before", type=Path, required=True)
    parser.add_argument("--usage-after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite a decision")
    def load(directory):
        return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]

    decision = decide(args.design.read_bytes(), load(args.baseline), load(args.candidate),
                      json.loads(args.usage_before.read_text()), json.loads(args.usage_after.read_text()))
    args.output.write_text(json.dumps(decision, indent=2) + "\n")
    print(json.dumps({"passed": decision["passed"], "checks": decision["checks"],
                      "hosted": decision["hosted"]}, indent=2))


if __name__ == "__main__":
    main()
