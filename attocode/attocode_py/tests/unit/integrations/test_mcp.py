"""Tests for MCP config, client manager, tool search, and tool validator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.mcp.client import MCPCallResult, MCPTool
from attocode.integrations.mcp.client_manager import (
    ConnectionState,
    MCPClientManager,
    ServerEntry,
)
from attocode.integrations.mcp.config import MCPServerConfig, load_mcp_configs
from attocode.integrations.mcp.tool_search import (
    MCPToolMatch,
    MCPToolSearchIndex,
    create_mcp_tool_search_tool,
)
from attocode.integrations.mcp.tool_validator import MCPToolValidator


# =====================================================================
# Config loading
# =====================================================================


class TestMCPServerConfig:
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


class TestLoadMCPConfigs:
    def _write_config(self, path: Path, servers: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    def test_empty_when_no_files(self, tmp_path: Path) -> None:
        configs = load_mcp_configs(str(tmp_path))
        assert configs == []

    def test_loads_user_level(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

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
        assert configs[0].args == ["server.js"]
        assert configs[0].env == {"A": "1"}

    def test_loads_project_level(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "proj-server": {"command": "deno", "args": ["run", "srv.ts"]},
        })

        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "proj-server"
        assert configs[0].command == "deno"

    def test_loads_backward_compat(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        project = tmp_path / "project"
        self._write_config(project / ".mcp.json", {
            "legacy-server": {"command": "python", "args": ["-m", "srv"]},
        })

        configs = load_mcp_configs(str(project))
        assert len(configs) == 1
        assert configs[0].name == "legacy-server"

    def test_project_overrides_user(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

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
        assert configs[0].args == ["new.ts"]
        assert configs[0].lazy_load is True

    def test_backward_compat_overrides_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`.mcp.json` is loaded last and wins over `.attocode/mcp.json`."""
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

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

    def test_merges_multiple_servers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        self._write_config(home / ".attocode" / "mcp.json", {
            "alpha": {"command": "cmd-a"},
        })

        project = tmp_path / "project"
        self._write_config(project / ".attocode" / "mcp.json", {
            "beta": {"command": "cmd-b"},
        })

        configs = load_mcp_configs(str(project))
        names = {c.name for c in configs}
        assert names == {"alpha", "beta"}

    def test_invalid_json_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        project = tmp_path / "project"
        bad = project / ".mcp.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("NOT JSON", encoding="utf-8")

        configs = load_mcp_configs(str(project))
        assert configs == []

    def test_missing_servers_key_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        project = tmp_path / "project"
        path = project / ".mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"other": "stuff"}), encoding="utf-8")

        configs = load_mcp_configs(str(project))
        assert configs == []


# =====================================================================
# Client manager -- lazy loading state
# =====================================================================


class TestMCPClientManagerState:
    """Test state management without requiring real subprocess connections."""

    def test_register_sets_pending(self) -> None:
        mgr = MCPClientManager()
        cfg = MCPServerConfig(name="srv", command="node")
        mgr.register(cfg)
        assert mgr.get_state("srv") == ConnectionState.PENDING

    def test_unknown_server_state_is_none(self) -> None:
        mgr = MCPClientManager()
        assert mgr.get_state("nope") is None

    def test_server_names(self) -> None:
        mgr = MCPClientManager()
        mgr.register_all([
            MCPServerConfig(name="a", command="x"),
            MCPServerConfig(name="b", command="y"),
        ])
        assert set(mgr.server_names) == {"a", "b"}

    def test_connected_count_starts_zero(self) -> None:
        mgr = MCPClientManager()
        mgr.register(MCPServerConfig(name="a", command="x"))
        assert mgr.connected_count == 0

    def test_get_all_tools_empty_when_none_connected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(MCPServerConfig(name="a", command="x"))
        assert mgr.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_disabled_server_not_connectable(self) -> None:
        mgr = MCPClientManager()
        cfg = MCPServerConfig(name="off", command="x", enabled=False)
        mgr.register(cfg)
        result = await mgr.ensure_connected("off")
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_connected_unknown_returns_false(self) -> None:
        mgr = MCPClientManager()
        result = await mgr.ensure_connected("unknown")
        assert result is False


class TestMCPClientManagerConnectEager:
    """Test connect_eager with mocked MCPClient."""

    @pytest.mark.asyncio
    async def test_eager_connects_non_lazy(self) -> None:
        mgr = MCPClientManager()
        mgr.register(MCPServerConfig(name="eager", command="node", lazy_load=False))
        mgr.register(MCPServerConfig(name="lazy", command="node", lazy_load=True))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.tools = []
        mock_client.is_connected = True

        with patch("attocode.integrations.mcp.client_manager.MCPClient", return_value=mock_client):
            connected = await mgr.connect_eager()

        assert "eager" in connected
        assert "lazy" not in connected
        assert mgr.get_state("eager") == ConnectionState.CONNECTED
        assert mgr.get_state("lazy") == ConnectionState.PENDING

    @pytest.mark.asyncio
    async def test_disabled_skipped_on_eager(self) -> None:
        mgr = MCPClientManager()
        mgr.register(MCPServerConfig(name="off", command="node", enabled=False))

        connected = await mgr.connect_eager()
        assert connected == []
        assert mgr.get_state("off") == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_failure_sets_failed(self) -> None:
        mgr = MCPClientManager()
        mgr.register(MCPServerConfig(name="bad", command="node"))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("attocode.integrations.mcp.client_manager.MCPClient", return_value=mock_client):
            connected = await mgr.connect_eager()

        assert connected == []
        assert mgr.get_state("bad") == ConnectionState.FAILED


# =====================================================================
# Tool search
# =====================================================================


def _make_tool(name: str, desc: str, server: str = "srv") -> MCPTool:
    return MCPTool(name=name, description=desc, server_name=server)


class TestMCPToolSearchIndex:
    def test_empty_index_returns_nothing(self) -> None:
        idx = MCPToolSearchIndex()
        assert idx.search("anything") == []

    def test_exact_name_match(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("read_file", "Read a file from disk"))
        results = idx.search("read file")
        assert len(results) >= 1
        assert results[0].tool_name == "read_file"
        assert results[0].relevance_score > 0

    def test_description_match(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("fetch_url", "Download content from a URL"))
        results = idx.search("download")
        assert len(results) == 1
        assert results[0].tool_name == "fetch_url"

    def test_limit_respected(self) -> None:
        idx = MCPToolSearchIndex()
        for i in range(10):
            idx.add_tool(_make_tool(f"tool_{i}", f"description with common keyword {i}"))
        results = idx.search("keyword", limit=3)
        assert len(results) == 3

    def test_no_match_returns_empty(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("alpha", "first tool"))
        results = idx.search("zzzznotfound")
        assert results == []

    def test_name_match_scores_higher_than_desc(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("search", "Find things"))
        idx.add_tool(_make_tool("other", "Has search in description"))
        results = idx.search("search")
        assert results[0].tool_name == "search"

    def test_server_name_propagated(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("read", "Read", server="my-server"))
        results = idx.search("read")
        assert results[0].server_name == "my-server"

    def test_clear(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tools([_make_tool("a", "alpha"), _make_tool("b", "beta")])
        assert idx.tool_count == 2
        idx.clear()
        assert idx.tool_count == 0
        assert idx.search("alpha") == []

    def test_empty_query_returns_empty(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("tool", "desc"))
        assert idx.search("") == []

    def test_relevance_score_capped_at_100(self) -> None:
        idx = MCPToolSearchIndex()
        # Name and description both containing many matching tokens
        idx.add_tool(_make_tool(
            "search_files_recursively",
            "Search for files recursively in a directory tree using search patterns",
        ))
        results = idx.search("search files recursively")
        assert results[0].relevance_score <= 100


class TestCreateMCPToolSearchTool:
    @pytest.mark.asyncio
    async def test_tool_callable(self) -> None:
        idx = MCPToolSearchIndex()
        idx.add_tool(_make_tool("git_commit", "Commit staged changes"))
        tool = create_mcp_tool_search_tool(idx)

        assert tool.name == "mcp_tool_search"
        result = await tool.execute({"query": "commit"})
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["tool_name"] == "git_commit"


# =====================================================================
# Tool validator
# =====================================================================


class TestMCPToolValidator:
    def _full_schema(self) -> dict:
        return {
            "description": "A well-documented tool.",
            "properties": {
                "path": {"type": "string", "description": "File path."},
                "recursive": {"type": "boolean", "description": "Recurse."},
            },
        }

    def test_perfect_score(self) -> None:
        v = MCPToolValidator()
        score = v.validate_tool("read_file", self._full_schema())
        assert score == 100

    def test_no_description_loses_25(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        del schema["description"]
        score = v.validate_tool("read_file", schema)
        assert score == 75

    def test_no_param_descriptions_loses_25(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        # Strip descriptions from params
        for p in schema["properties"].values():
            del p["description"]
        score = v.validate_tool("read_file", schema)
        assert score == 75

    def test_generic_name_loses_25(self) -> None:
        v = MCPToolValidator()
        score = v.validate_tool("run", self._full_schema())
        assert score == 75

    def test_too_many_params_loses_25(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Bloated tool.",
            "properties": {f"p{i}": {"type": "string", "description": f"param {i}"} for i in range(15)},
        }
        score = v.validate_tool("specific_tool", schema)
        assert score == 75  # lost reasonable param count

    def test_zero_params_loses_25(self) -> None:
        v = MCPToolValidator()
        schema = {"description": "No params tool.", "properties": {}}
        score = v.validate_tool("specific_tool", schema)
        # No params: loses param_count (+0), but no param descs to check either
        # Has description (+25), no param descs (+0), 0 params (+0), specific name (+25)
        assert score == 50

    def test_empty_schema_generic_name(self) -> None:
        v = MCPToolValidator()
        score = v.validate_tool("do", {})
        assert score == 0

    def test_validate_result_none(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", None) is False

    def test_validate_result_empty_string(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", "") is False
        assert v.validate_result("tool", "   ") is False

    def test_validate_result_empty_list(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", []) is False

    def test_validate_result_empty_dict(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {}) is False

    def test_validate_result_error_dict(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {"error": "something went wrong"}) is False

    def test_validate_result_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", "ok") is True
        assert v.validate_result("tool", [1, 2, 3]) is True
        assert v.validate_result("tool", {"data": "value"}) is True
        assert v.validate_result("tool", 42) is True
