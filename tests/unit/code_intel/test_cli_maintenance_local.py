"""Focused tests for CLI maintenance command handlers."""

from __future__ import annotations

import types
from pathlib import Path

import httpx
import pytest

from attocode.code_intel.config import CodeIntelConfig, RemoteConfig


def test_cmd_gc_local_mode_clears_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_gc

    cache_dir = tmp_path / ".attocode" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "a.tmp").write_text("x", encoding="utf-8")
    (cache_dir / "b.tmp").write_text("y", encoding="utf-8")

    monkeypatch.setattr("attocode.code_intel.config.load_remote_config", lambda _project_dir: RemoteConfig())
    monkeypatch.setattr("attocode.code_intel.config.CodeIntelConfig.from_env", classmethod(lambda cls: CodeIntelConfig(database_url="")))

    _cmd_gc(["--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert not any(cache_dir.iterdir())
    assert "Local mode: clearing AST cache" in captured.err
    assert "GC complete." in captured.out


def test_cmd_gc_remote_mode_enqueues_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_gc

    observed: list[tuple[str, dict[str, str], dict[str, str]]] = []

    class _Resp:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class _Client:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, json: dict[str, str], headers: dict[str, str]):
            observed.append((url, json, headers))
            return _Resp(200)

    monkeypatch.setattr(
        "attocode.code_intel.config.load_remote_config",
        lambda _project_dir: RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1"),
    )
    monkeypatch.setattr("httpx.Client", _Client)

    _cmd_gc(["--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert len(observed) == 2
    assert observed[0][0] == "https://example.com/api/v1/jobs/enqueue"
    assert observed[0][1] == {"function": "gc_orphaned_embeddings"}
    assert observed[1][1] == {"function": "gc_unreferenced_content"}
    assert "GC jobs enqueued on remote server." in captured.out


def test_cmd_gc_remote_mode_http_error_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from attocode.code_intel.cli import _cmd_gc

    class _Client:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, json: dict[str, str], headers: dict[str, str]):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(
        "attocode.code_intel.config.load_remote_config",
        lambda _project_dir: RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1"),
    )
    monkeypatch.setattr("httpx.Client", _Client)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_gc(["--project", str(tmp_path)])

    assert exc_info.value.code == 1


def test_cmd_reindex_local_no_provider_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from attocode.code_intel.cli import _cmd_reindex

    observed: dict[str, object] = {}

    class _FakeMgr:
        def __init__(self, root_dir: str):
            observed["root_dir"] = root_dir
            self.is_available = False

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr("attocode.code_intel.config.load_remote_config", lambda _project_dir: RemoteConfig())
    monkeypatch.setattr("attocode.integrations.context.semantic_search.SemanticSearchManager", _FakeMgr)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_reindex(["--project", str(tmp_path)])

    assert exc_info.value.code == 1
    assert observed["root_dir"] == str(tmp_path.resolve())
    assert observed["closed"] is True


def test_cmd_reindex_local_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_reindex

    observed: dict[str, object] = {}
    cache_dir = tmp_path / ".attocode" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "stale.tmp").write_text("x", encoding="utf-8")
    index_file = tmp_path / ".attocode" / "index.json"
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text("{}", encoding="utf-8")

    class _FakeMgr:
        def __init__(self, root_dir: str):
            observed["root_dir"] = root_dir
            self.is_available = True

        def index(self) -> int:
            observed["indexed"] = True
            return 9

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr("attocode.code_intel.config.load_remote_config", lambda _project_dir: RemoteConfig())
    monkeypatch.setattr("attocode.integrations.context.semantic_search.SemanticSearchManager", _FakeMgr)

    _cmd_reindex(["--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert observed["indexed"] is True
    assert observed["closed"] is True
    assert not index_file.exists()
    assert "Indexed 9 chunks." in captured.out
    assert "Reindex complete." in captured.out


def test_cmd_reindex_remote_missing_repo_id_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from attocode.code_intel.cli import _cmd_reindex

    monkeypatch.setattr(
        "attocode.code_intel.config.load_remote_config",
        lambda _project_dir: RemoteConfig(server="https://example.com", token="tok", repo_id=""),
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_reindex(["--project", str(tmp_path)])

    assert exc_info.value.code == 1


def test_cmd_reindex_remote_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_reindex

    observed: list[tuple[str, dict[str, str]]] = []

    class _Resp:
        status_code = 202

        @staticmethod
        def json() -> dict[str, str]:
            return {"status": "queued"}

        text = "queued"

    class _Client:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict[str, str]):
            observed.append((url, headers))
            return _Resp()

    monkeypatch.setattr(
        "attocode.code_intel.config.load_remote_config",
        lambda _project_dir: RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1"),
    )
    monkeypatch.setattr("httpx.Client", _Client)

    _cmd_reindex(["--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert observed == [("https://example.com/api/v1/repos/repo-1/index", {"Authorization": "Bearer tok"})]
    assert "Reindex triggered on remote server." in captured.out
