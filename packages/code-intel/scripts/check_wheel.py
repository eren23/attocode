"""Run using only the installed wheel in a clean environment."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    importlib.metadata.distribution("attocode")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError("Wheel verification must run without the attocode distribution")


class NoAgent:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "attocode",
            "attoswarm",
            "attocode_core",
            "textual",
            "anthropic",
            "openai",
        }:
            raise AssertionError(f"Standalone intelligence imported {fullname}")
        return None


sys.meta_path.insert(0, NoAgent())


async def check_command(root):
    """The installed command starts a stdio server that lists the daily tools and finds a file."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = Path(sys.executable).parent / "attocode-code-intel"
    version = subprocess.run([command, "--version"], capture_output=True, text=True, check=True).stdout
    assert version.split() == ["attocode-code-intel", importlib.metadata.version("attocode-code-intel")], version
    params = StdioServerParameters(
        command=str(command), args=["--project", str(root), "--profile", "daily", "--no-watch"]
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert {"semantic_search", "inspect_symbol", "bootstrap"} <= names and len(names) < 25, names
        # The first search can answer before the index of a new project is ready.
        for _ in range(10):
            result = await session.call_tool("semantic_search", {"query": "independently installed"})
            if "helper.py" in result.content[0].text:
                break
            await asyncio.sleep(2)
        else:
            raise AssertionError(f"semantic_search did not find helper.py: {result.content[0].text[:500]}")


async def check():
    from attocode_intel.catalog import tool_catalog
    from attocode_intel.gateway import OperationGateway

    assert len(tool_catalog("full")) >= 135
    assert "inspect_symbol" in {tool.name for tool in tool_catalog("daily")}
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "helper.py").write_text("def independently_installed(): return 1\n")
        (root / "typed.ts").write_text(
            "export function typedOperation(value: number): number {\n"
            "  return value + 1;\n"
            "}\n"
        )
        (root / "caller.ts").write_text(
            "import { typedOperation } from './typed';\n"
            "export function callTyped() { return typedOperation(1); }\n"
        )
        gateway = OperationGateway(str(root), watch=False)
        try:
            result = await gateway.execute("symbols", {"path": "helper.py"})
            assert "independently_installed" in result.content[0].text
            compact = await gateway.execute("inspect_symbol", {"symbol_name": "independently_installed", "max_tokens": 2000}, compact=True)
            from attocode_intel.output import response_tokens
            assert compact.structuredContent is None and response_tokens(compact) <= 2000
            assert json.loads(compact.content[0].text)["data"]["definition"]["file_path"] == "helper.py"
            typed = await gateway.execute(
                "inspect_symbol",
                {"symbol_name": "typedOperation", "file_path": "typed.ts",
                 "task_hint": "increment the value", "max_tokens": 2000},
                compact=True,
            )
            assert not typed.isError and response_tokens(typed) <= 2000
            assert json.loads(typed.content[0].text)["data"]["definition"]["file_path"] == "typed.ts"
            dependencies = await gateway.execute("dependencies", {"path": "caller.ts"})
            assert "typed.ts" in dependencies.structuredContent["data"]["imports"]
        finally:
            await gateway.close()
        await check_command(root)
    from attocode_intel.rules.loader import load_builtin_rules

    assert load_builtin_rules(), "Builtin assets missing from wheel"
    print(
        json.dumps(
            {
                "version": importlib.metadata.version("attocode-code-intel"),
                "tools": len(tool_catalog()),
                "agent_required": False,
            }
        )
    )


asyncio.run(check())
