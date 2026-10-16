"""CLI exports use full structured data, never a budget-trimmed MCP envelope."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path


async def _collect(project, operation, arguments):
    from attocode_intel.gateway import OperationGateway

    gateway = OperationGateway(project, profile="full", watch=False)
    try:
        response = await gateway.execute(operation, arguments)
        if response.isError:
            raise ValueError(response.content[0].text)
        return response.structuredContent["data"]
    finally:
        await gateway.close()


def read_report(path):
    from attocode_intel.change_evidence import validate_report

    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Report exceeds the 1 MiB limit")
    report = json.loads(raw)
    validate_report(report)
    return report


def _output(path, text):
    # Explicit output is atomic and private. Never silently overwrite source.
    target = Path(path)
    if target.exists():
        raise ValueError("Output already exists; select a new file")
    descriptor, temporary = tempfile.mkstemp(prefix=".attocode-report-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run(command, args):
    parser = argparse.ArgumentParser(prog="attocode-code-intel " + command)
    parser.add_argument("--project", default=".")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="Create a new report file (never overwrite)")
    parser.add_argument("--depth", type=int, default=2)
    if command == "changes":
        parser.add_argument(
            "--mode", choices=["working", "staged", "unstaged", "branch"], default="working"
        )
        parser.add_argument("--base", default="")
        parser.add_argument("--max-files", type=int, default=24)
        parser.add_argument("--max-symbols", type=int, default=32)
        saved = parser.add_mutually_exclusive_group()
        saved.add_argument("--check", metavar="REPORT.json")
        saved.add_argument("--refresh", metavar="REPORT.json")
    else:
        parser.add_argument("symbol_name")
        parser.add_argument("--file", dest="file_path")
        parser.add_argument("--line", type=int)
        parser.add_argument("--max-nodes", type=int, default=32)
    opts = parser.parse_args(args)
    if (
        command == "changes"
        and (opts.check or opts.refresh)
        and any(
            arg.split("=", 1)[0] in {"--mode", "--base", "--depth", "--max-files", "--max-symbols"}
            for arg in args
        )
    ):
        parser.error(
            "Saved reports retain their original request; omit collection options when checking or refreshing"
        )
    from attocode_intel.change_evidence import check_report
    from attocode_intel.change_investigation import markdown_report

    try:
        project = str(Path(opts.project).resolve())
        if command == "changes" and opts.check:
            if opts.format != "json" or opts.output:
                raise ValueError("--check prints JSON status; it does not export a report")
            result = check_report(project, read_report(opts.check))
            print(json.dumps(result, indent=2))
            if result["status"] != "current":
                raise SystemExit(1)
            return
        if command == "changes" and opts.refresh:
            report = read_report(opts.refresh)
            if report["snapshot"]["workspace"] != project:
                raise ValueError("Report belongs to a different workspace")
            request = dict(report["request"])
            operation = request.pop("operation")
            if operation not in {"change_context", "trace_flow"}:
                raise ValueError("Unknown report operation")
        elif command == "changes":
            operation = "change_context"
            request = {
                k: getattr(opts, k) for k in ("mode", "base", "depth", "max_files", "max_symbols")
            }
        else:
            operation = "trace_flow"
            request = {
                k: getattr(opts, k)
                for k in ("symbol_name", "file_path", "line", "depth", "max_nodes")
            }
        report = asyncio.run(_collect(project, operation, request))
        text = (
            markdown_report(report)
            if opts.format == "markdown"
            else json.dumps(report, indent=2) + "\n"
        )
        if len(text.encode()) > 1024 * 1024:
            raise ValueError("Export exceeds 1 MiB; reduce the collection limits")
        if opts.output:
            _output(opts.output, text)
        else:
            print(text, end="")
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
