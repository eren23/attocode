"""Tests for CLI remote commands: _cmd_connect and _notify_remote."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from attocode.code_intel.cli import _cmd_connect, _notify_remote
from attocode.code_intel.config import RemoteConfig, load_remote_config


# ---------------------------------------------------------------------------
# _cmd_connect
# ---------------------------------------------------------------------------


class TestCmdConnect:
    def test_writes_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        _cmd_connect([
            "--server", "https://example.com/",
            "--token", "tok123",
            "--repo", "repo-1",
            "--project", str(tmp_path),
        ])

        rc = load_remote_config(str(tmp_path))
        assert rc.server == "https://example.com"  # trailing slash stripped
        assert rc.token == "tok123"
        assert rc.repo_id == "repo-1"
        assert rc.branch_auto_detect is True
        assert rc.is_configured is True

    def test_config_file_is_valid_toml(self, tmp_path, monkeypatch):
        import tomllib

        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        _cmd_connect([
            "--server", "https://example.com",
            "--token", "tok",
            "--project", str(tmp_path),
        ])

        config_path = tmp_path / ".attocode" / "config.toml"
        assert config_path.exists()

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert "remote" in data
        assert data["remote"]["server"] == "https://example.com"
        assert data["remote"]["token"] == "tok"
        assert data["remote"]["branch_auto_detect"] is True

    def test_missing_server_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_connect(["--token", "tok", "--project", str(tmp_path)])
        assert exc_info.value.code == 1

    def test_missing_token_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_connect(["--server", "https://example.com", "--project", str(tmp_path)])
        assert exc_info.value.code == 1

    def test_strips_trailing_slash(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        _cmd_connect([
            "--server", "https://example.com///",
            "--token", "tok",
            "--project", str(tmp_path),
        ])

        rc = load_remote_config(str(tmp_path))
        assert not rc.server.endswith("/")
        assert rc.server == "https://example.com"

    def test_equals_sign_syntax(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        _cmd_connect([
            "--server=https://eq.example.com",
            "--token=tok_eq",
            "--repo=repo-eq",
            "--project", str(tmp_path),
        ])

        rc = load_remote_config(str(tmp_path))
        assert rc.server == "https://eq.example.com"
        assert rc.token == "tok_eq"
        assert rc.repo_id == "repo-eq"


# ---------------------------------------------------------------------------
# _notify_remote
# ---------------------------------------------------------------------------


class TestNotifyRemote:
    @patch("subprocess.run")
    @patch("httpx.post")
    def test_posts_to_correct_url(self, mock_post, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {"accepted": 1}
        mock_post.return_value = mock_resp

        rc = RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1")
        _notify_remote(rc, ["src/a.py"], str(tmp_path))

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "https://example.com/api/v1/notify/file-changed"

    @patch("subprocess.run")
    @patch("httpx.post")
    def test_sends_auth_header(self, mock_post, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"accepted": 2}
        mock_post.return_value = mock_resp

        rc = RemoteConfig(server="https://example.com", token="secret_jwt", repo_id="r")
        _notify_remote(rc, ["a.py", "b.py"], str(tmp_path))

        _, call_kwargs = mock_post.call_args
        assert call_kwargs["headers"]["Authorization"] == "Bearer secret_jwt"

    @patch("subprocess.run")
    @patch("httpx.post")
    def test_includes_branch_in_body(self, mock_post, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="feat/x\n")
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {"accepted": 1}
        mock_post.return_value = mock_resp

        rc = RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1")
        _notify_remote(rc, ["src/a.py"], str(tmp_path))

        _, call_kwargs = mock_post.call_args
        body = call_kwargs["json"]
        assert body["branch"] == "feat/x"
        assert body["paths"] == ["src/a.py"]
        assert body["project"] == "repo-1"

    @patch("subprocess.run")
    @patch("httpx.post")
    def test_falls_back_to_main_on_git_failure(self, mock_post, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("git not found")
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {"accepted": 1}
        mock_post.return_value = mock_resp

        rc = RemoteConfig(server="https://example.com", token="tok", repo_id="repo-1")
        _notify_remote(rc, ["f.py"], str(tmp_path))

        _, call_kwargs = mock_post.call_args
        assert call_kwargs["json"]["branch"] == "main"

    @patch("subprocess.run")
    @patch("httpx.post")
    def test_strips_trailing_slash_from_server(self, mock_post, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"accepted": 1}
        mock_post.return_value = mock_resp

        rc = RemoteConfig(server="https://example.com/", token="tok", repo_id="r")
        _notify_remote(rc, ["x.py"], str(tmp_path))

        call_args, _ = mock_post.call_args
        assert call_args[0] == "https://example.com/api/v1/notify/file-changed"
