"""Selection and evidence accounting shared by bounded quality commands.

These functions do not execute product code. A green contract with no positive
relationship label is limited evidence, not a successful relationship assertion.
"""
from __future__ import annotations

from collections import Counter

OUTCOMES = ("passed", "failed", "limited", "unsupported", "incomplete")


def select_packs(specs, packs=(), shard=None):
    """Deterministic, disjoint shards; unknown or empty selections are errors."""
    ids = [spec["id"] for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate repository IDs in quality manifest")
    unknown = set(packs) - set(ids)
    if unknown:
        raise ValueError("Unknown quality packs: " + ", ".join(sorted(unknown)))
    selected = sorted((s for s in specs if not packs or s["id"] in packs), key=lambda s: s["id"])
    if shard:
        try:
            index, count = map(int, shard.split("/"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Shard must be I/N, with 1 <= I <= N") from exc
        if not 1 <= index <= count <= len(selected):
            raise ValueError("Shard must be I/N, with 1 <= I <= N <= selected packs")
        selected = selected[index - 1::count]
    if not selected:
        raise ValueError("No quality packs selected")
    return selected


def check_outcome(check):
    """Read both old boolean evidence and the explicit v2 outcome."""
    outcome = check.get("outcome", "passed" if check.get("passed") else "failed")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown quality outcome: {outcome}")
    return outcome


def summarize(rows, expected):
    """Count evidence independently of execution and require every selected pack."""
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids) or set(ids) - set(expected):
        raise ValueError("Duplicate or unexpected repository evidence")
    counts = Counter({name: 0 for name in OUTCOMES})
    for row in rows:
        for check in row.get("checks", []):
            counts[check_outcome(check)] += 1
    missing = sorted(set(expected) - set(ids))
    missing_questions = sorted(q for row in rows for q in row.get("expected_questions", [])
                               if q not in {r["id"] for r in row.get("retrieval", [])})
    incomplete = missing or any(row.get("status") not in {"passed", "failed"}
                                or not row.get("checks")
                                or row.get("cleanup_verified") is not True for row in rows)
    failed = counts["failed"] or any(row.get("status") == "failed" for row in rows)
    incomplete = bool(incomplete or missing_questions)
    status = "failed" if failed else "incomplete" if incomplete or counts["incomplete"] else "passed"
    retrieval = [q for row in rows for q in row.get("retrieval", [])]
    return {"outcomes": dict(counts), "missing_packs": missing, "status": status,
            "retrieval": {"observed_questions": len(retrieval),
                          "missing_questions": missing_questions,
                          "labeled_hit_at_5": sum(q["hit_at_5"] for q in retrieval),
                          "labeled_hit_at_24": sum(q["hit_at_24"] for q in retrieval),
                          "scope": "Non-exhaustive development labels; missing questions are not zero-hit observations"},
            "passed": status == "passed", "complete": not incomplete and not counts["incomplete"]}


def reusable_rows(previous, identity, selected):
    """Resume completed evidence only, under exactly the same frozen inputs."""
    if previous.get("schema_version") != 2 or previous.get("identity") != identity:
        raise ValueError("Cannot resume quality evidence with different inputs or environment")
    if previous.get("reason") == "inputs_changed_during_run":
        raise ValueError("Cannot resume evidence collected while inputs changed")
    rows = previous.get("repositories", [])
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate repository evidence in resume report")
    return {row["id"]: row for row in rows
            if row["id"] in selected and row.get("status") == "passed"
            and row.get("cleanup_verified") is True and row.get("checks")
            and set(row.get("expected_questions", [])) <= {q["id"] for q in row.get("retrieval", [])}
            and all(check_outcome(c) in {"passed", "limited", "unsupported"} for c in row["checks"])}


def merge_reports(reports):
    """Aggregate coherent workflow shards without hiding conflicts or omissions."""
    if not reports or reports[0].get("schema_version") != 2:
        raise ValueError("Aggregation requires v2 workflow reports")
    first = reports[0]
    rows = {}
    for report in reports:
        if (report.get("schema_version") != 2 or report.get("identity") != first["identity"]
                or report.get("manifest_packs") != first["manifest_packs"]):
            raise ValueError("Cannot aggregate different candidate inputs or environments")
        if report.get("reason") == "inputs_changed_during_run" or report.get("cleanup_verified") is not True:
            raise ValueError("Cannot aggregate changed inputs or unverified cleanup")
        for row in report["repositories"]:
            if row["id"] in rows and rows[row["id"]] != row:
                raise ValueError("Conflicting repository evidence: " + row["id"])
            rows[row["id"]] = row
    result = {"schema_version": 2, "identity": first["identity"],
              "manifest_packs": first["manifest_packs"], "selected_packs": first["manifest_packs"],
              "repositories": [rows[k] for k in sorted(rows)], "model_runs": 0,
              "cleanup_verified": True}
    result.update(summarize(result["repositories"], result["manifest_packs"]))
    if any(row.get("cleanup_verified") is not True for row in result["repositories"]):
        result.update(status="incomplete", passed=False, complete=False)
    return result
