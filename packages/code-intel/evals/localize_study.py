"""Agent file localization: Claude Code names the files that a fix for an issue must edit.

Setups: `native` (Read, Grep, Glob), `intel` (the native tools, the attocode MCP server and
its installed guidance), `intel_first` (intel, and the prompt asks for semantic_search
first), and `issue_only` (no tools, an empty workspace and one trial: the contamination
control). `run` records what the client did. Only `summary` grades, with code.

The input is a matrix `instances.jsonl`: one `asdict(eval.matrix.datasets.Instance)` on each
line, as `python -m eval.matrix.run ingest` writes it. The harness reads it as JSON and does
not import `eval.matrix`.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from external_benchmarks import shell
from external_study import ready, successful
from onboarding_study import GUIDANCE, NAME, configure_setup
from study import (
    GIT_USER,
    digest,
    environment_versions,
    harness_hash,
    schedule,
    source_hash,
    tree_hash,
    write_json,
)
from study_clients import invoke, parse_events, subscription_env
from workflows import snapshot

HERE = Path(__file__).resolve().parent
PROMPT_V1 = ("{issue}\n\nFind the files that must be edited to fix this issue. Do not edit files or run code. "
             'Return {{"files": [...]}}: at most 10 repository-relative paths, most likely first.')
FIRST = " Call semantic_search with the issue title first."
SCHEMA = {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}}},
          "required": ["files"], "additionalProperties": False}
SETUPS = ("native", "intel", "intel_first", "issue_only")
INTEL = ("intel", "intel_first")
# No ToolSearch in any setup: all setups get the same built-in tools, and the wiring check
# proves that the MCP tools are callable without it.
NATIVE = ["Read", "Grep", "Glob"]
TOOLS = {"native": NATIVE, "intel": NATIVE, "intel_first": NATIVE, "issue_only": []}
# A config_id names extra MCP server environment. "product" is the shipped default.
CONFIGS = {"product": {}}
LOCAL_ENV = {"ATTOCODE_LOCAL_ONLY": "1", "HF_HUB_OFFLINE": "1"}
FOLDERS = ("runs", "sources", "wiring", "clones", "prepare")
TOKENS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
TIMEOUT, WARM_TIMEOUT, SEED = 600, 1800, 7331
WIRING_SCHEMA = {"type": "object", "properties": {"readiness_token": {"type": "string"},
                 "user_instructions": {"type": "string"}, "search_called": {"type": "boolean"}},
                 "required": ["readiness_token", "user_instructions", "search_called"], "additionalProperties": False}
WIRING_PROMPT = ("Excluded wiring check, not a scored trial. Do not edit files. Set readiness_token to the readiness "
                 "token in your project instructions; do not read files to find it. Set user_instructions to the "
                 "first line of any instructions that you loaded from the home directory, or to none. Call "
                 "semantic_search once with the query 'benchmark value', then set search_called to true.")


def task_id(instance):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", instance["id"])


def source(repo):
    """Where prepare fetches from: GitHub for owner/name, else the read-only local clone of a case pack."""
    return f"https://github.com/{repo}.git" if "/" in repo else str(Path.home() / "Documents/ai/benchmark-repos" / repo)


def as_task(instance):
    """A study task from one matrix instance. The matrix id is the instance_id join key."""
    queries = instance["queries"]
    return {"id": task_id(instance), "instance_id": instance["id"], "dataset": instance["id"].split("/", 1)[0],
            "repo": instance["repo"], "source": source(instance["repo"]), "base_commit": instance["base_commit"],
            "language": instance.get("language", ""), "issue": queries["full"],
            "title": queries.get("title") or queries["full"], "gold": instance["gold"]}


def prompt(task, setup):
    return PROMPT_V1.format(issue=task["issue"]) + (FIRST if setup == "intel_first" else "")


def client_version():
    return subprocess.check_output(["claude", "--version"], text=True, timeout=20).strip()


def git(root, *args, timeout=300):
    return shell(["git", *args], cwd=root, timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def run_dir(study, row):
    return study / "runs" / row["id"].replace(":", "-")


def check(instance):
    queries, gold = instance.get("queries"), instance.get("gold")
    if not ("/" in str(instance.get("id")) and instance.get("repo")
            and re.fullmatch(r"[0-9a-f]{40}", str(instance.get("base_commit")))
            and isinstance(queries, dict) and str(queries.get("full") or "").strip()
            and isinstance(gold, list) and gold and all(isinstance(p, str) and p for p in gold)):
        raise ValueError(f"Instance {instance.get('id')} needs a dataset/native id, a repo, a full base_commit, "
                         "queries.full and gold")


def freeze(args):
    project, study = args.project.resolve(), args.study.resolve()
    if study.is_relative_to(project):
        raise ValueError("Study artifacts must be outside the source repository")
    if study.exists():
        raise ValueError("Study directory already exists; use a new directory for a new study")
    if not (args.instances and args.ids and args.model):
        raise ValueError("Localize mode needs --instances, --ids and --model")
    if not re.search(r"\d", args.model):
        raise ValueError("Pin an explicit model ID, not an alias such as 'sonnet'")
    setups = list(args.setups or SETUPS)
    if set(setups) - set(SETUPS) or len(set(setups)) != len(setups):
        raise ValueError(f"Setups must be distinct names from {SETUPS}")
    if args.config_id not in CONFIGS or args.trials < 1:
        raise ValueError(f"Use --trials of 1 or more and a config id from {sorted(CONFIGS)}")
    wanted = {line.strip() for line in args.ids.read_text().splitlines() if line.strip() and not line.startswith("#")}
    instances = [json.loads(line) for line in args.instances.read_text().splitlines() if line.strip()]
    found = Counter(instance.get("id") for instance in instances)
    if missing := sorted(name for name in wanted if found[name] != 1):
        raise ValueError(f"Each id must match the id of exactly one instance (dataset/native): {missing[:5]}")
    selected = [instance for instance in instances if instance.get("id") in wanted]
    for instance in selected:
        check(instance)
    tasks = [as_task(instance) for instance in selected]
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("Two instances have the same path-safe task id")
    for task in tasks:
        task["prompts"] = {setup: prompt(task, setup) for setup in setups}
    study.mkdir(parents=True, mode=0o700)
    shutil.copytree(project / "packages/code-intel/src", study / "engine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(HERE, study / "harness", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    python = str(Path(sys.executable).absolute())
    server_env = {**LOCAL_ENV, **CONFIGS[args.config_id]}
    manifest = {"version": 1, "mode": "localize", "prompt_version": "PROMPT_V1", "client": "claude",
                "model": args.model, "client_version": client_version(), "python": python, "project": str(project),
                "config_id": args.config_id, "server_env": server_env,
                # Trials replay the installed entry (onboarding_study.configure_setup) with this command.
                "mcp_server": {"command": python, "args": ["-m", "attocode_intel.entrypoint", "--profile", "daily",
                                                           "--project", "<workspace>"],
                               "env": {"PYTHONPATH": "<study>/engine", "ATTOCODE_INTEL_PRECISION": "off", **server_env}},
                "setups": setups, "tools": {setup: TOOLS[setup] for setup in setups}, "trials": args.trials,
                "timeout": TIMEOUT, "seed": SEED, "tasks": tasks,
                "schedule": [row for row in schedule(tasks, args.trials, seed=SEED, lanes=setups, clients=("claude",))
                             if row["lane"] != "issue_only" or row["repeat"] == 0],
                "engine_sha256": source_hash(study / "engine"), "harness_sha256": harness_hash(study / "harness"),
                "environment": environment_versions(),
                "isolation": "History-free snapshot per instance, fresh copy per trial, read-only tools, project "
                             "guidance only; no hooks, memory, session persistence or other MCP servers",
                "scope": "Development diagnostic of agent file localization; no release claim"}
    manifest["study_id"] = digest(manifest)
    write_json(study / "manifest.json", manifest)
    print(json.dumps({"study": str(study), "study_id": manifest["study_id"], "runs": len(manifest["schedule"])}))


def load(study, live=True):
    """LIVE also checks what a new trial uses: the engine, the client and the installed packages."""
    manifest = json.loads((study / "manifest.json").read_text())
    identity = manifest.pop("study_id")
    if digest(manifest) != identity:
        raise ValueError("Study manifest changed after freezing")
    manifest["study_id"] = identity
    checks = [(harness_hash(HERE), manifest["harness_sha256"], "harness")]
    if live:
        checks += [(source_hash(study / "engine"), manifest["engine_sha256"], "engine"),
                   (client_version(), manifest["client_version"], "client version"),
                   (environment_versions(), manifest["environment"], "runtime or dependency versions")]
    for actual, expected, label in checks:
        if actual != expected:
            raise ValueError(f"Frozen {label} changed; run STUDY/harness or freeze a new study")
    return manifest


def processes(*fragments):
    """Processes, other than this one, whose command line contains one of FRAGMENTS."""
    listing = subprocess.run(["ps", "axww", "-o", "pid=,command="], capture_output=True, text=True, check=True).stdout
    found = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and int(pid) != os.getpid() and any(fragment in command for fragment in fragments):
            found.append((int(pid), command.strip()))
    return found


def sweep(*fragments):
    """Kill every process whose command line names one of FRAGMENTS; fail if one survives.

    Every study process names its folder: the client (--mcp-config), the MCP server
    (--project) and the warm-up worker (--root). This also stops a server that left the
    client's process group, and the orphans of an earlier killed session.
    """
    for _ in range(10):
        found = processes(*fragments)
        if not found:
            return
        for pid, _ in found:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(.5)
    raise RuntimeError(f"Processes survived the sweep: {processes(*fragments)}")


def fragments(study):
    return [f"{study}/{name}/" for name in FOLDERS]


def exclude(root, paths):
    (root / ".git/info").mkdir(exist_ok=True)
    with (root / ".git/info/exclude").open("a") as stream:
        stream.write("".join(path + "\n" for path in paths))


def commit(root):
    """One commit and no history, so that `git log --all` cannot show the fix."""
    git(root, "init", "-q")
    git(root, "add", "-A", "-f")
    git(root, *GIT_USER, "commit", "-q", "--no-verify", "-m", "Frozen benchmark input")
    exclude(root, [".attocode/"])


def hide_setup_files(root):
    """Ignore what the setup wrote (guidance, MCP config), so that only the agent can change `git status`."""
    entries = [entry for entry in git(root, "status", "--porcelain", "-z").split("\0") if entry]
    if any(not entry.startswith("?? ") for entry in entries):
        raise RuntimeError("Setup changed tracked files")
    exclude(root, ["/" + entry[3:] for entry in entries])


def conflict(manifest, study, root):
    """Why the snapshot cannot be used: its own agent guidance would compete with the setups."""
    if next(root.rglob(".claude"), None):
        return "Snapshot contains a .claude folder"
    try:
        configure_setup(manifest, study, root, "native", None, "claude")
    except ValueError as exc:
        return str(exc)
    return None


def warm(study, root, directory, manifest):
    """Index ROOT outside the timed run: one neutral bootstrap, then wait until the indexes are ready.

    The bootstrap barrier waits for the symbol index only. The keyword and body indexes of search
    build in the background and persist in .attocode, so a search waits for them here too. Before,
    the worker stopped first, and on a medium repository the first search of the timed run built
    them and found no index.
    """
    from warm_cache import Worker
    directory.mkdir(parents=True, exist_ok=True)
    started, worker, search = time.monotonic(), None, {}
    try:
        worker = Worker(study, root, directory, 0, WARM_TIMEOUT, script=HERE / "warm_cache.py", env=manifest["server_env"])
        reply = worker.request({"operation": "bootstrap", "arguments": {"task_hint": "", "max_tokens": 1000},
                                "wait_until_ready": True})
        while not reply.get("is_error") and search.get("status", "warming") == "warming":
            if time.monotonic() - started > WARM_TIMEOUT:
                raise TimeoutError("The search indexes did not become ready")
            found = worker.request({"operation": "semantic_search", "arguments": {"query": "index", "top_k": 1}})
            if found.get("is_error"):
                raise RuntimeError(found.get("error") or "The warm-up search failed")
            search = found["payload"]["metadata"]["ranking"]["index"]
            time.sleep(1 if search.get("status") == "warming" else 0)
        worker.close()
    except Exception as exc:
        reply = {"is_error": True, "error": f"{type(exc).__name__}: {exc}"}
        if worker:
            worker.close(force=True)
    coverage = reply.get("ready_coverage") or {}
    return {"ready": not reply.get("is_error") and coverage.get("phase") == "ready" and search.get("status") == "ready",
            "seconds": time.monotonic() - started, "coverage": coverage, "search": search, "error": reply.get("error")}


def prepare_task(study, manifest, clone, task):
    root = study / "sources" / task["id"]
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    # A fetch only reads the source, so a local case-pack clone stays unchanged.
    git(clone, "fetch", "-q", "--depth", "1", task["source"], task["base_commit"], timeout=1800)
    snapshot(clone, root, revision=task["base_commit"])
    reason = conflict(manifest, study, root)
    if not reason:
        commit(root)
        tracked = set(git(root, "ls-files", "-z").split("\0")) - {""}
        if not tracked & set(task["gold"]):
            reason = "No gold file exists in the base tree"
    if reason:
        shutil.rmtree(root)
        return {"status": "excluded", "reason": reason}
    index = warm(study, root, study / "prepare" / task["id"], manifest)
    sweep(f"{study}/sources/")
    return {"status": "ready" if index["ready"] else "excluded",
            "reason": None if index["ready"] else "The index did not become ready",
            "tree_sha256": tree_hash(root), "files": len(tracked),
            "gold_in_tree": len(tracked & set(task["gold"])), "index": index}


def prepare(args):
    """Snapshot every instance (one clone at a time) and build its index. Resumable."""
    study = args.study
    manifest = load(study)
    path = study / "preparation.json"
    prepared = json.loads(path.read_text())["tasks"] if path.exists() else {}
    sweep(*fragments(study))
    groups = {}
    for task in manifest["tasks"]:
        if task["id"] not in prepared:
            groups.setdefault(task["source"], []).append(task)
    for origin in sorted(groups):
        clone = study / "clones" / "current"
        shutil.rmtree(clone, ignore_errors=True)
        clone.mkdir(parents=True)
        try:
            git(clone, "init", "-q")
            for task in groups[origin]:
                prepared[task["id"]] = prepare_task(study, manifest, clone, task)
                write_json(path, {"study_id": manifest["study_id"], "tasks": prepared})
                print(json.dumps({"task": task["id"], "status": prepared[task["id"]]["status"],
                                  "reason": prepared[task["id"]]["reason"]}), flush=True)
        finally:
            shutil.rmtree(clone, ignore_errors=True)
    write_json(path, {"study_id": manifest["study_id"], "tasks": prepared})


def intel_setup(manifest, study, root, stage):
    """Run the frozen installer and pin its MCP entry to the frozen engine and the study server env."""
    configured = configure_setup(manifest, study, root, "intel_installed", stage, "claude")
    for entry in configured["servers"].values():
        entry["env"].update(manifest["server_env"])
    return configured


def wiring_passed(study, manifest):
    path = study / "wiring" / "result.json"
    record = json.loads(path.read_text()) if path.exists() else {}
    return record.get("study_id") == manifest["study_id"] and record.get("passed") is True


def wiring(args):
    """Excluded check with the intel setup: guidance loads, home instructions do not, MCP answers, tools are read-only."""
    study = args.study
    manifest = load(study)
    directory = study / "wiring"
    if not set(INTEL) & set(manifest["setups"]) or wiring_passed(study, manifest):
        print(json.dumps({"wiring": "passed" if wiring_passed(study, manifest) else "not needed"}))
        return
    if directory.exists():
        raise ValueError("Keep the failed or interrupted wiring check; fix the cause and freeze a new study")
    ready(args, "claude")
    root = directory / "repository"
    root.mkdir(parents=True)
    (root / "benchmark_fixture.py").write_text("def benchmark_value():\n    return 42\n")
    commit(root)
    configured = intel_setup(manifest, study, root, directory / "stage")
    token = secrets.token_hex(16)
    guidance = root / GUIDANCE["claude"]
    guidance.write_text(guidance.read_text() + f"\nReadiness token: {token}\n")
    try:
        result = invoke("claude", manifest["model"], root, directory / "stage", configured["servers"], WIRING_PROMPT, 300,
                        subscription_env(), answer_schema=WIRING_SCHEMA, project_guidance=True,
                        tools=next(manifest["tools"][setup] for setup in manifest["setups"] if setup in INTEL))
    finally:
        sweep(f"{directory}/")
    events = (directory / "stage/events.jsonl").read_text()
    parsed = parse_events("claude", events)
    init = next((row["event"] for row in map(json.loads, events.splitlines())
                 if row["event"].get("subtype") == "init"), {})
    outputs = {row["id"]: row for row in parsed["tool_results"] if row["id"]}
    arguments = json.dumps([call["arguments"] for call in parsed["tool_calls"]])
    personal = Path.home() / ".claude/CLAUDE.md"
    lines = [line.strip() for line in personal.read_text().splitlines() if len(line.strip()) >= 20] if personal.is_file() else []
    answer = result["output"]
    checks = {"client": successful(result),
              "guidance_without_reads": answer.get("readiness_token") == token and "CLAUDE.md" not in arguments,
              "no_home_instructions": not any(line in str(answer.get("user_instructions", "")) for line in lines)
              and "/.claude/" not in arguments,
              "mcp_transport": any(call["name"].startswith(f"mcp__{NAME}__") and call["id"] in outputs
                                   and not outputs[call["id"]]["is_error"] for call in parsed["tool_calls"]),
              "read_only_tools": bool(init) and not {"Edit", "Write", "Bash", "NotebookEdit"} & set(init.get("tools", []))}
    record = {"study_id": manifest["study_id"], "excluded": True, "passed": all(checks.values()), "checks": checks,
              "init_tools": init.get("tools"), "mcp_servers": init.get("mcp_servers"), "setup": configured,
              "execution": result}
    write_json(directory / "result.json", record)
    print(json.dumps({"wiring": record["passed"], "checks": checks}), flush=True)
    if not record["passed"]:
        raise RuntimeError("Wiring failed; scored trials cannot start")


def trial(study, manifest, task, row):
    """One timed client run in a fresh copy. The result is the client output, not a grade."""
    directory = run_dir(study, row)
    directory.mkdir(parents=True, mode=0o700)
    root, stage, setup = directory / "repository", directory / "stage-0", row["lane"]
    record = {**row, "study_id": manifest["study_id"], "model": manifest["model"], "config_id": manifest["config_id"],
              "dataset": task["dataset"], "instance_id": task["instance_id"], "workspace": str(root),
              "status": "error", "index_reused": False}
    try:
        started = time.monotonic()
        if setup == "issue_only":
            root.mkdir()
            git(root, "init", "-q")
        else:
            shutil.copytree(study / "sources" / task["id"], root, symlinks=True,
                            ignore=None if setup in INTEL else shutil.ignore_patterns(".attocode"))
        configured = (intel_setup(manifest, study, root, stage) if setup in INTEL else
                      configure_setup(manifest, study, root, "native", stage, "claude"))
        hide_setup_files(root)
        if setup in INTEL:
            record["index_reused"] = (root / ".attocode").is_dir()
            # The copy changed the ctime of every file, so the server would repair the whole
            # index inside the timed run. Repair it here, outside the timed run.
            record["warm"] = warm(study, root, directory / "warm", manifest)
            if not record["warm"]["ready"]:
                raise RuntimeError("The index did not become ready")
        record.update(configured=configured, setup_seconds=time.monotonic() - started)
        write_json(directory / "started.json", {**row, "study_id": manifest["study_id"], "time": time.time()})
        result = invoke("claude", manifest["model"], root, stage, configured["servers"], task["prompts"][setup],
                        manifest["timeout"], subscription_env(), answer_schema=SCHEMA, project_guidance=True,
                        tools=manifest["tools"][setup])
        record.update(stage=result, seconds=result["seconds"], git_status=git(root, "status", "--porcelain"))
        record["status"] = ("failed" if not successful(result) else
                             "protocol_violation" if record["git_status"] else "completed")
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        sweep(f"{directory}/")
        write_json(directory / "result.json", record)
        shutil.rmtree(root, ignore_errors=True)
    return record


def run(args):
    """Run pending trials in schedule order. A result is never replaced; a started trial without one is kept as interrupted."""
    study = args.study
    manifest = load(study)
    preparation = json.loads((study / "preparation.json").read_text())
    if preparation.get("study_id") != manifest["study_id"]:
        raise ValueError("Run prepare for this study first")
    if set(INTEL) & set(manifest["setups"]) and not wiring_passed(study, manifest):
        raise ValueError("Run a passing wiring check first")
    if args.jobs not in (1, 2) or (args.max_runs is not None and args.max_runs < 1):
        raise ValueError("Use --jobs 1 or 2 and a positive --max-runs")
    prepared, tasks = preparation["tasks"], {task["id"]: task for task in manifest["tasks"]}
    sweep(*fragments(study))
    pending = []
    for row in manifest["schedule"]:
        directory = run_dir(study, row)
        if (args.tasks and row["task"] not in args.tasks or prepared.get(row["task"], {}).get("status") != "ready"
                or (directory / "result.json").exists()):
            continue
        if directory.exists():
            write_json(directory / "result.json", {**row, "study_id": manifest["study_id"], "status": "interrupted"})
            continue
        pending.append(row)
    pending = pending[:args.max_runs]
    for name in {row["task"] for row in pending}:
        if tree_hash(study / "sources" / name) != prepared[name]["tree_sha256"]:
            raise ValueError(f"Prepared source changed: {name}")
    deadline = time.monotonic() + args.deadline_minutes * 60
    queue, lock, stop = iter(pending), threading.Lock(), threading.Event()

    def work():
        try:
            while not stop.is_set() and time.monotonic() < deadline:
                with lock:
                    row = next(queue, None)
                if row is None:
                    return
                ready(args, "claude")
                record = trial(study, manifest, tasks[row["task"]], row)
                print(json.dumps({key: record.get(key) for key in ("id", "status", "seconds")}), flush=True)
                if record.get("stage", {}).get("quota_exhausted"):
                    stop.set()
        except BaseException:
            stop.set()
            raise

    with ThreadPoolExecutor(args.jobs) as pool:
        for future in [pool.submit(work) for _ in range(args.jobs)]:
            future.result()
    sweep(*fragments(study))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text_of(item.get("text", item) if isinstance(item, dict) else item) for item in content)
    return json.dumps(content, ensure_ascii=False)


def clean_paths(paths, root=""):
    """Repository-relative answer paths: strip the workspace root, "./" and ":line"; dedupe; keep 10."""
    prefix = root.rstrip("/") + "/" if root else None
    cleaned = []
    for path in paths:
        path = path.strip().replace("\\", "/")
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        path = re.sub(r"(:\d+([-:]\d+)*)+$", "", path)
        while path.startswith("./"):
            path = path[2:]
        if path and path not in cleaned:
            cleaned.append(path)
    return cleaned[:10]


def gold_seen(results, gold):
    """Client seconds at the first tool result that names a gold file."""
    patterns = [re.compile(r"(?<![\w.-])" + re.escape(path) + r"(?![\w-]|\.\w)") for path in gold]
    for row in sorted(results, key=lambda row: row["event_index"]):
        if row["received_seconds"] is not None and any(p.search(text_of(row["content"])) for p in patterns):
            return row["received_seconds"]
    return None


def failure(record):
    stage = record.get("stage") or {}
    return next((key for key in ("timed_out", "quota_exhausted", "permission_denials", "terminal_error", "exit_code")
                 if stage.get(key)), record.get("status"))


def grade(study, manifest, task, record, metrics, tracked):
    """Score one run. A failed run scores 0 and takes the full timeout."""
    stage = record.get("stage") or {}
    failed = record.get("status") != "completed"
    answer = stage.get("output", {}).get("files")
    parsed = isinstance(answer, list) and all(isinstance(path, str) for path in answer)
    files = clean_paths(answer if parsed else [], record.get("workspace", ""))
    ranked, gold = [] if failed else files, set(task["gold"])
    events = run_dir(study, record) / "stage-0/events.jsonl"
    trace = parse_events("claude", events.read_text()) if events.exists() else {"tool_calls": [], "tool_results": []}
    mcp = {call["id"] for call in trace["tool_calls"] if call["name"].startswith("mcp__")}
    usage = stage.get("usage") or {}
    return {"dataset": task["dataset"], "instance_id": task["instance_id"], "config_id": manifest["config_id"],
            "task": task["id"], "setup": record["lane"], "trial": record["repeat"], "id": record["id"],
            "model": manifest["model"], "status": record.get("status"), "failed": failed,
            "failure": failure(record) if failed else None, "answer_parsed": parsed, "files": files,
            "invalid_paths": None if tracked is None else sum(path not in tracked for path in files),
            "acc1": metrics.compute_acc_at_k(ranked, gold, 1), "acc5": metrics.compute_acc_at_k(ranked, gold, 5),
            "acc10": metrics.compute_acc_at_k(ranked, gold, 10), "recall10": metrics.compute_recall_at_k(ranked, gold, 10),
            "mrr5": metrics.compute_mrr(ranked, gold, 5),
            "seconds": manifest["timeout"] if failed else stage.get("seconds"), "turns": stage.get("turns"),
            "cost_usd": stage.get("cost_usd"), "tokens": {key: usage.get(key) for key in TOKENS},
            "tool_calls": dict(Counter(call["name"] for call in trace["tool_calls"])), "mcp_calls": len(mcp),
            "mcp_warming_results": sum('"status":"warming"' in text_of(row["content"])
                                       for row in trace["tool_results"] if row["id"] in mcp),
            "gold_seen_s": gold_seen(trace["tool_results"], gold), "index_reused": record.get("index_reused"),
            "events": str(events.relative_to(study))}


def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def show(value, digits=2):
    return "–" if value is None else f"{value:.{digits}f}"


def summary(args):
    """Grade every recorded run: runs.jsonl, summary.md and review.md."""
    study = args.study
    manifest = load(study, live=False)
    sys.path.append(manifest["project"])
    from eval import metrics
    metrics_sha = hashlib.sha256(Path(metrics.__file__).read_bytes()).hexdigest()
    path = study / "preparation.json"
    prepared = json.loads(path.read_text())["tasks"] if path.exists() else {}
    tasks, tracked, rows = {task["id"]: task for task in manifest["tasks"]}, {}, []
    for entry in manifest["schedule"]:
        result = run_dir(study, entry) / "result.json"
        if not result.exists():
            continue
        record = json.loads(result.read_text())
        if any(record.get(key) != value for key, value in entry.items()) or record.get("study_id") != manifest["study_id"]:
            raise ValueError(f"Result does not match the frozen schedule: {entry['id']}")
        source = study / "sources" / entry["task"]
        if entry["task"] not in tracked:
            tracked[entry["task"]] = set(git(source, "ls-files", "-z").split("\0")) - {""} if source.is_dir() else None
        rows.append(grade(study, manifest, tasks[entry["task"]], record, metrics, tracked[entry["task"]]))
    with (study / "runs.jsonl").open("w") as stream:
        stream.writelines(json.dumps({**row, "metrics_sha256": metrics_sha}) + "\n" for row in rows)
    excluded = {name: state["reason"] for name, state in prepared.items() if state.get("status") != "ready"}
    lines = ["# Localize study summary", "",
             f"Study `{manifest['study_id'][:12]}`. Model `{manifest['model']}`, config `{manifest['config_id']}`, "
             f"{manifest['trials']} trial(s) per task and setup. Recorded runs: {len(rows)} of {len(manifest['schedule'])} "
             f"scheduled. Excluded tasks: {len(excluded)}.",
             f"Metrics: `{metrics.__file__}` (sha256 `{metrics_sha[:12]}`). A failed run scores 0, takes the "
             f"{manifest['timeout']} s timeout and the worst cost of its setup.",
             "pass@k: share of tasks with an Acc@5 hit in any of their k trials. pass^k: in all k trials.", "",
             "| Setup | Runs | Tasks | Acc@5 | pass@k | pass^k | Median cost (USD) | Median seconds | Median turns "
             "| MCP adoption | Failures |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for setup in manifest["setups"]:
        selected = [row for row in rows if row["setup"] == setup]
        if not selected:
            continue
        hits = {}
        for row in selected:
            hits.setdefault(row["task"], []).append(row["acc5"] == 1)
        worst = max((row["cost_usd"] for row in selected if row["cost_usd"] is not None), default=None)
        lines.append(f"| {setup} | {len(selected)} | {len(hits)} | {show(statistics.fmean(r['acc5'] for r in selected))} | "
                     f"{show(statistics.fmean(any(v) for v in hits.values()))} | "
                     f"{show(statistics.fmean(all(v) for v in hits.values()))} | "
                     f"{show(median([worst if r['failed'] else r['cost_usd'] for r in selected]), 4)} | "
                     f"{show(median([r['seconds'] for r in selected]), 1)} | {show(median([r['turns'] for r in selected]), 0)} | "
                     f"{sum(r['mcp_calls'] > 0 for r in selected)}/{len(selected)} | {sum(r['failed'] for r in selected)} |")
    lines += ["", *[f"- Excluded `{name}`: {reason}" for name, reason in sorted(excluded.items())]]
    (study / "summary.md").write_text("\n".join(lines) + "\n")
    review(study, manifest, rows)
    print(json.dumps({"runs": len(rows), "scheduled": len(manifest["schedule"]), "excluded": len(excluded),
                      "metrics_sha256": metrics_sha}), flush=True)


def review(study, manifest, rows):
    """Material for a human pass: discordant pairs, failures and five random runs."""
    keyed = {(row["task"], row["trial"], row["setup"]): row for row in rows}
    lines = ["# Localize study review", "", "## Discordant pairs (Acc@5 against native)", "",
             "| Task | Trial | Setup | Native | Setup Acc@5 | Native events | Setup events |", "|---|---:|---|---:|---:|---|---|"]
    for (name, number, setup), row in sorted(keyed.items()):
        native = keyed.get((name, number, "native"))
        if setup != "native" and native and native["acc5"] != row["acc5"]:
            lines.append(f"| {name} | {number} | {setup} | {native['acc5']:.0f} | {row['acc5']:.0f} | "
                         f"{native['events']} | {row['events']} |")
    lines += ["", "## Failures", ""]
    lines += [f"- `{row['id']}`: {row['failure']}. Events: {row['events']}" for row in rows if row["failed"]] or ["None."]
    lines += ["", "## Five random runs", ""]
    for row in random.Random(manifest["seed"]).sample(rows, min(5, len(rows))):
        lines.append(f"- `{row['id']}`: Acc@5 {row['acc5']:.0f}, files {row['files']}, "
                     f"MCP calls {row['mcp_calls']}. Events: {row['events']}")
    (study / "review.md").write_text("\n".join(lines) + "\n")
