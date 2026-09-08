"""Opt-in, metered Claude CLI navigation comparison on disposable snapshots.

Same prompt/model and native read tools in each lane. Reports known-file anchor
hits, actual tool usage, cost and tokens; this is not a coding-success benchmark.
Requires an authenticated Claude CLI. Run artifacts belong outside the source
repository. Serena requires an explicitly supplied, revision-pinned launcher.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from workflows import SCENARIOS, engine_fingerprint, snapshot

NATIVE = ["Read", "Grep", "Glob", "ToolSearch"]
INTEL = ["bootstrap", "search_symbols", "symbols", "cross_references", "dependencies",
         "suggest_tests", "relevant_context", "capabilities"]
SERENA = ["initial_instructions", "check_onboarding_performed", "find_symbol",
          "find_referencing_symbols", "get_symbols_overview", "search_for_pattern",
          "find_file", "list_dir", "read_file", "get_current_config"]
TARGETS = {"fastapi": "the serialize_response function used by request handling",
           "express": "the Express response object's json method",
           "frontend": "the cn utility used by UI components",
           "ripgrep": "the ignore crate's WalkBuilder type"}
SCHEMA = {"type": "object", "properties": {
    key: {"type": "string"} for key in ("definition", "caller", "importer", "test", "limitations")
}, "required": ["definition", "caller", "importer", "test", "limitations"],
    "additionalProperties": False}


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"model_requested": args.model, "claude_version": subprocess.check_output(
        ["claude", "--version"], text=True).strip(), "engine_sha256": engine_fingerprint(args.project),
        "navigation_tools_required": args.require_navigation_tools,
        "method": "Single runs of four navigation questions; known file anchors only; no coding-success or exhaustive-recall claim",
        "runs": []}
    launcher = json.loads(args.serena_launcher.read_text()) if args.serena_launcher else None
    if "serena" in args.lanes and not launcher:
        raise ValueError("Serena lane requires --serena-launcher JSON with command and args")
    with tempfile.TemporaryDirectory(prefix="intel-client-eval-") as temp:
        engine_source = Path(temp) / "engine"
        shutil.copytree(args.project / "packages/code-intel/src", engine_source,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for spec in SCENARIOS:
            if spec["repo"] not in args.repos:
                continue
            source = args.project if spec["repo"] == "frontend" else args.repo_dir / spec["repo"]
            revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            for lane in args.lanes:
                destination = Path(temp) / (spec["repo"] + "-" + lane)
                destination.mkdir()
                root = snapshot(source, destination, spec["repo"] == "frontend", revision)
                servers = {}
                allowed = list(NATIVE)
                if lane.startswith("intel"):
                    servers["intelligence"] = {"command": str(args.intel.resolve()),
                        "args": ["--profile", "daily", "--project", str(root)],
                        "env": {"ATTOCODE_INTEL_PRECISION": "auto" if lane == "intel_precision" else "off",
                                "PYTHONPATH": str(engine_source)}}
                    allowed += ["mcp__intelligence__" + tool for tool in INTEL]
                elif lane == "serena":
                    servers["serena"] = {**launcher, "args": launcher["args"] + ["--project", str(root)]}
                    allowed += ["mcp__serena__" + tool for tool in SERENA]
                config = destination / "mcp.json"
                config.write_text(json.dumps({"mcpServers": servers}))
                prompt = (f"Inspect this repository to locate {TARGETS[spec['repo']]}. "
                          "Report (1) its definition file and line, (2) one actual call/use site file and line, "
                          "(3) a production file that imports its module or reexports it, and "
                          "(4) a relevant test file, or say none found. Give repository-relative paths. "
                          "Explain uncertainty briefly. Use the available read tools, including connected code "
                          "intelligence when useful. Read the code as evidence. Do not execute commands, edit "
                          "files, install dependencies, write memory, or perform onboarding.")
                if args.require_navigation_tools:
                    prompt += (" If a code-intelligence MCP server is connected, use its symbol lookup "
                               "and references tools before native source verification. If those tools "
                               "fail, report that failure and continue with native reads. Do not silently "
                               "skip the connected tools. If no server is connected, use native tools only.")
                command = ["claude", "-p", "--model", args.model, "--strict-mcp-config",
                           "--mcp-config", str(config), "--setting-sources", "",
                           "--settings", '{"disableAllHooks":true}', "--tools", ",".join(NATIVE),
                           "--allowedTools", ",".join(allowed), "--no-session-persistence",
                           "--disable-slash-commands", "--max-budget-usd", str(args.budget_per_run),
                           "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(SCHEMA), prompt]
                start = time.monotonic()
                process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, start_new_session=True)
                timed_out = False
                try:
                    stdout, stderr = process.communicate(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        stdout, stderr = process.communicate(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout, stderr = process.communicate()
                    timed_out = True
                events = []
                for line in stdout.splitlines():
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
                final = next((e for e in reversed(events) if e.get("type") == "result"), {})
                output = final.get("structured_output") or {}
                calls = [block for event in events for block in event.get("message", {}).get("content", [])
                         if isinstance(block, dict) and block.get("type") == "tool_use"]
                expected = {"definition": spec["file"], "caller": spec["caller"],
                            "importer": spec["importer"], "test": spec["test"]}
                hits = {key: value in str(output.get(key, "")) if value else "none" in str(output.get(key, "")).lower()
                        for key, value in expected.items()}
                row = {"repo": spec["repo"], "revision": revision, "lane": lane,
                       "exit_code": process.returncode, "timed_out": timed_out,
                       "seconds": round(time.monotonic() - start, 1), "anchor_hits": hits,
                       "cost_usd": final.get("total_cost_usd"), "usage": final.get("usage"),
                       "model_usage": final.get("modelUsage"), "output": output,
                       "tool_calls": [c["name"] for c in calls],
                       "mcp_used": any(c["name"].startswith("mcp__") for c in calls),
                       "permission_denials": final.get("permission_denials", []),
                       "stderr_tail": stderr[-1000:]}
                # Traces contain only disposable repository content; keep them private.
                trace = args.output / (spec["repo"] + "-" + lane + ".jsonl")
                trace.write_text(stdout.replace(str(root), spec["repo"] + " snapshot"))
                trace.chmod(0o600)
                report["runs"].append(row)
                (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps({k: row[k] for k in ("repo", "lane", "seconds", "anchor_hits", "cost_usd", "timed_out")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--repos", nargs="+", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--lanes", nargs="+", choices=["native", "intel_base", "intel_precision", "serena"], default=["native", "intel_base", "intel_precision"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--intel", type=Path, required=True)
    parser.add_argument("--serena-launcher", type=Path)
    parser.add_argument("--budget-per-run", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--require-navigation-tools", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
