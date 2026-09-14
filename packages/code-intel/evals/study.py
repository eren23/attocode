"""Freeze, prepare and resume paired real-client evaluations outside the repository."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from study_clients import CLIENTS, invoke, preflight, subscription_env
from study_tasks import TASKS, acceptance, evidence, inject, prompt
from workflows import SCENARIOS, engine_fingerprint, snapshot

LANES = ("native", "intel_base", "intel_precision", "serena")
PILOT_LANES = (*LANES, "previous_base", "previous_precision")


def design(mode):
    if mode in {"quality", "onboarding"}:
        from quality_tasks import TASKS as QUALITY_TASKS
        if mode == "onboarding":
            from onboarding_study import LANES as ONBOARDING_LANES
            from onboarding_study import TASK_IDS
            return [t for t in QUALITY_TASKS if t["id"] in TASK_IDS], 1, ONBOARDING_LANES
        return QUALITY_TASKS, 3, LANES
    tasks = [task for task in TASKS if mode != "pilot" or task["id"] == "express:lookup"]
    return tasks, 3 if mode == "pilot" else 5, PILOT_LANES if mode == "pilot" else LANES


def source_hash(root):
    engine = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        engine.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return engine.hexdigest()


def selected_repos(manifest):
    names = {task["repo"] for task in manifest["tasks"]}
    return [spec for spec in SCENARIOS if spec["repo"] in names]


def environment_versions():
    result = {"python": sys.version, "packages": sorted(
        [dist.metadata.get("Name", ""), dist.version] for dist in importlib.metadata.distributions())}
    for tool in ("node", "npm", "cargo"):
        try:
            result[tool] = subprocess.check_output([tool, "--version"], text=True, timeout=20).strip()
        except (OSError, subprocess.SubprocessError):
            result[tool] = "unavailable"
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def schedule(tasks, repetitions=5, seed=7329, lanes=LANES, clients=CLIENTS):
    rng = random.Random(seed)
    pairs = [(task, client, repeat) for task in tasks for client in clients for repeat in range(repetitions)]
    rng.shuffle(pairs)
    rows = []
    for task, client, repeat in pairs:
        order = list(lanes)
        rng.shuffle(order)
        for lane in order:
            rows.append({"id": f"{task['id']}:{client}:{repeat}:{lane}", "task": task["id"],
                         "client": client, "repeat": repeat, "lane": lane})
    return rows


def freeze(args):
    if args.study.resolve().is_relative_to(args.project.resolve()):
        raise ValueError("Study artifacts must be outside the source repository")
    if args.study.exists():
        raise ValueError("Study directory already exists; use a new directory for a new candidate")
    mode = getattr(args, "mode", "release")
    baseline = getattr(args, "baseline_src", None)
    if mode == "pilot" and (not baseline or not (baseline / "attocode_intel/entrypoint.py").is_file()):
        raise ValueError("Pilot mode requires --baseline-src containing attocode_intel/entrypoint.py")
    if mode != "pilot" and baseline:
        raise ValueError("--baseline-src is only used by pilot mode")
    selected, repetitions, lanes = design(mode)
    models = json.loads(args.models.read_text())
    if set(models) != set(CLIENTS) or not all(isinstance(v, str) and v for v in models.values()):
        raise ValueError("Supply one explicit model ID for codex, claude and cursor")
    launcher = json.loads(args.serena_launcher.read_text()) if args.serena_launcher else {}
    if mode != "onboarding" and not any("@" in str(arg) and len(str(arg).rsplit("@", 1)[-1]) == 40 for arg in launcher.get("args", [])):
        raise ValueError("Serena launcher must pin a full source revision")
    args.study.mkdir(parents=True, mode=0o700)
    versions = {}
    for client in CLIENTS:
        command = ["cursor", "agent", "--version"] if client == "cursor" else [client, "--version"]
        try:
            versions[client] = subprocess.check_output(command, text=True, timeout=20).strip()
        except (OSError, subprocess.SubprocessError):
            versions[client] = "unavailable"
    shutil.copytree(args.project / "packages/code-intel/src", args.study / "engine",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if baseline:
        shutil.copytree(baseline, args.study / "previous-engine",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(Path(__file__).parent, args.study / "harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    revisions = {}
    for spec in selected_repos({"tasks": selected}):
        source = args.project if spec["repo"] == "frontend" else args.repo_dir / spec["repo"]
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        revisions[spec["repo"]] = revision
        destination = args.study / "sources" / spec["repo"]
        destination.mkdir(parents=True)
        root = snapshot(source, destination, spec["repo"] == "frontend", revision)
        if root != destination:
            for path in root.iterdir():
                path.rename(destination / path.name)
            root.rmdir()
        if spec["repo"] in {"express", "frontend"} and not (destination / "package-lock.json").exists():
            subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
                           cwd=destination, check=True, stdout=subprocess.DEVNULL)
    if mode in {"quality", "onboarding"}:
        from quality_tasks import compile_task, materialize, source_files
        from quality_tasks import prompt as quality_prompt
        tasks = []
        for task in selected:
            with tempfile.TemporaryDirectory(prefix="intel-quality-rubric-") as temp:
                root = Path(temp)
                for name in source_files(args.study / "sources" / task["repo"], task):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(args.study / "sources" / task["repo"] / name, target)
                materialize(root, task)
                compiled = compile_task(root, task)
                tasks.append({**compiled, "prompts": [quality_prompt(compiled)]})
    else:
        tasks = [{**task, "prompts": [prompt(task, stage) for stage in range(2 if task["family"] == "returning" else 1)]}
                 for task in selected]
    active_clients = ("codex", "claude") if mode == "onboarding" else CLIENTS
    manifest = {"version": 2, "mode": mode, "engine_sha256": engine_fingerprint(args.project), "models": models,
                "client_versions": versions, "revisions": revisions, "serena": launcher,
                "python": str(Path(sys.executable).absolute()), "tasks": tasks,
                "repetitions": repetitions, "seed": 7329, "timeout": 600, "lanes": lanes,
                "selection": "natural", "schedule": schedule(tasks, repetitions, lanes=lanes, clients=active_clients),
                "harness_sha256": harness_hash(args.study / "harness")}
    if mode == "onboarding":
        manifest["onboarding"] = {"clients": active_clients, "precision": "off", "cache_state": "fresh_repository",
                                  "scope": "Installed project guidance diagnostic; one repetition; no competitor or release claim",
                                  "comparisons": [["intel_installed", "intel_available"],
                                                  ["intel_available", "native"], ["intel_installed", "native"]]}
    if baseline:
        manifest["previous_engine_sha256"] = source_hash(args.study / "previous-engine")
    manifest["environment"] = environment_versions()
    manifest["source_hashes"] = {spec["repo"]: tree_hash(args.study / "sources" / spec["repo"]) for spec in selected_repos(manifest)}
    manifest["study_id"] = digest(manifest)
    write_json(args.study / "manifest.json", manifest)
    print(json.dumps({"study": str(args.study), "study_id": manifest["study_id"], "runs": len(manifest["schedule"])}))


def harness_hash(path):
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.glob("*.py"))})


def tree_hash(root):
    hashes = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {"node_modules", "target", "__pycache__", ".attocode", ".serena", ".git"})
        for name in sorted(files):
            if not name.endswith(".pyc"):
                path = Path(directory) / name
                hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(hashes)


def manifest_for(study):
    manifest = json.loads((study / "manifest.json").read_text())
    original = manifest.pop("study_id")
    if digest(manifest) != original:
        raise ValueError("Study manifest changed after freezing")
    manifest["study_id"] = original
    if environment_versions() != manifest["environment"]:
        raise ValueError("Runtime or dependency versions changed; freeze a new study")
    for client, expected in manifest["client_versions"].items():
        command = ["cursor", "agent", "--version"] if client == "cursor" else [client, "--version"]
        try:
            actual = subprocess.check_output(command, text=True, timeout=20).strip()
        except (OSError, subprocess.SubprocessError):
            actual = "unavailable"
        if actual != expected:
            raise ValueError(f"Client version changed: {client}; freeze a new study")
    if harness_hash(Path(__file__).parent) != manifest["harness_sha256"]:
        raise ValueError("Run the frozen harness in STUDY/harness; this harness differs from the manifest")
    if source_hash(study / "engine") != manifest["engine_sha256"]:
        raise ValueError("Frozen engine changed")
    if manifest.get("mode") == "pilot" and source_hash(study / "previous-engine") != manifest.get("previous_engine_sha256"):
        raise ValueError("Frozen previous engine changed")
    for repo, expected in manifest["source_hashes"].items():
        if tree_hash(study / "sources" / repo) != expected:
            raise ValueError(f"Frozen repository changed: {repo}")
    return manifest


def prepare(args):
    manifest = manifest_for(args.study)
    report = {}
    env = subscription_env()
    for spec in selected_repos(manifest):
        root = args.study / "sources" / spec["repo"]
        if spec["repo"] in {"frontend", "express"}:
            subprocess.run(["npm", "ci", "--ignore-scripts"], cwd=root, env=env, check=True, stdout=subprocess.DEVNULL)
        elif spec["repo"] == "ripgrep":
            subprocess.run(["cargo", "fetch", "--locked"], cwd=root, env=env, check=True, stdout=subprocess.DEVNULL)
        task = {**spec, "id": spec["repo"] + ":change", "family": "change"}
        from study_tasks import FAULTS
        source = root / FAULTS[spec["repo"]][0]
        original = source.read_bytes()
        try:
            good = acceptance(root, task, manifest["python"], env)
            inject(root, task)
            bad = acceptance(root, task, manifest["python"], env)
        finally:
            source.write_bytes(original)
            (root / "crates/ignore/tests/intelligence_acceptance.rs").unlink(missing_ok=True)
        report[spec["repo"]] = {"clean_passes": good["passed"], "fault_detected": not bad["passed"],
                                "clean": good, "fault": bad}
        if manifest.get("mode") in {"quality", "onboarding"} and spec["repo"] == "express":
            from quality_tasks import verify_counterfactual
            report["quality_counterfactual"] = verify_counterfactual(root)
        if spec["repo"] == "fastapi" and any(t.get("discovery") for t in manifest["tasks"]):
            from quality_tasks import verify_discovery
            report["quality_discovery"] = verify_discovery(root, manifest["python"], env)
        write_json(args.study / "preparation.json", report)
        print(json.dumps({"repo": spec["repo"], "ready": good["passed"] and not bad["passed"]}), flush=True)


def servers_for(manifest, study, root, lane, stage_dir, client):
    if lane.startswith(("intel", "previous")):
        engine = "previous-engine" if lane.startswith("previous") else "engine"
        return {"intelligence": {"command": manifest["python"], "args": ["-m", "attocode_intel.entrypoint",
                    "--project", str(root), "--profile", "daily"],
                "env": {"PYTHONPATH": str(study / engine), "ATTOCODE_INTEL_PRECISION": "off" if lane.endswith("_base") else "auto",
                        "ATTOCODE_INTEL_TRACE": str(stage_dir / "engine.jsonl")}}}
    if lane == "serena":
        launcher = json.loads(json.dumps(manifest["serena"]))
        # Match the officially supplied client context when one is present.
        if "--context" in launcher["args"]:
            launcher["args"][launcher["args"].index("--context") + 1] = "codex" if client == "codex" else "claude-code" if client == "claude" else "ide"
        launcher["args"] += ["--project", str(root)]
        return {"serena": launcher}
    return {}


def run(args):
    manifest = manifest_for(args.study)
    preparation = json.loads((args.study / "preparation.json").read_text())
    if any(not preparation.get(s["repo"], {}).get("clean_passes") or not preparation[s["repo"]].get("fault_detected") for s in selected_repos(manifest)):
        raise ValueError("Prepare all repositories and verify clean/fault acceptance first")
    if manifest.get("mode") in {"quality", "onboarding"} and not preparation.get("quality_counterfactual", {}).get("passed"):
        raise ValueError("Verify the quality counterfactual and negative control before scoring")
    if any(t.get("discovery") for t in manifest["tasks"]) and not preparation.get("quality_discovery", {}).get("passed"):
        raise ValueError("Verify dependency discovery behavior and fault controls before scoring")
    tasks = {task["id"]: task for task in manifest["tasks"]}
    env = subscription_env()
    completed = 0
    maximum = args.max_runs if args.max_runs is not None else (6 if manifest.get("mode") in {"pilot", "quality"} else 12)
    if maximum < 1:
        raise ValueError("--max-runs must be positive")
    for row in manifest["schedule"]:
        if args.clients and row["client"] not in args.clients:
            continue
        if args.tasks and row["task"] not in args.tasks:
            continue
        directory = args.study / "runs" / row["id"].replace(":", "-")
        if (directory / "result.json").exists():
            continue
        if (directory / "started.json").exists():
            # Do not silently discard an interrupted, potentially unfavorable attempt.
            write_json(directory / "result.json", {**row, "status": "interrupted", "passed": False,
                                                    "seconds": manifest["timeout"], "study_id": manifest["study_id"],
                                                    "model": manifest["models"][row["client"]]})
            continue
        quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
        status = preflight(row["client"], quota, env)
        if not status["ready"]:
            print(json.dumps({"client": row["client"], "blocked": status}), flush=True)
            return
        if manifest.get("mode") in {"pilot", "quality", "onboarding"}:
            from pilot import wiring_ready
            if manifest.get("mode") == "onboarding":
                from onboarding_study import wiring_ready
            if not wiring_ready(args.study, manifest, row["client"]):
                print(json.dumps({"client": row["client"], "blocked": "Run a successful excluded wiring check before scoring"}), flush=True)
                return
        directory.mkdir(parents=True, mode=0o700)
        task = tasks[row["task"]]
        root = directory / "repository"
        setup = time.monotonic()
        shutil.copytree(args.study / "sources" / task["repo"], root,
                        ignore=shutil.ignore_patterns(".attocode", ".serena", "__pycache__", "target", "node_modules"))
        modules = args.study / "sources" / task["repo"] / "node_modules"
        if modules.exists():
            shutil.copytree(modules, root / "node_modules")
        if task["family"] == "quality":
            from quality_tasks import materialize
            materialize(root, task)
        onboarding = None
        if manifest.get("mode") == "onboarding":
            from onboarding_study import configure_setup
            onboarding = configure_setup(manifest, args.study, root, row["lane"], directory / "stage-0", row["client"])
            write_json(directory / "onboarding.json", onboarding)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Intelligence evaluation", "-c", "user.email=eval@localhost",
                        "commit", "-qm", "Frozen benchmark input"], cwd=root, check=True)
        setup_seconds = time.monotonic() - setup
        if task["family"] == "change":
            inject(root, task)
        write_json(directory / "started.json", {**row, "time": time.time(), "study_id": manifest["study_id"]})
        stages = []
        try:
            for stage, text in enumerate(task["prompts"]):
                if stage:
                    inject(root, task)
                    quota = json.loads(args.quota.read_text())
                    if not preflight(row["client"], quota, env)["ready"]:
                        raise RuntimeError("Subscription quota could not be verified for returning session")
                stage_dir = directory / f"stage-{stage}"
                stage_dir.mkdir()
                servers = onboarding["servers"] if onboarding else servers_for(manifest, args.study, root, row["lane"], stage_dir, row["client"])
                options = {"project_guidance": True} if onboarding else {}
                if task["family"] == "quality":
                    from quality_scoring import ANSWER_SCHEMA, failed_grade, grade
                    options["answer_schema"] = ANSWER_SCHEMA
                result = invoke(row["client"], manifest["models"][row["client"]], root, stage_dir, servers,
                                text, manifest["timeout"], env, **options)
                if task["family"] == "quality":
                    quality = grade(root, task, result["output"])
                    if (result["exit_code"] or result["timed_out"] or result["quota_exhausted"]
                            or result.get("terminal_error") or result["permission_denials"]):
                        quality = failed_grade("Client did not complete successfully")
                    result["evidence"] = {"quality_criteria": quality["automated_pass"]}
                else:
                    result["evidence"] = evidence(root, task, result["output"])
                stages.append(result)
                if result["quota_exhausted"] or result["timed_out"] or result["exit_code"]:
                    break
            grade_start = time.monotonic()
            patch = subprocess.check_output(["git", "diff", "--no-ext-diff", "--binary"], cwd=root)
            (directory / "change.diff").write_bytes(patch)
            check = acceptance(root, task, manifest["python"], env) if task["family"] in {"change", "returning"} else {"passed": True}
            if task["family"] == "quality" and patch:
                quality = failed_grade("Analysis-only trial modified tracked source")
                check = {"passed": False}
            grade_seconds = time.monotonic() - grade_start
            passed = (len(stages) == len(task["prompts"]) and check["passed"] and
                      all(not s["exit_code"] and not s["timed_out"] and not s.get("terminal_error")
                          and not s["permission_denials"] and all(s["evidence"].values()) for s in stages))
            result = {**row, "study_id": manifest["study_id"], "status": "completed", "passed": passed,
                      "seconds": sum(s["seconds"] for s in stages) + grade_seconds,
                      "setup_seconds": setup_seconds, "acceptance_seconds": grade_seconds, "acceptance": check,
                      "model": manifest["models"][row["client"]], "stages": stages}
            result["patch_sha256"] = hashlib.sha256(patch).hexdigest()
            if task["family"] == "quality":
                result["quality"] = quality
            if onboarding:
                result["onboarding"] = onboarding
        except Exception as exc:
            result = {**row, "study_id": manifest["study_id"], "status": "failed", "passed": False,
                      "seconds": max(manifest["timeout"], sum(s["seconds"] for s in stages)),
                      "model": manifest["models"][row["client"]], "error": str(exc), "stages": stages}
        write_json(directory / "result.json", result)
        print(json.dumps({key: result[key] for key in ("id", "passed", "seconds", "status")}), flush=True)
        completed += 1
        if any(s.get("quota_exhausted") for s in stages) or completed >= maximum:
            break


def report(args):
    manifest = manifest_for(args.study)
    rows = [json.loads(p.read_text()) for p in sorted((args.study / "runs").glob("*/result.json"))]
    report = {"manifest": manifest, "runs": rows}
    volume = args.study / "client-response-volume.json"
    if volume.exists():
        report["response_volume"] = json.loads(volume.read_text())
    if manifest.get("mode") == "pilot":
        from pilot import summarize, write_review
        report["pilot"] = summarize(manifest, rows)
        write_review(args.study, report)
    elif manifest.get("mode") in {"quality", "onboarding"}:
        from quality_scoring import summarize, write_review
        report["quality"] = summarize(manifest, rows)
        write_review(args.study, report)
        if manifest.get("mode") == "onboarding":
            from onboarding_study import summarize as summarize_onboarding
            report["onboarding"] = summarize_onboarding(manifest, rows)
    write_json(args.study / "report.json", report)
    print(json.dumps({"report": str(args.study / "report.json"), "completed": len(rows), "required": len(manifest["schedule"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[3])
    freezing.add_argument("--repo-dir", type=Path, required=True)
    freezing.add_argument("--models", type=Path, required=True)
    freezing.add_argument("--serena-launcher", type=Path)
    freezing.add_argument("--mode", choices=("release", "pilot", "quality", "onboarding", "understanding", "external"), default="release")
    freezing.add_argument("--baseline-src", type=Path)
    freezing.add_argument("--case-pack", type=Path, help="Private understanding case-pack directory")
    freezing.add_argument("--benchmark-pack", type=Path, help="Prepared external benchmark pack, outside the repository")
    for name in ("prepare", "run", "report", "wiring"):
        sub = commands.add_parser(name)
        if name in {"run", "wiring"}:
            sub.add_argument("--quota", type=Path)
            sub.add_argument("--clients", nargs="+", choices=CLIENTS)
        if name == "run":
            sub.add_argument("--max-runs", type=int, help="Batch limit (pilot/quality: 6; release: 12)")
            sub.add_argument("--tasks", nargs="+")
    for sub in commands.choices.values():
        sub.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    args.study = args.study.resolve()
    mode = args.mode if args.command == "freeze" else json.loads((args.study / "manifest.json").read_text()).get("mode")
    if mode in {"understanding", "external"}:
        import importlib
        runner = importlib.import_module("external_study" if mode == "external" else "understanding_study")
        getattr(runner, args.command)(args)
        sys.exit(0)
    if args.command == "wiring":
        from pilot import wiring
        if json.loads((args.study / "manifest.json").read_text()).get("mode") == "onboarding":
            from onboarding_study import wiring
        wiring(args)
    else:
        {"freeze": freeze, "prepare": prepare, "run": run, "report": report}[args.command](args)
