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


async def check_command(root, profile):
    """The installed command starts a stdio server that lists the daily tools and finds a file."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = Path(sys.executable).parent / "attocode-code-intel"
    version = subprocess.run(
        [command, "--version"], capture_output=True, text=True, check=True
    ).stdout
    assert version.split() == [
        "attocode-code-intel",
        importlib.metadata.version("attocode-code-intel"),
    ], version
    params = StdioServerParameters(
        command=str(command), args=["--project", str(root), "--profile", profile, "--no-watch"]
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert {"semantic_search", "inspect_symbol", "bootstrap"} <= names and len(names) < 25, (
            names
        )
        if profile == "lean":
            from attocode_intel.catalog import LEAN

            assert names == set(LEAN) | {"notify_file_changed"}, names
        # The first search can answer before the index of a new project is ready.
        for _ in range(10):
            result = await session.call_tool(
                "semantic_search", {"query": "independently installed"}
            )
            if "helper.py" in result.content[0].text:
                break
            await asyncio.sleep(2)
        else:
            raise AssertionError(
                f"semantic_search did not find helper.py: {result.content[0].text[:500]}"
            )


async def check():
    from attocode_intel.catalog import tool_catalog
    from attocode_intel.gateway import OperationGateway

    assert len(tool_catalog("full")) >= 135
    assert "inspect_symbol" in {tool.name for tool in tool_catalog("daily")}
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "helper.py").write_text("def independently_installed(): return 1\n")
        (root / "typed.ts").write_text(
            "export function typedOperation(value: number): number {\n  return value + 1;\n}\n"
        )
        (root / "caller.ts").write_text(
            "import { typedOperation } from './typed';\n"
            "export function callTyped() { return typedOperation(1); }\n"
        )
        gateway = OperationGateway(str(root), watch=False)
        try:
            result = await gateway.execute("symbols", {"path": "helper.py"})
            assert "independently_installed" in result.content[0].text
            compact = await gateway.execute(
                "inspect_symbol",
                {"symbol_name": "independently_installed", "max_tokens": 2000},
                compact=True,
            )
            from attocode_intel.output import response_tokens

            assert compact.structuredContent is None and response_tokens(compact) <= 2000
            assert (
                json.loads(compact.content[0].text)["data"]["definition"]["file_path"]
                == "helper.py"
            )
            typed = await gateway.execute(
                "inspect_symbol",
                {
                    "symbol_name": "typedOperation",
                    "file_path": "typed.ts",
                    "task_hint": "increment the value",
                    "max_tokens": 2000,
                },
                compact=True,
            )
            assert not typed.isError and response_tokens(typed) <= 2000
            assert (
                json.loads(typed.content[0].text)["data"]["definition"]["file_path"] == "typed.ts"
            )
            dependencies = await gateway.execute("dependencies", {"path": "caller.ts"})
            assert "typed.ts" in dependencies.structuredContent["data"]["imports"]
        finally:
            await gateway.close()
        for profile in ("daily", "lean"):
            await check_command(root, profile)
        await check_change_workflow(root)
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


async def check_change_workflow(temp):
    """New workflow must work from the installed distribution, including CLI exports."""
    from attocode_intel.change_evidence import check_report
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = temp / "changes repo"
    root.mkdir()
    (root / ".gitignore").write_text(".attocode/\n")
    (root / "helper.py").write_text("def helper():\n    return 1\n")
    (root / "caller.py").write_text("from helper import helper\ndef run():\n    return helper()\n")
    (root / "test_helper.py").write_text(
        "from caller import run\ndef test_run():\n    assert run() == 2\n"
    )

    def git(*args):
        subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Wheel check",
                "-c",
                "user.email=wheel-check@example.invalid",
                *args,
            ],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=15,
        )

    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "base")
    (root / "helper.py").write_text("def helper():\n    return 2\n")
    command = Path(sys.executable).parent / "attocode-code-intel"
    params = StdioServerParameters(
        command=str(command), args=["--project", str(root), "--profile", "full", "--no-watch"]
    )
    async with asyncio.timeout(45), stdio_client(params) as streams:  # noqa: SIM117
        async with ClientSession(*streams) as session:
            await session.initialize()
            assert {"change_context", "trace_flow"} <= {
                t.name for t in (await session.list_tools()).tools
            }
            result = await session.call_tool("change_context", {})
            assert not result.isError
            report = result.structuredContent["data"]
            assert report["symbols"][0]["after"]["name"] == "helper"
            assert any(
                edge["site"]["file_path"] == "caller.py"
                for edge in report["symbols"][0]["flow"]["edges"]
            )
            assert "test_helper.py" in {row["file_path"] for row in report["tests"]["candidates"]}
            assert check_report(str(root), report)["status"] == "current"
            traced = await session.call_tool(
                "trace_flow", {"symbol_name": "helper", "file_path": "helper.py"}
            )
            assert not traced.isError and traced.structuredContent["data"]["flow"]["edges"]

    def cli(*args, expected=0):
        result = subprocess.run(
            [str(command), *args, "--project", str(root)],
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == expected, result.stderr
        return result.stdout

    saved, refreshed = temp / "report.json", temp / "refreshed.json"
    cli("changes", "--output", str(saved))
    assert json.loads(cli("changes", "--check", str(saved)))["status"] == "current"
    (root / "helper.py").write_text("def helper():\n    return 3\n")
    assert json.loads(cli("changes", "--check", str(saved), expected=1))["status"] == "stale"
    cli("changes", "--refresh", str(saved), "--output", str(refreshed))
    assert json.loads(cli("changes", "--check", str(refreshed)))["status"] == "current"
    assert "# Change investigation" in cli(
        "trace", "helper", "--file", "helper.py", "--format", "markdown"
    )
    print(
        json.dumps(
            {
                "installed_change_workflow": "passed",
                "full_mcp": True,
                "cli_export_check_refresh": True,
            }
        )
    )


asyncio.run(check())
