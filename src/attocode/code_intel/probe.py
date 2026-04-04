"""Runtime MCP install probing for file-based assistant configurations."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace

from attocode.code_intel.installer import ResolvedInstallSpec, resolve_install_spec
from attocode.integrations.mcp.client import MCPClient


def _substitute_workspace_folder(value: str, project_dir: str) -> str:
    return value.replace("${workspaceFolder}", project_dir)


def _materialize_spec(spec: ResolvedInstallSpec, project_dir: str) -> ResolvedInstallSpec:
    """Resolve runtime placeholders before spawning the stdio process."""
    env = {
        key: _substitute_workspace_folder(value, project_dir)
        for key, value in spec.env.items()
    }
    return replace(
        spec,
        command=_substitute_workspace_folder(spec.command, project_dir),
        args=[_substitute_workspace_folder(arg, project_dir) for arg in spec.args],
        env=env,
    )


def _has_concrete_project_arg(args: list[str]) -> bool:
    for idx, arg in enumerate(args):
        if arg == "--project" and idx + 1 < len(args):
            return True
        if arg.startswith("--project="):
            return True
    return False


async def _run_probe(
    spec: ResolvedInstallSpec,
    *,
    project_dir: str,
    should_call_project_summary: bool,
) -> tuple[int, int]:
    client = MCPClient(
        spec.command,
        server_args=spec.args,
        server_name=spec.target,
        env=spec.env,
        cwd=project_dir,
    )
    try:
        await client.connect()
        if not client.is_connected:
            raise RuntimeError("MCP initialize did not complete")
        if should_call_project_summary:
            result = await client.call_tool("project_summary", {"max_tokens": 128})
            if not result.success:
                raise RuntimeError(result.error or "project_summary probe failed")
        return len(client.tools), 0
    finally:
        await client.disconnect()


def probe_install(
    target: str,
    project_dir: str = ".",
    scope: str = "local",
    *,
    force_project_probe: bool = False,
) -> int:
    """Run a runtime MCP probe for an installed assistant target.

    Exit codes:
      0: success
      1: target missing or probe failed
      2: unsupported target for v1 probing
    """
    abs_project = os.path.abspath(project_dir)
    resolved = resolve_install_spec(target, project_dir=abs_project, scope=scope)
    if resolved is None:
        print(f"{target}: attocode-code-intel is not installed for scope={scope}.", file=sys.stderr)
        return 1
    if not resolved.is_supported:
        print(f"{target}: {resolved.unsupported_reason}", file=sys.stderr)
        return 2

    runtime_spec = _materialize_spec(resolved, abs_project)
    should_call_project_summary = force_project_probe or _has_concrete_project_arg(runtime_spec.args)

    try:
        tools_count, _ = asyncio.run(
            _run_probe(
                runtime_spec,
                project_dir=abs_project,
                should_call_project_summary=should_call_project_summary,
            )
        )
    except Exception as exc:
        print(f"{target}: probe failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1

    project_note = " with project_summary probe" if should_call_project_summary else ""
    print(
        f"{target}: probe succeeded{project_note} "
        f"({runtime_spec.command} {' '.join(runtime_spec.args)}; tools={tools_count})"
    )
    return 0
