"""Pinned source-only workflow packs and the existing ranking gate.

Existing historical trees/clones are read-only inputs. New indexes and copies
are disposable. No repository tests, install scripts, or models are executed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.matrix import run as matrix
from eval.quality.runner import REPO, write_json

PACK = Path(__file__).with_name("workflows.yaml")
HISTORY = Path.home() / "Documents/AI/attocode-evals/matrix"
CLONES = Path.home() / "Documents/ai/benchmark-repos"


def materialize(spec, destination, cache):
    name, commit = spec["repo"], spec["commit"]
    historical = matrix._tree_file(HISTORY, name, commit)
    if historical.exists():
        tree = json.loads(historical.read_text())
        blob_root = HISTORY
    else:
        source = REPO if spec["id"] == "frontend" else CLONES / spec["id"]
        if (source / ".git").exists():
            tree = matrix._read_tree(source, commit, cache, remote=False)
        else:
            if os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1":
                raise ValueError(f"Missing pinned source {name}@{commit}; enable downloads on the remote worker")
            with tempfile.TemporaryDirectory(prefix="quality-fetch-") as tmp:
                clone = matrix._remote(name, Path(tmp))
                matrix._git(clone, "fetch", "-q", "--depth", "1", "--filter=blob:limit=1000001", "--no-tags", "origin", commit)
                tree = matrix._read_tree(clone, commit, cache, remote=True)
        blob_root = cache
    if tree.get("error"):
        raise ValueError(tree["error"])
    if prefix := spec.get("subdir"):
        tree = {**tree, "entries": [[p[len(prefix) + 1:], mode, oid, size]
                                    for p, mode, oid, size in tree["entries"] if p.startswith(prefix + "/")]}
    matrix._materialize(blob_root, tree, destination)
    return tree.get("tree")


async def evaluate(root, spec):
    source = root / spec["file"]
    content = source.read_text()
    assert spec["anchor"] in content, "Pinned source anchor missing: invalid fixture"
    line = content[:content.index(spec["anchor"])].count("\n") + 1
    selection = {"symbol_name": spec["symbol"], "file_path": spec["file"], "line": line}
    gateway = OperationGateway(str(root), "daily", watch=False)
    rows = []
    async def check(name, tool, arguments, predicate, *, paginate=False):
        start = time.monotonic()
        response = await gateway.execute_mcp(tool, {"max_tokens": 4000, **arguments})
        decoded = json.loads(response.content[0].text)
        data = decoded.get("data", {})
        pages = [decoded]
        within_budget = response_tokens(response) <= 4000
        while paginate and not predicate(data) and data.get("next_cursor") and len(pages) < 10:
            response = await gateway.execute_mcp(tool, {"max_tokens": 4000, **arguments, "cursor": data["next_cursor"]})
            decoded = json.loads(response.content[0].text)
            data = decoded.get("data", {})
            pages.append(decoded)
            within_budget = within_budget and response_tokens(response) <= 4000
            if response.isError:
                break
        passed = not response.isError and within_budget and bool(predicate(data))
        rows.append({"name": name, "passed": passed, "seconds": time.monotonic() - start,
                     "response": decoded, "tool": tool, "pages_requested": len(pages)})
        return data
    try:
        await check("definition", "search_symbols", {"name": spec["symbol"]},
                    lambda d: any(r["file_path"] == spec["file"] for r in d))
        await check("source", "inspect_symbol", selection,
                    lambda d: d.get("status") == "found" and d["definition"]["file_path"] == spec["file"]
                    and bool(d.get("source", {}).get("text")))
        await check("scoped_search", "semantic_search", {"query": spec.get("query", spec["symbol"]), "file_filter": spec["file"], "top_k": 5},
                    lambda d: bool(d.get("results")) and all(r["file_path"] == spec["file"] for r in d["results"]))
        await check("caller_syntax", "cross_references", {"symbol_name": spec["symbol"]},
                    lambda d: any(r["file_path"] == spec["caller"] for r in d.get("references", [])), paginate=True)
        await check("dependencies", "dependencies", {"path": spec["file"]},
                    lambda d: spec["importer"] in d.get("imported_by", []) if spec["importer"] else not d.get("absence_proven", False))
        await check("impact", "impact_analysis", {"changed_files": [spec["file"]]},
                    lambda d: not d.get("absence_proven", False) and
                    (not spec["importer"] or spec["importer"] in d.get("impacted_files", []) or
                     any(spec["importer"] in layer["files"] for layer in d.get("layers", []))))
        await check("tests", "suggest_tests", {"files": [spec["file"]]},
                    lambda d: not d.get("absence_proven", False) and
                    (not spec["test"] or any(r["file_path"] == spec["test"] for r in d.get("candidates", []))))
        await gateway.close()
        gateway = OperationGateway(str(root), "daily", watch=False)
        await check("restart", "inspect_symbol", selection,
                    lambda d: d.get("status") == "found" and d["definition"]["file_path"] == spec["file"])
    finally:
        await gateway.close()
    return rows


def frozen_ranking(destination):
    """Give the existing clean-tree gate a disposable commit of the local input.

    The user's checkout and history stay untouched. The report binds this
    temporary commit to the actual source hash, not to a claimed upstream SHA.
    """
    for relative in ("eval/matrix", "eval/meta_harness", "packages/code-intel/src"):
        shutil.copytree(REPO / relative, destination / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    destination.mkdir(exist_ok=True)
    for name in ("metrics.py", "harness.py"):
        shutil.copyfile(REPO / "eval" / name, destination / "eval" / name)
    release_gate = Path("packages/code-intel/evals/release_gate.py")
    (destination / release_gate).parent.mkdir(parents=True)
    shutil.copyfile(REPO / release_gate, destination / release_gate)
    for command in (["init", "-q"], ["add", "."], ["commit", "-qm", "Frozen local quality input"]):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
                        "-c", "user.name=Quality runner", "-c", "user.email=quality@localhost", "-C", str(destination), *command], check=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(destination / "packages/code-intel/src") + os.pathsep + str(destination)
    cache = destination / ".cache"
    if os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1":
        # Existing gate snapshots can be read without duplicating the 14 GB
        # historical blob pool. Only the required blobs are copied.
        from eval.matrix.ci import instances
        for inst in instances():
            tree_path = matrix._tree_file(HISTORY, inst.repo, inst.base_commit)
            if not tree_path.exists():
                raise ValueError("Ranking snapshot unavailable locally; run broad on the remote worker")
            tree = json.loads(tree_path.read_text())
            target = matrix._tree_file(cache, inst.repo, inst.base_commit)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tree_path, target)
            for entry in tree.get("entries", []):
                if matrix._stored(entry):
                    blob = matrix._blob_file(cache, entry[2])
                    if not blob.exists():
                        blob.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(matrix._blob_file(HISTORY, entry[2]), blob)
    code = subprocess.call([sys.executable, "-m", "eval.matrix.run", "ci", "--cache", str(cache)], cwd=destination, env=env)
    return {"passed": code == 0, "exit_code": code, "frozen_local_snapshot": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ranking", action="store_true")
    args = parser.parse_args()
    report = {"pack_sha256": hashlib.sha256(PACK.read_bytes()).hexdigest(), "repositories": [],
              "model_runs": 0, "scope": "Development evidence anchors, not exhaustive recall or agent benefit"}
    report["git_version"] = subprocess.check_output(["git", "--version"], text=True).strip()
    try:
        with tempfile.TemporaryDirectory(prefix="quality-corpus-") as tmp:
            if args.ranking:
                report.update(frozen_ranking(Path(tmp) / "ranking"))
            else:
                for spec in yaml.safe_load(PACK.read_text())["repositories"]:
                    row = {"id": spec["id"], "revision": spec["commit"], "language": spec["language"]}
                    with tempfile.TemporaryDirectory(prefix=spec["id"] + "-", dir=tmp) as workspace:
                        try:
                            started = time.monotonic()
                            row["tree"] = materialize(spec, Path(workspace), Path(tmp) / "blobs")
                            row["setup_seconds"] = time.monotonic() - started
                            row["checks"] = asyncio.run(evaluate(Path(workspace), spec))
                            row["passed"] = all(c["passed"] for c in row["checks"])
                            row["limited_checks"] = [name for name, key in (("dependencies", "importer"), ("impact", "importer"), ("tests", "test")) if not spec[key]]
                        except Exception as exc:
                            row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
                            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                                detail = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
                                row["stderr_tail"] = detail[-2000:]
                    report["repositories"].append(row)
                    write_json(args.output, report)
                    print(json.dumps({"repository": spec["id"], "passed": row["passed"]}), flush=True)
                report["passed"] = all(r["passed"] for r in report["repositories"])
    finally:
        write_json(args.output, report)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
