"""Tests for MCP server scaffolder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from attocode.integrations.mcp.scaffolder import (
    MCPScaffolder,
    MCPScaffolderError,
    MCPServerSpec,
    MCPToolSpec as ToolSpec,
)


class TestMCPScaffolder:
    def test_scaffold_creates_files(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        spec = MCPServerSpec(
            name="greeting",
            description="A greeting server",
            tools=[ToolSpec(name="greet", description="Say hello")],
        )
        result = scaffolder.scaffold(spec)
        assert (result / "server.py").exists()
        assert (result / "spec.json").exists()

    def test_scaffold_server_code(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        spec = MCPServerSpec(
            name="math_tools",
            description="Math utilities",
            tools=[
                ToolSpec(
                    name="add",
                    description="Add numbers",
                    parameters={"properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
                    implementation="return str(a + b)",
                ),
            ],
        )
        result = scaffolder.scaffold(spec)
        code = (result / "server.py").read_text()
        assert "FastMCP" in code
        assert "def add" in code
        assert "return str(a + b)" in code

    def test_scaffold_spec_roundtrip(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        spec = MCPServerSpec(
            name="test_server",
            description="Test",
            tools=[ToolSpec(name="foo", description="Do foo")],
        )
        result = scaffolder.scaffold(spec)
        data = json.loads((result / "spec.json").read_text())
        assert data["name"] == "test_server"
        assert len(data["tools"]) == 1

    def test_scaffold_invalid_name(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        spec = MCPServerSpec(name="123-bad", description="Bad", tools=[ToolSpec(name="t", description="d")])
        with pytest.raises(MCPScaffolderError, match="Invalid"):
            scaffolder.scaffold(spec)

    def test_scaffold_no_tools(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        spec = MCPServerSpec(name="empty", description="No tools")
        with pytest.raises(MCPScaffolderError, match="at least one"):
            scaffolder.scaffold(spec)

    def test_scaffold_no_dir(self) -> None:
        scaffolder = MCPScaffolder()
        spec = MCPServerSpec(name="x", description="x", tools=[ToolSpec(name="t", description="d")])
        with pytest.raises(MCPScaffolderError, match="directory"):
            scaffolder.scaffold(spec)

    def test_list_servers(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        scaffolder.scaffold(MCPServerSpec(
            name="srv1", description="Server 1",
            tools=[ToolSpec(name="t1", description="d1")],
        ))
        scaffolder.scaffold(MCPServerSpec(
            name="srv2", description="Server 2",
            tools=[ToolSpec(name="t2", description="d2")],
        ))
        servers = scaffolder.list_servers()
        assert len(servers) == 2
        names = {s["name"] for s in servers}
        assert names == {"srv1", "srv2"}

    def test_list_servers_empty(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "nonexistent")
        assert scaffolder.list_servers() == []

    def test_get_server_command(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        scaffolder.scaffold(MCPServerSpec(
            name="myserver", description="My server",
            tools=[ToolSpec(name="t", description="d")],
        ))
        cmd = scaffolder.get_server_command("myserver")
        assert cmd is not None
        assert "python3" in cmd[0]
        assert "server.py" in cmd[1]

    def test_get_server_command_missing(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        assert scaffolder.get_server_command("nonexistent") is None

    def test_scaffolded_servers_dict(self, tmp_path: Path) -> None:
        scaffolder = MCPScaffolder(servers_dir=tmp_path / "servers")
        scaffolder.scaffold(MCPServerSpec(
            name="test", description="Test",
            tools=[ToolSpec(name="t", description="d")],
        ))
        assert "test" in scaffolder.scaffolded_servers
