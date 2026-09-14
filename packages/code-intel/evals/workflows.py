"""Thirty-two reproducible daily-workflow checks on isolated real-repo snapshots.

Requires local clones; never modifies originals or makes model/network calls.
Reports observed evidence rather than claiming complete reference recall.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens
from attocode_intel.gateway import OperationGateway

SCENARIOS = [
    {"repo": "fastapi", "symbol": "serialize_response", "file": "fastapi/routing.py",
     "caller": "fastapi/routing.py", "importer": "fastapi/utils.py",
     "test": "tests/test_custom_route_class.py"},
    {"repo": "express", "symbol": "json", "file": "lib/response.js",
     "caller": "test/res.json.js", "importer": "lib/express.js", "test": "test/res.json.js"},
    {"repo": "frontend", "symbol": "cn", "file": "src/lib/cn.ts",
     "caller": "src/components/layout/Sidebar.tsx", "importer": "src/components/layout/Sidebar.tsx", "test": None},
    {"repo": "ripgrep", "symbol": "WalkBuilder", "file": "crates/ignore/src/walk.rs",
     "caller": "crates/core/flags/hiargs.rs", "importer": "crates/ignore/src/lib.rs", "test": "crates/ignore/src/walk.rs"},
]


def engine_fingerprint(project):
    digest = hashlib.sha256()
    root = project / "packages/code-intel/src"
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def snapshot(source, destination, frontend=False, revision="HEAD"):
    archive = destination / "source.tar"
    command = ["git", "-C", str(source), "archive", revision] + (["frontend"] if frontend else [])
    with archive.open("wb") as output:
        subprocess.run(command, stdout=output, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")
    archive.unlink()
    return (destination / "frontend" if frontend else destination).resolve()


async def evaluate(root, spec):
    gateway = OperationGateway(str(root), "daily", watch=False)
    rows = []

    async def check(task, tool, arguments, predicate):
        start = time.perf_counter()
        try:
            result = await gateway.execute(tool, arguments)
            data = result.structuredContent
            passed = not result.isError and bool(predicate(data))
            row = {"task": task, "tool": tool, "arguments": arguments, "passed": passed,
                   "readable_tokens": count_tokens(result.content[0].text),
                   "structured_tokens": count_tokens(json.dumps(data)), "response": data}
        except Exception as exc:
            row = {"task": task, "tool": tool, "arguments": arguments, "passed": False, "error": str(exc)}
        row["ms"] = round((time.perf_counter() - start) * 1000, 1)
        rows.append(row)
        return row

    try:
        await check("definition", "search_symbols", {"name": spec["symbol"], "max_tokens": 1500},
                    lambda d: any(r["file_path"] == spec["file"] for r in d["data"]))
        await check("caller", "cross_references", {"symbol_name": spec["symbol"], "max_tokens": 2000},
                    lambda d: any(r["file_path"] == spec["caller"] for r in d["data"]["references"]))
        await check("dependencies", "dependencies", {"path": spec["file"], "max_tokens": 2000},
                    lambda d: spec["importer"] in d["data"]["imported_by"])
        await check("impact", "impact_analysis", {"changed_files": [spec["file"]], "max_tokens": 2000},
                    lambda d: spec["importer"] in d["data"]["impacted_files"] and not d["data"]["absence_proven"])
        await check("test_selection", "suggest_tests", {"files": [spec["file"]], "max_tokens": 4000},
                    lambda d: spec["test"] in d["result"] if spec["test"] else "No specific test files" in d["result"])
        await check("context", "relevant_context", {"files": [spec["file"]], "max_tokens": 2000},
                    lambda d: spec["symbol"] in d["result"] and count_tokens(d["result"]) <= 2000)
        source = root / spec["file"]
        original = source.read_bytes()
        await gateway.execute("record_learning", {"type": "gotcha", "description": "evidence_anchor_7329 " + spec["symbol"], "scope": spec["file"]})
        await gateway.close()
        gateway = OperationGateway(str(root), "daily", watch=False)
        await check("knowledge_handoff", "recall", {"query": "evidence_anchor_7329"},
                    lambda d: bool(d["data"]) and not d["data"][0]["stale"])
        probe = {"fastapi": "\ndef attocode_fresh_probe():\n    return True\n",
                 "express": "\nexports.attocode_fresh_probe = () => true;\n",
                 "frontend": "\nexport function attocode_fresh_probe() { return true; }\n",
                 "ripgrep": "\npub fn attocode_fresh_probe() -> bool { true }\n"}[spec["repo"]]
        try:
            source.write_bytes(original + probe.encode())
            await check("edit_freshness", "search_symbols", {"name": "attocode_fresh_probe"},
                        lambda d: any(r["file_path"] == spec["file"] for r in d["data"]))
            stale = (await gateway.execute("recall", {"query": "evidence_anchor_7329"})).structuredContent
            rows[-1]["stale_anchor"] = bool(stale["data"] and stale["data"][0]["stale"])
            rows[-1]["passed"] &= rows[-1]["stale_anchor"]
        finally:
            source.write_bytes(original)
    finally:
        await gateway.close()
    return rows


async def main(args):
    os.environ["ATTOCODE_INTEL_PRECISION"] = args.precision
    report = {"precision": args.precision, "comparative_agent_benchmark": False,
              "engine_sha256": engine_fingerprint(args.project),
              "evaluation": "Known evidence anchors; not exhaustive precision or recall", "repos": []}
    revisions = json.loads(args.revisions.read_text()) if args.revisions else {}
    with tempfile.TemporaryDirectory(prefix="intel-workflows-") as temp:
        for spec in SCENARIOS:
            source = args.project if spec["repo"] == "frontend" else args.repos / spec["repo"]
            destination = Path(temp) / spec["repo"]
            destination.mkdir()
            revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "--verify", "--end-of-options",
                                               revisions.get(spec["repo"], "HEAD") + "^{commit}"], text=True).strip()
            root = snapshot(source, destination, spec["repo"] == "frontend", revision)
            tasks = await evaluate(root, spec)
            # Keep portable provenance rather than dead temporary paths.
            tasks = json.loads(json.dumps(tasks).replace(str(root), spec["repo"] + " snapshot"))
            report["repos"].append({"repo": spec["repo"], "revision": revision, "tasks": tasks})
            print(json.dumps({"repo": spec["repo"], "passed": sum(r["passed"] for r in tasks), "total": len(tasks)}), flush=True)
    report["passed"] = sum(row["passed"] for repo in report["repos"] for row in repo["tasks"])
    report["total"] = sum(len(repo["tasks"]) for repo in report["repos"])
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] == 32 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--precision", choices=["off", "auto"], default="off")
    parser.add_argument("--revisions", type=Path, help="JSON mapping repository names to Git revisions")
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
