"""Excluded client wiring checks and descriptive reports for the 54-run pilot."""
from __future__ import annotations

import json
import math
import re
import shutil
import statistics

from study import PILOT_LANES, manifest_for, servers_for, write_json
from study_clients import CLIENTS, invoke, parse_events, preflight, subscription_env
from study_tasks import evidence


def wiring_ready(study, manifest, client):
    path = study / "wiring" / client / "result.json"
    if not path.exists():
        return False
    row = json.loads(path.read_text())
    return row.get("study_id") == manifest["study_id"] and row.get("passed") is True and row.get("excluded") is True


def wiring_checks(parsed, execution, root, task, model):
    calls = parsed["tool_calls"]
    outputs = {row["id"]: row for row in parsed["tool_results"] if row["id"]}
    checks = {"client_exit": not execution["exit_code"] and not execution["timed_out"] and not execution["quota_exhausted"],
              "no_denials_or_terminal_error": not parsed["permission_denials"] and not parsed["terminal_error"],
              "tool_results": bool(calls) and all(row["id"] in outputs and outputs[row["id"]]["content"] is not None
                                                and not outputs[row["id"]]["is_error"] for row in calls),
              "source_evidence": all(evidence(root, task, parsed["output"]).values())}
    for server in ("previous", "current", "serena"):
        checks[server + "_source_result"] = any(
            row["name"].startswith(f"mcp__{server}__") and row["id"] in outputs
            and "lib/response.js" in json.dumps(outputs[row["id"]]["content"]) for row in calls)
    checks["native_source_read"] = any(
        row["name"] in {"Read", "readToolCall", "read_file", "Bash", "shell", "shellToolCall"}
        and row["id"] in outputs and "res.json = function json" in json.dumps(outputs[row["id"]]["content"])
        for row in calls)
    def normalize(value):
        return re.sub(r"[^a-z0-9]", "", value.lower())
    # Some clients do not expose a resolved model; retain that absence explicitly.
    checks["model_if_reported"] = not parsed["resolved_models"] or any(
        normalize(actual).startswith(normalize(model)) for actual in parsed["resolved_models"])
    return checks


def wiring(args):
    manifest = manifest_for(args.study)
    if manifest.get("mode") not in {"pilot", "quality"}:
        raise ValueError("Excluded wiring checks are for pilot and quality studies")
    preparation = json.loads((args.study / "preparation.json").read_text())
    if not preparation["express"]["clean_passes"] or not preparation["express"]["fault_detected"]:
        raise ValueError("Prepare and validate the Express snapshot first")
    from workflows import SCENARIOS
    env = subscription_env()
    task = next(spec for spec in SCENARIOS if spec["repo"] == "express")
    for client in args.clients or CLIENTS:
        directory = args.study / "wiring" / client
        if directory.exists():
            if wiring_ready(args.study, manifest, client):
                continue
            raise ValueError(f"Preserve failed/interrupted {client} wiring; fix the issue and freeze a new pilot")
        quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
        status = preflight(client, quota, env)
        if not status["ready"]:
            print(json.dumps({"client": client, "blocked": status}), flush=True)
            continue
        directory.mkdir(parents=True, mode=0o700)
        servers = {}
        lanes = [("current", "intel_precision"), ("serena", "serena")]
        if manifest["mode"] == "pilot":
            lanes.insert(1, ("previous", "previous_precision"))
        for name, lane in lanes:
            root = directory / name
            shutil.copytree(args.study / "sources/express", root,
                            ignore=shutil.ignore_patterns("node_modules", ".git", ".attocode", ".serena", "__pycache__"))
            servers[name] = next(iter(servers_for(manifest, args.study, root, lane, directory / name, client).values()))
        root = directory / "current"
        previous = "previous.search_symbols(name='json'), " if manifest["mode"] == "pilot" else ""
        prompt = ("This is an excluded wiring check, not a scored trial. Use a native read tool to read "
                  "lib/response.js. Use " + previous + "current.inspect_symbol(symbol_name='json', "
                  "file_path='lib/response.js'), and serena.find_symbol to locate json in lib/response.js including its body. "
                  "Read an actual usage with native tools and return JSON with definition and usage (path, 1-based line, "
                  "exact source-line quote), tests (paths or []), and summary. Use repository-relative paths. "
                  "Do not edit files, delegate, install packages, use the network, or change client settings.")
        execution = invoke(client, manifest["models"][client], root, directory, servers, prompt, manifest["timeout"], env)
        parsed = parse_events(client, (directory / "events.jsonl").read_text(), directory / "answer.json")
        checks = wiring_checks(parsed, execution, root, task, manifest["models"][client])
        if manifest["mode"] == "quality":
            checks.pop("previous_source_result")
        write_json(directory / "result.json", {"study_id": manifest["study_id"], "client": client,
                   "excluded": True, "selection": "forced_wiring", "passed": all(checks.values()), "checks": checks,
                   "model": manifest["models"][client], "resolved_models": parsed["resolved_models"], "execution": execution})
        print(json.dumps({"client": client, "wiring_passed": all(checks.values()), "checks": checks}), flush=True)
        if execution["quota_exhausted"]:
            return


def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def summarize(manifest, rows):
    expected = {row["id"] for row in manifest["schedule"]}
    indexed = {row.get("id"): row for row in rows}
    issues = []
    if len(indexed) != len(rows) or not set(indexed).issubset(expected):
        issues.append("Duplicate or unexpected run IDs")
    for row in rows:
        identity = f"{row.get('task')}:{row.get('client')}:{row.get('repeat')}:{row.get('lane')}"
        if (row.get("id") != identity or row.get("study_id") != manifest["study_id"]
                or row.get("model") != manifest["models"].get(row.get("client"))
                or row.get("status") not in {"completed", "failed", "interrupted"}
                or type(row.get("passed")) is not bool
                or (row["passed"] and row["status"] != "completed")
                or type(row.get("seconds")) not in {int, float} or not math.isfinite(row["seconds"]) or row["seconds"] <= 0):
            issues.append("Invalid run identity, status, model, or time")
            break
    complete = not issues and set(indexed) == expected
    comparisons, lanes = [], []
    if not issues:
        for client in CLIENTS:
            for lane in PILOT_LANES:
                selected = [row for row in rows if row["client"] == client and row["lane"] == lane]
                stages = [stage for row in selected for stage in row.get("stages", [])]
                observed = [stage["observations"] for stage in stages if "observations" in stage]
                lanes.append({"client": client, "lane": lane, "runs": len(selected),
                              "successes": sum(row["passed"] for row in selected),
                              "median_completion_seconds": median([row["seconds"] for row in selected]),
                              "observed_stages": len(observed),
                              "mcp_used_runs": sum(any(s.get("mcp_used") for s in row.get("stages", [])) for row in selected),
                              "observations": {key: median([r.get(key) for r in observed]) for key in (
                                  "inspect_symbol_calls", "discovery_calls", "native_read_search_calls", "native_shell_calls",
                                  "follow_up_read_search_calls", "follow_up_shell_calls", "mcp_result_tokens", "first_event_seconds",
                                  "tool_intervals_observed", "tool_intervals_missing")}})
            for current, previous in (("intel_base", "previous_base"), ("intel_precision", "previous_precision")):
                for comparator in (previous, "native", "serena"):
                    pairs = []
                    for repeat in range(3):
                        a = indexed.get(f"express:lookup:{client}:{repeat}:{current}")
                        b = indexed.get(f"express:lookup:{client}:{repeat}:{comparator}")
                        if a and b:
                            a_time = a["seconds"] if a["passed"] else max(a["seconds"], manifest["timeout"])
                            b_time = b["seconds"] if b["passed"] else max(b["seconds"], manifest["timeout"])
                            pairs.append({"current": a["id"], "comparator": b["id"], "speedup": 1 - a_time / b_time,
                                          "seconds_saved": b_time - a_time, "current_passed": a["passed"], "comparator_passed": b["passed"]})
                    speedup = median([pair["speedup"] for pair in pairs])
                    quality = sum(p["current_passed"] for p in pairs) >= sum(p["comparator_passed"] for p in pairs)
                    promising = (len(pairs) == 3 and quality and any(p["current_passed"] for p in pairs) and speedup >= .20)
                    comparisons.append({"client": client, "lane": current, "comparator": comparator, "pairs": pairs,
                                        "median_paired_speedup": speedup, "median_seconds_saved": median([p["seconds_saved"] for p in pairs]),
                                        "status": "incomplete" if len(pairs) != 3 else "promising" if promising else "needs_work"})
    return {"mode": "pilot", "complete": complete, "attempted": len(indexed), "required": len(expected),
            "missing": sorted(expected - set(indexed)), "issues": issues, "release_eligible": False,
            "interpretation": "Three repetitions are descriptive development evidence, not a competitive ranking.",
            "lanes": lanes, "comparisons": comparisons}


def write_review(study, report):
    """Keep hypotheses separate from observed timing and manual source-overlap review."""
    pilot = report["pilot"]
    def show(value):
        return "unavailable" if value is None else f"{value:.2f}"
    lines = ["# All-client lookup pilot", "", f"Attempts: {pilot['attempted']}/{pilot['required']}. Complete: {pilot['complete']}.",
             "", pilot["interpretation"], "", "This report cannot authorize a release.", "",
             "| Client | Setup | Passed/attempted | Median seconds | MCP used in runs | Follow-up reads/searches |",
             "|---|---|---:|---:|---:|---:|"]
    for row in pilot["lanes"]:
        lines.append(f"| {row['client']} | {row['lane']} | {row['successes']}/{row['runs']} | "
                     f"{show(row['median_completion_seconds'])} | {row['mcp_used_runs']} | "
                     f"{show(row['observations']['follow_up_read_search_calls'])} |")
    lines += ["", "## Paired comparisons", "", "Failed attempts receive at least the 600-second timeout penalty in comparisons.", "",
              "| Client | Current setup | Comparator | Pairs | Median time reduction | Status |", "|---|---|---|---:|---:|---|"]
    for row in pilot["comparisons"]:
        gain = row["median_paired_speedup"]
        lines.append(f"| {row['client']} | {row['lane']} | {row['comparator']} | {len(row['pairs'])} | "
                     f"{'unavailable' if gain is None else format(gain, '.1%')} | {row['status']} |")
    lines += ["", "## Trace review", "", "Follow-up calls alone do not establish redundancy. Check requested paths, lines, "
              "and evidence already returned before proposing a change. Shell calls are listed separately because their purpose may be ambiguous.", ""]
    for row in report["runs"]:
        directory = row["id"].replace(":", "-")
        lines.append(f"- {row['id']}: passed={row['passed']}; [run](runs/{directory}/result.json); "
                     f"[timestamped events](runs/{directory}/stage-0/events.jsonl).")
    lines += ["", "## Next-fix evidence", ""]
    if not report["runs"]:
        lines.append("No live evidence yet. Complete client readiness and wiring checks before choosing a performance fix.")
    else:
        for row in pilot["lanes"]:
            if not row["lane"].startswith("intel") or not row["runs"]:
                continue
            prefix = f"{row['client']} / {row['lane']}"
            if row["successes"] < row["runs"]:
                lines.append(f"- {prefix}: inspect failed source evidence or client errors before optimizing latency.")
            if row["mcp_used_runs"] < row["runs"]:
                lines.append(f"- {prefix}: intelligence was unused in {row['runs'] - row['mcp_used_runs']} attempts; inspect tool discovery and task fit.")
            followup = row["observations"]["follow_up_read_search_calls"]
            if followup:
                lines.append(f"- {prefix}: median {followup:g} native follow-up calls; compare their requested evidence with the bundle before changing it.")
        lines.append("Engine phase timings remain in stage-0/engine.jsonl where available. They can overlap and must not be added to client timings.")
    with (study / "pilot-review.md").open("w") as stream:
        stream.write("\n".join(lines) + "\n")
    (study / "pilot-review.md").chmod(0o600)
