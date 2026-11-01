"""Acceptance for the hosted embedding trial (ATTOCODE_INTEL_EMBEDDING=openrouter).

Both arms run the same engine; the candidate arm indexes the pack with the
hosted model and fuses its file list. Labels are authored and non-exhaustive,
not agent outcomes.

    python -m eval.quality.embed_trial fresh --design NEW.json
    python -m eval.quality.embed_trial decide --design D --baseline B --candidate C \\
        --usage-before U0 --usage-after U1 --spend-limit 5 --output OUT
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from attocode_intel._internal.integrations.context.embeddings import _same_model

from eval.quality.mcp_search import compare, worst_of

DESIGNS = Path(__file__).resolve().parents[2] / "packages/code-intel/evals/designs"
MODEL = "voyageai/voyage-code-4"
# Net judged-file gain on the first page, summed over repositories.
MIN_GAIN = {"development": 2, "validation": 3}
SAMPLES = 3
NO_CALLS = {"posted": 0, "refused": 0, "cost": 0.0, "models": []}


def p95(values):
    values = sorted(values)
    return values[math.ceil(.95 * len(values)) - 1] if values else None


def decide(design_bytes, baseline_runs, candidate_runs, usage_before, usage_after, spend_limit):
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
    del result["checks"]["latency"]  # replaced by the hosted latency gate below

    pages = [row["pages"][page] for row in candidate for page in ("5", "24", "scoped")]
    if any(len(p["samples"]) != SAMPLES or p["hits"] != worst_of(p["samples"]) for p in pages):
        raise ValueError("Each candidate page needs three samples scored worst of three")
    dense = [s["dense"] for p in pages for s in p["samples"]]
    statuses = Counter(d.get("status", "not_attempted") for d in dense)
    attempts = statuses["ok"] + statuses["failed"]
    searches = [s["seconds"] for row in candidate for page in ("5", "24")
                for s in row["pages"][page]["samples"]]
    by_id = {row["id"]: row for row in candidate}
    net = dict.fromkeys(packs, 0)
    for old in baseline:
        net[old["pack"]] += (len(by_id[old["id"]]["pages"]["5"]["hits"]["files"])
                             - len(old["pages"]["5"]["hits"]["files"]))
    file_losses = {page: sum(len(x["labels"]) for x in result["individual_losses"]
                             if x["page"] == page and x["metric"] == "files") for page in ("5", "24")}
    indexes = [r["embed_index"] or {} for r in candidate_runs]
    models = sorted({m for r in candidate_runs for m in r["embed_calls"]["models"]}, key=str)
    cost = sum(r["embed_calls"]["cost"] for r in candidate_runs)
    measured = usage_after["usage"] - usage_before["usage"]
    result["checks"].update(
        files_5_gain=(sum(net.values()) >= MIN_GAIN[design["split"]]
                      and sum(v > 0 for v in net.values()) >= 2),
        no_file_loss_24=file_losses["24"] == 0,
        at_most_one_file_loss_5=file_losses["5"] <= 1,
        packs_indexed=all(i.get("chunks") and i.get("stored") and i.get("abort") is None for i in indexes),
        pinned_model=bool(models) and all(_same_model(MODEL, m) for m in models),
        no_consent_refusal=statuses["off"] == 0,
        fallback_rate=bool(attempts) and statuses["failed"] <= .05 * attempts,
        search_p95=p95(searches) <= 2.0,
        baseline_no_remote_calls=all(r["embed_calls"] == NO_CALLS and r["embed_index"] is None
                                     for r in baseline_runs),
        no_refused_calls=not any(r["embed_calls"]["refused"] for r in candidate_runs),
        spend=cost <= spend_limit and 0 <= measured <= spend_limit,
    )
    result["passed"] = all(result["checks"].values())
    result["hosted"] = {
        "split": design["split"], "files_5_net_by_pack": net, "file_label_losses": file_losses,
        "dense_statuses": dict(statuses),
        "dense_p95_ms": p95([d["ms"] for d in dense if "ms" in d]),
        "search_p95_seconds": p95(searches), "models": models,
        "index": {r["pack"]: r["embed_index"] for r in candidate_runs},
        "posted_calls": sum(r["embed_calls"]["posted"] for r in candidate_runs),
        "reported_usd": round(cost, 6), "measured_usage_delta_usd": measured,
        "spend_limit_usd": spend_limit,
    }
    result["questions_sha256"] = digest
    return result


def _walk(node):
    """Yield every (query text, evidence list) pair in a design, whatever its schema."""
    if isinstance(node, dict):
        if isinstance(node.get("query"), str):
            yield node["query"], node.get("evidence") or []
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def freshness(design_path, designs=DESIGNS):
    """Collisions of a new design with every earlier design: exact or near queries, same anchors."""
    def norm(text):
        return " ".join(text.lower().split())

    new = list(_walk(json.loads(design_path.read_text())))
    seen_queries, seen_anchors, skipped = {}, {}, []
    for path in sorted(designs.glob("*.json")):
        if path.resolve() == design_path.resolve():
            continue
        try:
            old = list(_walk(json.loads(path.read_text())))
        except ValueError:
            skipped.append(path.name)
            continue
        for query, evidence in old:
            seen_queries.setdefault(norm(query), path.name)
            for e in evidence:
                if isinstance(e, dict) and "file" in e and "line" in e:
                    seen_anchors.setdefault((e["file"], e["line"]), path.name)
    collisions = []
    for query, evidence in new:
        q = norm(query)
        for old, source in seen_queries.items():
            ratio = difflib.SequenceMatcher(None, q, old).ratio()
            if ratio >= .8:
                collisions.append({"kind": "query", "query": query, "earlier": old,
                                   "design": source, "ratio": round(ratio, 3)})
        for e in evidence:
            anchor = (e["file"], e["line"])
            if anchor in seen_anchors:
                collisions.append({"kind": "anchor", "query": query, "anchor": list(anchor),
                                   "design": seen_anchors[anchor]})
    return {"design": design_path.name, "queries": len(new), "earlier_queries": len(seen_queries),
            "collisions": collisions, "unparsed": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fresh = sub.add_parser("fresh")
    fresh.add_argument("--design", type=Path, required=True)
    run = sub.add_parser("decide")
    run.add_argument("--design", type=Path, required=True)
    for name in ("baseline", "candidate"):
        run.add_argument(f"--{name}", type=Path, required=True, help="Directory of per-pack observations")
    run.add_argument("--usage-before", type=Path, required=True)
    run.add_argument("--usage-after", type=Path, required=True)
    run.add_argument("--spend-limit", type=float, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fresh":
        report = freshness(args.design)
        print(json.dumps(report, indent=2))
        raise SystemExit(1 if report["collisions"] else 0)
    if args.output.exists():
        raise ValueError("Refusing to overwrite a decision")

    def load(directory):
        return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]

    decision = decide(args.design.read_bytes(), load(args.baseline), load(args.candidate),
                      json.loads(args.usage_before.read_text()), json.loads(args.usage_after.read_text()),
                      args.spend_limit)
    args.output.write_text(json.dumps(decision, indent=2) + "\n")
    print(json.dumps({"passed": decision["passed"], "checks": decision["checks"],
                      "hosted": decision["hosted"]}, indent=2))


if __name__ == "__main__":
    main()
