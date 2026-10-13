"""Freeze and prepare optional-intel bug fixes; model wiring is an explicit later step."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from external_benchmarks import (
    copy_source,
    initialize_git,
    shell,
    start_runtime,
    stop_runtime,
    submitted_patch,
)
from repair_grading import (
    EVALUATOR_REVISION,
    digest,
    file_hash,
    gate,
    source_digest,
    test_list,
    verdict,
    write_json,
)
from study import environment_versions, harness_hash, schedule, source_hash, tree_hash
from study_clients import invoke, parse_events, preflight, subscription_env

HERE = Path(__file__).resolve().parent
LANES = ("native", "lean_optional")
MODEL = "claude-sonnet-5-5"
SERVER_ENV = {"ATTOCODE_INTEL_PRECISION": "off", "ATTOCODE_INTEL_BROAD_RERANK": "0",
              "ATTOCODE_INTEL_RANKING_PROVIDER": "off", "ATTOCODE_INTEL_RANKING_ALLOW_REMOTE": "0",
              "ATTOCODE_EMBEDDING_MODEL": "", "ATTOCODE_NL_EMBEDDING_MODE": "none",
              "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "OPENAI_API_KEY": ""}
TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash(python3 .benchmark/run.py:*)", "Bash(git diff:*)",
         "Bash(git status:*)", "Bash(git ls-files:*)"]
PROMPT = ("Fix the issue below in this repository. You may inspect and edit code and run tests using "
          "the provided task environment. Choose tools when they help. Leave your completed changes "
          "in the workspace and report the tests you ran and any remaining issue.\n\n{problem_statement}")


def worker(python, *args, capture=False):
    argv = [str(python), str(HERE / "repair_worker.py"), *map(str, args)]
    if capture:
        return json.loads(subprocess.check_output(argv, text=True, timeout=1900))
    subprocess.run(argv, check=True, timeout=1900)


def load(study, *, live=True):
    manifest = json.loads((study / "manifest.json").read_text())
    identity = manifest.pop("study_id")
    if digest(manifest) != identity:
        raise ValueError("Frozen repair manifest changed")
    manifest["study_id"] = identity
    checks = [(harness_hash(HERE), manifest["harness_sha256"], "harness"),
              (source_hash(study / "engine"), manifest["engine_sha256"], "engine"),
              (tree_hash(study / "private"), manifest["pack_sha256"], "private pack")]
    checks += [(source_digest(study / "sources" / t["id"]), manifest["source_hashes"][t["id"]], t["id"])
               for t in manifest["tasks"]]
    if live:
        checks += [(shell(["claude", "--version"]).strip(), manifest["client_version"], "client"),
                   (environment_versions(), manifest["environment"], "runtime"),
                   (worker(manifest["evaluator_python"], "identity", capture=True), manifest["evaluator"], "evaluator")]
    for actual, expected, label in checks:
        if actual != expected:
            raise ValueError("Frozen repair " + label + " changed; use the frozen harness or a new study")
    return manifest


def freeze(args):
    project, study = args.project.resolve(), args.study.resolve()
    if args.model != MODEL or args.trials != 2 or (args.setups and tuple(args.setups) != LANES):
        raise ValueError("R7 fixes the model, two trials and native/lean_optional arms")
    if not args.benchmark_pack or not args.evaluator_python:
        raise ValueError("Repair freeze requires --benchmark-pack and --evaluator-python")
    pack_path = args.benchmark_pack.resolve()
    if study.exists() or study.is_relative_to(project) or pack_path.is_relative_to(project):
        raise ValueError("Use a new study and an external private pack")
    pack = json.loads((pack_path / "pack.json").read_text())
    if pack.get("kind") != "repair" or len(pack["tasks"]) != 8 or len({t["repo"] for t in pack["tasks"]}) != 8:
        raise ValueError("Need eight prepared tasks from eight repositories")
    evaluator = worker(args.evaluator_python, "identity", capture=True)
    if evaluator != pack["evaluator"] or evaluator["revision"] != EVALUATOR_REVISION:
        raise ValueError("Evaluator environment drift")
    preparation = pack.get("preparation", {})
    if (preparation.get("worker_sha256") != file_hash(HERE / "repair_worker.py")
            or preparation.get("grading_sha256") != file_hash(HERE / "repair_grading.py")):
        raise ValueError("Preparation tooling differs; prepare a new pack")
    for task in pack["tasks"]:
        if source_digest(pack_path / "sources" / task["id"]) != task.get("source_sha256"):
            raise ValueError("Complete mounted runtime preparation first")
    study.mkdir(parents=True, mode=0o700)
    shutil.copytree(project / "packages/code-intel/src", study / "engine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(HERE, study / "harness", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(pack_path, study / "private", ignore=shutil.ignore_patterns("sources", "__pycache__", "*.pyc"))
    for task in pack["tasks"]:
        copy_source(pack_path / "sources" / task["id"], study / "sources" / task["id"])
        initialize_git(study / "sources" / task["id"])
        # Exact-input cache reuse avoids repeating successful, identical container tests.
        # The frozen worker revalidates task/image/patch/source/evaluator/code identities.
        for control in ("base", "gold", "mounted-base", "mounted-gold"):
            shutil.copytree(pack_path / "candidates" / task["id"] / control,
                            study / "controls" / task["id"] / control / "evaluation")
    tasks = [{**t, "cpus": 2, "memory": "4g"} for t in pack["tasks"]]
    manifest = {"version": 1, "mode": "repair", "model": MODEL, "tasks": tasks,
                # Resolving the executable symlink would discard its virtualenv.
                "python": sys.executable, "evaluator_python": str(args.evaluator_python.expanduser().absolute()),
                "evaluator": evaluator, "client_version": shell(["claude", "--version"]).strip(),
                "environment": environment_versions(), "engine_sha256": source_hash(study / "engine"),
                "harness_sha256": harness_hash(study / "harness"), "pack_sha256": tree_hash(study / "private"),
                "source_hashes": {t["id"]: source_digest(study / "sources" / t["id"]) for t in tasks},
                "schedule": schedule(tasks, 2, seed=7332, lanes=LANES, clients=("claude",)),
                "seed": 7332, "trials": 2, "setups": LANES, "prompt": PROMPT, "tools": TOOLS,
                "server_env": SERVER_ENV,
                "limits": {"timeout": 600, "grading_timeout": 1800, "soft_estimate_usd": 20,
                           "jobs": 2, "session_minutes": 50, "model_wiring_runs": 2},
                "scope": "Development completion pilot; host-client trace audit, not OS isolation",
                "gate": {"resolution_delta": .125, "cost_ratio_max": 1.25, "time_ratio_max": 1.25,
                         "adoption_threshold": None}}
    manifest["study_id"] = digest(manifest)
    write_json(study / "manifest.json", manifest)
    print(json.dumps({"study_id": manifest["study_id"], "scheduled": 32, "model_wiring": "pending"}), flush=True)


def grade_task(study, manifest, task, patch, destination, *, source=None):
    destination.mkdir(parents=True, exist_ok=True)
    patch_path = destination / "submission.patch"
    if patch_path.exists() and patch_path.read_text() != patch:
        raise ValueError("Do not overwrite a submitted patch")
    patch_path.write_text(patch)
    worker(manifest["evaluator_python"], "evaluate", "--task", study / "private" / task["task_file"],
           "--image", task["image"], "--patch", patch_path, "--output", destination / "evaluation",
           *(["--source", source] if source else []))
    return json.loads((destination / "evaluation/acceptance.json").read_text())


def servers_for(study, manifest, root, stage, lane):
    if lane == "native":
        return {}
    env = subscription_env()
    env.update(manifest.get("server_env", SERVER_ENV))
    env["PYTHONPATH"] = str(study / "engine")
    script = "import sys; from attocode_intel.onboarding import configure_client; configure_client('claude', sys.argv[1], profile='lean')"
    subprocess.run([manifest["python"], "-c", script, str(root)], env=env, check=True, capture_output=True)
    return {"attocode-code-intel": {"command": manifest["python"],
            "args": ["-m", "attocode_intel.entrypoint", "--project", str(root), "--profile", "lean"],
            "env": {**manifest.get("server_env", SERVER_ENV), "PYTHONPATH": str(study / "engine"),
                    "ATTOCODE_INTEL_TRACE": str(stage / "engine.jsonl")}}}


def prepare(args):
    study, manifest = args.study, load(args.study)
    controls = {}
    for task in manifest["tasks"]:
        image = json.loads(shell(["docker", "image", "inspect", task["image"]]))[0]
        if image["Id"] != task["image"] or image["Architecture"] != "amd64":
            raise ValueError("Pinned runtime image unavailable")
        raw = json.loads((study / "private" / task["task_file"]).read_text())
        if file_hash(study / "private" / task["task_file"]) != task["task_sha256"]:
            raise ValueError("Task metadata changed")
        base = grade_task(study, manifest, task, "", study / "controls" / task["id"] / "base")
        gold = grade_task(study, manifest, task, raw["patch"], study / "controls" / task["id"] / "gold")
        from repair_worker import preparation_control
        if not preparation_control(base, gold, raw):
            raise ValueError("Frozen base/gold control failed: " + task["id"])
        source = study / "sources" / task["id"]
        mounted_base = grade_task(study, manifest, task, "", study / "controls" / task["id"] / "mounted-base", source=source)
        mounted_gold = grade_task(study, manifest, task, raw["patch"], study / "controls" / task["id"] / "mounted-gold", source=source)
        if not preparation_control(mounted_base, mounted_gold, raw):
            raise ValueError("Frozen mounted runtime controls failed: " + task["id"])
        corrupted = dict(gold["statuses"])
        corrupted[test_list(raw["PASS_TO_PASS"])[-1]] = "FAILED"
        regression = verdict(raw["FAIL_TO_PASS"], raw["PASS_TO_PASS"], corrupted, exit_code=0)
        if regression["resolved"]:
            raise ValueError("Regression control incorrectly passed")
        controls[task["id"]] = {"passed": True, "base": base, "gold": gold,
                                "mounted_base": mounted_base, "mounted_gold": mounted_gold,
                                "regression_rejected": True}
        write_json(study / "preparation.json", {"study_id": manifest["study_id"], "passed": False, "tasks": controls})
        print(json.dumps({"control": task["id"], "passed": True}), flush=True)
    write_json(study / "preparation.json", {"study_id": manifest["study_id"], "passed": True, "tasks": controls,
                                           "model_wiring": "pending", "cache_policy": "Exact-input identity validated by frozen worker"})


async def offline_transport(study, manifest, root, task):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    servers = servers_for(study, manifest, root, study / "wiring/offline", "lean_optional")
    params = StdioServerParameters(**servers["attocode-code-intel"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        expected = {"bootstrap", "search_symbols", "inspect_symbol", "semantic_search", "impact_analysis", "suggest_tests", "capabilities"}
        if names != expected:
            raise ValueError("Wrong advertised treatment tools")
        first = await session.call_tool("inspect_symbol", {"symbol_name": "repair_fixture"})
        if first.isError or "return 1" not in first.content[0].text:
            raise ValueError("Offline inspection failed")
        shell([sys.executable, ".benchmark/run.py", "--", "python", "-c",
               "from pathlib import Path; Path('fixture.py').write_text('def repair_fixture(): return 99\\n')"], cwd=root)
        changed = await session.call_tool("inspect_symbol", {"symbol_name": "repair_fixture"})
        if changed.isError or "return 99" not in changed.content[0].text:
            raise ValueError("Container edit is not reflected in inspection")
    return {"mcp_tools": sorted(names), "container_edit_visible": True, "model_requests": 0}


def offline_wiring(study, manifest):
    path = study / "wiring/offline/result.json"
    if path.exists():
        record = json.loads(path.read_text())
        if record.get("study_id") != manifest["study_id"] or not record.get("passed"):
            raise ValueError("Preserve failed wiring; use a new study after fixing it")
        print(json.dumps(record), flush=True)
        return
    root = path.parent / "repository"
    root.mkdir(parents=True, exist_ok=False)
    (root / "fixture.py").write_text("def repair_fixture(): return 1\n")
    name = "attocode-r7-offline-" + uuid.uuid4().hex[:10]
    task = manifest["tasks"][0]
    record = {"study_id": manifest["study_id"], "passed": False, "model_requests": 0,
              "model_wiring": "pending"}
    try:
        start_runtime(task, root, name)
        output = shell([sys.executable, ".benchmark/run.py", "--", "python", "-c", "print(42)"], cwd=root)
        if output.strip().splitlines()[-1] != "42":
            raise ValueError("Task runtime did not execute")
        record["checks"] = asyncio.run(offline_transport(study, manifest, root, task))
        record["passed"] = True
    finally:
        stop_runtime(name)
        write_json(path, record)
    print(json.dumps(record), flush=True)


def ready(args):
    quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
    status = preflight("claude", quota, subscription_env())
    if not status["ready"]:
        raise ValueError("Fresh subscription-only quota check required: " + str(status))


def protocol_audit(root, calls, helper_hash):
    """Conservative trace audit. Ambiguous host commands require explicit review."""
    root = root.resolve()
    violations, review = [], []
    if file_hash(root / ".benchmark/run.py") != helper_hash:
        violations.append("Runtime helper changed")
    for call in calls:
        args, name = call.get("arguments") or {}, call["name"]
        for key in ("file_path", "path", "workspace", "directory", "files", "changed_files", "scope"):
            value = args.get(key)
            for candidate in value if isinstance(value, list) else [value]:
                if isinstance(candidate, str) and candidate:
                    target = (root / candidate).resolve()
                    if not target.is_relative_to(root):
                        violations.append({"call": call.get("id"), "reason": "Access outside public workspace"})
                    elif name in {"Edit", "Write"} and target.relative_to(root).parts[0] in {".benchmark", ".attocode", ".mcp.json"}:
                        violations.append({"call": call.get("id"), "reason": "Harness infrastructure edit"})
        if name == "Bash":
            command = args.get("command", "")
            try:
                lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
                lexer.whitespace_split = True
                words = list(lexer)
            except ValueError:
                words = []
            simple = (not any(w in {";", "&&", "||", "|", ">", ">>", "<", "&"} for w in words)
                      and "$(" not in command and "`" not in command)
            wrapper = words[:3] == ["python3", ".benchmark/run.py", "--"]
            git_read = (len(words) >= 2 and words[0] == "git" and words[1] in {"diff", "status", "ls-files"}
                        and "--no-index" not in words
                        and all(not w.startswith(("/", "../")) for w in words[2:]))
            if not simple or not (wrapper or git_read):
                review.append({"call": call.get("id"), "command": command})
    return {"status": "violation" if violations else "needs_review" if review else "clear",
            "violations": violations, "review_required": review, "os_sandbox": False}


def trial(study, manifest, task, row, *, wiring=False):
    directory = study / ("wiring/model" if wiring else "runs") / row["id"].replace(":", "-")
    directory.mkdir(parents=True, exist_ok=False)
    root, stage = directory / "repository", directory / "stage-0"
    copy_source(study / "sources" / task["id"], root)
    initialize_git(root)
    name = "attocode-r7-trial-" + uuid.uuid4().hex[:10]
    result = {**row, "study_id": manifest["study_id"], "status": "infrastructure_error", "grade": None,
              "model": manifest["model"],
              "seconds": 600, "cost_usd": None, "protocol_status": "needs_review", "excluded": wiring}
    setup_start = time.monotonic()
    try:
        start_runtime(task, root, name)
        helper_hash = file_hash(root / ".benchmark/run.py")
        servers = servers_for(study, manifest, root, stage, row["lane"])
        if servers:
            from localize_study import warm
            warmed = warm(study, root, directory / "warm", manifest)
            if not warmed["ready"]:
                raise ValueError("Treatment warm-up failed")
            result["warm"] = warmed
        result["setup_seconds"] = time.monotonic() - setup_start
        write_json(directory / "started.json", {**row, "time": time.time(), "study_id": manifest["study_id"]})
        environment = ("Run repository programs and tests with `python3 .benchmark/run.py -- <command> <args...>`. "
                       "Native reads and edits use this same workspace. Do not inspect other host directories, "
                       "Docker resources, benchmark inputs or online solutions. Do not edit .benchmark infrastructure.\n\n")
        prompt = environment + manifest["prompt"].format(problem_statement=task["prompt"])
        if wiring:
            (root / "wiring_value.py").write_text("VALUE = 1\n")
            prompt = (environment + "Excluded wiring check. Change wiring_value.py to VALUE = 2 using Edit or Write. "
                      "Run `python3 .benchmark/run.py -- python -c 'from wiring_value import VALUE; assert VALUE == 2'`. "
                      + ("Call inspect_symbol on a real repository symbol too. " if servers else "") + "Report the result.")
        execution = invoke("claude", manifest["model"], root, stage, servers, prompt, 600,
                           subscription_env(), plain_text=True, project_guidance=True, tools=manifest["tools"])
        result.update(stage=execution, seconds=execution["seconds"], cost_usd=execution.get("cost_usd"))
        parsed = parse_events("claude", (stage / "events.jsonl").read_text())
        audit = protocol_audit(root, parsed["tool_calls"], helper_hash)
        result.update(protocol=audit, protocol_status=audit["status"],
                      any_adoption=any(c["name"].startswith("mcp__") for c in parsed["tool_calls"]),
                      substantive_adoption=any(c["name"].startswith("mcp__") and not c["name"].endswith("__capabilities")
                                               and any(r["id"] == c["id"] and not r["is_error"] for r in parsed["tool_results"])
                                               for c in parsed["tool_calls"]))
        result["status"] = "failed" if any(execution.get(key) for key in (
            "timed_out", "exit_code", "quota_exhausted", "terminal_error")) else "completed"
        patch, changed = submitted_patch(root)
        result.update(changed_files=changed, patch_sha256=hashlib.sha256(patch.encode()).hexdigest())
        (directory / "submission.patch").write_text(patch)
        if wiring:
            check = shell([sys.executable, ".benchmark/run.py", "--", "python", "-c",
                           "from wiring_value import VALUE; assert VALUE == 2; print('ok')"], cwd=root)
            result["passed"] = ("ok" in check and audit["status"] == "clear" and result["status"] == "completed"
                                and (not servers or result["substantive_adoption"]))
        else:
            grade = grade_task(study, manifest, task, patch, directory / "grade")
            if result["status"] != "completed" or audit["status"] != "clear":
                grade = {**grade, "resolved": False}
            result["grade"] = grade if grade["status"] != "infrastructure_error" else None
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        stop_runtime(name)
        result["end_to_end_seconds"] = time.monotonic() - setup_start
        write_json(directory / "result.json", result)


def wiring(args):
    study, manifest = args.study, load(args.study)
    prepared = json.loads((study / "preparation.json").read_text())
    if prepared.get("study_id") != manifest["study_id"] or not prepared.get("passed"):
        raise ValueError("Complete offline preparation first")
    if args.offline:
        offline_wiring(study, manifest)
        return
    for lane in LANES:
        row = {"id": "excluded-" + lane, "task": manifest["tasks"][0]["id"], "lane": lane, "repeat": 0, "client": "claude"}
        directory = study / "wiring/model" / row["id"]
        if directory.exists():
            path = directory / "result.json"
            existing = json.loads(path.read_text()) if path.exists() else {}
            if existing.get("passed") and existing.get("study_id") == manifest["study_id"]:
                continue
            raise ValueError("Keep failed/interrupted model wiring; freeze a new study")
        existing = [json.loads(p.read_text()) for p in (study / "wiring/model").glob("*/result.json")]
        if any(r.get("cost_usd") is None for r in existing) or sum(r["cost_usd"] for r in existing) >= 20:
            raise ValueError("Model wiring cost limit reached or estimates unavailable")
        ready(args)
        record = trial(study, manifest, manifest["tasks"][0], row, wiring=True)
        if not record.get("passed"):
            raise ValueError("Model wiring failed; scored attempts cannot start")


def run(args):
    study, manifest = args.study, load(args.study)
    if args.jobs not in (1, 2) or args.deadline_minutes > 50 or args.deadline_minutes <= 0:
        raise ValueError("Use one/two workers and a session deadline at most 50 minutes")
    prep = json.loads((study / "preparation.json").read_text())
    if not prep.get("passed") or prep.get("study_id") != manifest["study_id"]:
        raise ValueError("Offline preparation is required")
    offline = study / "wiring/offline/result.json"
    offline_record = json.loads(offline.read_text()) if offline.exists() else {}
    if not offline_record.get("passed") or offline_record.get("study_id") != manifest["study_id"]:
        raise ValueError("Offline transport check required")
    for lane in LANES:
        path = study / "wiring/model" / ("excluded-" + lane) / "result.json"
        record = json.loads(path.read_text()) if path.exists() else {}
        if not record.get("passed") or record.get("study_id") != manifest["study_id"]:
            raise ValueError("Model wiring pending; no scored model request was made")
    if args.max_runs is not None and args.max_runs < 1:
        raise ValueError("--max-runs must be positive")
    records = [json.loads(p.read_text()) for p in (study / "runs").glob("*/result.json")]
    wiring_records = [json.loads(p.read_text()) for p in (study / "wiring/model").glob("*/result.json")]
    if any(r.get("cost_usd") is None for r in [*records, *wiring_records]):
        raise ValueError("An existing attempt lacks a cost estimate; preserve it and stop scheduling")
    total = sum(r.get("cost_usd") or 0 for r in [*records, *wiring_records])
    pending = []
    for row in manifest["schedule"]:
        directory = study / "runs" / row["id"].replace(":", "-")
        if (directory / "result.json").exists() or args.tasks and row["task"] not in args.tasks:
            continue
        if directory.exists():
            write_json(directory / "result.json", {**row, "study_id": manifest["study_id"], "status": "interrupted",
                                                    "seconds": 600, "cost_usd": None,
                                                    "grade": {"resolved": False}, "protocol_status": "clear"})
            raise ValueError("Interrupted attempt retained; cost and protocol review required before resuming")
        else:
            pending.append(row)
    queue = iter(pending[:args.max_runs])
    lock, stop = threading.Lock(), threading.Event()
    deadline = time.monotonic() + args.deadline_minutes * 60
    tasks = {t["id"]: t for t in manifest["tasks"]}

    def work():
        nonlocal total
        while not stop.is_set() and time.monotonic() < deadline:
            with lock:
                row = next(queue, None) if total < 20 and not stop.is_set() and time.monotonic() < deadline else None
            if row is None:
                return
            try:
                ready(args)
            except Exception:
                stop.set()
                raise
            with lock:
                if stop.is_set() or total >= 20 or time.monotonic() >= deadline:
                    return
            record = trial(study, manifest, tasks[row["task"]], row)
            with lock:
                total += record.get("cost_usd") or 0
                if record.get("stage", {}).get("quota_exhausted") or record.get("cost_usd") is None:
                    stop.set()
            print(json.dumps({"id": row["id"], "status": record["status"], "cost_total": total}), flush=True)

    with ThreadPoolExecutor(args.jobs) as pool:
        for future in [pool.submit(work) for _ in range(args.jobs)]:
            future.result()


def summary(args):
    study, manifest = args.study, load(args.study, live=False)
    rows = [json.loads(p.read_text()) for p in sorted((study / "runs").glob("*/result.json"))]
    by_task = []
    for task in manifest["tasks"]:
        arms = {arm: [r for r in rows if r["task"] == task["id"] and r["lane"] == arm] for arm in LANES}
        scores = {arm: sum(bool((r.get("grade") or {}).get("resolved")) for r in records) / 2
                  if len(records) == 2 else None for arm, records in arms.items()}
        by_task.append({"task": task["id"], "resolution": scores, "delta":
                        scores["lean_optional"] - scores["native"] if None not in scores.values() else None})
    expected = {r["id"]: r for r in manifest["schedule"]}
    by_id = {r["id"]: r for r in rows}
    trial_pairs = []
    for task in manifest["tasks"]:
        for repeat in range(2):
            pair = {arm: next(r["id"] for r in manifest["schedule"]
                              if r["task"] == task["id"] and r["repeat"] == repeat and r["lane"] == arm) for arm in LANES}
            scores = {arm: bool((by_id[identity].get("grade") or {}).get("resolved"))
                      if identity in by_id else None for arm, identity in pair.items()}
            trial_pairs.append({"task": task["id"], "repeat": repeat, "runs": pair, "resolved": scores,
                                "delta": int(scores["lean_optional"]) - int(scores["native"])
                                if None not in scores.values() else None})
    tool_calls = Counter(c["name"] for r in rows for c in r.get("stage", {}).get("tool_calls", [])
                         if c["name"].startswith("mcp__"))
    valid = all(r.get("study_id") == manifest["study_id"] and r.get("id") in expected
                and all(r.get(k) == v for k, v in expected[r["id"]].items()) for r in rows)
    report = {"study_id": manifest["study_id"], "recorded": len(rows), "scheduled": 32,
              "run_identities_valid": valid,
              "task_differences": by_task, "trial_pairs": trial_pairs,
              "adoption": {"any": sum(bool(r.get("any_adoption")) for r in rows),
                           "substantive": sum(bool(r.get("substantive_adoption")) for r in rows),
                           "substantive_tasks": len({r["task"] for r in rows if r.get("substantive_adoption")}),
                           "tool_calls": dict(tool_calls)},
              "gate": gate(rows) if valid else {"decision": "inconclusive", "reason": "Run identities differ"},
              "model_wiring": "pending" if not all(
                  (study / "wiring/model" / ("excluded-" + a) / "result.json").exists() for a in LANES) else "recorded"}
    write_json(study / "summary.json", report)
    (study / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (study / "summary.md").write_text(
        f"# R7 completion pilot\n\nStudy `{manifest['study_id'][:12]}`. Recorded {len(rows)}/32 scored attempts.\n\n"
        f"Model wiring: {report['model_wiring']}. Continuation: {report['gate']['decision']}.\n\n"
        "Host-client trace audit; not OS isolation. Adoption is descriptive, not a continuation gate.\n")
    print(json.dumps(report), flush=True)


report = summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-pack")
    prep.add_argument("--dataset", required=True, type=Path)
    prep.add_argument("--pack", required=True, type=Path)
    prep.add_argument("--evaluator-python", required=True, type=Path)
    args = parser.parse_args()
    subprocess.run([str(args.evaluator_python), str(HERE / "repair_worker.py"), "prepare-pack",
                    "--dataset", str(args.dataset), "--pack", str(args.pack)], check=True)


if __name__ == "__main__":
    main()
