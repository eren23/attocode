"""Six-request subscription diagnostic, separate from the frozen Claude R7 study.

Two excluded wiring requests precede four exploratory repairs. No quality gate or
cross-model comparison. Global guidance is suppressed per invocation, never edited.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

from external_benchmarks import (
    copy_source,
    initialize_git,
    shell,
    start_runtime,
    stop_runtime,
    submitted_patch,
)
from repair_grading import digest, file_hash, source_digest, write_json
from repair_study import PROMPT, SERVER_ENV, grade_task
from study import harness_hash, source_hash, tree_hash
from study_clients import command, subscription_env, toml_literal
from study_events import capture, parse_events

HERE = Path(__file__).resolve().parent
MODEL = "gpt-6.1-sol"
LANES = ("native", "lean_optional")
FEATURES = ("hooks", "memories", "apps", "plugins", "goals", "multi_agent")


def client_env(home=None):
    env = subscription_env()
    if home is not None:
        env["CODEX_HOME"] = str(home)
    return env


def settings(guidance="", skills=()):
    return {"project_doc_max_bytes": 0, "model_reasoning_effort": "high",
            "forced_login_method": "chatgpt", "approval_policy": "never", "web_search": "disabled",
            "developer_instructions": guidance, "mcp_servers": {},
            **{"features." + feature: False for feature in FEATURES},
            "skills.config": [{"path": p, "enabled": False} for p in skills]}


class Rpc:
    """Model-free account and instruction-source checks, using the installed API."""

    def __init__(self, config, home=None):
        argv = ["codex", "app-server", "--stdio"]
        for key, value in config.items():
            argv += ["-c", key + "=" + toml_literal(value)]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=client_env(home))
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.pending, self.identity = b"", 0

    def request(self, method, params=None):
        self.identity += 1
        row = {"id": self.identity, "method": method}
        if params is not None:
            row["params"] = params
        self.process.stdin.write((json.dumps(row) + "\n").encode())
        self.process.stdin.flush()
        end = time.monotonic() + 45
        while time.monotonic() < end:
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                response = json.loads(line)
                if response.get("id") == self.identity:
                    if "error" in response:
                        raise ValueError(response["error"])
                    return response["result"]
            if not self.selector.select(max(0, end - time.monotonic())):
                break
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Account/instruction reader exited")
            self.pending += chunk
        raise TimeoutError("Account/instruction read timed out")

    def __enter__(self):
        self.request("initialize", {"clientInfo": {"name": "attocode_codex_diagnostic", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}})
        self.process.stdin.write(b'{"method":"initialized","params":{}}\n')
        self.process.stdin.flush()
        return self

    def __exit__(self, *_):
        self.selector.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def quota_check(previous=None, home=None):
    with Rpc(settings(), home) as rpc:
        account = rpc.request("account/read", {"refreshToken": False}).get("account") or {}
        limits = rpc.request("account/rateLimits/read")
    limits.pop("accountId", None)
    record = {"checked_at": time.time(), "account": {k: account.get(k) for k in ("type", "planType")},
              "limits": limits, "model_requests": 0}
    validate_quota(record, previous)
    return record


def validate_quota(record, previous=None):
    limits = record["limits"]
    current = limits.get("rateLimits") or {}
    windows = [current.get(k) for k in ("primary", "secondary") if current.get(k) is not None]
    if (record["account"].get("type") != "chatgpt" or limits.get("ordinaryUsageAllowed") is not True
            or current.get("spendControlReached") or not windows
            or not 0 <= time.time() - record["checked_at"] <= 60
            or any(not isinstance(w.get("usedPercent"), (int, float)) or not 0 <= w["usedPercent"] < 20
                   for w in windows)):
        raise ValueError("Fresh included quota below the conservative 20% usage ceiling required")
    balance = (current.get("credits") or {}).get("balance")
    if previous is not None:
        before = ((previous["limits"].get("rateLimits") or {}).get("credits") or {}).get("balance")
        if balance is None or before is None or Decimal(balance) < Decimal(before):
            raise ValueError("Credit balance decreased or unavailable; stop further model requests")


def isolation(root, config, home=None):
    with Rpc(config, home) as rpc:
        result = rpc.request("thread/start", {"cwd": str(root), "model": MODEL, "ephemeral": True,
                                              "sandbox": "workspace-write", "config": config})
    if result.get("instructionSources") != [] or result.get("model") != MODEL:
        raise ValueError("Inherited instructions or wrong model in model-free thread check")
    return {k: result.get(k) for k in ("instructionSources", "model", "reasoningEffort", "serviceTier")}


def freeze(study, parent):
    if study.exists():
        raise ValueError("Never overwrite a diagnostic")
    old = json.loads((parent / "manifest.json").read_text())
    original = dict(old)
    if digest({k: v for k, v in old.items() if k != "study_id"}) != old["study_id"]:
        raise ValueError("Parent manifest drift")
    if not json.loads((parent / "preparation.json").read_text()).get("passed"):
        raise ValueError("Parent controls must pass")
    tasks = old["tasks"][:2]
    study.mkdir(parents=True, mode=0o700)
    home = study / "client-home"
    home.mkdir(mode=0o700)
    # Link only the existing login in private harness state. Never copy secrets or
    # replace the real home. No private harness directory is mounted in Docker.
    (home / "auth.json").symlink_to(Path.home() / ".codex/auth.json")
    shutil.copytree(parent / "engine", study / "engine")
    shutil.copytree(HERE, study / "harness", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for task in tasks:
        if source_digest(parent / "sources" / task["id"]) != old["source_hashes"][task["id"]]:
            raise ValueError("Prepared source changed")
        copy_source(parent / "sources" / task["id"], study / "sources" / task["id"])
        initialize_git(study / "sources" / task["id"])
        source = parent / "private" / task["task_file"]
        if file_hash(source) != task["task_sha256"]:
            raise ValueError("Private task changed")
        target = study / "private" / task["task_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copytree(parent / "controls" / task["id"], study / "controls" / task["id"])
    skills = sorted({str(p.parent) for folder in (Path.home() / ".codex/skills", Path.home() / ".agents/skills")
                     for p in folder.rglob("SKILL.md")})
    from attocode_intel.catalog import profile_instructions
    socket = shell(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
    if not socket.strip().startswith("unix://"):
        raise ValueError("Local Unix Docker socket required")
    manifest = {"kind": "codex-repair-diagnostic", "model": MODEL, "reasoning": "high", "tasks": tasks,
                "python": old["python"], "evaluator_python": old["evaluator_python"], "evaluator": old["evaluator"],
                "parent_study_id": old["study_id"], "client_version": shell(["codex", "--version"]).strip(),
                "engine_sha256": source_hash(study / "engine"), "harness_sha256": harness_hash(study / "harness"),
                "pack_sha256": tree_hash(study / "private"), "server_env": SERVER_ENV, "prompt": PROMPT,
                "source_hashes": {t["id"]: source_digest(study / "sources" / t["id"]) for t in tasks},
                "runtime_socket": socket.strip()[7:], "skills": skills, "guidance": profile_instructions("lean"),
                "schedule": [{"id": t["id"] + "-" + lane, "task": t["id"], "lane": lane}
                             for i, t in enumerate(tasks) for lane in (LANES if i == 0 else LANES[::-1])],
                "limits": {"model_requests": 6, "timeout": 600, "session_minutes": 50,
                           "included_usage_ceiling_percent": 20},
                "scope": "Two development tasks, four repairs, exploratory only. Host trace audit; no OS private-input isolation.",
                "adaptation": "Private disposable CODEX_HOME links existing login only; no inherited AGENTS or personal skills. Optional lean routing via explicit developer instructions."}
    manifest["study_id"] = digest(manifest)
    write_json(study / "manifest.json", manifest)
    if original != json.loads((parent / "manifest.json").read_text()):
        raise ValueError("Parent changed during freeze")
    print(json.dumps({"study_id": manifest["study_id"], "scheduled": 4, "wiring": 2}), flush=True)


def load(study):
    manifest = json.loads((study / "manifest.json").read_text())
    if digest({k: v for k, v in manifest.items() if k != "study_id"}) != manifest["study_id"]:
        raise ValueError("Diagnostic manifest drift")
    checks = [(harness_hash(HERE), manifest["harness_sha256"]),
              (source_hash(study / "engine"), manifest["engine_sha256"]),
              (tree_hash(study / "private"), manifest["pack_sha256"]),
              (shell(["codex", "--version"]).strip(), manifest["client_version"])]
    checks += [(source_digest(study / "sources" / t["id"]), manifest["source_hashes"][t["id"]])
               for t in manifest["tasks"]]
    if any(a != b for a, b in checks):
        raise ValueError("Frozen diagnostic inputs changed")
    return manifest


def prepare(study):
    manifest = load(study)
    from repair_study import worker
    from repair_worker import preparation_control
    if worker(manifest["evaluator_python"], "identity", capture=True) != manifest["evaluator"]:
        raise ValueError("Evaluator environment drift")
    for task in manifest["tasks"]:
        raw = json.loads((study / "private" / task["task_file"]).read_text())
        for prefix, source in (("", None), ("mounted-", study / "sources" / task["id"])):
            records = [grade_task(study, manifest, task, patch,
                                  study / "controls" / task["id"] / (prefix + label), source=source)
                       for label, patch in (("base", ""), ("gold", raw["patch"]))]
            if not preparation_control(*records, raw):
                raise ValueError("Base/gold controls failed")
        print(json.dumps({"control": task["id"], "passed": True}), flush=True)
    write_json(study / "preparation.json", {"study_id": manifest["study_id"], "passed": True})


def servers_for(study, manifest, root, stage, lane):
    if lane == "native":
        return {}
    return {"attocode-code-intel": {"command": manifest["python"],
            "args": ["-m", "attocode_intel.entrypoint", "--project", str(root), "--profile", "lean"],
            "env": {**manifest["server_env"], "PYTHONPATH": str(study / "engine"),
                    "ATTOCODE_INTEL_TRACE": str(stage / "engine.jsonl")}}}


async def transport(servers):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async with (stdio_client(StdioServerParameters(**servers["attocode-code-intel"])) as (read, write),
                ClientSession(read, write) as session):
        await session.initialize()
        names = sorted(t.name for t in (await session.list_tools()).tools)
        if set(names) != {"bootstrap", "search_symbols", "inspect_symbol", "semantic_search",
                          "impact_analysis", "suggest_tests", "capabilities"}:
            raise ValueError("Wrong treatment tool list")
        result = await session.call_tool("inspect_symbol", {"symbol_name": "repair_fixture"})
        if result.isError or "return 1" not in result.content[0].text:
            raise ValueError("Treatment inspection unavailable")
        return {"tools": names, "answered_inspection": True, "model_requests": 0}


def audit(root, parsed, helper_hash):
    violations = []
    if file_hash(root / ".benchmark/run.py") != helper_hash:
        violations.append("Runtime helper changed")
    for call in parsed["tool_calls"]:
        for key in ("workspace", "path", "file_path", "files", "changed_files"):
            value = (call.get("arguments") or {}).get(key)
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and not (root / item).resolve().is_relative_to(root.resolve()):
                    violations.append("Tool path outside public workspace: " + item)
    # All shell commands and file_change events require an operator read before acceptance.
    return {"status": "violation" if violations else "needs_review", "violations": violations,
            "shell_commands": [c for c in parsed["tool_calls"] if c["name"] == "shell"],
            "os_private_input_isolation": False}


def argv_for(manifest, root, stage, servers, prompt, lane):
    argv = command("codex", MODEL, root, stage, servers, prompt, plain_text=True,
                   runtime_socket=manifest["runtime_socket"])
    config = settings(manifest["guidance"] if lane != "native" else "", manifest["skills"])
    config.pop("mcp_servers")
    for key, value in config.items():
        argv[-1:-1] = ["-c", key + "=" + toml_literal(value)]
    return argv, config


def trial(study, manifest, task, row, *, wiring=False):
    directory = study / ("wiring" if wiring else "runs") / row["id"]
    directory.mkdir(parents=True, exist_ok=False)
    root, stage = directory / "repository", directory / "stage-0"
    stage.mkdir()
    if wiring:
        root.mkdir()
        (root / "fixture.py").write_text("def repair_fixture(): return 1\n")
        (root / "wiring_value.py").write_text("VALUE = 1\n")
    else:
        copy_source(study / "sources" / task["id"], root)
    initialize_git(root)
    name = "attocode-codex-diagnostic-" + uuid.uuid4().hex[:10]
    result = {**row, "study_id": manifest["study_id"], "excluded": wiring, "status": "infrastructure_error"}
    started = time.monotonic()
    try:
        start_runtime(task, root, name)
        helper_hash = file_hash(root / ".benchmark/run.py")
        environment = ("Run repository programs and tests with `python3 .benchmark/run.py -- <command> <args...>`. "
                       "Read and edit the current workspace. Do not inspect other host directories, Docker resources, "
                       "benchmark inputs or online solutions. Do not delegate or edit .benchmark infrastructure.\n\n")
        prompt = environment + manifest["prompt"].format(problem_statement=task["prompt"])
        servers = servers_for(study, manifest, root, stage, row["lane"])
        if wiring:
            if servers:
                result["transport"] = asyncio.run(transport(servers))
            prompt = (environment + "Excluded wiring check. Change wiring_value.py to VALUE = 2. "
                      "Run `python3 .benchmark/run.py -- python -c 'from wiring_value import VALUE; assert VALUE == 2'`. "
                      + ("Call inspect_symbol on repair_fixture too. " if servers else "") + "Report the result.")
        elif servers:
            from localize_study import warm
            result["warm"] = warm(study, root, directory / "warm", manifest)
            if not result["warm"]["ready"]:
                raise ValueError("Treatment warm-up failed")
        argv, config = argv_for(manifest, root, stage, servers, prompt, row["lane"])
        # No servers in the model-free isolation probe; the exec argv contains only frozen treatment servers.
        home = study / "client-home"
        result["instruction_check"] = isolation(root, {**config, "mcp_servers": {}}, home)
        previous_path = study / "last-quota.json"
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
        before = quota_check(previous, home)
        write_json(directory / "quota-before.json", before)
        write_json(previous_path, before)
        result["setup_seconds"] = time.monotonic() - started
        write_json(directory / "started.json", {"time": time.time(), "study_id": manifest["study_id"]})
        execution = capture(argv, root, stage, 600, client_env(home))
        parsed = parse_events("codex", (stage / "events.jsonl").read_text())
        result.update(execution=execution, usage=parsed["usage"], tool_calls=parsed["tool_calls"],
                      protocol=audit(root, parsed, helper_hash), cost_usd=None)
        result["substantive_adoption"] = any(
            c["name"].startswith("mcp__") and not c["name"].endswith("__capabilities")
            and any(o["id"] == c["id"] and not o["is_error"] for o in parsed["tool_results"])
            for c in parsed["tool_calls"])
        result["status"] = ("failed" if any(execution.get(k) for k in ("exit_code", "timed_out", "quota_exhausted"))
                            or parsed["terminal_error"] else "completed")
        patch, changed = submitted_patch(root)
        (directory / "submission.patch").write_text(patch)
        result.update(changed_files=changed, patch_sha256=digest(patch))
        if wiring:
            check = shell([sys.executable, ".benchmark/run.py", "--", "python", "-c",
                           "from wiring_value import VALUE; assert VALUE == 2; print('ok')"], cwd=root)
            result["runtime_assertion"] = check.strip().endswith("ok")
            result["passed_pending_review"] = (result["runtime_assertion"] and result["status"] == "completed"
                                                and (not servers or result["substantive_adoption"]))
        else:
            result["grade"] = grade_task(study, manifest, task, patch, directory / "grade")
        after = quota_check(before, home)
        write_json(directory / "quota-after.json", after)
        write_json(previous_path, after)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop_runtime(name)
        result["end_to_end_seconds"] = time.monotonic() - started
        write_json(directory / "result.json", result)
    print(json.dumps({k: result.get(k) for k in ("id", "status", "error", "usage", "substantive_adoption",
                                               "runtime_assertion", "end_to_end_seconds")}), flush=True)


def run_one(study, kind, index):
    manifest = load(study)
    prep_path = study / "preparation.json"
    prep = json.loads(prep_path.read_text()) if prep_path.exists() else {}
    if not prep.get("passed") or prep.get("study_id") != manifest["study_id"]:
        raise ValueError("Validated independent base/gold controls required")
    if kind == "wiring":
        if index not in (0, 1):
            raise ValueError("Exactly two excluded wiring slots")
        row = {"id": "excluded-" + LANES[index], "lane": LANES[index]}
    else:
        if index not in range(4):
            raise ValueError("Exactly four repair slots")
        for lane in LANES:
            path = study / "wiring" / ("excluded-" + lane) / "review.json"
            review = json.loads(path.read_text()) if path.exists() else {}
            result_path = path.parent / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            if (review.get("study_id") != manifest["study_id"] or review.get("status") != "clear"
                    or not result.get("passed_pending_review") or result.get("error")):
                raise ValueError("Both wiring attempts must pass and receive trace review before repairs")
        row = manifest["schedule"][index]
    paths = list(study.glob("wiring/*/started.json")) + list(study.glob("runs/*/started.json"))
    if len(paths) >= 6:
        raise ValueError("Six-request ceiling reached")
    trial(study, manifest, next((t for t in manifest["tasks"] if t["id"] == row.get("task")),
                               manifest["tasks"][0]), row, wiring=kind == "wiring")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "prepare", "wiring", "repair", "quota"))
    parser.add_argument("--study", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--index", type=int, default=0)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.study, args.parent)
    elif args.action == "quota":
        print(json.dumps(quota_check()))
    elif args.action == "prepare":
        prepare(args.study)
    else:
        run_one(args.study, args.action, args.index)


if __name__ == "__main__":
    main()
