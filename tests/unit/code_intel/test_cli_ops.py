"""Focused tests for operational CLI command handlers."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from attocode.code_intel.config import RemoteConfig


def test_cmd_test_connection_requires_remote_config(tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_test_connection

    with pytest.raises(SystemExit) as exc_info:
        _cmd_test_connection(["--project", str(tmp_path)])

    assert exc_info.value.code == 1


def test_cmd_test_connection_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_test_connection

    observed: dict[str, object] = {}

    def _fake_get(url: str, headers=None, timeout: int = 10):
        if url.endswith("/health"):
            return MagicMock(status_code=200)
        if url.endswith("/api/v1/auth/me"):
            return MagicMock(status_code=200, json=lambda: {"email": "dev@example.com"})
        if url.endswith("/api/v1/repos/repo-1"):
            return MagicMock(status_code=200, json=lambda: {"name": "demo"})
        if url.endswith("/api/v1/repos/repo-1/branches"):
            return MagicMock(status_code=200, json=lambda: [{"name": "main"}])
        if url.endswith("/api/v2/repos/repo-1/stats"):
            return MagicMock(status_code=200, json=lambda: {"total_files": 12, "embedded_files": 9})
        raise AssertionError(f"Unexpected GET {url}")

    def _fake_post(url: str, json: dict[str, object], headers=None, timeout: int = 10):
        observed["notify"] = (url, json, headers)
        return MagicMock(status_code=202)

    def _fake_connect(url: str, close_timeout: int, open_timeout: int):
        observed["ws_url"] = url
        return types.SimpleNamespace(close=lambda: observed.setdefault("ws_closed", True))

    websockets_mod = types.ModuleType("websockets")
    websockets_sync = types.ModuleType("websockets.sync")
    websockets_client = types.ModuleType("websockets.sync.client")
    websockets_client.connect = _fake_connect
    websockets_sync.client = websockets_client
    websockets_mod.sync = websockets_sync
    monkeypatch.setitem(sys.modules, "websockets", websockets_mod)
    monkeypatch.setitem(sys.modules, "websockets.sync", websockets_sync)
    monkeypatch.setitem(sys.modules, "websockets.sync.client", websockets_client)

    monkeypatch.setattr(
        "attocode.code_intel.config.load_remote_config",
        lambda _project_dir: RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1"),
    )
    monkeypatch.setattr("httpx.get", _fake_get)
    monkeypatch.setattr("httpx.post", _fake_post)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: MagicMock(returncode=0, stdout="main\n"),
    )

    _cmd_test_connection(["--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert "All checks passed!" in captured.out
    assert observed["notify"][0] == "https://example.com/api/v1/notify/file-changed"
    assert observed["ws_url"] == "wss://example.com/ws/repos/repo-1/events?token=tok"
    assert observed["ws_closed"] is True


def test_cmd_watch_requires_remote_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from attocode.code_intel.cli import _cmd_watch

    watchfiles_mod = types.ModuleType("watchfiles")
    watchfiles_mod.Change = types.SimpleNamespace(modified="modified", added="added", deleted="deleted")
    watchfiles_mod.watch = lambda *args, **kwargs: iter(())
    monkeypatch.setitem(sys.modules, "watchfiles", watchfiles_mod)
    monkeypatch.setattr("attocode.code_intel.config.load_remote_config", lambda _project_dir: RemoteConfig())

    with pytest.raises(SystemExit) as exc_info:
        _cmd_watch(["--project", str(tmp_path)])

    assert exc_info.value.code == 1


def test_cmd_index_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_index

    progress = types.SimpleNamespace(
        status="ready",
        coverage=0.5,
        indexed_files=10,
        total_files=20,
        elapsed_seconds=1.2,
    )

    class _FakeMgr:
        def __init__(self, root_dir: str):
            self.provider_name = "sentence-transformers"

        def get_index_progress(self):
            return progress

        def is_index_ready(self) -> bool:
            return True

        def close(self) -> None:
            return None

    monkeypatch.setattr("attocode.integrations.context.semantic_search.SemanticSearchManager", _FakeMgr)

    _cmd_index(["--status", "--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert "Provider: sentence-transformers" in captured.out
    assert "Coverage: 50% (10/20 files)" in captured.out
    assert "Vector search active: True" in captured.out


def test_cmd_index_foreground(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_index

    observed: dict[str, object] = {}

    class _FakeMgr:
        def __init__(self, root_dir: str):
            observed["root_dir"] = root_dir
            self.is_available = True

        def index(self) -> int:
            observed["indexed"] = True
            return 11

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr("attocode.integrations.context.semantic_search.SemanticSearchManager", _FakeMgr)

    _cmd_index(["--foreground", "--project", str(tmp_path)])
    captured = capsys.readouterr()

    assert observed["root_dir"] == str(tmp_path.resolve())
    assert observed["indexed"] is True
    assert observed["closed"] is True
    assert "Indexed 11 chunks." in captured.err


def test_cmd_setup_missing_required_files_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from attocode.code_intel.cli import _cmd_setup

    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")

    with pytest.raises(SystemExit) as exc_info:
        _cmd_setup(["--project", str(tmp_path)])

    assert exc_info.value.code == 1


def test_cmd_setup_api_unreachable_exits_zero_with_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_setup

    compose_file = tmp_path / "docker" / "code-intel" / "docker-compose.dev.yml"
    compose_file.parent.mkdir(parents=True, exist_ok=True)
    compose_file.write_text("services: {}", encoding="utf-8")
    env_file = tmp_path / ".env.dev"
    env_file.write_text("ATTOCODE_PORT=8080\n", encoding="utf-8")

    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr("attocode.code_intel.cli._run", lambda cmd, check=True, capture=False: None)
    monkeypatch.setattr(
        "httpx.get",
        lambda url, timeout=5: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )

    with pytest.raises(SystemExit) as exc_info:
        _cmd_setup(["--project", str(tmp_path), "--skip-deps"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 0
    assert "API server not reachable" in captured.err
    assert "uvicorn attocode.code_intel.api.app:create_app" in captured.err
