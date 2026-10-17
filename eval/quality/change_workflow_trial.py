"""Replay selected real fixes without executing any code from the input repositories.

Run under the installed intelligence environment, with a bounded outer supervisor.
Labels are source-audited examples, not exhaustive relevance or task-success grades.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path


def command(args, cwd, expected=0):
    start = time.perf_counter()
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=90, check=False)
    seconds = time.perf_counter() - start
    if result.returncode != expected:
        raise RuntimeError(f"{args[0]} {args[1:3]}: exit {result.returncode}: "
                           + result.stderr.decode(errors="replace")[-2000:])
    return result.stdout, seconds


def git(root, *args):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_CONFIG_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
               GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-c", "commit.gpgsign=false", *args], cwd=root, env=env,
        capture_output=True, timeout=90, check=True,
    )
    return result.stdout


def source(repo, revision, path):
    return git(repo, "show", revision + ":" + path)


def prepare(repo, task, root):
    """Actual parent tree plus only the selected production and regression files."""
    root.mkdir()
    archive = git(repo, "archive", "--format=tar", task["parent"])
    total, symlinks = 0, []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = tar.getmembers()
        if len(members) > 3000:
            raise ValueError("Snapshot exceeds 3000 entries")
        for member in members:
            path = root / member.name
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Archive path escapes snapshot")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if member.size > 2 * 1024**2 or total > 48 * 1024**2:
                    raise ValueError("Snapshot exceeds file/total byte bound")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tar.extractfile(member).read())
            elif member.issym() and (path.parent / member.linkname).resolve().is_relative_to(root.resolve()):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(member.linkname)
                symlinks.append({"path": member.name, "target": member.linkname})
            else:
                raise ValueError("Non-regular snapshot member")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Workflow replay")
    git(root, "config", "user.email", "replay@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Pinned parent source")
    hashes = {}
    for path in task["patch_files"]:
        raw = source(repo, task["commit"], path)
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(raw)
        hashes[path] = hashlib.sha256(raw).hexdigest()
    return {"parent_tree_bytes": total, "contained_symlinks": symlinks,
            "selected_after_sha256": hashes}


def call_labels(root, task):
    """Locate preselected calls with Python's AST, independently of the product AST."""
    result = []
    for label in task["known_callers"]:
        tree = ast.parse((root / label["file"]).read_text())
        class Visitor(ast.NodeVisitor):
            def __init__(self, caller, callee):
                self.scope = []
                self.caller = caller
                self.callee = callee
                self.matches = []

            def definition(self, node):
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            visit_FunctionDef = definition  # noqa: N815 - stdlib AST protocol
            visit_AsyncFunctionDef = definition  # noqa: N815
            visit_ClassDef = definition  # noqa: N815

            def visit_Call(self, node):
                name = (node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else None)
                if ".".join(self.scope) == self.caller and name == self.callee:
                    self.matches.append(node.lineno)
                self.generic_visit(node)

        visitor = Visitor(label["caller"], task["symbol"])
        visitor.visit(tree)
        if not visitor.matches:
            raise ValueError(f"Frozen caller has no source call: {label}")
        result.extend({**label, "line": line} for line in visitor.matches)
    return result


def grade(report, task, labels):
    flow = report.get("flow", {})
    edges = flow.get("edges", [])
    hits = []
    for label in labels:
        hits.append({**label, "found": any(
            e["site"]["file_path"] == label["file"] and e["site"]["line"] == label["line"]
            and e["caller"]["qualified_name"] == label["caller"]
            and e["callee"]["qualified_name"] == task["symbol"]
            and e["callee"]["file_path"] == task["file"] for e in edges)})
    return {"known_call_sites": hits, "nodes": len(flow.get("nodes", [])),
            "edges": len(edges), "unresolved": len(flow.get("unresolved", [])),
            "omitted": flow.get("omitted", {}), "coverage": report.get("coverage")}


async def collect_warm(root, task):
    from attocode_intel.gateway import OperationGateway

    gateway = OperationGateway(str(root), profile="full", watch=False)
    rows = []
    try:
        for iteration in range(5):
            start = time.perf_counter()
            response = await gateway.execute("trace_flow", {
                "symbol_name": task["symbol"], "file_path": task["file"],
                "depth": 2, "max_nodes": 32,
            })
            if response.isError:
                raise ValueError(response.content[0].text)
            rows.append({"iteration": iteration, "seconds": time.perf_counter() - start,
                         "report": response.structuredContent["data"]})
    finally:
        await gateway.close()
    return rows


async def collect_stdio(root, task, cli):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=cli,
                                  args=["--project", str(root), "--profile", "full", "--no-watch"])
    start = time.perf_counter()
    async with asyncio.timeout(90), stdio_client(params) as streams:  # noqa: SIM117
        async with ClientSession(*streams) as session:
            await session.initialize()
            assert {"change_context", "trace_flow"} <= {t.name for t in (await session.list_tools()).tools}
            response = await session.call_tool("trace_flow", {
                "symbol_name": task["symbol"], "file_path": task["file"],
                "depth": 2, "max_nodes": 32,
            })
            if response.isError:
                raise ValueError(response.content[0].text)
            return {"seconds_including_startup": time.perf_counter() - start,
                    "report": response.structuredContent["data"]}


def run_task(repo, task, scratch, cli):
    from attocode_intel.change_evidence import check_report

    root = scratch / task["id"]
    preparation = prepare(repo, task, root)
    labels = call_labels(root, task)
    reports = scratch / (task["id"] + "-reports")
    reports.mkdir()
    changed = reports / "changed.json"
    prefix = [cli, "changes", "--project", str(root)]
    _, change_seconds = command([*prefix, "--output", str(changed)], repo)
    report = json.loads(changed.read_text())
    command([*prefix, "--check", str(changed)], repo)
    traced = reports / "trace.json"
    _, trace_seconds = command([cli, "trace", task["symbol"], "--project", str(root),
                                "--file", task["file"], "--depth", "2", "--max-nodes", "32",
                                "--output", str(traced)], repo)
    trace = json.loads(traced.read_text())
    assert check_report(str(root), trace)["status"] == "current"
    warm = asyncio.run(collect_warm(root, task))
    stdio = asyncio.run(collect_stdio(root, task, cli))
    # Full structured MCP output is measured as delivered, including any trimming.
    try:
        stdio["portable_status"] = check_report(str(root), stdio["report"])["status"]
    except ValueError as error:
        stdio["portable_status"] = "invalid: " + str(error)
    controls = []
    for mutation in ("source_edit", "stage", "branch"):
        caller = root / labels[0]["file"]
        original = caller.read_bytes()
        if mutation == "source_edit":
            caller.write_bytes(original + b"\n# saved-report freshness control\n")
        elif mutation == "stage":
            git(root, "add", *task["patch_files"])
        else:
            git(root, "checkout", "-qb", "workflow-replay")
        old, _ = command([*prefix, "--check", str(changed)], repo, expected=1)
        refreshed = reports / (mutation + ".json")
        _, seconds = command([*prefix, "--refresh", str(changed), "--output", str(refreshed)], repo)
        fresh, _ = command([*prefix, "--check", str(refreshed)], repo)
        controls.append({"mutation": mutation, "old": json.loads(old)["status"],
                         "refreshed": json.loads(fresh)["status"], "refresh_seconds": seconds})
        if mutation == "source_edit":
            caller.write_bytes(original)
        elif mutation == "stage":
            git(root, "reset", "-q")
        else:
            git(root, "checkout", "-q", "-")
        command([*prefix, "--check", str(changed)], repo)
    rows = report.get("symbols", [])
    test_paths = [t["file_path"] for t in report.get("tests", {}).get("candidates", [])]
    return {"id": task["id"], "preparation": preparation, "labels": labels,
            "changes": {"seconds_including_startup": change_seconds, "bytes": changed.stat().st_size,
                        "known_changed_symbol_found": any(
                            (s.get("after") or {}).get("qualified_name") == task["symbol"]
                            and s["after"]["file_path"] == task["file"] for s in rows),
                        "known_tests": [{"file": p, "found": p in test_paths,
                                        "rank": test_paths.index(p) + 1 if p in test_paths else None}
                                       for p in task["known_tests"]], "report": report},
            "trace": {"seconds_including_startup": trace_seconds, "bytes": traced.stat().st_size,
                      "grade": grade(trace, task, labels), "report": trace},
            "warm_trace": [{**r, "grade": grade(r["report"], task, labels)} for r in warm],
            "stdio_trace": {**stdio, "grade": grade(stdio["report"], task, labels)},
            "freshness_controls": controls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cli", required=True)
    args = parser.parse_args()
    if args.scratch.exists() or args.output.exists():
        parser.error("Scratch and output must be new paths")
    args.scratch.mkdir(parents=True)
    manifest_raw = args.manifest.read_bytes()
    manifest = json.loads(manifest_raw)
    observation = {"manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(), "tasks": []}
    try:
        for task in manifest["tasks"]:
            print("starting " + task["id"], flush=True)
            row = run_task(args.repo, task, args.scratch, args.cli)
            observation["tasks"].append(row)
            print(json.dumps({"id": row["id"], "trace_grade": row["trace"]["grade"],
                              "known_tests": row["changes"]["known_tests"],
                              "stdio_portable": row["stdio_trace"]["portable_status"]}), flush=True)
    finally:
        shutil.rmtree(args.scratch)
        observation["scratch_cleaned"] = not args.scratch.exists()
        args.output.write_bytes(gzip.compress(json.dumps(observation, sort_keys=True).encode(), mtime=0))


if __name__ == "__main__":
    main()
