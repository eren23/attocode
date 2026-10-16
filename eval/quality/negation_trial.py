"""Acceptance for a penalty-only behavioral-negation trial, using actual MCP output."""
from eval.quality.mcp_search import compare


def decide(baseline, candidate, expected_ids):
    result = compare(baseline, candidate, expected_ids)
    by_id = {row["id"]: row for row in candidate}
    generation, scopes = True, True
    for old in baseline:
        new = by_id[old["id"]]
        for page in ("5", "24", "scoped"):
            before = old["pages"][page].get("generation_diagnostic", [])
            after = new["pages"][page].get("generation_diagnostic", [])
            generation &= (len(before) == 3 and {x["stage"] for x in before} == {"keyword", "body", "file_bm25"}
                           and before == after)
            if old["category"] == "scope":
                scopes &= old["pages"][page]["response"]["data"]["results"] == new["pages"][page]["response"]["data"]["results"]
    result["checks"].update(generation_identical=generation, explicit_scope_results_identical=scopes)
    result["passed"] = all(result["checks"].values())
    return result
