"""Source-grounded development scoring; prose quality requires separate blind review."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics

from jsonschema import Draft202012Validator

VERDICTS = ("supported", "contradicted", "insufficient")
MAX_CITATION_LINES = 12
CITATION = {"type": "object", "properties": {"path": {"type": "string"}, "line": {"type": "integer", "minimum": 1},
            "quote": {"type": "string", "minLength": 1}}, "required": ["path", "line", "quote"], "additionalProperties": False}
ANSWER_SCHEMA = {"type": "object", "properties": {
    "claims": {"type": "array", "maxItems": 32, "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "maxItems": 12, "items": CITATION},
        "explanation": {"type": "string"}}, "required": ["id", "verdict", "confidence", "evidence", "explanation"],
        "additionalProperties": False}},
    "ranked_files": {"type": "array", "maxItems": 32, "items": {"type": "string"}},
    "summary": {"type": "string"}}, "required": ["claims", "ranked_files", "summary"], "additionalProperties": False}
METRICS = ("verdict_accuracy", "balanced_verdict_accuracy", "answer_coverage", "grounded_claim_precision",
           "grounded_claim_recall", "citation_validity", "citation_anchor_precision", "unsupported_assertion_rate",
           "brier_score", "retrieval_precision", "retrieval_recall", "retrieval_f1", "mrr", "ndcg",
           "retrieval_judgment_coverage")


def validate_sources(root, task):
    for name, expected in task["file_hashes"].items():
        path = (root / name).resolve()
        if (not path.is_relative_to(root.resolve()) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError(f"Quality ground truth no longer matches source: {name}")


def failed_grade(reason):
    # Precision and calibration are undefined without an answer; coverage and recall are zero.
    values = {key: None for key in METRICS}
    values.update(verdict_accuracy=0.0, balanced_verdict_accuracy=0.0, answer_coverage=0.0,
                  grounded_claim_recall=0.0, retrieval_recall=0.0, retrieval_f1=0.0, mrr=0.0, ndcg=0.0)
    return {"automated_pass": False, "assessment": "failed", "issues": [reason], "metrics": values,
            "claims": [], "citation_review": {"required": False, "unmatched": [], "invalid": []},
            "prose_review": "pending"}


def grade(root, task, answer):
    """A correct label with unrelated source is not a grounded answer."""
    validate_sources(root, task)
    try:
        json.dumps(answer, allow_nan=False)
        errors = list(Draft202012Validator(ANSWER_SCHEMA).iter_errors(answer))
        if errors:
            return failed_grade("Answer does not conform to the quality schema")
    except (TypeError, ValueError):
        return failed_grade("Answer contains non-JSON or non-finite values")
    expected = {c["id"]: c for c in task["claims"]}
    ids = [c["id"] for c in answer["claims"]]
    ranks = answer["ranked_files"]
    if len(ids) != len(set(ids)) or not set(ids).issubset(expected):
        return failed_grade("Duplicate or unknown claim IDs")
    if len(ranks) != len(set(ranks)):
        return failed_grade("Duplicate retrieval results")
    rows, valid_cites, supporting_cites, all_cites, asserted, wrong_asserted, brier = [], 0, 0, 0, 0, 0, []
    answered = {c["id"]: c for c in answer["claims"]}
    unmatched, invalid = [], []
    for identity, gold in expected.items():
        given = answered.get(identity)
        correct = bool(given and given["verdict"] == gold["verdict"])
        groups = gold["evidence_groups"]
        allowed = {(a["path"], a["line"]) for group in groups for a in group}
        observed = set()
        # Repeating a citation cannot increase its weight.
        citations = {(c["path"], int(c["line"]), c["quote"]) for c in given["evidence"]} if given else set()
        for name, line, quote in sorted(citations):
            all_cites += 1
            citation = {"claim": identity, "path": name, "line": line, "quote": quote}
            path = (root / name).resolve()
            if name not in task["file_hashes"] or not path.is_relative_to(root.resolve()):
                invalid.append({**citation, "reason": "Path is outside the frozen source evidence"})
                continue
            lines = path.read_text().splitlines()
            quoted = quote.splitlines()
            actual = lines[line - 1:line - 1 + len(quoted)]
            if len(quoted) > MAX_CITATION_LINES:
                invalid.append({**citation, "reason": "Citation exceeds the 12-line excerpt limit"})
                continue
            if (not quote.strip() or len(actual) != len(quoted) or actual[0].strip() != quoted[0].strip()
                    or [s.rstrip() for s in actual[1:]] != [s.rstrip() for s in quoted[1:]]):
                invalid.append({**citation, "reason": "Quote does not match the cited source excerpt"})
                continue
            valid_cites += 1
            covered_lines = {(name, line + i) for i in range(len(quoted))} & allowed
            if covered_lines:
                supporting_cites += 1
                observed.update(covered_lines)
            else:
                # Exact source outside an authored anchor is unjudged, not proven unrelated.
                unmatched.append(citation)
        covered = sum(any((a["path"], a["line"]) in observed for a in group) for group in groups)
        grounded = correct and covered == len(groups) and bool(groups)
        if given:
            brier.append((given["confidence"] - int(correct)) ** 2)
            if given["verdict"] != "insufficient":
                asserted += 1
                wrong_asserted += not correct
        rows.append({"id": identity, "expected": gold["verdict"], "answered": bool(given), "correct": correct,
                     "grounded": grounded, "evidence_groups_covered": covered, "evidence_groups_required": len(groups)})
    truth, found = set(task["relevant_files"]), set(ranks)
    unjudged = sorted(found - set(task["candidate_files"])) if task.get("discovery") else []
    invalid_retrieval = sorted(found - set(task["file_hashes"])) if task.get("discovery") else []
    relevant = len(truth & found)
    precision = relevant / len(found) if found else 0.0
    recall = relevant / len(truth)
    dcg = sum(int(name in truth) / math.log2(i + 2) for i, name in enumerate(ranks))
    ideal = sum(1 / math.log2(i + 2) for i in range(len(truth)))
    per_verdict = [statistics.mean(r["correct"] for r in rows if r["expected"] == label)
                   for label in VERDICTS if any(r["expected"] == label for r in rows)]
    grounded = sum(r["grounded"] for r in rows)
    metrics = {"verdict_accuracy": sum(r["correct"] for r in rows) / len(rows),
               "balanced_verdict_accuracy": statistics.mean(per_verdict), "answer_coverage": len(ids) / len(rows),
               "grounded_claim_precision": grounded / len(ids) if ids else None, "grounded_claim_recall": grounded / len(rows),
               "citation_validity": valid_cites / all_cites if all_cites else None,
               "citation_anchor_precision": supporting_cites / all_cites if all_cites else None,
               "unsupported_assertion_rate": wrong_asserted / asserted if asserted else None,
               "brier_score": statistics.mean(brier) if brier else None,
               "retrieval_precision": precision if ranks else None, "retrieval_recall": recall,
               "retrieval_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
               "mrr": next((1 / (i + 1) for i, name in enumerate(ranks) if name in truth), 0.0), "ndcg": dcg / ideal,
               "retrieval_judgment_coverage": len(found & set(task["candidate_files"])) / len(found) if found else None}
    if unjudged:
        # Unlabeled files are neither false positives nor automatically relevant.
        # Required-file recall is known; precision-dependent metrics await adjudication.
        metrics.update(retrieval_precision=None, retrieval_f1=None, mrr=None, ndcg=None)
    issues = []
    if unjudged:
        issues.append("Retrieved files outside the private relevance judgments require review")
    elif not found.issubset(task["candidate_files"]):
        issues.append("Retrieval contains files outside the judged candidate pool")
    if invalid_retrieval:
        issues.append("Retrieved paths are outside the frozen Python source evidence")
    if len(ids) != len(rows):
        issues.append("Required claims are missing")
    if any(r["answered"] and not r["correct"] for r in rows):
        issues.append("One or more claim verdicts disagree with the frozen source rubric")
    if any(r["answered"] and r["evidence_groups_covered"] < r["evidence_groups_required"] for r in rows):
        issues.append("One or more required evidence groups lack an authored anchor citation")
    judged_found = found - set(unjudged)
    if truth != judged_found:
        issues.append("Retrieved files differ from the judged relevant set")
    if invalid:
        issues.append("One or more citations do not match frozen source")
    if unmatched:
        issues.append("Valid source citations outside authored anchors require review")
    passed = (not issues and grounded == len(rows) and truth == found and supporting_cites == all_cites)
    review_only = (bool(unmatched or unjudged) and not invalid and not invalid_retrieval
                   and all(r["correct"] for r in rows) and truth == judged_found)
    return {"automated_pass": passed, "assessment": "passed" if passed else "needs_review" if review_only else "failed",
            "issues": issues, "metrics": metrics, "claims": rows, "prose_review": "pending",
            "citation_review": {"required": bool(unmatched), "unmatched": unmatched, "invalid": invalid},
            "retrieval_review": {"required": bool(unjudged), "unjudged": unjudged, "invalid": invalid_retrieval},
            "retrieval_scope": "Required-file recall with private partial judgments" if task.get("discovery")
                               else "Finite judged candidate pool; not exhaustive repository recall"}


def mean_observed(values):
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def summarize(manifest, runs):
    expected = {r["id"] for r in manifest["schedule"]}
    ids = [r.get("id") for r in runs]
    issues = []
    if len(ids) != len(set(ids)) or not set(ids).issubset(expected):
        issues.append("Duplicate or unexpected trials")
    for row in runs:
        if (row.get("study_id") != manifest["study_id"] or row.get("model") != manifest["models"].get(row.get("client"))
                or row.get("id") != f"{row.get('task')}:{row.get('client')}:{row.get('repeat')}:{row.get('lane')}"
                or row.get("status") not in {"completed", "failed", "interrupted"}
                or type(row.get("passed")) is not bool or (row["passed"] and row["status"] != "completed")
                or type(row.get("seconds")) not in {float, int} or not math.isfinite(row["seconds"]) or row["seconds"] <= 0):
            issues.append("Invalid trial provenance or timing")
            break
    groups = []
    if not issues:
        for client in manifest.get("onboarding", {}).get("clients", manifest["models"]):
            for lane in manifest["lanes"]:
                selected = [r for r in runs if r["client"] == client and r["lane"] == lane]
                grades = [r.get("quality", failed_grade("No completed answer")) for r in selected]
                groups.append({"client": client, "lane": lane, "attempted": len(selected),
                               "automated_passes": sum(g["automated_pass"] for g in grades),
                               "citation_review_required": sum(g.get("citation_review", {}).get("required", False) for g in grades),
                               "retrieval_review_required": sum(g.get("retrieval_review", {}).get("required", False) for g in grades),
                               "assessments": {status: sum(g.get("assessment", "unclassified") == status for g in grades)
                                               for status in ("passed", "needs_review", "failed", "unclassified")},
                               "mcp_used_runs": sum(any(s.get("mcp_used") for s in r.get("stages", [])) for r in selected),
                               "median_seconds": statistics.median(r["seconds"] for r in selected) if selected else None,
                               "metrics": {key: {"mean": statistics.mean(values) if values else None, "observed": len(values)}
                                           for key in METRICS for values in [[g["metrics"][key] for g in grades if g["metrics"][key] is not None]]}})
    comparisons = []
    if not issues:
        indexed = {r["id"]: r for r in runs}
        comparisons_to_run = manifest.get("onboarding", {}).get("comparisons", [
            [current, comparator] for current in ("intel_base", "intel_precision") for comparator in ("native", "serena")])
        for client in manifest.get("onboarding", {}).get("clients", manifest["models"]):
            for current, comparator in comparisons_to_run:
                pairs = []
                for scheduled in manifest["schedule"]:
                    if scheduled["client"] != client or scheduled["lane"] != current:
                        continue
                    a = indexed.get(scheduled["id"])
                    b = indexed.get(f"{scheduled['task']}:{client}:{scheduled['repeat']}:{comparator}")
                    if a and b:
                        ga = a.get("quality", failed_grade("Incomplete answer"))["metrics"]
                        gb = b.get("quality", failed_grade("Incomplete answer"))["metrics"]
                        pairs.append({"current": a["id"], "comparator": b["id"],
                                      "grounded_recall_delta": ga["grounded_claim_recall"] - gb["grounded_claim_recall"],
                                      "retrieval_f1_delta": ga["retrieval_f1"] - gb["retrieval_f1"]
                                          if ga["retrieval_f1"] is not None and gb["retrieval_f1"] is not None else None,
                                      "seconds_delta": a["seconds"] - b["seconds"]})
                comparisons.append({"client": client, "current": current, "comparator": comparator, "pairs": pairs,
                                    "mean_grounded_recall_delta": statistics.mean(p["grounded_recall_delta"] for p in pairs) if pairs else None,
                                    "mean_retrieval_f1_delta": mean_observed(p["retrieval_f1_delta"] for p in pairs),
                                    "retrieval_f1_pairs_observed": sum(p["retrieval_f1_delta"] is not None for p in pairs)})
    return {"attempted": len(ids), "required": len(expected), "complete": not issues and set(ids) == expected,
            "missing": sorted(expected - set(ids)), "issues": issues, "groups": groups,
            "comparisons": comparisons,
            "release_eligible": False, "prose_review": "pending",
            "scope": "Development cases with supplied or private partial relevance pools; no held-out or exhaustive accuracy claim"}


def write_review(study, report):
    """Export answer content for human review without client, lane, timing, or score labels."""
    from quality_tasks import materialize
    from study import write_json
    manifest, rows = report["manifest"], report["runs"]
    tasks = {t["id"]: t for t in manifest["tasks"]}
    packets, key = [], {}
    for row in rows:
        identity = hashlib.sha256((manifest["study_id"] + row["id"]).encode()).hexdigest()[:20]
        key[identity] = row["id"]
        task = tasks[row["task"]]
        source_view = "review-sources/" + hashlib.sha256(task["id"].encode()).hexdigest()[:16]
        review_root = study / source_view
        if not any(p.get("source_view") == source_view for p in packets):
            for name in task["file_hashes"]:
                if name == "BENCH_NOTES.md" and task.get("mutation"):
                    continue  # The materializer creates this versioned note.
                destination = review_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(study / "sources" / task["repo"] / name, destination)
            materialize(review_root, task)
            validate_sources(review_root, task)
        packets.append({"id": identity, "question": task["question"], "claims": [{"id": c["id"], "text": c["text"]} for c in task["claims"]],
                        "answer": (row.get("stages") or [{}])[-1].get("output"),
                        "source_view": source_view, "repository": task["repo"],
                        "source_revision": manifest["revisions"][task["repo"]], "source_variant": task.get("mutation"),
                        "review": {"factual_errors": None, "missing_reasoning": None, "unsupported_prose_claims": None,
                                   "actionable": None, "identity_revealed_in_answer": None, "notes": ""}})
    write_json(study / "blind-review.json", sorted(packets, key=lambda x: x["id"]))
    write_json(study / "blind-review-key.json", key)
    lines = ["# Source-grounded quality evaluation", "", report["quality"]["scope"], "",
             f"Attempts: {report['quality']['attempted']}/{report['quality']['required']}. Prose review remains pending.", "",
             "The automatic score checks supplied claims and citations. It does not grade arbitrary prose assertions. "
             "Use blind-review.json for that review; keep the identity key separate. Reviewer must flag identity leaks in prose.", "",
             "Citation anchor precision measures agreement with authored lines, not semantic citation relevance. "
             "Valid source outside those lines requires review; it is not automatically an answer error.", "",
             "Discovery questions omit candidate paths. Unjudged retrieved files require review and leave precision-dependent "
             "metrics unavailable; required-file recall remains measurable.", "",
             "| Client | Setup | Automated passes | Citation reviews needed | Retrieval reviews needed | Grounded claim recall | Retrieval F1 | Median seconds | MCP used |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    def show(value):
        return "unavailable" if value is None else f"{value:.3f}"
    for g in report["quality"]["groups"]:
        lines.append(f"| {g['client']} | {g['lane']} | {g['automated_passes']}/{g['attempted']} | "
                     f"{g['citation_review_required']} | "
                     f"{g['retrieval_review_required']} | "
                     f"{show(g['metrics']['grounded_claim_recall']['mean'])} | {show(g['metrics']['retrieval_f1']['mean'])} | "
                     f"{show(g['median_seconds'])} | {g['mcp_used_runs']} |")
    lines += ["", "Failed and interrupted attempts remain in coverage/recall denominators. Undefined precision and calibration "
              "remain null with observation counts. Compare matched task/repetition rows before attributing a quality or speed difference.", ""]
    (study / "quality-review.md").write_text("\n".join(lines))
    (study / "quality-review.md").chmod(0o600)
