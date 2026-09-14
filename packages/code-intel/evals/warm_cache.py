"""Frozen, model-free cache-lifecycle measurements on private repository packs.

This compares the same engine with and without cache reuse, not agents or rg.
Each task uses the real compact MCP gateway. Restarts use new OS processes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path

LANES = ("cold_each_task", "persistent")
IGNORED = {".git", ".attocode", "__pycache__", "node_modules", ".venv"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def fingerprint(root):
    entries = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in sorted(files + [d for d in dirs if (Path(folder) / d).is_symlink()]):
            path = Path(folder) / name
            if name.endswith(".pyc"):
                continue
            entries[path.relative_to(root).as_posix()] = (
                {"link": str(path.readlink())} if path.is_symlink() else
                {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "executable": bool(path.stat().st_mode & 0o111)})
    return digest(entries)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def local_path(root, relative):
    path = root / relative
    if not relative or Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path must stay inside the disposable repository")
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(root)):
        raise ValueError("Do not edit through symlinks")
    if any(part in IGNORED for part in Path(relative).parts):
        raise ValueError("Edits must target source, not benchmark state")
    return path


def apply_edits(root, edits):
    for edit in edits:
        path = local_path(root, edit["path"])
        before = path.read_text() if path.exists() else None
        if before != edit["before"]:
            raise ValueError(f"Edit preimage mismatch: {edit['path']}")
        if edit["after"] is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit["after"])


def subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    return type(actual) is type(expected) and actual == expected


def grade(payload, checks):
    """Check response fields, never credit echoed arguments or metadata as evidence."""
    outcomes = []
    for check in checks:
        try:
            if not check["path"] or check["path"][0] != "data":
                raise ValueError("Checks must address result data")
            value = payload
            for part in check["path"]:
                value = value[part]
            if "equals" in check:
                passed = subset(value, check["equals"])
            elif "any" in check:
                passed = isinstance(value, list) and any(subset(item, check["any"]) for item in value)
            elif "none" in check:
                passed = isinstance(value, list) and not any(subset(item, check["none"]) for item in value)
            elif "contains" in check:
                passed = isinstance(value, str) and check["contains"] in value
            else:
                passed = False
        except (KeyError, IndexError, TypeError, ValueError):
            passed = False
        outcomes.append(bool(passed))
    return {"passed": bool(outcomes) and all(outcomes), "checks": outcomes}


def validate_pack(pack):
    repos = pack["repositories"]
    if not repos or len({r["id"] for r in repos}) != len(repos):
        raise ValueError("Unique repositories required")
    for repo in repos:
        if not repo["id"].replace("-", "").replace("_", "").isalnum():
            raise ValueError("Repository id must be a simple name")
        tasks = repo["tasks"]
        if len(tasks) < 4 or len({t["id"] for t in tasks}) != len(tasks):
            raise ValueError("A sequence needs distinct task ids")
        if not any(t.get("restart") for t in tasks[1:]) or not any(t.get("edits") for t in tasks[1:]):
            raise ValueError("Include a process restart and source edits")
        for task in tasks:
            if task.get("edit_while_closed") and (not task.get("restart") or not task.get("edits")):
                raise ValueError("Offline edits require edits and a process restart")
            if not task.get("checks") or not task.get("operation") or not isinstance(task.get("arguments"), dict):
                raise ValueError("Each task needs an operation, arguments and evidence checks")
            for check in task["checks"]:
                if not check.get("path") or check["path"][0] != "data" or sum(k in check for k in ("equals", "any", "none", "contains")) != 1:
                    raise ValueError("Checks must address data with one supported predicate")


def freeze(args):
    project, study = args.project.resolve(), args.study.resolve()
    if study.is_relative_to(project) or args.pack.resolve().is_relative_to(project):
        raise ValueError("Pack and study must remain outside the repository")
    if study.exists():
        raise ValueError("Never overwrite a frozen study")
    pack = json.loads(args.pack.read_text())
    validate_pack(pack)
    selected_lanes = tuple(getattr(args, "lanes", LANES))
    if not selected_lanes or len(set(selected_lanes)) != len(selected_lanes) or set(selected_lanes) - set(LANES):
        raise ValueError("Select distinct supported lifecycle lanes")
    study.mkdir(parents=True, mode=0o700)
    engine_source = getattr(args, "engine_source", None) or project / "packages/code-intel/src"
    shutil.copytree(engine_source, study / "engine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(Path(__file__), study / "warm_cache.py")
    repos = []
    for spec in pack["repositories"]:
        source = Path(spec["source"]).resolve()
        if study.is_relative_to(source):
            raise ValueError("Study cannot be nested inside an input source")
        root = study / "sources" / spec["id"]
        shutil.copytree(source, root, symlinks=True, ignore=shutil.ignore_patterns(*IGNORED, "*.pyc"))
        repos.append({**{k: v for k, v in spec.items() if k != "source"}, "source_sha256": fingerprint(root)})
    schedule = []
    rng = random.Random(args.seed)
    for repeat in range(args.repetitions):
        order = list(repos)
        rng.shuffle(order)
        for repo in order:
            # Alternate lane order across repetitions; do not always warm OS caches for one lane.
            lanes = selected_lanes if (repeat + [r["id"] for r in repos].index(repo["id"])) % 2 == 0 else selected_lanes[::-1]
            schedule.extend({"id": f"{repo['id']}-{repeat}-{lane}", "repo": repo["id"],
                             "repeat": repeat, "lane": lane} for lane in lanes)
    manifest = {"version": 1, "kind": "engine-cache-lifecycle", "repositories": repos,
                "schedule": schedule, "repetitions": args.repetitions, "seed": args.seed,
                "timeout_seconds": args.timeout, "python": sys.executable,
                "python_version": sys.version, "platform": platform.platform(),
                "engine_sha256": fingerprint(study / "engine"),
                "harness_sha256": hashlib.sha256((study / "warm_cache.py").read_bytes()).hexdigest(),
                "precision": "off", "watch": False,
                "scope": "Frozen engine cache lifecycle; only selected lanes measured. No agent/native comparison.",
                "cache_limits": "OS caches uncontrolled; source copies excluded; startup, shutdown and edit costs included."}
    manifest["study_id"] = digest(manifest)
    write_json(study / "manifest.json", manifest)
    print(json.dumps({"study_id": manifest["study_id"], "sequences": len(schedule)}), flush=True)


def load(study):
    manifest = json.loads((study / "manifest.json").read_text())
    identity = manifest.pop("study_id")
    if digest(manifest) != identity:
        raise ValueError("Manifest drift")
    manifest["study_id"] = identity
    if (fingerprint(study / "engine") != manifest["engine_sha256"] or
            hashlib.sha256((study / "warm_cache.py").read_bytes()).hexdigest() != manifest["harness_sha256"]):
        raise ValueError("Engine or harness drift")
    for repo in manifest["repositories"]:
        if fingerprint(study / "sources" / repo["id"]) != repo["source_sha256"]:
            raise ValueError("Source drift")
    return manifest


async def worker(root):
    # Import and initialization are deliberately after process spawn, inside measured startup.
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens
    gateway = OperationGateway(str(root), "daily", watch=False)
    print(json.dumps({"ready": True, "pid": os.getpid()}), flush=True)
    try:
        for line in sys.stdin:
            task = json.loads(line)
            if task.get("close"):
                break
            started = time.perf_counter()
            try:
                result = await gateway.execute_mcp(task["operation"], task["arguments"])
                payload = json.loads(result.content[0].text)
                row = {"payload": payload, "is_error": bool(result.isError), "tokens": response_tokens(result)}
                if task.get("wait_until_ready") and not result.isError:
                    # Bootstrap can return before background indexing and persistence finish.
                    # Charge this barrier to setup instead of calling a partial index fully warm.
                    waiting, polls = time.perf_counter(), 0
                    while True:
                        status = await gateway.execute("hydration_status", {})
                        polls += 1
                        coverage = status.structuredContent["metadata"]["coverage"]
                        print(json.dumps({"readiness_progress": coverage}), file=sys.stderr, flush=True)
                        if status.isError or coverage.get("discovery_truncated"):
                            raise ValueError("Index readiness is incomplete")
                        if coverage.get("phase") == "ready":
                            break
                        await asyncio.sleep(5)
                    row.update(ready_wait_seconds=time.perf_counter() - waiting,
                               readiness_polls=polls, ready_coverage=coverage)
            except Exception as exc:
                row = {"is_error": True, "error": f"{type(exc).__name__}: {exc}"}
            row.update(operation_seconds=time.perf_counter() - started, pid=os.getpid())
            print(json.dumps(row), flush=True)
    finally:
        await gateway.close()


class Worker:
    def __init__(self, study, root, directory, number, timeout):
        self.timeout = timeout
        self.errors = (directory / f"worker-{number}.stderr").open("w")
        env = dict(os.environ, PYTHONPATH=str(study / "engine"), ATTOCODE_INTEL_PRECISION="off",
                   ATTOCODE_INTEL_TRACE=str(directory / f"worker-{number}.telemetry.jsonl"),
                   PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen([sys.executable, str(study / "warm_cache.py"), "worker", "--root", str(root)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, env=env,
                                        start_new_session=True, bufsize=0)
        self.pending = b""
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            ready = self.read()
            if not ready.get("ready"):
                raise ValueError("Worker did not start")
            self.pid = ready["pid"]
        except BaseException:
            self.close(force=True)
            raise

    def read(self):
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Worker response deadline exceeded")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Worker exited without a response")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def request(self, task):
        self.process.stdin.write((json.dumps(task) + "\n").encode())
        return self.read()

    def close(self, force=False):
        try:
            if self.process.poll() is None:
                if force:
                    self.process.kill()
                else:
                    self.process.stdin.write(b'{"close":true}\n')
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()
            self.errors.close()


def phase(task, index, state):
    if task.get("edits"):
        return "edited"
    if task.get("restart"):
        return "restart"
    if index == 0:
        return "cold"
    return "edited_warm" if state in {"edited", "edited_warm"} else "warm"


def run_sequence(study, manifest, spec, entry, directory):
    root = directory / "repository"
    setup = time.perf_counter()
    shutil.copytree(study / "sources" / spec["id"], root, symlinks=True)
    setup_seconds = time.perf_counter() - setup
    worker_instance, number, rows, state = None, 0, [], "cold"
    try:
        for index, task in enumerate(spec["tasks"]):
            start = time.perf_counter()
            state = phase(task, index, state)
            row = {"task": task["id"], "index": index + 1, "phase": state,
                   "operation": task["operation"], "arguments": task["arguments"]}
            try:
                if task.get("edit_while_closed") and worker_instance:
                    worker_instance.close()
                    worker_instance = None
                apply_edits(root, task.get("edits", []))
                if (entry["lane"] == "cold_each_task" or task.get("restart")) and worker_instance:
                    worker_instance.close()
                    worker_instance = None
                if entry["lane"] == "cold_each_task":
                    shutil.rmtree(root / ".attocode", ignore_errors=True)
                startup = time.perf_counter()
                if worker_instance is None:
                    number += 1
                    worker_instance = Worker(study, root, directory, number, manifest["timeout_seconds"])
                    row["startup_seconds"] = time.perf_counter() - startup
                else:
                    row["startup_seconds"] = 0.0
                response = worker_instance.request(task)
                row.update(response)
                row["grade"] = grade(response.get("payload", {}), task["checks"])
                row["passed"] = not response["is_error"] and row["grade"]["passed"]
                if task.get("wait_until_ready"):
                    row["passed"] &= response.get("ready_coverage", {}).get("phase") == "ready"
                if entry["lane"] == "cold_each_task" or index == len(spec["tasks"]) - 1:
                    worker_instance.close()
                    worker_instance = None
            except Exception as exc:
                row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
                if worker_instance:
                    worker_instance.close(force=True)
                    worker_instance = None
            row["seconds"] = time.perf_counter() - start
            row["penalized_seconds"] = row["seconds"] if row["passed"] else max(row["seconds"], manifest["timeout_seconds"])
            write_json(directory / f"task-{index + 1:02}.json", row)
            rows.append(row)
            print(json.dumps({"run": entry["id"], "task": index + 1, "phase": state,
                              "seconds": round(row["seconds"], 3), "passed": row["passed"]}), flush=True)
    finally:
        if worker_instance:
            worker_instance.close(force=True)
    result = {**entry, "study_id": manifest["study_id"], "status": "completed", "rows": rows,
              "source_copy_seconds": setup_seconds, "passed": all(r["passed"] for r in rows)}
    write_json(directory / "result.json", result)
    return result


def run(args):
    manifest = load(args.study)
    specs = {r["id"]: r for r in manifest["repositories"]}
    for entry in manifest["schedule"]:
        directory = args.study / "runs" / entry["id"]
        if (directory / "result.json").exists():
            continue
        if directory.exists():
            # No implicit replacement of an interrupted sequence, including its prior successful calls.
            write_json(directory / "result.json", {**entry, "study_id": manifest["study_id"],
                                                    "status": "interrupted", "passed": False})
            continue
        directory.mkdir(parents=True, mode=0o700)
        write_json(directory / "started.json", {**entry, "study_id": manifest["study_id"], "time": time.time()})
        run_sequence(args.study, manifest, specs[entry["repo"]], entry, directory)
    report(args)


def cumulative_pair(control, candidate):
    if not control or len(control) != len(candidate) or any(a["task"] != b["task"] for a, b in zip(control, candidate, strict=True)):
        raise ValueError("Only complete aligned sequences can be paired")
    rows, a_total, b_total, valid = [], 0.0, 0.0, True
    for index, (a, b) in enumerate(zip(control, candidate, strict=True), 1):
        a_total += a["penalized_seconds"]
        b_total += b["penalized_seconds"]
        valid &= a["passed"] and b["passed"]
        rows.append({"tasks": index, "control_seconds": a_total, "candidate_seconds": b_total,
                     "saved_seconds": a_total - b_total, "all_correct": bool(valid)})
    # A fast failed result never establishes break-even. Require an advantage that survives the observed horizon.
    crossover = next((r["tasks"] for i, r in enumerate(rows)
                      if all(x["all_correct"] and x["saved_seconds"] > 0 for x in rows[i:])), None)
    return {"cumulative": rows, "sustained_crossover_task": crossover,
            "all_correct": bool(valid), "speedup": a_total / b_total if valid and b_total else None}


def percentile(values, quantile):
    values = sorted(values)
    return values[max(0, math.ceil(quantile * len(values)) - 1)] if values else None


def report(args):
    manifest = load(args.study)
    runs = {}
    for entry in manifest["schedule"]:
        path = args.study / "runs" / entry["id"] / "result.json"
        if path.exists():
            result = json.loads(path.read_text())
            if any(result.get(k) != v for k, v in entry.items()) or result.get("study_id") != manifest["study_id"]:
                raise ValueError("Run identity drift")
            if result.get("status") == "completed":
                spec = next(r for r in manifest["repositories"] if r["id"] == entry["repo"])
                if len(result.get("rows", [])) != len(spec["tasks"]):
                    raise ValueError("Incomplete sequence marked complete")
                for index, (task, row) in enumerate(zip(spec["tasks"], result["rows"], strict=True), 1):
                    saved = json.loads((path.parent / f"task-{index:02}.json").read_text())
                    if row != saved or row.get("task") != task["id"] or row.get("index") != index:
                        raise ValueError("Task record drift")
                    seconds = row.get("seconds")
                    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                        raise ValueError("Invalid task timing")
                    passed = not row.get("error") and not row.get("is_error", True) and grade(row.get("payload", {}), task["checks"])["passed"]
                    if task.get("wait_until_ready"):
                        passed &= row.get("ready_coverage", {}).get("phase") == "ready"
                    penalty = seconds if passed else max(seconds, manifest["timeout_seconds"])
                    if row.get("passed") != passed or row.get("penalized_seconds") != penalty:
                        raise ValueError("Grade or penalty drift")
            runs[entry["id"]] = result
    pairs, phases = [], []
    for spec in manifest["repositories"]:
        for repeat in range(manifest["repetitions"]):
            a, b = (runs.get(f"{spec['id']}-{repeat}-{lane}", {}) for lane in LANES)
            if all(r.get("status") == "completed" and len(r.get("rows", [])) == len(spec["tasks"]) for r in (a, b)):
                pairs.append({"repo": spec["id"], "repeat": repeat, **cumulative_pair(a["rows"], b["rows"])})
        for lane in LANES:
            for label in ("cold", "warm", "restart", "edited", "edited_warm"):
                rows = [row for r in runs.values() if r["repo"] == spec["id"] and r["lane"] == lane
                        for row in r.get("rows", []) if row["phase"] == label]
                if rows:
                    phases.append({"repo": spec["id"], "lane": lane, "phase": label, "calls": len(rows),
                                   "passed": sum(r["passed"] for r in rows),
                                   "p50_seconds": percentile([r["seconds"] for r in rows], .5),
                                   "p95_seconds": percentile([r["seconds"] for r in rows], .95)})
    result = {"study_id": manifest["study_id"], "scope": manifest["scope"],
              "required_sequences": len(manifest["schedule"]), "recorded_sequences": len(runs),
              "completed_sequences": sum(r.get("status") == "completed" for r in runs.values()),
              "pairs": pairs, "phases": phases,
              "agent_comparison": {"status": "not_measured", "native_break_even": None}}
    write_json(args.study / "report.json", result)
    lines = ["# Cache lifecycle measurements", "", manifest["scope"], "",
             "When selected, cold_each_task recreates the engine's process and index for every task. Unselected lanes are not measured. This is not a native-agent baseline.",
             "Times include process startup, shutdown, edits and retrieval; source copying is separate. OS caches are uncontrolled.",
             "A crossover is measured only against this control, with every answer correct through the complete observed sequence.",
             "", "| Repository | Repeat | Correct throughout | Control seconds | Reuse seconds | Speedup | Sustained crossover |",
             "|---|---:|---|---:|---:|---:|---:|"]
    for pair in pairs:
        last = pair["cumulative"][-1]
        speed = f"{pair['speedup']:.2f}x" if pair["speedup"] else "unproven"
        lines.append(f"| {pair['repo']} | {pair['repeat'] + 1} | {pair['all_correct']} | "
                     f"{last['control_seconds']:.2f} | {last['candidate_seconds']:.2f} | {speed} | "
                     f"{pair['sustained_crossover_task'] or 'none'} |")
    lines += ["", "Failed operations receive at least the fixed timeout penalty; raw timings and failures remain in task records.",
              "Phase percentiles mix operations and are descriptive; use aligned task pairs for comparisons.",
              "", "Actual agent task time, tool adoption, reasoning quality, and break-even versus native tools remain unmeasured."]
    (args.study / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"recorded_sequences": len(runs), "pairs": len(pairs)}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("--pack", type=Path, required=True)
    freeze_parser.add_argument("--study", type=Path, required=True)
    freeze_parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[3])
    freeze_parser.add_argument("--repetitions", type=int, default=3)
    freeze_parser.add_argument("--seed", type=int, default=9341)
    freeze_parser.add_argument("--timeout", type=int, default=240)
    freeze_parser.add_argument("--lanes", nargs="+", choices=LANES, default=list(LANES))
    freeze_parser.add_argument("--engine-source", type=Path, help="Freeze a preserved engine for a matched comparison")
    for name in ("run", "report"):
        commands.add_parser(name).add_argument("--study", type=Path, required=True)
    commands.add_parser("worker").add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        asyncio.run(worker(args.root))
    elif args.command == "freeze":
        if args.repetitions < 1 or args.timeout < 1:
            parser.error("Repetitions and timeout must be positive")
        freeze(args)
    else:
        globals()[args.command](args)


if __name__ == "__main__":
    main()
