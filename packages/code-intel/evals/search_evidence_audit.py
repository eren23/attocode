"""Audit existing Claude localization traces offline; never run clients or rescore.

Usage: python search_evidence_audit.py --study /frozen/r3 --output /new/directory
Requires the editable code-intel package for its shared lexical tokenizer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import attocode_intel.focused_evidence as lexical
from attocode_intel.focused_evidence import terms


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_path(value: str, workspace: str = "") -> str:
    if workspace and value.startswith(workspace.rstrip("/") + "/"):
        value = value[len(workspace.rstrip("/")) + 1:]
    value = re.sub(r":\d+(?:-\d+)?$", "", value)
    return value.removeprefix("./")


def content_text(content) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b["text"] for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        return "".join(parts) if parts else None
    return None


def trace_calls(raw: str) -> tuple[list[dict], list[str]]:
    """Join calls to results by ID, keeping malformed/ambiguous evidence unknown."""
    calls, by_id, warnings = [], {}, []
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
            event = event.get("event", event)
            content = (event.get("message") or {}).get("content")
        except (ValueError, AttributeError, TypeError):
            warnings.append(f"event {number}: malformed event")
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                call_id = block.get("id")
                if not isinstance(call_id, str):
                    warnings.append(f"event {number}: missing tool ID")
                    continue
                call = {"id": call_id, "name": block.get("name"), "arguments": block.get("input"),
                        "call_event": number, "result_event": None, "result_text": None,
                        "result_error": False, "ambiguous": False}
                if call_id in by_id:
                    old = by_id[call_id]
                    if (old["name"], old["arguments"]) != (call["name"], call["arguments"]):
                        old["ambiguous"] = True
                        warnings.append(f"event {number}: conflicting tool ID {call_id}")
                else:
                    by_id[call_id] = call
                    calls.append(call)
            elif block.get("type") == "tool_result":
                call = by_id.get(block.get("tool_use_id"))
                if call is None:
                    warnings.append(f"event {number}: unmatched tool result")
                    continue
                value = content_text(block.get("content"))
                error = bool(block.get("is_error"))
                if call["result_event"] is not None:
                    if (call["result_text"], call["result_error"]) != (value, error):
                        call["ambiguous"] = True
                        warnings.append(f"event {number}: conflicting result for {call['id']}")
                    continue
                call.update(result_event=number, result_text=value, result_error=error)
    return calls, warnings


def search_result(call: dict) -> dict:
    result = {"call_id": call["id"], "call_event": call["call_event"],
              "result_event": call["result_event"], "arguments": call["arguments"],
              "status": "unknown", "reason": None, "hits": []}
    if call["ambiguous"] or call["result_error"] or call["result_text"] is None:
        result["reason"] = "conflicting, failed, or missing tool result"
        return result
    try:
        payload = json.loads(call["result_text"])
        data = payload["data"]
        hits = data["results"]
        if not isinstance(hits, list) or any(
            not isinstance(h, dict) or not isinstance(h.get("file_path"), str) for h in hits
        ):
            raise ValueError("invalid result rows")
        for hit in hits:
            if "snippet" in hit and not isinstance(hit["snippet"], str):
                raise ValueError("invalid snippet")
            for key in ("matched_terms", "match_fields"):
                if key in hit and (not isinstance(hit[key], list)
                                   or any(not isinstance(term, str) for term in hit[key])):
                    raise ValueError("invalid match explanation")
    except (ValueError, KeyError, TypeError):
        result["reason"] = "unparseable search response; not evidence of no results"
        return result
    result.update(status="observed", hits=hits, metadata=payload.get("metadata", {}),
                  ranking=data.get("ranking", {}), follow_up=data.get("follow_up"))
    return result


def audit_run(row: dict, task: dict, raw: str, workspace: str = "") -> dict:
    calls, warnings = trace_calls(raw)
    gold = set(task["gold"])
    answer = {normalize_path(p, workspace) for p in row["files"]}
    searches = []
    for call in calls:
        if not str(call["name"]).endswith("semantic_search"):
            continue
        search = search_result(call)
        for rank, hit in enumerate(search["hits"], 1):
            path = normalize_path(hit["file_path"], workspace)
            snippet = hit.get("snippet", "")
            snippet = snippet if isinstance(snippet, str) else ""
            hit.update(
                delivered_rank=rank, file_path=path, labeled=path in gold,
                in_answer=path in answer,
                reported_terms_not_visible=sorted(set(hit.get("matched_terms", [])) - terms(snippet)),
                explicit_reads_after_result=[c["id"] for c in calls
                    if c["name"] == "Read" and not c["result_error"] and not c["ambiguous"]
                    and c["result_event"] is not None
                    and c["call_event"] > (call["result_event"] or len(raw.splitlines()))
                    and isinstance(c["arguments"], dict)
                    and normalize_path(c["arguments"].get("file_path", ""), workspace) == path],
            )
        searches.append(search)
    shown = {h["file_path"] for s in searches for h in s["hits"]}
    complete = bool(searches) and not warnings and all(s["status"] == "observed" for s in searches)
    observations = []
    for call in calls:
        if call["name"] not in {"Read", "Grep", "Glob"}:
            continue
        response = call["result_text"]
        observations.append({
            "id": call["id"], "name": call["name"], "arguments": call["arguments"],
            "call_event": call["call_event"], "result_event": call["result_event"],
            "result_error": call["result_error"], "ambiguous": call["ambiguous"],
            "response_sha256": digest(response.encode()) if response is not None else None,
            "response_preview": response[:500] if response is not None else None,
            "response_preview_truncated": response is not None and len(response) > 500,
        })
    return {
        "id": row["id"], "task": row["task"], "setup": row["setup"], "trial": row["trial"],
        "events": row["events"], "gold": sorted(gold), "answer": sorted(answer),
        "searches": searches, "search_trace_complete": complete, "warnings": warnings,
        "labeled_delivered": sorted(gold & shown),
        "labeled_delivered_not_answered": sorted((gold & shown) - answer),
        "labeled_not_delivered": sorted(gold - shown) if complete else None,
        "local_tool_calls": observations,
    }


def audit(study: Path) -> dict:
    study = study.resolve()
    hashes = {}

    def read(relative):
        path = (study / relative).resolve()
        if not path.is_relative_to(study):
            raise ValueError(f"Input escapes study: {relative}")
        data = path.read_bytes()
        hashes[str(path.relative_to(study))] = digest(data)
        return data.decode()

    manifest = json.loads(read("manifest.json"))
    rows = [json.loads(line) for line in read("runs.jsonl").splitlines() if line.strip()]
    tasks = {t["id"]: t for t in manifest["tasks"]}
    ledger, ids, pairs = [], set(), Counter()
    for row in rows:
        if row["id"] in ids:
            raise ValueError(f"Duplicate run: {row['id']}")
        ids.add(row["id"])
        pairs[(row["task"], row["trial"], row["setup"])] += 1
        run_file = str(Path(row["events"]).parent.parent / "result.json")
        run_result = json.loads(read(run_file))
        ledger.append(audit_run(row, tasks[row["task"]], read(row["events"]),
                                run_result.get("workspace", "")))
    expected = {(t["id"], trial, setup) for t in manifest["tasks"]
                for trial in range(manifest["trials"]) for setup in manifest["setups"]}
    if set(pairs) != expected or any(n != 1 for n in pairs.values()):
        raise ValueError("Study does not contain exactly the declared task/trial/setup pairs")
    treatment = [r for r in ledger if r["setup"] == "intel_first"]
    omitted_hits = [h for r in treatment for s in r["searches"] for h in s["hits"]
                    if h["labeled"] and not h["in_answer"]]
    summary = {
        "runs": len(ledger), "tasks": len(tasks),
        "runs_by_setup": dict(Counter(r["setup"] for r in ledger)),
        "search_calls": sum(len(r["searches"]) for r in ledger),
        "treatment_runs_with_complete_search_trace": sum(r["search_trace_complete"] for r in treatment),
        "treatment_runs_with_all_labels_delivered": sum(set(r["gold"]) <= set(r["labeled_delivered"])
                                                        for r in treatment),
        "treatment_runs_with_delivered_label_omitted": sum(bool(r["labeled_delivered_not_answered"])
                                                           for r in treatment),
        "treatment_runs_with_no_labels_delivered": sum(not r["labeled_delivered"] and r["search_trace_complete"]
                                                       for r in treatment),
        "omitted_labeled_hit_occurrences": len(omitted_hits),
        "omitted_labeled_hits_with_truncated_snippets": sum(bool(h.get("snippet_truncated")) for h in omitted_hits),
        "omitted_labeled_hits_with_explicit_read_after": sum(bool(h["explicit_reads_after_result"]) for h in omitted_hits),
    }
    for relative, expected_hash in hashes.items():
        if digest((study / relative).read_bytes()) != expected_hash:
            raise ValueError(f"Input changed during audit: {relative}")
    script = Path(__file__)
    tokenizer = Path(lexical.__file__)
    return {"version": 1, "study_id": manifest["study_id"], "model": manifest["model"],
            "engine_sha256": manifest.get("engine_sha256"), "input_sha256": hashes,
            "audit_sha256": digest(script.read_bytes()), "tokenizer_sha256": digest(tokenizer.read_bytes()),
            "summary": summary, "runs": sorted(ledger, key=lambda r: r["id"])}


def report(data: dict) -> str:
    summary = data["summary"]
    treatments = summary["runs_by_setup"].get("intel_first", 0)
    lines = ["# R3 search evidence audit", "", "Offline analysis of existing traces; no client calls or rescoring.",
             "", f"Study: `{data['study_id']}`. Model: `{data['model']}`.", "",
             f"Audited {summary['runs']} runs across {summary['tasks']} tasks, "
             f"with {summary['search_calls']} recorded search calls.", "",
             f"All labels were delivered in {summary['treatment_runs_with_all_labels_delivered']}/{treatments} treatment runs. "
             f"A delivered label was omitted from the answer in "
             f"{summary['treatment_runs_with_delivered_label_omitted']}/{treatments} runs. "
             f"No label was delivered in {summary['treatment_runs_with_no_labels_delivered']}/{treatments} runs.",
             "", "## Task observations", "",
             "| Task | Native answers containing every label | Intel answers containing every label | Intel runs omitting a delivered label |",
             "| --- | ---: | ---: | ---: |"]
    for task in sorted({r["task"] for r in data["runs"]}):
        rows = [r for r in data["runs"] if r["task"] == task]
        groups = {s: [r for r in rows if r["setup"] == s] for s in ("native", "intel_first")}
        cells = [f"{sum(set(r['gold']) <= set(r['answer']) for r in rs)}/{len(rs)}" for rs in groups.values()]
        omitted = sum(bool(r["labeled_delivered_not_answered"]) for r in groups["intel_first"])
        lines.append(f"| {task} | {cells[0]} | {cells[1]} | {omitted} |")
    lines.extend(["", "## Delivered labels omitted from answers", "",
                  f"There are {summary['omitted_labeled_hit_occurrences']} omitted labeled hit occurrences, "
                  f"including {summary['omitted_labeled_hits_with_truncated_snippets']} truncated snippets. "
                  f"{summary['omitted_labeled_hits_with_explicit_read_after']} have an explicit successful Read "
                  "after the search result. This does not exclude inspection through Grep.", "",
                  "| Path | Occurrences | Delivered ranks | Truncated snippets | Reported terms outside preview |",
                  "| --- | ---: | --- | ---: | --- |"])
    by_path = {}
    for run in data["runs"]:
        for search in run["searches"]:
            for hit in search["hits"]:
                if hit["labeled"] and not hit["in_answer"]:
                    by_path.setdefault(hit["file_path"], []).append(hit)
    for path, hits in sorted(by_path.items()):
        ranks = ", ".join(str(n) for n in sorted({h["delivered_rank"] for h in hits}))
        outside = ", ".join(sorted({t for h in hits for t in h["reported_terms_not_visible"]})) or "none"
        truncated = sum(bool(h.get("snippet_truncated")) for h in hits)
        lines.append(f"| `{path}` | {len(hits)} | {ranks} | {truncated} | {outside} |")
    lines.extend(["", "## Interpretation", "",
        "Delivered-but-omitted paths are observations, not proof that the agent ignored them or that output caused failure. "
        "Explicit Read calls are recorded separately from Grep and Glob; a path can be seen without a Read call.", "",
        "Missing from the delivered page does not establish a candidate-pool miss. Full pools and historical source "
        "chunks are unavailable in these traces. Reported terms absent from snippets can match symbol identity "
        "or omitted source, so that diagnostic alone is not a source-loss judgment.", "",
        "Labels are developer-changed files, not exhaustive relevance judgments. Native comparisons are observations "
        "on the same tasks, not causal explanations for individual tool-assisted failures.", "",
        "The ledger binds the manifest, original scores, run metadata and traces to SHA-256 hashes. "
        "Raw records and scores are unchanged. These cases are development evidence, not a fresh held-out evaluation.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    study, output = args.study.resolve(), args.output.resolve()
    if output.is_relative_to(study) or study.is_relative_to(output):
        parser.error("Output must be separate from the frozen study")
    if output.exists():
        parser.error("Output directory must be new; existing artifacts are never overwritten")
    data = audit(study)
    output.mkdir(parents=True, exist_ok=False)
    (output / "ledger.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    (output / "report.md").write_text(report(data))
    print(json.dumps({"output": str(output), **data["summary"]}, indent=2))


if __name__ == "__main__":
    main()
