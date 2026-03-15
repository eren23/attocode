"""Tests for RemoteConfig, load_remote_config, and save_remote_config."""

from __future__ import annotations

import pytest

from attocode.code_intel.config import RemoteConfig, load_remote_config, save_remote_config


# ---------------------------------------------------------------------------
# RemoteConfig dataclass
# ---------------------------------------------------------------------------


class TestRemoteConfigDefaults:
    def test_defaults(self):
        rc = RemoteConfig()
        assert rc.server == ""
        assert rc.token == ""
        assert rc.repo_id == ""
        assert rc.branch_auto_detect is True

    def test_is_configured_both_set(self):
        rc = RemoteConfig(server="https://example.com", token="tok_123")
        assert rc.is_configured is True

    def test_is_configured_missing_server(self):
        rc = RemoteConfig(server="", token="tok_123")
        assert rc.is_configured is False

    def test_is_configured_missing_token(self):
        rc = RemoteConfig(server="https://example.com", token="")
        assert rc.is_configured is False

    def test_is_configured_both_empty(self):
        rc = RemoteConfig()
        assert rc.is_configured is False


# ---------------------------------------------------------------------------
# load_remote_config
# ---------------------------------------------------------------------------


class TestLoadRemoteConfig:
    def test_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        rc = load_remote_config(str(tmp_path))
        assert rc.server == ""
        assert rc.token == ""
        assert rc.repo_id == ""
        assert rc.branch_auto_detect is True

    def test_loads_from_toml(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            '[remote]\nserver = "https://host.io"\ntoken = "abc"\n'
            'repo_id = "r1"\nbranch_auto_detect = false\n',
            encoding="utf-8",
        )

        rc = load_remote_config(str(tmp_path))
        assert rc.server == "https://host.io"
        assert rc.token == "abc"
        assert rc.repo_id == "r1"
        assert rc.branch_auto_detect is False

    def test_env_vars_override_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            '[remote]\nserver = "https://file.io"\ntoken = "file_tok"\n'
            'repo_id = "file_repo"\n',
            encoding="utf-8",
        )

        monkeypatch.setenv("ATTOCODE_REMOTE_URL", "https://env.io")
        monkeypatch.setenv("ATTOCODE_REMOTE_TOKEN", "env_tok")
        monkeypatch.setenv("ATTOCODE_REMOTE_REPO_ID", "env_repo")

        rc = load_remote_config(str(tmp_path))
        assert rc.server == "https://env.io"
        assert rc.token == "env_tok"
        assert rc.repo_id == "env_repo"

    def test_env_vars_without_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ATTOCODE_REMOTE_URL", "https://env-only.io")
        monkeypatch.setenv("ATTOCODE_REMOTE_TOKEN", "env_tok")
        monkeypatch.setenv("ATTOCODE_REMOTE_REPO_ID", "env_repo")

        rc = load_remote_config(str(tmp_path))
        assert rc.server == "https://env-only.io"
        assert rc.token == "env_tok"
        assert rc.repo_id == "env_repo"

    def test_malformed_toml_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text("{{not valid toml", encoding="utf-8")

        rc = load_remote_config(str(tmp_path))
        assert rc.server == ""
        assert rc.token == ""


# ---------------------------------------------------------------------------
# save_remote_config
# ---------------------------------------------------------------------------


class TestSaveRemoteConfig:
    def test_creates_directory_and_file(self, tmp_path):
        rc = RemoteConfig(server="https://s.io", token="t", repo_id="r")
        path = save_remote_config(str(tmp_path), rc)

        assert path.exists()
        assert path == tmp_path / ".attocode" / "config.toml"

    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        original = RemoteConfig(
            server="https://round.trip",
            token="secret_token",
            repo_id="repo_42",
            branch_auto_detect=False,
        )
        save_remote_config(str(tmp_path), original)
        loaded = load_remote_config(str(tmp_path))

        assert loaded.server == original.server
        assert loaded.token == original.token
        assert loaded.repo_id == original.repo_id
        assert loaded.branch_auto_detect == original.branch_auto_detect

    def test_preserves_existing_sections(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            '[other]\nkey = "value"\n', encoding="utf-8"
        )

        rc = RemoteConfig(server="https://s.io", token="t")
        save_remote_config(str(tmp_path), rc)

        import tomllib

        data = tomllib.loads(
            (config_dir / "config.toml").read_text(encoding="utf-8")
        )
        assert data["other"]["key"] == "value"
        assert data["remote"]["server"] == "https://s.io"

    def test_overwrites_existing_remote_section(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATTOCODE_REMOTE_URL", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_TOKEN", raising=False)
        monkeypatch.delenv("ATTOCODE_REMOTE_REPO_ID", raising=False)

        first = RemoteConfig(server="https://old.io", token="old")
        save_remote_config(str(tmp_path), first)

        second = RemoteConfig(server="https://new.io", token="new", repo_id="r2")
        save_remote_config(str(tmp_path), second)

        loaded = load_remote_config(str(tmp_path))
        assert loaded.server == "https://new.io"
        assert loaded.token == "new"
        assert loaded.repo_id == "r2"
