"""One disposable cold/restart navigation trial; no repository code is executed."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def engine_identity(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        result.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return result.hexdigest()


def canonical(operation, data):
    # Compare user-visible evidence; timing/cache/readiness metadata varies by pass.
    if operation == "search_symbols":
        return data
    keys = {
        "inspect_symbol": ("status", "definition", "source", "references", "reference_candidates", "tests", "ambiguous"),
        "cross_references": ("definitions", "references", "reference_candidates", "total_references", "total_reference_candidates"),
        "dependencies": ("path", "imports", "imported_by", "absence_proven"),
        "suggest_tests": ("candidates", "absence_proven", "evidence"),
        "semantic_search": ("results",),
    }[operation]
    return {key: data[key] for key in keys if key in data}


async def navigate(root, spec):
    from attocode_intel.gateway import OperationGateway

    gateway = OperationGateway(str(root), "daily", watch=False)
    selection = {"symbol_name": spec["symbol"], "file_path": spec["file"], "line": spec["definition_line"]}
    requests = [
        ("definition", "search_symbols", {"name": spec["symbol"]}),
        ("source", "inspect_symbol", selection),
        ("caller_syntax", "cross_references", selection),
        ("dependencies", "dependencies", {"path": spec["file"]}),
        ("tests", "suggest_tests", {"files": [spec["file"]]}),
        ("scoped_search", "semantic_search", {"query": spec["symbol"], "file_filter": spec["file"], "top_k": 5}),
    ]
    requests += [(q["id"], "semantic_search", {"query": q["query"], "top_k": 24}) for q in spec.get("queries", [])]
    evidence, timings = {}, {}
    started = time.monotonic()
    try:
        for label, operation, arguments in requests:
            before = time.monotonic()
            while True:
                response = await gateway.execute(operation, arguments)
                if response.isError:
                    raise AssertionError({"operation": label, "error": str(response.content)[:1500]})
                data = response.structuredContent["data"]
                warming = (operation == "semantic_search" and isinstance(data, dict)
                           and data.get("ranking", {}).get("index", {}).get("status") == "warming")
                if not warming:
                    break
                await asyncio.sleep(.1)  # Included in this trial's fixed deadline/timing.
            if label == "definition":
                assert any(row["file_path"] == spec["file"] and row["start_line"] == spec["definition_line"]
                           and row["name"] == spec["symbol"] for row in data), data
            elif label == "source":
                assert data["status"] == "found", data
                assert data["definition"]["file_path"] == spec["file"], data
                assert data["definition"]["start_line"] == spec["definition_line"], data
                assert spec["anchor"] in data["source"]["text"], data
            elif operation == "semantic_search":
                assert data.get("results"), {"label": label, "data": data}
                if label == "scoped_search":
                    assert all(row["file_path"] == spec["file"] for row in data["results"])
            evidence[label] = canonical(operation, data)
            timings[label] = time.monotonic() - before
    finally:
        closing = time.monotonic()
        await gateway.close()
        timings["close"] = time.monotonic() - closing
    return {"seconds": time.monotonic() - started, "operations_seconds": timings,
            "evidence": evidence, "evidence_sha256": digest(evidence)}


def validate_engine(args):
    engine = Path(args.engine).resolve()
    sys.path.insert(0, str(engine))
    import attocode_intel

    assert Path(attocode_intel.__file__).resolve().is_relative_to(engine)
    return engine


async def phase(args):
    validate_engine(args)
    spec = json.loads(Path(args.manifest).read_text())["spec"]
    result = await navigate(Path(args.workspace), spec)
    result["pid"] = os.getpid()
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")


async def trial(args):
    engine = Path(args.engine).resolve()
    fixture, workspace = Path(args.fixture).resolve(), Path(args.workspace).resolve()
    assert workspace.parent.name == "work" and not workspace.exists()
    spec = json.loads(Path(args.manifest).read_text())["spec"]
    source = fixture / spec["file"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == spec["source_sha256"]
    assert source.read_text().splitlines()[spec["definition_line"] - 1].startswith(spec["anchor"])
    setup = time.monotonic()
    shutil.copytree(fixture, workspace, symlinks=True)
    setup_seconds = time.monotonic() - setup
    record = {"engine_sha256": engine_identity(engine), "fixture_manifest_sha256": hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
              "setup_seconds": setup_seconds, "pid": os.getpid(), "restart_scope": "separate fresh Python phase process, same persisted index/workspace"}
    try:
        # The supervising trial process owns one deadline across two fresh phase
        # processes. Their elapsed times include Python imports/grammar startup.
        async with asyncio.timeout(args.seconds):
            for label in ("cold", "restart"):
                output = Path(args.output).with_name(Path(args.output).stem + "-" + label + ".json")
                command = [sys.executable, str(Path(__file__).resolve()), "--engine", args.engine,
                           "--fixture", args.fixture, "--workspace", args.workspace,
                           "--manifest", args.manifest, "--output", str(output), "--phase", label]
                started = time.monotonic()
                process = await asyncio.create_subprocess_exec(*command)
                try:
                    code = await process.wait()
                finally:
                    if process.returncode is None:
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), .5)
                        except TimeoutError:
                            process.kill()
                            await process.wait()
                if code:
                    raise RuntimeError(f"{label} phase exited {code}")
                row = json.loads(output.read_text())
                row["navigation_seconds"], row["seconds"] = row["seconds"], time.monotonic() - started
                assert row["pid"] != os.getpid()
                record[label] = row
        assert record["cold"]["pid"] != record["restart"]["pid"]
        assert record["cold"]["evidence_sha256"] == record["restart"]["evidence_sha256"]
        record["status"] = "passed"
    finally:
        shutil.rmtree(workspace)
        record["workspace_removed"] = not workspace.exists()
        Path(args.output).write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Runtime validation runs only on GitHub Actions.')
    parser = argparse.ArgumentParser()
    for name in ("engine", "fixture", "workspace", "manifest", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--phase", choices=["cold", "restart"])
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    asyncio.run(phase(args) if args.phase else trial(args))


if __name__ == "__main__":
    main()
