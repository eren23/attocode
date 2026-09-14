"""Check experimental separation and real installer replay without model calls."""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest


@pytest.fixture
def onboarding(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "personal"))
    import onboarding_study
    return onboarding_study


@pytest.mark.parametrize("client", ["codex", "claude"])
def test_frozen_installer_lanes_differ_only_in_guidance(onboarding, tmp_path, client):
    from attocode_intel.catalog import INSTRUCTIONS
    study = tmp_path / "study"
    shutil.copytree(Path(__file__).parents[1] / "src", study / "engine",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = {"python": sys.executable}
    audits = {}
    for lane in onboarding.LANES:
        root = study / lane / "repo"
        root.mkdir(parents=True)
        (root / "source.py").write_text("def helper(): pass\n")
        audit = onboarding.configure_setup(manifest, study, root, lane, study / lane / "stage", client)
        assert (root / "source.py").read_text() == "def helper(): pass\n"
        guidance = root / onboarding.GUIDANCE[client]
        assert guidance.exists() == (lane == "intel_installed")
        if guidance.exists():
            assert INSTRUCTIONS in guidance.read_text()
        if lane == "native":
            assert not audit["servers"] and not audit["guidance_present"]
        else:
            entry = audit["servers"][onboarding.NAME]
            assert entry["args"][:2] == ["-m", "attocode_intel.entrypoint"]
            assert entry["env"]["PYTHONPATH"] == str(study / "engine")
            assert entry["env"]["ATTOCODE_INTEL_PRECISION"] == "off"
        audits[lane] = audit
    assert audits["intel_installed"]["guidance_sha256"] == audits["intel_available"]["installed_guidance_sha256"]
    assert not (tmp_path / "personal").exists()
    # A second install must not silently reuse prior config/caches.
    with pytest.raises(ValueError, match="already contains"):
        onboarding.configure_setup(manifest, study, root, "intel_installed", study / "stage", client)


def test_client_isolation_keeps_project_guidance_and_subscription_auth(onboarding, tmp_path):
    import study_clients
    root = tmp_path / "repository"
    root.mkdir()
    for client in ("codex", "claude"):
        argv = study_clients.command(client, "fixed", root, tmp_path / client, {}, "task", project_guidance=True)
        assert "--bare" not in argv and "--safe-mode" not in argv
        if client == "codex":
            assert "--ignore-user-config" in argv and "--ignore-rules" in argv
        else:
            assert argv[argv.index("--setting-sources") + 1] == "project"
            settings = json.loads(argv[argv.index("--settings") + 1])
            excludes = settings["claudeMdExcludes"]
            assert str(root / "CLAUDE.md") not in excludes
            assert str(Path.home() / ".claude/CLAUDE.md") in excludes
            assert str(root.parent / "CLAUDE.md") in excludes
            assert settings["disableAllHooks"] and settings["autoMemoryEnabled"] is False
    global_file = Path.home() / ".codex/AGENTS.md"
    global_file.parent.mkdir(parents=True)
    global_file.write_text("personal instructions")
    with pytest.raises(ValueError, match="global guidance"):
        study_clients.command("codex", "fixed", root, tmp_path / "codex", {}, "task", project_guidance=True)
    assert global_file.read_text() == "personal instructions"


def test_readiness_rejects_reading_token_and_wrong_token(onboarding):
    result = {"exit_code": 0, "timed_out": False, "quota_exhausted": False, "terminal_error": False,
              "permission_denials": [], "tool_calls": [], "output": {"readiness_token": "secret"}}
    assert onboarding.guidance_checks(result, "secret")
    assert not onboarding.guidance_checks(result, "other")
    result["tool_calls"] = [{"name": "StructuredOutput"}]
    assert onboarding.guidance_checks(result, "secret")
    result["tool_calls"] = [{"name": "Read", "arguments": {"path": "AGENTS.md"}}]
    assert not onboarding.guidance_checks(result, "secret")


def test_onboarding_design_pairs_all_setups_and_retains_failed_runs(onboarding):
    import quality_scoring
    import study
    selected, repetitions, lanes = study.design("onboarding")
    schedule = study.schedule(selected, repetitions, lanes=lanes, clients=("codex", "claude"))
    assert len(schedule) == 12 and {t["id"] for t in selected} == set(onboarding.TASK_IDS)
    assert repetitions == 1 and all(r["repeat"] == 0 for r in schedule)
    manifest = {"study_id": "fixture", "models": {"codex": "fixed", "claude": "fixed"},
                "schedule": schedule, "lanes": lanes, "onboarding": {"clients": ["codex", "claude"],
                "scope": "diagnostic", "comparisons": [["intel_installed", "intel_available"], ["intel_installed", "native"]]}}
    rows = [{**row, "study_id": "fixture", "model": "fixed", "status": "failed", "passed": False,
             "seconds": 600} for row in schedule]
    report = quality_scoring.summarize(manifest, rows)
    assert report["complete"] and not report["release_eligible"]
    assert len(report["comparisons"]) == 4
    assert all(len(c["pairs"]) == 2 for c in report["comparisons"])
    assert all(g["attempted"] == 2 and g["metrics"]["grounded_claim_recall"]["mean"] == 0 for g in report["groups"])
    assert onboarding.summarize(manifest, rows)["groups"][0]["attempted"] == 2
    incomplete = quality_scoring.summarize(manifest, rows[:-1])
    assert not incomplete["complete"] and len(incomplete["missing"]) == 1
    forged = copy.deepcopy(rows)
    forged[0]["study_id"] = "other"
    assert onboarding.summarize(manifest, forged)["issues"]
