"""Comprehensive tests for MCP client manager.

Covers MCPClientManager registration, connection lifecycle (eager/lazy),
tool access, introspection, and error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.mcp.client import MCPCallResult, MCPTool
from attocode.integrations.mcp.client_manager import (
    ConnectionState,
    MCPClientManager,
    ServerEntry,
)
from attocode.integrations.mcp.config import MCPServerConfig


# =====================================================================
# Helpers
# =====================================================================


def _make_config(
    name: str = "test",
    command: str = "node",
    *,
    enabled: bool = True,
    lazy_load: bool = False,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        command=command,
        args=args or [],
        env=env or {},
        enabled=enabled,
        lazy_load=lazy_load,
    )


def _make_mock_client(
    tools: list[MCPTool] | None = None,
    call_result: MCPCallResult | None = None,
) -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.tools = tools or []
    client.is_connected = True
    if call_result is not None:
        client.call_tool = AsyncMock(return_value=call_result)
    else:
        client.call_tool = AsyncMock(
            return_value=MCPCallResult(success=True, result="ok")
        )
    return client


def _make_tool(name: str, desc: str = "A tool", server: str = "srv") -> MCPTool:
    return MCPTool(name=name, description=desc, server_name=server)


# =====================================================================
# ConnectionState enum
# =====================================================================


class TestConnectionState:
    def test_values(self) -> None:
        assert ConnectionState.PENDING == "pending"
        assert ConnectionState.CONNECTING == "connecting"
        assert ConnectionState.CONNECTED == "connected"
        assert ConnectionState.FAILED == "failed"
        assert ConnectionState.DISCONNECTED == "disconnected"

    def test_all_states_exist(self) -> None:
        states = {s.value for s in ConnectionState}
        assert states == {"pending", "connecting", "connected", "failed", "disconnected"}


# =====================================================================
# ServerEntry dataclass
# =====================================================================


class TestServerEntry:
    def test_defaults(self) -> None:
        cfg = _make_config()
        entry = ServerEntry(config=cfg)
        assert entry.client is None
        assert entry.state == ConnectionState.PENDING
        assert entry.error is None

    def test_custom_fields(self) -> None:
        cfg = _make_config()
        client = _make_mock_client()
        entry = ServerEntry(
            config=cfg,
            client=client,
            state=ConnectionState.CONNECTED,
            error=None,
        )
        assert entry.client is client
        assert entry.state == ConnectionState.CONNECTED


# =====================================================================
# Registration
# =====================================================================


class TestMCPClientManagerRegistration:
    def test_register_single(self) -> None:
        mgr = MCPClientManager()
        cfg = _make_config(name="srv")
        mgr.register(cfg)
        assert "srv" in mgr.server_names
        assert mgr.get_state("srv") == ConnectionState.PENDING

    def test_register_all(self) -> None:
        mgr = MCPClientManager()
        configs = [
            _make_config(name="a"),
            _make_config(name="b"),
            _make_config(name="c"),
        ]
        mgr.register_all(configs)
        assert set(mgr.server_names) == {"a", "b", "c"}

    def test_register_overwrites_existing(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv", command="old"))
        mgr.register(_make_config(name="srv", command="new"))
        assert len(mgr.server_names) == 1

    def test_register_all_empty_list(self) -> None:
        mgr = MCPClientManager()
        mgr.register_all([])
        assert mgr.server_names == []


# =====================================================================
# Introspection
# =====================================================================


class TestMCPClientManagerIntrospection:
    def test_server_names_empty_initially(self) -> None:
        mgr = MCPClientManager()
        assert mgr.server_names == []

    def test_connected_count_zero_initially(self) -> None:
        mgr = MCPClientManager()
        assert mgr.connected_count == 0

    def test_connected_count_after_registration_is_zero(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="a"))
        mgr.register(_make_config(name="b"))
        assert mgr.connected_count == 0

    def test_get_state_unknown_server(self) -> None:
        mgr = MCPClientManager()
        assert mgr.get_state("nonexistent") is None

    def test_get_state_registered_server(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))
        assert mgr.get_state("srv") == ConnectionState.PENDING


# =====================================================================
# connect_eager
# =====================================================================


class TestMCPClientManagerConnectEager:
    @pytest.mark.asyncio
    async def test_connects_non_lazy_servers(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="eager", lazy_load=False))
        mgr.register(_make_config(name="lazy", lazy_load=True))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            connected = await mgr.connect_eager()

        assert "eager" in connected
        assert "lazy" not in connected
        assert mgr.get_state("eager") == ConnectionState.CONNECTED
        assert mgr.get_state("lazy") == ConnectionState.PENDING

    @pytest.mark.asyncio
    async def test_disabled_servers_set_to_disconnected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="off", enabled=False))

        connected = await mgr.connect_eager()
        assert connected == []
        assert mgr.get_state("off") == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connection_failure_sets_failed(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="bad"))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=RuntimeError("connection refused"))
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            connected = await mgr.connect_eager()

        assert connected == []
        assert mgr.get_state("bad") == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_connection_failure_records_error_message(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="bad"))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=ValueError("port in use"))
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        entry = mgr._servers["bad"]
        assert entry.error == "port in use"

    @pytest.mark.asyncio
    async def test_connected_count_after_eager(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="a"))
        mgr.register(_make_config(name="b"))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        assert mgr.connected_count == 2

    @pytest.mark.asyncio
    async def test_multiple_eager_with_mixed_results(self) -> None:
        """One server connects, another fails."""
        mgr = MCPClientManager()
        mgr.register(_make_config(name="good"))
        mgr.register(_make_config(name="bad"))

        call_count = 0

        def client_factory(**kwargs):
            nonlocal call_count
            call_count += 1
            client = MagicMock()
            if call_count == 1:
                client.connect = AsyncMock()
                client.tools = []
            else:
                client.connect = AsyncMock(side_effect=OSError("fail"))
                client.tools = []
            return client

        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            side_effect=client_factory,
        ):
            connected = await mgr.connect_eager()

        assert len(connected) == 1
        assert mgr.connected_count == 1

    @pytest.mark.asyncio
    async def test_no_servers_returns_empty(self) -> None:
        mgr = MCPClientManager()
        connected = await mgr.connect_eager()
        assert connected == []


# =====================================================================
# ensure_connected
# =====================================================================


class TestMCPClientManagerEnsureConnected:
    @pytest.mark.asyncio
    async def test_unknown_server_returns_false(self) -> None:
        mgr = MCPClientManager()
        assert await mgr.ensure_connected("nonexistent") is False

    @pytest.mark.asyncio
    async def test_already_connected_returns_true(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        # Already connected -- should return True without reconnecting
        result = await mgr.ensure_connected("srv")
        assert result is True

    @pytest.mark.asyncio
    async def test_disabled_server_returns_false(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="off", enabled=False))
        assert await mgr.ensure_connected("off") is False

    @pytest.mark.asyncio
    async def test_lazy_server_connects_on_demand(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="lazy", lazy_load=True))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            result = await mgr.ensure_connected("lazy")

        assert result is True
        assert mgr.get_state("lazy") == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_ensure_connected_failure(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=ConnectionError("timeout"))
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            result = await mgr.ensure_connected("srv")

        assert result is False
        assert mgr.get_state("srv") == ConnectionState.FAILED


# =====================================================================
# disconnect / disconnect_all
# =====================================================================


class TestMCPClientManagerDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_all(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="a"))
        mgr.register(_make_config(name="b"))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()
            assert mgr.connected_count == 2

        await mgr.disconnect_all()
        assert mgr.connected_count == 0
        assert mgr.get_state("a") == ConnectionState.DISCONNECTED
        assert mgr.get_state("b") == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_single(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="a"))
        mgr.register(_make_config(name="b"))

        mock_client_a = _make_mock_client()
        mock_client_b = _make_mock_client()
        clients = iter([mock_client_a, mock_client_b])

        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            side_effect=lambda **kw: next(clients),
        ):
            await mgr.connect_eager()

        await mgr.disconnect("a")
        assert mgr.get_state("a") == ConnectionState.DISCONNECTED
        assert mgr.get_state("b") == ConnectionState.CONNECTED
        assert mgr.connected_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_unknown_server_no_error(self) -> None:
        mgr = MCPClientManager()
        await mgr.disconnect("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_disconnect_pending_server_no_error(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="pending"))
        await mgr.disconnect("pending")  # No client, should not raise
        assert mgr.get_state("pending") == ConnectionState.PENDING

    @pytest.mark.asyncio
    async def test_disconnect_sets_client_to_none(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()
        assert mgr._servers["srv"].client is not None

        await mgr.disconnect("srv")
        assert mgr._servers["srv"].client is None

    @pytest.mark.asyncio
    async def test_disconnect_all_calls_client_disconnect(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        await mgr.disconnect_all()
        mock_client.disconnect.assert_called_once()


# =====================================================================
# Tool access -- get_all_tools / get_tools_for_server
# =====================================================================


class TestMCPClientManagerToolAccess:
    def test_get_all_tools_empty_when_none_connected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))
        assert mgr.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_get_all_tools_returns_tools_from_connected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        tools = [_make_tool("read"), _make_tool("write")]
        mock_client = _make_mock_client(tools=tools)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        result = mgr.get_all_tools()
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"read", "write"}

    @pytest.mark.asyncio
    async def test_get_all_tools_from_multiple_servers(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="a"))
        mgr.register(_make_config(name="b"))

        tools_a = [_make_tool("tool_a")]
        tools_b = [_make_tool("tool_b")]
        clients = iter([
            _make_mock_client(tools=tools_a),
            _make_mock_client(tools=tools_b),
        ])
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            side_effect=lambda **kw: next(clients),
        ):
            await mgr.connect_eager()

        result = mgr.get_all_tools()
        names = {t.name for t in result}
        assert names == {"tool_a", "tool_b"}

    def test_get_tools_for_unknown_server(self) -> None:
        mgr = MCPClientManager()
        assert mgr.get_tools_for_server("nope") == []

    def test_get_tools_for_pending_server(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))
        assert mgr.get_tools_for_server("srv") == []

    @pytest.mark.asyncio
    async def test_get_tools_for_connected_server(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        tools = [_make_tool("my_tool")]
        mock_client = _make_mock_client(tools=tools)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        result = mgr.get_tools_for_server("srv")
        assert len(result) == 1
        assert result[0].name == "my_tool"


# =====================================================================
# call_tool
# =====================================================================


class TestMCPClientManagerCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_on_connected_server(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        expected_result = MCPCallResult(success=True, result="hello")
        tools = [_make_tool("greet")]
        mock_client = _make_mock_client(tools=tools, call_result=expected_result)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()
            result = await mgr.call_tool("greet", {"name": "world"})

        assert result.success is True
        assert result.result == "hello"
        mock_client.call_tool.assert_called_once_with("greet", {"name": "world"})

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = _make_mock_client(tools=[])
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()
            result = await mgr.call_tool("nonexistent", {})

        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_call_tool_triggers_lazy_connect(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="lazy-srv", lazy_load=True))

        expected_result = MCPCallResult(success=True, result="lazy-result")
        tools = [_make_tool("lazy_tool")]
        mock_client = _make_mock_client(tools=tools, call_result=expected_result)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            result = await mgr.call_tool("lazy_tool", {"key": "value"})

        assert result.success is True
        assert result.result == "lazy-result"
        assert mgr.get_state("lazy-srv") == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_call_tool_lazy_connect_fails(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="bad-lazy", lazy_load=True))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            result = await mgr.call_tool("any_tool", {})

        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_call_tool_no_servers_registered(self) -> None:
        mgr = MCPClientManager()
        result = await mgr.call_tool("tool", {})
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_call_tool_finds_correct_server(self) -> None:
        """When multiple servers are connected, finds the tool on the right server."""
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv-a"))
        mgr.register(_make_config(name="srv-b"))

        result_a = MCPCallResult(success=True, result="from-a")
        result_b = MCPCallResult(success=True, result="from-b")

        client_a = _make_mock_client(
            tools=[_make_tool("tool_a")],
            call_result=result_a,
        )
        client_b = _make_mock_client(
            tools=[_make_tool("tool_b")],
            call_result=result_b,
        )
        clients = iter([client_a, client_b])
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            side_effect=lambda **kw: next(clients),
        ):
            await mgr.connect_eager()

        r = await mgr.call_tool("tool_b", {})
        assert r.success is True
        assert r.result == "from-b"

    @pytest.mark.asyncio
    async def test_call_tool_with_disabled_lazy_server(self) -> None:
        """Disabled lazy servers should not be connected during call_tool."""
        mgr = MCPClientManager()
        mgr.register(_make_config(name="disabled-lazy", lazy_load=True, enabled=False))

        result = await mgr.call_tool("some_tool", {})
        assert result.success is False


# =====================================================================
# get_tool_summaries
# =====================================================================


class TestMCPClientManagerToolSummaries:
    def test_empty_when_nothing_connected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))
        assert mgr.get_tool_summaries() == []

    @pytest.mark.asyncio
    async def test_returns_summaries_from_connected(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="my-srv"))

        tools = [
            _make_tool("read_file", "Read a file"),
            _make_tool("write_file", "Write a file"),
        ]
        mock_client = _make_mock_client(tools=tools)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        summaries = mgr.get_tool_summaries()
        assert len(summaries) == 2
        assert summaries[0]["name"] == "read_file"
        assert summaries[0]["description"] == "Read a file"
        assert summaries[0]["server"] == "my-srv"

    @pytest.mark.asyncio
    async def test_skips_pending_lazy_servers(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="eager", lazy_load=False))
        mgr.register(_make_config(name="lazy", lazy_load=True))

        tools = [_make_tool("eager_tool")]
        mock_client = _make_mock_client(tools=tools)
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        summaries = mgr.get_tool_summaries()
        assert len(summaries) == 1
        assert summaries[0]["name"] == "eager_tool"

    @pytest.mark.asyncio
    async def test_summaries_from_multiple_servers(self) -> None:
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv-a"))
        mgr.register(_make_config(name="srv-b"))

        client_a = _make_mock_client(tools=[_make_tool("tool_a", "desc_a")])
        client_b = _make_mock_client(tools=[_make_tool("tool_b", "desc_b")])
        clients = iter([client_a, client_b])
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            side_effect=lambda **kw: next(clients),
        ):
            await mgr.connect_eager()

        summaries = mgr.get_tool_summaries()
        assert len(summaries) == 2
        servers = {s["server"] for s in summaries}
        assert servers == {"srv-a", "srv-b"}


# =====================================================================
# _connect internal method
# =====================================================================


class TestMCPClientManagerConnect:
    @pytest.mark.asyncio
    async def test_connect_passes_config_to_client(self) -> None:
        mgr = MCPClientManager()
        cfg = _make_config(
            name="srv",
            command="npx",
            args=["-y", "@test/server"],
            env={"KEY": "val"},
        )
        mgr.register(cfg)

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ) as mock_cls:
            await mgr.connect_eager()

        mock_cls.assert_called_once_with(
            server_command="npx",
            server_args=["-y", "@test/server"],
            server_name="srv",
            env={"KEY": "val"},
        )

    @pytest.mark.asyncio
    async def test_connect_with_empty_env_passes_none(self) -> None:
        mgr = MCPClientManager()
        cfg = _make_config(name="srv", env={})
        mgr.register(cfg)

        mock_client = _make_mock_client()
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ) as mock_cls:
            await mgr.connect_eager()

        # env={} is falsy, so `or None` in _connect yields None
        mock_cls.assert_called_once_with(
            server_command="node",
            server_args=[],
            server_name="srv",
            env=None,
        )

    @pytest.mark.asyncio
    async def test_connect_sets_connecting_then_connected(self) -> None:
        """State transitions through CONNECTING to CONNECTED on success."""
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        states_seen: list[ConnectionState] = []

        original_connect = AsyncMock()

        async def track_connect():
            states_seen.append(mgr._servers["srv"].state)
            await original_connect()

        mock_client = _make_mock_client()
        mock_client.connect = track_connect
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            await mgr.connect_eager()

        assert ConnectionState.CONNECTING in states_seen
        assert mgr.get_state("srv") == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_catches_any_exception(self) -> None:
        """Any exception type should be caught and set FAILED state."""
        mgr = MCPClientManager()
        mgr.register(_make_config(name="srv"))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=TypeError("unexpected"))
        with patch(
            "attocode.integrations.mcp.client_manager.MCPClient",
            return_value=mock_client,
        ):
            connected = await mgr.connect_eager()

        assert connected == []
        assert mgr.get_state("srv") == ConnectionState.FAILED
        assert mgr._servers["srv"].error == "unexpected"
