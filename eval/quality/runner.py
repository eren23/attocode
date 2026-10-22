"""One supervised workspace for test outputs, caches and disposable inputs."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil
from filelock import FileLock

REPO = Path(__file__).resolve().parents[2]
GIB = 1024**3
MARKER = "attocode-quality-v1"
LIMITS = {"quick": 120, "local": 600, "broad": 3600}
QUICK_TESTS = ["test_search_evidence.py", "test_focused_inspection.py", "test_language_capabilities.py",
               "test_quality_runner.py", "test_quality_cloud.py", "test_quality_lifecycle.py", "test_quality_evidence.py",
               "test_experiment_evidence.py"]
LOCAL_TESTS = QUICK_TESTS + ["test_trigram_workspace.py", "test_change_focus.py", "test_change_investigation.py", "test_behavioral_negation.py", "test_chunk_identity.py", "test_query_requirements.py", "test_mcp_search_evaluation.py", "test_product.py", "test_query_ranking.py", "test_ranking_intent.py",
                           "test_compact_inspection.py", "test_lean_profile.py", "test_daily_workflows.py",
                           "test_index_reuse.py", "test_edit_restart.py", "test_navigation_evidence.py",
                           "test_cold_index_cost.py", "test_structural_write_cost.py", "test_lexical_sql_cost.py", "test_index_probe.py", "test_discovery_reuse.py", "test_ast_snapshot.py",
                           "test_index_sequences.py", "test_mixed_workspace.py", "test_index_processes.py",
                           "test_file_symbol_scope.py", "test_retrieval_audit.py",
                           "test_importance_publication.py", "test_retrieval_ablation.py", "test_retrieval_cycle.py", "test_lsp_document_lifecycle.py", "test_retrieval_body_trial.py",
                           "test_structural_evidence.py", "test_search_evidence_audit.py", "test_remote.py", "test_db_navigation_http.py",
                           "test_module_ownership.py", "test_real_language_server.py", "test_precision_protocol.py",
                           "test_source_exclusions.py", "test_operation_contracts.py", "test_navigation_prefix_trial.py", "test_kotlin_test_paths.py", "test_precision_recovery.py", "test_workflow_sequences.py", "test_test_intent_trial.py"]
LINT_PATHS = ["eval/quality", "packages/code-intel/tests/test_trigram_workspace.py", "packages/code-intel/tests/test_change_focus.py", "packages/code-intel/tests/test_change_investigation.py", "packages/code-intel/tests/test_behavioral_negation.py", "packages/code-intel/tests/test_chunk_identity.py", "packages/code-intel/tests/test_query_requirements.py", "packages/code-intel/tests/test_mcp_search_evaluation.py", *["packages/code-intel/src/attocode_intel/" + p for p in (
    "tools/search_tools.py", "change_evidence.py", "change_investigation.py", "investigation_cli.py", "focused_evidence.py", "test_ranking.py", "tools/composite_tools.py", "search_evidence.py", "symbol_links.py", "output.py", "query_ranking.py", "gateway.py",
    "api/models.py", "api/providers/db_provider.py",
    "indexing/full_indexer.py", "indexing/incremental.py", "indexing/parser.py", "storage/symbol_store.py",
    "freshness.py", "_internal/integrations/context/codebase_context.py",
    "_internal/integrations/context/semantic_search.py",
    "_internal/integrations/context/index_probe.py",
    "_internal/integrations/context/discovery_snapshot.py",
    "_internal/integrations/context/ast_snapshot.py",
    "_internal/integrations/context/ts_parser.py", "_internal/integrations/context/codebase_ast.py",
    "_internal/integrations/context/syntax_evidence.py",
    "_internal/integrations/context/language_registry.py", "_internal/integrations/context/module_resolution.py",
    "_internal/integrations/context/index_store.py", "_internal/integrations/context/cross_references.py",
    "_internal/integrations/context/index_repair.py", "_internal/integrations/context/ast_service.py",
    "precision.py", "_internal/integrations/lsp/client.py", "_internal/integrations/utilities/ignore.py")],
    *["packages/code-intel/tests/" + p for p in QUICK_TESTS],
    "packages/code-intel/tests/test_search_evidence_audit.py",
    "packages/code-intel/tests/test_db_navigation_http.py",
    *["packages/code-intel/tests/" + p for p in (
        "test_index_sequences.py", "test_mixed_workspace.py", "test_index_processes.py",
        "test_file_symbol_scope.py", "test_retrieval_audit.py",
        "test_importance_publication.py", "test_retrieval_ablation.py", "test_retrieval_cycle.py", "test_lsp_document_lifecycle.py", "test_retrieval_body_trial.py",
        "test_module_ownership.py", "test_real_language_server.py", "test_source_exclusions.py",
        "test_operation_contracts.py", "test_navigation_prefix_trial.py", "test_kotlin_test_paths.py", "test_precision_recovery.py", "test_workflow_sequences.py", "test_test_intent_trial.py", "test_structural_write_cost.py", "test_lexical_sql_cost.py", "test_index_probe.py", "test_discovery_reuse.py", "test_ast_snapshot.py")]]


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fingerprint(paths):
    digest = hashlib.sha256()
    for base in paths:
        files = sorted(base.rglob("*")) if base.is_dir() else [base]
        for path in files:
            if (path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
                    and path.suffix in {".py", ".toml", ".yaml", ".json", ".jsonl", ".lock"}):
                digest.update(str(path.relative_to(REPO)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def disk_bytes(root):
    """Count logical and allocated bytes conservatively; never follow links."""
    total = 0
    for directory, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                stat = (Path(directory) / name).lstat()
                total += max(stat.st_size, getattr(stat, "st_blocks", 0) * 512)
            except FileNotFoundError:
                pass
    return total


def managed_root(root):
    root = Path(root).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("Managed root must not pass through symlinks")
    marker = root / ".owner"
    if marker.is_symlink():
        raise ValueError("Ownership marker must not be a symlink")
    if root.exists() and any(root.iterdir()) and not marker.exists():
        raise ValueError("Refusing to adopt a nonempty unowned directory")
    root.mkdir(parents=True, exist_ok=True)
    if marker.exists() and marker.read_text() != MARKER:
        raise ValueError("Unknown workspace ownership marker")
    marker.write_text(MARKER)
    for name in ("runs", "cache", "work"):
        child = root / name
        if child.is_symlink():
            raise ValueError("Managed directories must not be symlinks")
        child.mkdir(exist_ok=True)
    return root


def environment(root):
    env = os.environ.copy()
    env.update({"TMPDIR": str(root / "work"), "TMP": str(root / "work"), "TEMP": str(root / "work"),
                "UV_CACHE_DIR": str(root / "cache" / "uv"), "XDG_CACHE_HOME": str(root / "cache"),
                "HF_HOME": str(root / "cache" / "hf"), "PYTHONDONTWRITEBYTECODE": "1",
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ATTOCODE_LOCAL_ONLY": "1",
                "ATTOCODE_INTEL_PRECISION": "off", "ATTOCODE_INTEL_BROAD_RERANK": "0",
                "ATTOCODE_INTEL_RANKING_PROVIDER": "off", "ATTOCODE_INTEL_RANKING_ALLOW_REMOTE": "0",
                "ATTOCODE_INTEL_RERANKER_PATH": "", "ATTOCODE_INTEL_RERANKER_SHA256": "",
                "ATTOCODE_EMBEDDING_MODEL": "", "ATTOCODE_NL_EMBEDDING_MODE": "none"})
    # A test subprocess does not need provider or infrastructure credentials.
    for name in list(env):
        if name.endswith(("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "SECRET_ACCESS_KEY")) or name in {"GITHUB_TOKEN", "GH_TOKEN", "QUALITY_DIGITALOCEAN_TOKEN"}:
            env.pop(name)
    return env


def stop_group(process):
    for sig, wait in ((signal.SIGTERM, .3), (signal.SIGKILL, .1)):
        try:
            os.killpg(process.pid, sig)
        except PermissionError:
            # Some macOS execution sandboxes permit signalling owned PIDs but
            # prohibit process-group signals. Resolve the owned descendants.
            try:
                parent = psutil.Process(process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.send_signal(sig)
                    except psutil.NoSuchProcess:
                        pass
                process.send_signal(sig)
            except psutil.NoSuchProcess:
                break
        except ProcessLookupError:
            break
        time.sleep(wait)
    process.wait(timeout=5)


def supervise(command, *, cwd, env, root, log, deadline, max_bytes, max_rss=4 * GIB, log_cap=2**21,
              wall_deadline=None, include_controller=False, evidence_root=None,
              max_evidence_bytes=None):
    if (evidence_root is None) != (max_evidence_bytes is None):
        raise ValueError('Evidence root and limit must be supplied together')
    started = time.monotonic()
    wall_started = time.time()
    if wall_deadline is None:
        wall_deadline = wall_started + max(0, deadline - started)
    else:
        wall_deadline = min(wall_deadline, wall_started + max(0, deadline - started))
    row = {"command": command, "status": "incomplete", "peak_rss_bytes": 0,
           "peak_disk_bytes": disk_bytes(root), "log_truncated": False}
    if row["peak_disk_bytes"] >= max_bytes or started >= deadline or wall_started >= wall_deadline:
        return {**row, "reason": "admission_budget", "seconds": 0}
    try:
        psutil.Process().children(recursive=True)
    except (psutil.Error, PermissionError):
        return {**row, "reason": "process_inspection_unavailable", "seconds": 0}
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        return {**row, "reason": "launch_failed", "error": type(exc).__name__, "seconds": 0,
                "cleanup_verified": True}
    owned = {}
    cleanup_errors = []
    def drain():
        written = 0
        with Path(log).open("wb") as stream:
            while block := process.stdout.read1(8192):
                remaining = max(0, log_cap - written)
                stream.write(block[:remaining])
                stream.flush()  # Small progress/failure records must be visible before EOF.
                written += min(len(block), remaining)
                if len(block) > remaining:
                    row["log_truncated"] = True
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            try:
                parent = psutil.Process(process.pid)
                processes = [parent, *parent.children(recursive=True)]
                rss = psutil.Process().memory_info().rss if include_controller else 0
                for item in processes:
                    try:
                        owned[item.pid] = item.create_time()
                        rss += item.memory_info().rss
                    except psutil.Error:
                        pass
                row["peak_rss_bytes"] = max(row["peak_rss_bytes"], rss)
            except psutil.NoSuchProcess:
                pass  # The command can finish between poll() and inspection.
            except (psutil.Error, PermissionError):
                row["reason"] = "process_inspection_unavailable"
            row["peak_disk_bytes"] = max(row["peak_disk_bytes"], disk_bytes(root))
            if evidence_root is not None:
                row['peak_evidence_bytes'] = max(row.get('peak_evidence_bytes', 0), disk_bytes(evidence_root))
            if time.monotonic() >= deadline or time.time() >= wall_deadline:
                row["reason"] = "deadline"
            elif row["peak_disk_bytes"] >= max_bytes:
                row["reason"] = "disk_budget"
            elif row["peak_rss_bytes"] >= max_rss:
                row["reason"] = "memory_budget"
            elif evidence_root is not None and row['peak_evidence_bytes'] >= max_evidence_bytes:
                row['reason'] = 'evidence_budget'
            elif shutil.disk_usage(root).free < min(2 * GIB, max_bytes):
                row["reason"] = "free_space_floor"
            if "reason" in row:
                break
            time.sleep(.2)
    finally:
        # A child may finish while the controller is suspended. Do not report
        # that as an on-time pass merely because poll() skipped the loop.
        if time.monotonic() >= deadline or time.time() >= wall_deadline:
            row.setdefault("reason", "deadline")
        try:
            stop_group(process)
        except (OSError, subprocess.TimeoutExpired, psutil.Error) as exc:
            cleanup_errors.append(type(exc).__name__)
        # Also catch observed children that started their own process group.
        for pid, created in owned.items():
            try:
                child = psutil.Process(pid)
                if child.create_time() == created and child.status() != psutil.STATUS_ZOMBIE:
                    child.kill()
                    child.wait(timeout=2)
            except (psutil.NoSuchProcess, ProcessLookupError):
                pass
            except psutil.Error as exc:
                cleanup_errors.append(type(exc).__name__)
        reader.join(timeout=3)
        if not reader.is_alive():
            process.stdout.close()
    row.update(seconds=round(time.monotonic() - started, 3),
               wall_seconds=round(time.time() - wall_started, 3), exit_code=process.returncode,
               cleanup_verified=not reader.is_alive() and not cleanup_errors,
               cleanup_errors=cleanup_errors)
    row["peak_disk_bytes"] = max(row["peak_disk_bytes"], disk_bytes(root))
    if evidence_root is not None:
        row['peak_evidence_bytes'] = max(row.get('peak_evidence_bytes', 0), disk_bytes(evidence_root))
        if row['peak_evidence_bytes'] >= max_evidence_bytes:
            row.setdefault('reason', 'evidence_budget')
    if row['peak_disk_bytes'] >= max_bytes:
        row.setdefault('reason', 'disk_budget')
    if "reason" not in row:
        row["status"] = "passed" if process.returncode == 0 and row["cleanup_verified"] else "failed"
    return row


def commands(tier, directory, *, packs=(), shard=None, resume=None, suite="all"):
    tests = QUICK_TESTS if tier == "quick" else LOCAL_TESTS
    base = [sys.executable, "-m", "pytest", "-c", "packages/code-intel/pyproject.toml",
            "--confcutdir=packages/code-intel/tests", "-q", "-o", "cache_dir=" + str(directory / "pytest-cache"),
            "--basetemp=" + str(directory / "pytest-tmp"), "-p", "eval.quality.coverage",
            "--quality-operations=" + str(directory / "operations.json"),
            "--junitxml=" + str(directory / "contracts.xml")]
    result = [("lint", [sys.executable, "-m", "ruff", "check", *LINT_PATHS]),
              ("contracts", base + ["packages/code-intel/tests/" + name for name in tests])]
    if tier != "quick":
        result += [("scale", [sys.executable, "packages/code-intel/evals/daily.py", "--sizes", "100", "1000", "10000",
                              "--output", str(directory / "scale.json")]),
                   ("lifecycle", [sys.executable, "-m", "eval.quality.probes", "--output", str(directory / "lifecycle.json")])]
    if tier == "broad":
        workflows = [sys.executable, "-m", "eval.quality.corpus", "--output", str(directory / "workflows.json")]
        for pack in packs:
            workflows += ["--pack", pack]
        if shard:
            workflows += ["--shard", shard]
        if resume:
            workflows += ["--resume", str(Path(resume).resolve())]
        result += [("workflows", workflows),
                   ("ranking", [sys.executable, "-m", "eval.quality.corpus", "--ranking", "--output", str(directory / "ranking.json")])]
    if suite != "all":
        result = [item for item in result if item[0] == suite]
    if not result:
        raise ValueError("No checks selected for quality tier")
    return result


def inventory(root):
    paths = {"managed": Path(root), "historical_evaluations": Path.home() / "Documents/AI/attocode-evals",
             "shared_uv": Path.home() / ".cache/uv", "shared_models": Path.home() / ".cache/huggingface"}
    image = Path.home() / "Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw"
    docker = image.stat() if image.exists() else None
    return {"scope": "Read-only inventory; shared and frozen data are protected",
            "docker_disk": {"path": str(image), "logical_bytes": docker.st_size if docker else 0,
                            "allocated_bytes": docker.st_blocks * 512 if docker else 0,
                            "automatic_cleanup": False,
                            "note": "Sparse VM disk, not directly deletable; preserve study images and volumes"},
            "protected": [str(REPO / ".claude/worktrees/stage1"), "Historical traces, scores, pinned source blobs"],
            "paths": [{"path": str(p), "category": name, "bytes": disk_bytes(p) if p.exists() else 0,
                       "automatic_cleanup": name == "managed"} for name, p in paths.items()]}


def prune(root, *, apply=False):
    """Only expired, finished reports and disposable work; never shared caches."""
    root = managed_root(root)
    rows = []
    with FileLock(str(root / ".lock"), timeout=0):
        for path in (root / "runs").iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            report = path / "report.json"
            if report.is_file() and time.time() - report.stat().st_mtime > 7 * 86400:
                data = json.loads(report.read_text())
                if (data.get("owner") == MARKER and data.get("status") != "running"
                        and data.get("cleanup_verified", True)):
                    rows.append(str(path))
                    if apply:
                        shutil.rmtree(path)
    return {"dry_run": not apply, "paths": rows}


def run(tier, root, *, max_bytes=5 * GIB, seconds=None, packs=(), shard=None, resume=None, suite="all"):
    if tier not in LIMITS or suite not in {"all", "workflows", "ranking"}:
        raise ValueError("Unknown quality tier or suite")
    if (packs or shard or resume or suite != "all") and tier != "broad":
        raise ValueError("Workflow selection requires broad tier")
    if suite == "ranking" and (packs or shard or resume):
        raise ValueError("Ranking uses its unchanged complete frozen gate")
    if seconds is not None and not 1 <= seconds <= LIMITS[tier]:
        raise ValueError("Runtime must be positive and no greater than the tier limit")
    root = managed_root(root)
    with FileLock(str(root / ".lock"), timeout=0):
        if disk_bytes(root) >= max_bytes:
            raise ValueError("Managed storage full: inspect storage/gc before starting")
        run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        directory = root / "runs" / run_id
        directory.mkdir()
        work = root / "work" / run_id
        work.mkdir()
        env = environment(root)
        env.update({"TMPDIR": str(work), "TMP": str(work), "TEMP": str(work), "QUALITY_WORK": str(work),
                    "PYTHONPATH": str(REPO / "packages/code-intel/src") + os.pathsep + str(REPO)})
        report = {"owner": MARKER, "run_id": run_id, "tier": tier, "status": "running", "checks": [],
                  "selection": {"suite": suite, "packs": list(packs), "shard": shard,
                                "resume": str(resume) if resume else None},
                  "full_tier": suite == "all" and not packs and not shard,
                  "source_sha256": fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"]),
                  "fixture_sha256": fingerprint([REPO / "packages/code-intel/tests", REPO / "eval/matrix/configs"]),
                  "harness_sha256": fingerprint([REPO / "eval/matrix", REPO / "eval/meta_harness",
                      REPO / "eval/metrics.py", REPO / "eval/harness.py", REPO / "packages/code-intel/evals/daily.py",
                      REPO / "packages/code-intel/evals/release_gate.py", REPO / "uv.lock"]),
                  "python": sys.version, "platform": sys.platform, "budget_bytes": max_bytes,
                  "budget_seconds": seconds or LIMITS[tier], "started_at": time.time(), "model_runs": 0}
        output = directory / "report.json"
        write_json(output, report)
        deadline = time.monotonic() + report["budget_seconds"]
        wall_deadline = report["started_at"] + report["budget_seconds"]
        sequence = commands(tier, directory, packs=packs, shard=shard, resume=resume, suite=suite)
        try:
            for name, command in sequence:
                if time.monotonic() >= deadline or time.time() >= wall_deadline:
                    break
                row = supervise(command, cwd=REPO, env=env, root=root, log=directory / (name + ".log"),
                                deadline=deadline, wall_deadline=wall_deadline, max_bytes=max_bytes)
                row["name"] = name
                report["checks"].append(row)
                write_json(output, report)
                print(json.dumps({"run": run_id, "check": name, "status": row["status"], "seconds": row["seconds"]}), flush=True)
                if row["status"] != "passed":
                    break
        finally:
            shutil.rmtree(work)
            # pytest's disposable tree must not accumulate beside the reports.
            shutil.rmtree(directory / "pytest-tmp", ignore_errors=True)
            shutil.rmtree(directory / "pytest-cache", ignore_errors=True)
            report["remaining_checks"] = [name for name, _ in sequence[len(report["checks"]):]]
            report["status"] = "passed" if not report["remaining_checks"] and all(
                r["status"] == "passed" for r in report["checks"]) else (
                    "failed" if any(r["status"] == "failed" for r in report["checks"]) else "incomplete")
            report["finished_at"] = time.time()
            report["cleanup_verified"] = not work.exists() and all(r.get("cleanup_verified", False) for r in report["checks"])
            if not report["cleanup_verified"]:
                report["status"] = "incomplete"
            report["remaining_bytes"] = disk_bytes(root)
            report["ending_source_sha256"] = fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"])
            report["ending_fixture_sha256"] = fingerprint([REPO / "packages/code-intel/tests", REPO / "eval/matrix/configs"])
            if (report["ending_source_sha256"] != report["source_sha256"]
                    or report["ending_fixture_sha256"] != report["fixture_sha256"]):
                report.update(status="incomplete", reason="inputs_changed_during_run")
            write_json(output, report)
        return output, report
