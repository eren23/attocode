"""Acceptance for the test-recall trial (flag ATTOCODE_INTEL_TEST_RECALL).

Both arms run the same engine; the candidate arm sets the flag. Labels are
authored and non-exhaustive, not agent outcomes.

    python -m eval.quality.test_recall_trial fresh --design NEW.json
    python -m eval.quality.test_recall_trial decide --design D --baseline B --candidate C --output OUT
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path

from attocode_intel.query_ranking import explicit_test_query

from eval.quality.mcp_search import compare

DESIGNS = Path(__file__).resolve().parents[2] / "packages/code-intel/evals/designs"
# Net judged-file gain on the first page, summed over repositories.
MIN_GAIN = {"development": 2, "validation": 3}
PAGES = ("5", "24", "scoped")


def decide(design_bytes, baseline_runs, candidate_runs):
    design = json.loads(design_bytes)
    packs = {g["pack"]: g["commit"] for g in design["repositories"]}
    digest = hashlib.sha256(design_bytes).hexdigest()
    runs = [*baseline_runs, *candidate_runs]
    if (sorted(r["pack"] for r in baseline_runs) != sorted(packs)
            or sorted(r["pack"] for r in candidate_runs) != sorted(packs)
            or {r["arm"] for r in baseline_runs} != {"baseline"}
            or {r["arm"] for r in candidate_runs} != {"candidate"}
            or any(r["questions_sha256"] != digest or r["commit"] != packs[r["pack"]] for r in runs)
            or len({(r["operator_sha256"], r["engine_sha256"]) for r in runs}) != 1):
        raise ValueError("Observations do not match one frozen design, operator and engine")
    expected = [q["id"] for g in design["repositories"] for q in g["queries"]]
    baseline = [row for r in baseline_runs for row in r["queries"]]
    candidate = [row for r in candidate_runs for row in r["queries"]]
    result = compare(baseline, candidate, expected)
    by_id = {row["id"]: row for row in candidate}
    net = dict.fromkeys(packs, 0)
    changed_controls = []
    for old in baseline:
        new = by_id[old["id"]]
        net[old["pack"]] += len(new["pages"]["5"]["hits"]["files"]) - len(old["pages"]["5"]["hits"]["files"])
        if not explicit_test_query(old["query"]) and any(
                old["pages"][p]["response"]["data"]["results"] != new["pages"][p]["response"]["data"]["results"]
                for p in PAGES):
            changed_controls.append(old["id"])
    file_losses = {page: sum(len(x["labels"]) for x in result["individual_losses"]
                             if x["page"] == page and x["metric"] == "files") for page in ("5", "24")}
    result["checks"].update(
        files_5_gain=sum(net.values()) >= MIN_GAIN[design["split"]] and sum(v > 0 for v in net.values()) >= 2,
        no_file_loss_5=file_losses["5"] == 0,
        no_file_loss_24=file_losses["24"] == 0,
        controls_identical=not changed_controls,
    )
    result["passed"] = all(result["checks"].values())
    result["trial"] = {"split": design["split"], "files_5_net_by_pack": net,
                       "file_label_losses": file_losses, "changed_controls": changed_controls,
                       "test_queries": sum(explicit_test_query(r["query"]) for r in baseline)}
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

    decision = decide(args.design.read_bytes(), load(args.baseline), load(args.candidate))
    args.output.write_text(json.dumps(decision, indent=2) + "\n")
    print(json.dumps({"passed": decision["passed"], "checks": decision["checks"],
                      "trial": decision["trial"]}, indent=2))


if __name__ == "__main__":
    main()
