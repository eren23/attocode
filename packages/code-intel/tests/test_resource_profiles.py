"""MCP clients discover only resources that the active profile can read."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError


@asynccontextmanager
async def resource_session(tmp_path, profile):
    (tmp_path / "helper.py").write_text("def resource_helper():\n    return 1\n")
    (tmp_path / "caller.py").write_text("from helper import resource_helper\nresource_helper()\n")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "attocode_intel.entrypoint", "--project", str(tmp_path),
              "--profile", profile, "--no-watch"],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
             "ATTOCODE_INTEL_PRECISION": "off"},
    )
    async with asyncio.timeout(30), stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


@pytest.mark.parametrize("profile", ["daily", "full", "lean"])
async def test_advertised_resources_are_readable(tmp_path, profile, record_property):
    async with resource_session(tmp_path, profile) as session:
        if profile == "full":
            result = await session.call_tool("record_learning", {
                "type": "convention", "description": "Resources retain repository knowledge",
            })
            assert not result.isError, result
        resources = await session.list_resources()
        assert [str(item.uri) for item in resources.resources] == ["attocode://guidelines"]
        guidelines = await session.read_resource("attocode://guidelines")
        assert "bootstrap" in guidelines.contents[0].text
        templates = [item.uriTemplate for item in
                     (await session.list_resource_templates()).resourceTemplates]
        examples = {
            "attocode://project/{path}{?workspace,revision}":
                ("attocode://project/helper.py", "resource_helper"),
            "attocode://symbols/{name}{?workspace,revision}":
                ("attocode://symbols/resource_helper", "caller.py"),
            "attocode://learnings{?workspace,revision}":
                ("attocode://learnings", "Resources retain repository knowledge"
                 if profile == "full" else "No learnings"),
        }
        unreadable = []
        for template in templates:
            uri, expected_text = examples[template]
            try:
                resource = await session.read_resource(uri)
            except McpError:
                unreadable.append(uri)
            else:
                assert expected_text in resource.contents[0].text
    record_property("profile", profile)
    record_property("guidelines_read", "true")
    record_property("unreadable_resources", ",".join(sorted(unreadable)))
    assert not unreadable, "REGRESSION: profile advertises unreadable resource templates"
    expected = {
        "daily": ["attocode://project/{path}{?workspace,revision}",
                  "attocode://symbols/{name}{?workspace,revision}"],
        "full": ["attocode://project/{path}{?workspace,revision}",
                 "attocode://symbols/{name}{?workspace,revision}",
                 "attocode://learnings{?workspace,revision}"],
        "lean": [],
    }
    assert templates == expected[profile]


@pytest.mark.parametrize("profile,uri,reason", [
    pytest.param("daily", "attocode://learnings", "not available", id="daily-knowledge"),
    pytest.param("lean", "attocode://project/helper.py", "full-profile", id="lean-project"),
    pytest.param("lean", "attocode://symbols/resource_helper", "full-profile", id="lean-symbols"),
    pytest.param("lean", "attocode://learnings", "full-profile", id="lean-knowledge"),
])
async def test_excluded_resources_stay_unavailable(tmp_path, profile, uri, reason):
    async with resource_session(tmp_path, profile) as session:
        with pytest.raises(McpError, match=reason):
            await session.read_resource(uri)
