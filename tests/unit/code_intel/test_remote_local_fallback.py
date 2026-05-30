"""Route-less tools must run locally even when a remote is configured.

`call_graph` and `regex_search` have no server-side HTTP route, so dispatching
them through the remote proxy raises AttributeError in remote mode. They must
fall back to the local engine regardless of remote configuration.
"""

from __future__ import annotations

import attocode.code_intel._shared as shared


class _FakeRemote:
    """Stand-in remote proxy that lacks call_graph / regex_search (like the real one)."""

    project_dir = "remote:fake"

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def test_get_local_service_bypasses_remote(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(shared, "_remote_service", _FakeRemote(), raising=False)
    monkeypatch.setattr(shared, "_service", None, raising=False)

    # _get_service() returns the remote proxy when configured...
    assert isinstance(shared._get_service(), _FakeRemote)

    # ...but _get_local_service() always returns the real local service.
    local = shared._get_local_service()
    from attocode.code_intel.service import CodeIntelService

    assert isinstance(local, CodeIntelService)
    assert not isinstance(local, _FakeRemote)


def test_regex_search_runs_locally_when_remote_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    (tmp_path / "hello.py").write_text(
        "def greet():\n    return 'hello world'\n", encoding="utf-8",
    )

    # Remote proxy is set but has no regex_search — must NOT be used.
    monkeypatch.setattr(shared, "_remote_service", _FakeRemote(), raising=False)

    from attocode.code_intel.tools.search_tools import regex_search

    out = regex_search("hello world", path="", max_results=10)
    assert "hello.py" in out  # local grep found it; no AttributeError


class _RecordingRemote:
    """Remote proxy that records learning calls (parity with adr_tools)."""

    project_dir = "remote:fake"
    calls: list[tuple]

    def __init__(self) -> None:
        self.calls = []

    def record_learning(self, **kw) -> str:
        self.calls.append(("record_learning", kw))
        return "remote-recorded"

    def recall(self, query, scope="", max_results=10) -> str:
        self.calls.append(("recall", query))
        return "remote-recalled"

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def test_record_learning_routes_to_remote_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    fake = _RecordingRemote()
    monkeypatch.setattr(shared, "_remote_service", fake, raising=False)

    from attocode.code_intel.tools.learning_tools import record_learning

    out = record_learning(type="pattern", description="use X")
    assert out == "remote-recorded"
    assert fake.calls and fake.calls[0][0] == "record_learning"


def test_recall_routes_to_remote_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    fake = _RecordingRemote()
    monkeypatch.setattr(shared, "_remote_service", fake, raising=False)

    from attocode.code_intel.tools.learning_tools import recall

    out = recall("how to X")
    assert out == "remote-recalled"
    assert fake.calls and fake.calls[0][0] == "recall"


def test_enable_remote_if_configured_local_only(monkeypatch, tmp_path):
    """The shared startup helper is a no-op in local-only mode."""
    shared.clear_remote_service()
    shared.enable_remote_if_configured(str(tmp_path), local_only=True)
    assert shared._remote_service is None


def test_enable_remote_if_configured_no_config(monkeypatch, tmp_path):
    """No [remote] config and no env => stays local, no crash."""
    for var in ("ATTOCODE_REMOTE_URL", "ATTOCODE_REMOTE_TOKEN", "ATTOCODE_REMOTE_REPO_ID"):
        monkeypatch.delenv(var, raising=False)
    shared.clear_remote_service()
    shared.enable_remote_if_configured(str(tmp_path), local_only=False)
    assert shared._remote_service is None
