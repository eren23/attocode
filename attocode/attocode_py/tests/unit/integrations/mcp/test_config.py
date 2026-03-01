"""Comprehensive tests for MCP config loading.

Covers MCPServerConfig dataclass, _parse_servers_dict helper,
_load_config_file helper, and load_mcp_configs hierarchy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from attocode.integrations.mcp.config import (
    MCPServerConfig,
    _load_config_file,
    _parse_servers_dict,
    load_mcp_configs,
)


# =====================================================================
# MCPServerConfig dataclass
# =====================================================================


class TestMCPServerConfig:
    """Tests for the MCPServerConfig dataclass defaults and field behaviour."""

    def test_defaults(self) -> None:
        cfg = MCPServerConfig(name="test", command="node")
        assert cfg.name == "test"
        assert cfg.command == "node"
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.enabled is True
        assert cfg.lazy_load is False

    def test_custom_fields(self) -> None:
        cfg = MCPServerConfig(
            name="x",
            command="npx",
            args=["-y", "@foo/bar"],
            env={"KEY": "val"},
            enabled=False,
            lazy_load=True,
        )
        assert cfg.args == ["-y", "@foo/bar"]
        assert cfg.env == {"KEY": "val"}
        assert cfg.enabled is False
        assert cfg.lazy_load is True

    def test_independent_default_lists(self) -> None:
        """Default list/dict fields should not be shared between instances."""
        a = MCPServerConfig(name="a", command="x")
        b = MCPServerConfig(name="b", command="y")
        a.args.append("extra")
        assert b.args == []

    def test_independent_default_dicts(self) -> None:
        a = MCPServerConfig(name="a", command="x")
        b = MCPServerConfig(name="b", command="y")
        a.env["FOO"] = "bar"
        assert b.env == {}

    def test_slots_enabled(self) -> None:
        """MCPServerConfig should use __slots__ for memory efficiency."""
        cfg = MCPServerConfig(name="s", command="c")
        assert hasattr(cfg, "__slots__")


# =====================================================================
# _parse_servers_dict helper
# =====================================================================


class TestParseServersDict:
    """Tests for the internal _parse_servers_dict function."""

    def test_empty_dict(self) -> None:
        assert _parse_servers_dict({}) == []

    def test_single_server_minimal(self) -> None:
        configs = _parse_servers_dict({
            "my-server": {"command": "node", "args": ["server.js"]},
        })
        assert len(configs) == 1
        assert configs[0].name == "my-server"
        assert configs[0].command == "node"
        assert configs[0].args == ["server.js"]
        assert configs[0].env == {}
        assert configs[0].enabled is True
        assert configs[0].lazy_load is False

    def test_single_server_full(self) -> None:
        configs = _parse_servers_dict({
            "srv": {
                "command": "deno",
                "args": ["run", "main.ts"],
                "env": {"API_KEY": "secret"},
                "enabled": False,
                "lazy_load": True,
            }
        })
        assert len(configs) == 1
        c = configs[0]
        assert c.command == "deno"
        assert c.args == ["run", "main.ts"]
        assert c.env == {"API_KEY": "secret"}
        assert c.enabled is False
        assert c.lazy_load is True

    def test_multiple_servers(self) -> None:
        configs = _parse_servers_dict({
            "alpha": {"command": "a"},
            "beta": {"command": "b"},
            "gamma": {"command": "c"},
        })
        assert len(configs) == 3
        names = {c.name for c in configs}
        assert names == {"alpha", "beta", "gamma"}

    def test_non_dict_entry_skipped(self) -> None:
        """Non-dict entries in the servers dict should be silently skipped."""
        configs = _parse_servers_dict({
            "valid": {"command": "node"},
            "invalid_string": "not a dict",
            "invalid_list": ["also", "bad"],
            "invalid_number": 42,
            "invalid_none": None,
        })
        assert len(configs) == 1
        assert configs[0].name == "valid"

    def test_missing_command_defaults_to_empty(self) -> None:
        configs = _parse_servers_dict({"srv": {}})
        assert len(configs) == 1
        assert configs[0].command == ""

    def test_missing_args_defaults_to_empty_list(self) -> None:
        configs = _parse_servers_dict({"srv": {"command": "node"}})
        assert configs[0].args == []

    def test_missing_env_defaults_to_empty_dict(self) -> None:
        configs = _parse_servers_dict({"srv": {"command": "node"}})
        assert configs[0].env == {}


# =====================================================================
# _load_config_file helper
# =====================================================================


class TestLoadConfigFile:
    """Tests for the internal _load_config_file function."""

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        result = _load_config_file(tmp_path / "does_not_exist.json")
        assert result == []

    def test_valid_config_file(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(
            json.dumps({
                "servers": {
                    "test-srv": {
                        "command": "npx",
                        "args": ["-y", "@test/server"],
                    }
                }
            }),
            encoding="utf-8",
        )
        configs = _load_config_file(path)
        assert len(configs) == 1
        assert configs[0].name == "test-srv"
        assert configs[0].command == "npx"

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text("NOT VALID JSON {{{", encoding="utf-8")
        assert _load_config_file(path) == []

    def test_missing_servers_key_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"other": "stuff"}), encoding="utf-8")
        assert _load_config_file(path) == []

    def test_servers_not_dict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"servers": "not a dict"}), encoding="utf-8")
        assert _load_config_file(path) == []

    def test_servers_as_list_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(
            json.dumps({"servers": [{"name": "bad"}]}), encoding="utf-8"
        )
        assert _load_config_file(path) == []

    def test_directory_path_returns_empty(self, tmp_path: Path) -> None:
        """Passing a directory (not a file) should return empty."""
        assert _load_config_file(tmp_path) == []

    def test_empty_servers_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"servers": {}}), encoding="utf-8")
        assert _load_config_file(path) == []

    def test_multiple_servers_in_file(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.json"
        path.write_text(
            json.dumps({
                "servers": {
                    "alpha": {"command": "cmd-a", "args": ["--flag"]},
                    "beta": {"command": "cmd-b"},
                }
            }),
            encoding="utf-8",
        )
        configs = _load_config_file(path)
        assert len(configs) == 2
        names = {c.name for c in configs}
        assert names == {"alpha", "beta"}


# =====================================================================
# load_mcp_configs -- hierarchy and merging
# =====================================================================


class TestLoadMCPConfigs:
    """Tests for load_mcp_configs hierarchy loading and deduplication."""

    def _write_config(self, path: Path, servers: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    def _patch_home(self, monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def test_empty_when_no_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        self._patch_home(monkeypatch, home)
        project = tmp_path / "project"
        project.mkdir()
        assert load_mcp_configs(str(project)) == []

    def test_loads_user_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        self._write_config(home / ".attocode" / "mcp.json", {
            "my-server": {
                "command": "node",
                "args": ["server.js"],
                "env": {"A": "1"},
            }
        })
        project = tmp_path / "project"
        project.mkdir()
        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "my-server"
        assert configs[0].command == "node"

    def test_loads_project_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "proj-server": {"command": "deno", "args": ["run", "srv.ts"]},
        })
        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "proj-server"

    def test_loads_backward_compat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        project = tmp_path / "project"
        self._write_config(project / ".mcp.json", {
            "legacy": {"command": "python", "args": ["-m", "srv"]},
        })
        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "legacy"

    def test_project_overrides_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        self._write_config(home / ".attocode" / "mcp.json", {
            "shared": {"command": "node", "args": ["old.js"]},
        })
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "shared": {"command": "deno", "args": ["new.ts"], "lazy_load": True},
        })
        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].command == "deno"
        assert configs[0].lazy_load is True

    def test_backward_compat_overrides_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`.mcp.json` is loaded last and wins over `.attocode/mcp.json`."""
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "srv": {"command": "node"},
        })
        self._write_config(project / ".mcp.json", {
            "srv": {"command": "bun"},
        })
        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].command == "bun"

    def test_merges_multiple_servers_across_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        self._write_config(home / ".attocode" / "mcp.json", {
            "alpha": {"command": "cmd-a"},
        })
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "beta": {"command": "cmd-b"},
        })
        self._write_config(project / ".mcp.json", {
            "gamma": {"command": "cmd-c"},
        })
        configs = load_mcp_configs(str(project))
        names = {c.name for c in configs}
        assert names == {"alpha", "beta", "gamma"}

    def test_invalid_json_in_one_source_does_not_block_others(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        # Write valid user-level config
        self._write_config(home / ".attocode" / "mcp.json", {
            "user-srv": {"command": "node"},
        })
        # Write invalid project-level config
        project = tmp_path / "project"
        bad_path = project / ".attocode" / "mcp.json"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("NOT JSON", encoding="utf-8")

        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "user-srv"

    def test_all_three_levels_with_partial_overlap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test all three config levels with partial server name overlap."""
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        self._write_config(home / ".attocode" / "mcp.json", {
            "shared": {"command": "user-cmd"},
            "user-only": {"command": "user-exclusive"},
        })
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "shared": {"command": "project-cmd"},
            "proj-only": {"command": "proj-exclusive"},
        })
        self._write_config(project / ".mcp.json", {
            "shared": {"command": "legacy-cmd"},
            "legacy-only": {"command": "legacy-exclusive"},
        })
        configs = load_mcp_configs(str(project))
        by_name = {c.name: c for c in configs}
        assert len(by_name) == 4
        # "shared" should be overridden by the legacy (last) level
        assert by_name["shared"].command == "legacy-cmd"
        assert by_name["user-only"].command == "user-exclusive"
        assert by_name["proj-only"].command == "proj-exclusive"
        assert by_name["legacy-only"].command == "legacy-exclusive"

    def test_enabled_and_lazy_load_preserved_through_hierarchy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        self._patch_home(monkeypatch, home)
        self._write_config(home / ".attocode" / "mcp.json", {
            "srv": {"command": "node", "enabled": True, "lazy_load": False},
        })
        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "srv": {"command": "node", "enabled": False, "lazy_load": True},
        })
        configs = load_mcp_configs(str(project))
        assert configs[0].enabled is False
        assert configs[0].lazy_load is True
