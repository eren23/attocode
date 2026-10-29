"""Bounded large-source and lifecycle workloads against the installed product."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from eval.quality.scale_evidence import admit_coverage, case_outcome, require, write


def generate_tree(root, files):
    root = Path(root)
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname="scale-fixture"\nversion="0.1.0"\n')
    digest = hashlib.sha256()
    for i in range(files):
        name = f"module_{i}.py"
        content = f"from module_{i - 1} import operation_{i - 1}\n" if i else ""
        content += f"def operation_{i}(value: int) -> int:\n"
        content += f"    return operation_{i - 1}(value) + {i}\n" if i else "    return value\n"
        raw = content.encode()
        (root / name).write_bytes(raw)
        digest.update(name.encode() + b"\0" + hashlib.sha256(raw).digest())
    return {
        "source_files": files,
        "source_sha256": digest.hexdigest(),
        "generator": "python-import-call-chain-v1",
        "first": 0,
        "last": files - 1,
    }


class Requests:
    def __init__(self, gateway, output):
        self.gateway, self.output = gateway, Path(output)
        self.sequence = self.inflight = self.max_inflight = 0
        self.metrics = []

    async def call(self, tool, args, *, compact=True):
        from attocode_intel.output import response_tokens

        sequence = self.sequence
        self.sequence += 1
        started = time.monotonic()
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        row = {
            "sequence": sequence,
            "tool": tool,
            "arguments": args,
            "offered_monotonic": started,
            "pid": os.getpid(),
        }
        try:
            response = await (
                self.gateway.execute_mcp(tool, args)
                if compact
                else self.gateway.execute(tool, args)
            )
            row["response"] = response.model_dump(mode="json")
            row["seconds"] = time.monotonic() - started
            import psutil

            process = psutil.Process()
            cpu = process.cpu_times()
            row["usage"] = {
                "rss_bytes": process.memory_info().rss,
                "cpu_seconds": cpu.user + cpu.system,
            }
            write(self.output / f"raw-{sequence:06d}.json", row)
            require(not response.isError, f"{tool} returned an error")
            if compact:
                require(
                    response_tokens(response) <= args.get("max_tokens", 2000),
                    "wire budget exceeded",
                )
                page = json.loads(response.content[0].text)
            else:
                page = response.structuredContent
            self.metrics.append(
                {
                    "sequence": sequence,
                    "tool": tool,
                    "seconds": row["seconds"],
                    "error": False,
                    **row["usage"],
                }
            )
            return page
        except BaseException as error:
            row.update(
                seconds=time.monotonic() - started,
                error={"type": type(error).__name__, "message": str(error)[:2000]},
            )
            write(self.output / f"raw-{sequence:06d}.json", row)
            self.metrics.append(
                {"sequence": sequence, "tool": tool, "seconds": row["seconds"], "error": True}
            )
            raise
        finally:
            self.inflight -= 1


async def ready(requests, minimum, deadline):
    while True:
        page = await requests.call("hydration_status", {}, compact=False)
        coverage = page["metadata"]["coverage"]
        if coverage.get("phase") == "ready":
            admit_coverage(coverage, minimum)
            return coverage
        require(time.monotonic() < deadline, "full readiness deadline exceeded")
        await asyncio.sleep(1)


async def run_phase(spec, phase, output):
    import attocode_intel
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus_capture import validate_sources
    from eval.quality.experiment_evidence import assert_engine

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(spec["root"])
    result = {
        "id": spec["id"],
        "phase": phase,
        "pid": os.getpid(),
        "complete": False,
        "started_unix": time.time(),
        "checks": {},
        "source_files": spec["source_files"],
    }
    started = time.monotonic()
    deadline = started + spec["seconds"]
    gateway = OperationGateway(str(root), "daily", watch=False)
    requests = Requests(gateway, output)
    selected = Path(attocode_intel.__file__).parent
    try:
        result["origin_start"] = assert_engine(selected)
        await requests.call("bootstrap", {"task_hint": spec["symbol"], "max_tokens": 2000})
        result["bootstrap_seconds"] = time.monotonic() - started
        result["coverage"] = await ready(requests, spec["source_files"], deadline)
        result["hydration_seconds"] = time.monotonic() - started
        page = await requests.call(
            "inspect_symbol",
            {
                "symbol_name": spec["symbol"],
                "file_path": spec["file"],
                "line": spec["line"],
                "max_tokens": 2000,
            },
        )
        data = page["data"]
        require(
            data.get("status") == "found" and data["definition"]["file_path"] == spec["file"],
            "selected definition missing",
        )
        require(
            data["definition"]["name"].split(".")[-1] == spec["symbol"], "wrong selected symbol"
        )
        require(
            bool(validate_sources("inspect_symbol", page, root, [])),
            "selected source excerpt missing",
        )
        result["checks"]["definition"] = True
        if spec.get("dependency"):
            page = await requests.call("dependencies", {"path": spec["file"], "max_tokens": 2000})
            data = page["data"]
            require(spec["dependency"] in json.dumps(data), "known import edge missing")
            result["checks"]["dependency"] = True
        while True:
            page = await requests.call(
                "semantic_search",
                {
                    "query": spec["symbol"],
                    "file_filter": spec["file"],
                    "top_k": 3,
                    "max_tokens": 2000,
                },
            )
            index = page.get("data", {}).get("ranking", {}).get("index", {})
            if index.get("status") != "warming":
                require(
                    bool(page.get("data", {}).get("results")), "ready search omitted known source"
                )
                require(
                    all(r["file_path"] == spec["file"] for r in page["data"]["results"]),
                    "scoped search escaped file",
                )
                break
            require(time.monotonic() < deadline, "search readiness deadline exceeded")
            await asyncio.sleep(1)
        result["checks"]["search"] = True
        result["search_ready_seconds"] = time.monotonic() - started
        result["complete"] = True
        if phase == "crash":
            result["closed"] = False
            write(output / "result.json", result)
            while True:
                await asyncio.sleep(1)
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)[:4000]}
        raise
    finally:
        try:
            await gateway.close()
            result["closed"] = True
        except BaseException:
            result.update(closed=False, complete=False)
            raise
        finally:
            result.update(
                seconds=time.monotonic() - started,
                requests=requests.metrics,
                origin_end=assert_engine(selected),
            )
            write(output / "result.json", result)
    return result


def sqlite_integrity(root):
    databases = sorted(
        set(Path(root).rglob("*.db"))
        | set(Path(root).rglob("*.sqlite"))
        | set(Path(root).rglob("*.sqlite3"))
    )
    results = []
    for path in databases:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("PRAGMA integrity_check").fetchall()
        require(rows == [("ok",)], "SQLite integrity failed: " + str(path))
        results.append(str(path))
    require(bool(results), "no persisted SQLite database was checked")
    return results


async def lifecycle(root, output, *, soak_seconds):
    from attocode_intel.gateway import OperationGateway

    root, output = Path(root), Path(output)
    gateway = OperationGateway(str(root), "daily", watch=False)
    requests = Requests(gateway, output)
    result = {
        "complete": False,
        "concurrency_offered": [1, 4, 8],
        "mutations": {},
        "dispatch_model": "concurrent clients sharing the product serial workspace worker",
    }
    try:
        await requests.call("bootstrap", {"max_tokens": 2000})
        await ready(requests, len(list(root.glob("module_*.py"))), time.monotonic() + 180)

        async def look():
            page = await requests.call(
                "search_symbols", {"name": "operation_0", "max_tokens": 1000}
            )
            require(
                any(
                    d["name"] == "operation_0" and d["file_path"] == "module_0.py"
                    for d in page["data"]
                ),
                "concurrent lookup missing",
            )

        for clients in (1, 4, 8):
            await asyncio.gather(*(look() for _ in range(clients)))

        async def notify(names):
            await requests.call("notify_file_changed", {"files": names, "max_tokens": 1000})

        async def find(name):
            rows = (await requests.call("search_symbols", {"name": name, "max_tokens": 1000}))[
                "data"
            ]
            return [row for row in rows if row["name"] == name]

        # Edit, add, rename, delete and ignore-policy refresh all use the public path.
        path = root / "module_1.py"
        path.write_text("def scale_revised(value):\n    return value + 1\n")
        await asyncio.gather(notify(["module_1.py"]), look(), look())
        result["mutations"]["edit"] = any(
            d["name"] == "scale_revised" for d in await find("scale_revised")
        )
        path = root / "scale_added.py"
        path.write_text("def scale_added():\n    return 42\n")
        await notify(["scale_added.py"])
        result["mutations"]["add"] = any(
            d["file_path"] == "scale_added.py" for d in await find("scale_added")
        )
        path.rename(root / "scale_renamed.py")
        await notify(["scale_added.py", "scale_renamed.py"])
        matches = await find("scale_added")
        result["mutations"]["rename"] = bool(matches) and all(
            d["file_path"] == "scale_renamed.py" for d in matches
        )
        (root / "scale_renamed.py").unlink()
        await notify(["scale_renamed.py"])
        result["mutations"]["delete"] = not await find("scale_added")
        (root / "scale_ignored.py").write_text("def scale_ignored():\n    return 9\n")
        await notify(["scale_ignored.py"])
        require(bool(await find("scale_ignored")), "pre-ignore source absent")
        (root / ".gitignore").write_text("scale_ignored.py\n")
        await notify([".gitignore"])
        result["mutations"]["ignore"] = not await find("scale_ignored")
        require(all(result["mutations"].values()), "mutation failed")
        # Compare the changed workspace's definition identities with a fresh copy.
        fresh = root.parent / (root.name + "-fresh")
        shutil.copytree(
            root, fresh, ignore=shutil.ignore_patterns(".attocode", ".git", "__pycache__")
        )
        peer = OperationGateway(str(fresh), "daily", watch=False)
        try:
            other = Requests(peer, output / "fresh")
            original = await find("scale_revised")
            page = await other.call("search_symbols", {"name": "scale_revised", "max_tokens": 1000})

            def identity(rows):
                return sorted(
                    (r["name"], r["file_path"], r["start_line"], r["end_line"]) for r in rows
                )

            require(
                identity(original) == identity(page["data"]) and original,
                "incremental differs from fresh index",
            )
            result["mutations"]["fresh_equivalence"] = True
        finally:
            await peer.close()
        soak_started = time.monotonic()
        # Fixed 8-client burst per ten seconds; record all requests and queue time.
        while time.monotonic() - soak_started < soak_seconds:
            burst = time.monotonic()
            await asyncio.gather(*(look() for _ in range(8)))
            await asyncio.sleep(
                max(
                    0,
                    min(
                        10 - (time.monotonic() - burst),
                        soak_seconds - (time.monotonic() - soak_started),
                    ),
                )
            )
        result["soak_seconds"] = time.monotonic() - soak_started
        result["complete"] = True
    finally:
        try:
            await gateway.close()
            result["sqlite_databases"] = sqlite_integrity(root)
            result["sqlite_integrity"] = True
        except BaseException as error:
            result.update(complete=False, cleanup_error=str(error))
            raise
        finally:
            result.update(max_inflight=requests.max_inflight, requests=requests.metrics)
            write(output / "result.json", result)
    return result


def eligible_sources(root):
    from attocode_intel._internal.integrations.context.codebase_context import EXTENSION_LANGUAGES
    from attocode_intel._internal.integrations.utilities.ignore import IgnoreManager

    ignore = IgnoreManager(root)
    return [
        p
        for p in Path(root).rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and not any(s.startswith(".") for s in p.relative_to(root).parts)
        and p.suffix in EXTENSION_LANGUAGES
        and p.stat().st_size <= 1_000_000
        and not ignore.is_ignored(p.relative_to(root).as_posix())
    ]


def supervise_case(command, root, output, seconds):
    from eval.quality.runner import supervise

    output.mkdir(parents=True, exist_ok=True)
    return supervise(
        command,
        cwd=Path.cwd(),
        env=os.environ.copy(),
        root=root,
        log=output / "process.log",
        deadline=time.monotonic() + seconds,
        wall_deadline=time.time() + seconds,
        max_bytes=20 * 2**30,
        max_rss=12 * 2**30,
        evidence_root=root / "evidence",
        max_evidence_bytes=256 * 2**20,
    )


def run_batch(batch, root):
    import importlib.metadata

    import attocode_intel

    from eval.quality.scale_evidence import WHEEL_SHA, attest_wheel

    root = Path(root)
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report = {
        "batch": batch,
        "complete": False,
        "cases": [],
        "started_unix": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "model_calls": 0,
    }
    report["installed"] = attest_wheel(
        Path("/root/published.whl"), Path(attocode_intel.__file__).parent, WHEEL_SHA
    )
    write(
        evidence / "environment.json",
        {
            "cpu": Path("/proc/cpuinfo").read_text(),
            "memory": Path("/proc/meminfo").read_text(),
            "limits": Path("/proc/self/cgroup").read_text(),
            "packages": sorted(
                (d.metadata["Name"], d.version)
                for d in importlib.metadata.distributions()
                if d.metadata["Name"]
            ),
        },
    )
    deadline = time.monotonic() + 3500
    specs = []
    if batch == "capacity":
        for size, seconds in [(10000, 600), (50000, 1000), (100000, 1600)]:
            specs.append(
                {"id": f"synthetic-{size}", "kind": "synthetic", "size": size, "seconds": seconds}
            )
    elif batch == "real":
        import yaml

        packs = yaml.safe_load(Path("eval/quality/workflows.yaml").read_text())["repositories"]
        for name in ["cockroach", "pandas", "deno"]:
            source = next(p for p in packs if p["id"] == name)
            # A new larger scope, not a relabeling of the old narrow compatibility pack.
            source = {k: v for k, v in source.items() if k not in {"include", "subdir", "queries"}}
            specs.append({"id": name, "kind": "real", "source": source, "seconds": 1100})
    else:
        specs = [{"id": "lifecycle", "kind": "lifecycle", "size": 2000, "seconds": 3300}]
    try:
        for spec in specs:
            case = evidence / spec["id"]
            case.mkdir()
            seconds = min(spec["seconds"], int(deadline - time.monotonic()))
            require(seconds > 30, "batch deadline left case unissued")
            spec["seconds"] = seconds
            spec_path = case / "spec.json"
            write(spec_path, spec)
            row = supervise_case(
                [
                    sys.executable,
                    "-m",
                    "eval.quality.scale_workload",
                    "--case",
                    str(spec_path),
                    "--root",
                    str(root),
                ],
                root,
                case,
                seconds,
            )
            result_path = case / "case-result.json"
            result = (
                json.loads(result_path.read_text()) if result_path.exists() else {"complete": False}
            )
            report["cases"].append({"id": spec["id"], "supervision": row, "result": result})
            write(evidence / "batch-result.json", report)
            if case_outcome([row]) != "passed" or not result.get("complete"):
                break
        report["complete"] = len(report["cases"]) == len(specs) and all(
            r["result"].get("complete") and case_outcome([r["supervision"]]) == "passed"
            for r in report["cases"]
        )
        report["unissued_cases"] = [s["id"] for s in specs[len(report["cases"]) :]]
    finally:
        report["finished_unix"] = time.time()
        write(evidence / "batch-result.json", report)
    return report


def run_case(spec, root):
    root = Path(root)
    output = root / "evidence" / spec["id"]
    tree = root / "work" / spec["id"]
    start = time.monotonic()
    result = {"id": spec["id"], "complete": False, "phases": []}
    try:
        if spec["kind"] in {"synthetic", "lifecycle"}:
            source = generate_tree(tree, spec["size"])
            write(output / "source.json", source)
            last = spec["size"] - 1
            selected = {
                "id": spec["id"],
                "root": str(tree),
                "source_files": spec["size"],
                "file": f"module_{last}.py",
                "symbol": f"operation_{last}",
                "line": 2,
                "dependency": f"module_{last - 1}.py",
            }
        else:
            from eval.quality.corpus import materialize

            source = {}
            tree.mkdir(parents=True)
            materialize(spec["source"], tree, root / "cache" / spec["id"], receipt=source)
            write(output / "source.json", source)
            content = (tree / spec["source"]["file"]).read_text()
            selected = {
                "id": spec["id"],
                "root": str(tree),
                "source_files": len(eligible_sources(tree)),
                "file": spec["source"]["file"],
                "symbol": spec["source"]["symbol"],
                "line": content[: content.index(spec["source"]["anchor"])].count("\n") + 1,
            }
        if spec["kind"] == "lifecycle":
            from eval.quality.scale_native import run as native_run

            native_run(root, output / "native")
            # Keep 60 seconds for forced restart and collection in this case.
            soak = max(0, min(1800, int(spec["seconds"] - (time.monotonic() - start) - 120)))
            asyncio.run(lifecycle(tree, output / "load", soak_seconds=soak))
            result["lifecycle"] = True
        for phase in ("cold", "restart"):
            folder = output / phase
            seconds = max(1, int(spec["seconds"] - (time.monotonic() - start) - 5))
            selected["seconds"] = seconds
            selected_path = output / "selected.json"
            write(selected_path, selected)
            row = supervise_case(
                [
                    sys.executable,
                    "-m",
                    "eval.quality.scale_workload",
                    "--phase",
                    phase,
                    "--case",
                    str(selected_path),
                    "--root",
                    str(root),
                ],
                root,
                folder,
                seconds,
            )
            result["phases"].append({"phase": phase, "supervision": row})
            require(case_outcome([row]) == "passed", "phase process failed")
            raw = json.loads((folder / "result.json").read_text())
            require(raw["complete"] and raw["closed"], "phase did not complete")
            result["phases"][-1]["pid"] = raw["pid"]
        require(
            result["phases"][0]["pid"] != result["phases"][1]["pid"], "restart reused a process"
        )
        if spec["kind"] == "lifecycle":
            # Crash after reopening a real persisted index, then recover in another PID.
            crash = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "eval.quality.scale_workload",
                    "--phase",
                    "crash",
                    "--case",
                    str(selected_path),
                    "--root",
                    str(root),
                ],
                start_new_session=True,
            )
            try:
                until = time.monotonic() + 30
                marker = output / "crash" / "result.json"
                while not marker.exists() and crash.poll() is None and time.monotonic() < until:
                    time.sleep(0.1)
                require(
                    marker.exists() and json.loads(marker.read_text())["complete"],
                    "crash checkpoint not reached",
                )
                os.killpg(crash.pid, signal.SIGKILL)
                crash.wait(timeout=10)
                require(crash.returncode == -signal.SIGKILL, "forced stop not observed")
                seconds = max(1, int(spec["seconds"] - (time.monotonic() - start) - 5))
                row = supervise_case(
                    [
                        sys.executable,
                        "-m",
                        "eval.quality.scale_workload",
                        "--phase",
                        "recovery",
                        "--case",
                        str(selected_path),
                        "--root",
                        str(root),
                    ],
                    root,
                    output / "recovery",
                    seconds,
                )
                require(case_outcome([row]) == "passed", "forced restart recovery failed")
                result["forced_restart"] = {
                    "killed_pid": crash.pid,
                    "exit_code": crash.returncode,
                    "supervision": row,
                    "sqlite": sqlite_integrity(tree),
                }
            finally:
                if crash.poll() is None:
                    os.killpg(crash.pid, signal.SIGKILL)
                    crash.wait(timeout=10)
        result["complete"] = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)[:4000]}
        raise
    finally:
        result["seconds"] = time.monotonic() - start
        write(output / "case-result.json", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=["capacity", "real", "lifecycle"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--phase", choices=["cold", "restart", "crash", "recovery"])
    args = parser.parse_args()
    if args.phase:
        spec = json.loads(args.case.read_text())
        output = args.root / "evidence" / spec["id"] / args.phase
        asyncio.run(run_phase(spec, args.phase, output))
    elif args.case:
        run_case(json.loads(args.case.read_text()), args.root)
    else:
        return 0 if run_batch(args.batch, args.root)["complete"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
