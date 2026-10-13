"""Guard failures must occur before any paid/model request."""
import copy
import sys
import time
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import codex_repair_study as study


def quota():
    return {"checked_at": time.time(), "account": {"type": "chatgpt", "planType": "pro"},
            "limits": {"ordinaryUsageAllowed": True, "rateLimits": {
                "primary": {"usedPercent": 3}, "secondary": None,
                "credits": {"balance": "100"}, "spendControlReached": False}}}


@pytest.mark.parametrize("change", ["api", "missing", "ordinary", "ceiling", "stale", "credit"])
def test_quota_stops_uncertain_or_paid_continuation(change):
    before, after = quota(), copy.deepcopy(quota())
    if change == "api":
        after["account"]["type"] = "apiKey"
    elif change == "missing":
        after["limits"]["rateLimits"]["primary"] = None
    elif change == "ordinary":
        after["limits"]["ordinaryUsageAllowed"] = None
    elif change == "ceiling":
        after["limits"]["rateLimits"]["primary"]["usedPercent"] = 20
    elif change == "stale":
        after["checked_at"] -= 61
    else:
        after["limits"]["rateLimits"]["credits"]["balance"] = "99.9"
    with pytest.raises(ValueError):
        study.validate_quota(after, before)


def test_quota_accepts_included_usage_without_credit_change():
    study.validate_quota(quota(), quota())


def test_argv_isolates_settings_without_full_access(tmp_path):
    manifest = {"runtime_socket": "/tmp/docker.sock", "guidance": "optional", "skills": ["/tmp/personal"]}
    for lane in study.LANES:
        argv, _ = study.argv_for(manifest, tmp_path, tmp_path / lane, {}, "Fix issue", lane)
        config = {}
        for i, value in enumerate(argv):
            if value == "-c":
                for key, item in tomllib.loads(argv[i + 1]).items():
                    if isinstance(item, dict) and isinstance(config.get(key), dict):
                        config[key].update(item)
                    else:
                        config[key] = item
        assert "--ignore-user-config" in argv and "--ignore-rules" in argv
        assert config["forced_login_method"] == "chatgpt"
        assert config["project_doc_max_bytes"] == 0
        assert config["model_reasoning_effort"] == "high"
        assert config["developer_instructions"] == ("optional" if lane != "native" else "")
        assert config["skills"]["config"] == [{"path": "/tmp/personal", "enabled": False}]
        assert all(config["features"][name] is False for name in study.FEATURES)
        assert config["permissions"]["external_benchmark"]["extends"] == ":workspace"
        assert "danger-full-access" not in argv
        assert argv[-1] == "Fix issue"


def test_repairs_cannot_start_before_reviewed_wiring(tmp_path, monkeypatch):
    manifest = {"study_id": "frozen", "tasks": [], "schedule": []}
    monkeypatch.setattr(study, "load", lambda _: manifest)
    monkeypatch.setattr(study, "trial", lambda *a, **k: pytest.fail("Model requested before wiring passed"))
    study.write_json(tmp_path / "preparation.json", {"study_id": "frozen", "passed": True})
    with pytest.raises(ValueError, match="Both wiring"):
        study.run_one(tmp_path, "repair", 0)


def test_instruction_probe_rejects_global_guidance(tmp_path, monkeypatch):
    class FakeRpc:
        def __init__(self, _, home=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def request(self, method, _):
            assert method == "thread/start"
            return {"instructionSources": ["/home/personal/AGENTS.md"], "model": study.MODEL}

    monkeypatch.setattr(study, "Rpc", FakeRpc)
    with pytest.raises(ValueError, match="Inherited"):
        study.isolation(tmp_path, study.settings())
