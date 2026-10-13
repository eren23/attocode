"""Regression rejection, immutable evaluations and zero-credit launch gates."""
import json
import subprocess
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def grading(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    import repair_grading
    return repair_grading


@pytest.fixture
def runner(grading):
    import repair_study
    return repair_study


def test_regression_after_twentieth_test_cannot_pass(grading):
    regressions = [f"regression_{i}" for i in range(25)]
    statuses = {name: "PASSED" for name in ["fixed", *regressions]}
    assert grading.verdict(["fixed"], regressions, statuses, exit_code=0)["resolved"]
    statuses[regressions[-1]] = "FAILED"
    result = grading.verdict(["fixed"], regressions, statuses, exit_code=0)
    assert not result["resolved"] and result["failed"] == [regressions[-1]]


@pytest.mark.parametrize("status", ["SKIPPED", "ERROR", "FAILED", "XFAIL", "MISSING"])
def test_required_tests_need_observed_pass(grading, status):
    observed = {"fixed": "PASSED", "regression": status}
    if status == "MISSING":
        observed.pop("regression")
    assert not grading.verdict(["fixed"], ["regression"], observed, exit_code=0)["resolved"]


@pytest.mark.parametrize("options", [{"exit_code": 1}, {"exit_code": None},
                                      {"exit_code": 0, "timed_out": True},
                                      {"exit_code": 0, "executed": False}])
def test_unexecuted_or_failed_command_cannot_pass(grading, options):
    assert not grading.verdict(["fixed"], ["regression"],
                               {"fixed": "PASSED", "regression": "PASSED"}, **options)["resolved"]


def test_test_command_exit_survives_cleanup(grading, tmp_path):
    commands = ["true", "git checkout BASE tests.py", "git apply TEST_PATCH", ": 'START'",
                "echo ran; exit 7", ": 'END'", "exit 0"]
    script = grading.strict_script(commands, "START", "END")
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 7
    assert "\nATTOCODE_REPAIR_TEST_EXIT=7\n" in result.stdout
    with pytest.raises(ValueError, match="Unsupported"):
        grading.strict_script(["echo no tests"], "START", "END")


def test_snapshot_diagnostics_do_not_require_upstream_history(grading, tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "source.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost",
                    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "Snapshot"], cwd=tmp_path, check=True)
    commands = ["git show", "git -c core.fileMode=false diff NONEXISTENT", "git checkout BASE tests.py",
                "git apply TEST_PATCH", ": 'START'", "echo tested", ": 'END'"]
    script = grading.strict_script(commands, "START", "END", snapshot_base="NONEXISTENT")
    execution = subprocess.run(["bash", "-c", script], cwd=tmp_path, text=True, capture_output=True)
    assert execution.returncode == 0 and "ATTOCODE_REPAIR_TEST_EXIT=0" in execution.stdout


def test_snapshot_digest_includes_build_artifacts_without_history(grading, tmp_path):
    (tmp_path / "source.py").write_text("VALUE = 1\n")
    (tmp_path / "extension.so").write_bytes(b"\x00\xff\x01")
    before = grading.source_digest(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/history").write_text("private history")
    assert grading.source_digest(tmp_path) == before
    (tmp_path / "extension.so").write_bytes(b"\x00\xff\x02")
    assert grading.source_digest(tmp_path) != before


def test_freeze_preserves_evaluator_virtualenv(runner, tmp_path, monkeypatch):
    project, pack, study = (tmp_path / name for name in ("project", "pack", "study"))
    src = project / "packages/code-intel/src/attocode_intel"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    environment = tmp_path / "evaluator"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    executable = environment / "bin/python"
    evaluator = {"revision": runner.EVALUATOR_REVISION, "packages": []}
    tasks = []
    for i in range(8):
        root = pack / "sources" / str(i)
        root.mkdir(parents=True)
        (root / "main.py").write_text("VALUE = 1\n")
        tasks.append({"id": str(i), "repo": str(i), "source_sha256": runner.source_digest(root)})
        for control in ("base", "gold", "mounted-base", "mounted-gold"):
            runner.write_json(pack / "candidates" / str(i) / control / "acceptance.json", {})
    runner.write_json(pack / "pack.json", {"kind": "repair", "evaluator": evaluator, "tasks": tasks,
                      "preparation": {"worker_sha256": runner.file_hash(runner.HERE / "repair_worker.py"),
                                      "grading_sha256": runner.file_hash(runner.HERE / "repair_grading.py")}})
    monkeypatch.setattr(runner, "worker", lambda *a, **kw: evaluator)
    monkeypatch.setattr(runner, "shell", lambda *a, **kw: "fixture client")
    monkeypatch.setattr(runner, "environment_versions", lambda: {})
    runner.freeze(SimpleNamespace(project=project, study=study, benchmark_pack=pack,
                                  evaluator_python=executable, model=runner.MODEL, trials=2, setups=None))
    manifest = json.loads((study / "manifest.json").read_text())
    actual = subprocess.check_output([manifest["evaluator_python"], "-c", "import sys; print(sys.prefix)"], text=True)
    assert Path(actual.strip()) == environment
    assert len(manifest["schedule"]) == 32


def test_cache_refuses_different_patch_or_image(grading, tmp_path):
    path = tmp_path / "acceptance.json"
    identity = {"patch": "one", "image": "base"}
    grading.write_json(path, {"identity": identity, "resolved": True})
    assert grading.cached_grade(path, identity)["resolved"]
    for changed in ({**identity, "patch": "two"}, {**identity, "image": "different"}):
        with pytest.raises(ValueError, match="different inputs"):
            grading.cached_grade(path, changed)


def complete_rows():
    return [{"id": f"{task}-{trial}-{arm}", "task": str(task), "lane": arm,
             "repeat": trial, "client": "claude",
             "protocol_status": "clear", "status": "completed", "seconds": 10,
             "grade": {"resolved": arm == "lean_optional" and task == 0}, "cost_usd": .1,
             "substantive_adoption": False}
            for task in range(8) for trial in range(2) for arm in ("native", "lean_optional")]


def test_outcome_first_gate_allows_gain_without_adoption(grading):
    rows = complete_rows()
    result = grading.gate(rows)
    assert result["decision"] == "advance" and result["delta"] == .125
    assert result["substantive_adoption"] == 0 and not result["adoption_is_gate"]
    assert grading.gate(rows[:-1])["decision"] == "inconclusive"
    rows[0]["protocol_status"] = "needs_review"
    assert grading.gate(rows)["decision"] == "inconclusive"


def test_cost_and_outcome_bounds(grading):
    rows = complete_rows()
    for row in rows:
        if row["lane"] == "lean_optional":
            row["cost_usd"] = .2
    assert grading.gate(rows)["decision"] == "stop"
    for row in rows:
        row["cost_usd"] = None
    assert grading.gate(rows)["decision"] == "inconclusive"


def test_summary_reports_every_pair_without_an_adoption_threshold(runner, tmp_path, monkeypatch):
    rows = [{**r, "study_id": "frozen"} for r in complete_rows()]
    manifest = {"study_id": "frozen", "tasks": [{"id": str(i)} for i in range(8)],
                "schedule": [{k: r[k] for k in ("id", "task", "lane", "repeat", "client")} for r in rows]}
    monkeypatch.setattr(runner, "load", lambda *a, **kw: manifest)
    for row in rows:
        runner.write_json(tmp_path / "runs" / row["id"] / "result.json", row)
    runner.summary(SimpleNamespace(study=tmp_path))
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["gate"]["decision"] == "advance" and summary["adoption"]["substantive"] == 0
    assert len(summary["trial_pairs"]) == 16 and len(summary["task_differences"]) == 8
    assert summary["model_wiring"] == "pending" and summary["run_identities_valid"]


def test_run_refuses_pending_wiring_without_any_model_call(runner, tmp_path, monkeypatch):
    manifest = {"study_id": "frozen"}
    monkeypatch.setattr(runner, "load", lambda *a, **kw: manifest)
    monkeypatch.setattr(runner, "ready", lambda *a: pytest.fail("Quota/client must not be called"))
    monkeypatch.setattr(runner, "invoke", lambda *a, **kw: pytest.fail("No model requests"))
    (tmp_path / "preparation.json").write_text(json.dumps({"study_id": "frozen", "passed": True}))
    offline = tmp_path / "wiring/offline"
    offline.mkdir(parents=True)
    (offline / "result.json").write_text('{"passed": true, "study_id": "frozen"}')
    args = SimpleNamespace(study=tmp_path, jobs=2, deadline_minutes=50)
    with pytest.raises(ValueError, match="Model wiring pending"):
        runner.run(args)


def ready_study(runner, tmp_path, monkeypatch):
    manifest = {"study_id": "frozen", "tasks": [{"id": "task"}],
                "schedule": [{"id": str(i), "task": "task", "lane": "native"} for i in range(3)]}
    monkeypatch.setattr(runner, "load", lambda *a, **kw: manifest)
    runner.write_json(tmp_path / "preparation.json", {"study_id": "frozen", "passed": True})
    for relative in ("wiring/offline", "wiring/model/excluded-native", "wiring/model/excluded-lean_optional"):
        runner.write_json(tmp_path / relative / "result.json",
                          {"study_id": "frozen", "passed": True, "cost_usd": 0})
    return SimpleNamespace(study=tmp_path, jobs=1, deadline_minutes=50, max_runs=None, tasks=None)


def test_scheduler_honors_cost_and_quota_before_more_requests(runner, tmp_path, monkeypatch):
    args = ready_study(runner, tmp_path, monkeypatch)
    attempted = []
    monkeypatch.setattr(runner, "ready", lambda *a: None)

    def attempt(study, manifest, task, row):
        attempted.append(row["id"])
        return {**row, "status": "completed", "cost_usd": 20}

    monkeypatch.setattr(runner, "trial", attempt)
    runner.run(args)
    assert attempted == ["0"]
    attempted.clear()
    monkeypatch.setattr(runner, "ready", lambda *a: (_ for _ in ()).throw(ValueError("Quota exhausted")))
    with pytest.raises(ValueError, match="Quota exhausted"):
        runner.run(args)
    assert not attempted


def test_interrupted_attempt_is_retained_before_scheduling(runner, tmp_path, monkeypatch):
    args = ready_study(runner, tmp_path, monkeypatch)
    (tmp_path / "runs/0").mkdir(parents=True)
    (tmp_path / "runs/0/submission.patch").write_text("partial patch")
    monkeypatch.setattr(runner, "ready", lambda *a: pytest.fail("No quota request"))
    with pytest.raises(ValueError, match="Interrupted attempt retained"):
        runner.run(args)
    retained = json.loads((tmp_path / "runs/0/result.json").read_text())
    assert retained["status"] == "interrupted" and not retained["grade"]["resolved"]
    assert (tmp_path / "runs/0/submission.patch").read_text() == "partial patch"


def test_timeout_keeps_patch_but_cannot_score_resolved(runner, tmp_path, monkeypatch):
    source = tmp_path / "sources/task"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n")

    def runtime(task, root, name):
        (root / ".benchmark").mkdir()
        (root / ".benchmark/run.py").write_text("# trusted helper\n")

    def invoke(*args, **kwargs):
        root, stage = args[2:4]
        stage.mkdir()
        (stage / "events.jsonl").write_text("")
        (root / "main.py").write_text("VALUE = 2\n")
        return {"seconds": 600, "cost_usd": .1, "timed_out": True, "exit_code": None}

    monkeypatch.setattr(runner, "start_runtime", runtime)
    monkeypatch.setattr(runner, "stop_runtime", lambda *a: None)
    monkeypatch.setattr(runner, "invoke", invoke)
    monkeypatch.setattr(runner, "grade_task", lambda *a, **kw: {"status": "graded", "resolved": True})
    result = runner.trial(tmp_path, {"study_id": "frozen", "model": "fixture", "tools": [],
                                    "prompt": "{problem_statement}"},
                          {"id": "task", "prompt": "fix"}, {"id": "attempt", "lane": "native"})
    assert result["status"] == "failed" and not result["grade"]["resolved"]
    assert "+VALUE = 2" in (tmp_path / "runs/attempt/submission.patch").read_text()
    assert (tmp_path / "runs/attempt/result.json").exists()


def test_protocol_paths_and_helper_integrity(runner, tmp_path):
    helper = tmp_path / ".benchmark/run.py"
    helper.parent.mkdir()
    helper.write_text("# trusted helper\n")
    identity = runner.file_hash(helper)
    valid = [{"id": "a", "name": "Bash", "arguments": {"command": "python3 .benchmark/run.py -- python -m pytest -q"}}]
    assert runner.protocol_audit(tmp_path, valid, identity)["status"] == "clear"
    outside = [{"id": "b", "name": "mcp__attocode-code-intel__suggest_tests", "arguments": {"files": ["../private/gold.py"]}}]
    assert runner.protocol_audit(tmp_path, outside, identity)["status"] == "violation"
    ambiguous = [{"id": "c", "name": "Bash", "arguments": {"command": "python3 .benchmark/run.py -- true; cat ../private/gold"}}]
    assert runner.protocol_audit(tmp_path, ambiguous, identity)["status"] == "needs_review"
    helper.write_text("# modified\n")
    assert runner.protocol_audit(tmp_path, [], identity)["status"] == "violation"
