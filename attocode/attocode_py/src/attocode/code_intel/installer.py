"""Install/uninstall attocode-code-intel MCP server into coding assistants.

Supports:
- Claude Code: via `claude mcp add` CLI
- Cursor: via `.cursor/mcp.json`
- Windsurf: via `.windsurf/mcp.json`
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_command() -> str:
    """Determine the right command to invoke the MCP server.

    Checks for the installed entry point first, then falls back to
    `python -m attocode.code_intel.server`.
    """
    # Check if attocode-code-intel entry point is on PATH
    if shutil.which("attocode-code-intel"):
        return "attocode-code-intel"

    # Fall back to module invocation
    return f"{sys.executable} -m attocode.code_intel.server"


def _build_server_entry(project_dir: str) -> dict:
    """Build the MCP server config dict for JSON-based configs."""
    cmd = _find_command()
    parts = cmd.split()
    command = parts[0]
    args = parts[1:] + ["--project", os.path.abspath(project_dir)]
    return {
        "command": command,
        "args": args,
    }


def install_claude(project_dir: str = ".", scope: str = "local") -> bool:
    """Install into Claude Code via `claude mcp add`.

    Args:
        project_dir: Path to the project to index.
        scope: "local" (project) or "user" (global).

    Returns:
        True if installation succeeded.
    """
    if not shutil.which("claude"):
        print("Error: `claude` CLI not found. Install Claude Code first.", file=sys.stderr)
        return False

    cmd = _find_command()
    parts = cmd.split()
    command = parts[0]
    server_args = parts[1:]

    # For local installs (or explicit --project), bake in the absolute path.
    # For global installs without explicit --project, omit it so the server
    # dynamically uses whatever directory Claude Code runs it from.
    if scope != "user" or project_dir != ".":
        server_args += ["--project", os.path.abspath(project_dir)]

    claude_cmd = [
        "claude", "mcp", "add",
        "--transport", "stdio",
        "--scope", scope,
        "attocode-code-intel",
        "--",
        command,
        *server_args,
    ]

    try:
        result = subprocess.run(claude_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"Installed attocode-code-intel into Claude Code (scope={scope})")
            print(f"  command: {command}")
            print(f"  args: {server_args}")
            return True
        else:
            print(f"Error installing: {result.stderr.strip()}", file=sys.stderr)
            return False
    except FileNotFoundError:
        print("Error: `claude` CLI not found.", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("Error: `claude mcp add` timed out.", file=sys.stderr)
        return False


def install_json_config(
    target: str,
    project_dir: str = ".",
) -> bool:
    """Install into Cursor or Windsurf via .mcp.json file.

    Args:
        target: "cursor" or "windsurf".
        project_dir: Path to the project to index.

    Returns:
        True if installation succeeded.
    """
    config_dirs = {
        "cursor": ".cursor",
        "windsurf": ".windsurf",
    }

    config_dir = config_dirs.get(target)
    if not config_dir:
        print(f"Error: Unknown target '{target}'", file=sys.stderr)
        return False

    config_path = Path(project_dir) / config_dir / "mcp.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    existing: dict = {}
    if config_path.exists():
        import contextlib
        with contextlib.suppress(json.JSONDecodeError, OSError):
            existing = json.loads(config_path.read_text(encoding="utf-8"))

    servers = existing.setdefault("mcpServers", {})
    servers["attocode-code-intel"] = _build_server_entry(project_dir)

    config_path.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Installed attocode-code-intel into {config_path}")
    return True


def uninstall_claude(scope: str = "local") -> bool:
    """Uninstall from Claude Code."""
    if not shutil.which("claude"):
        print("Error: `claude` CLI not found.", file=sys.stderr)
        return False

    try:
        result = subprocess.run(
            ["claude", "mcp", "remove", "--scope", scope, "attocode-code-intel"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"Removed attocode-code-intel from Claude Code (scope={scope})")
            return True
        else:
            print(f"Error removing: {result.stderr.strip()}", file=sys.stderr)
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"Error: {e}", file=sys.stderr)
        return False


def uninstall_json_config(target: str, project_dir: str = ".") -> bool:
    """Uninstall from Cursor or Windsurf."""
    config_dirs = {
        "cursor": ".cursor",
        "windsurf": ".windsurf",
    }

    config_dir = config_dirs.get(target)
    if not config_dir:
        print(f"Error: Unknown target '{target}'", file=sys.stderr)
        return False

    config_path = Path(project_dir) / config_dir / "mcp.json"
    if not config_path.exists():
        print(f"No config found at {config_path}")
        return True

    try:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    servers = existing.get("mcpServers", {})
    if "attocode-code-intel" in servers:
        del servers["attocode-code-intel"]
        config_path.write_text(
            json.dumps(existing, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Removed attocode-code-intel from {config_path}")

    return True


def install(target: str, project_dir: str = ".", scope: str = "local") -> bool:
    """Install into the given target.

    Args:
        target: "claude", "cursor", or "windsurf".
        project_dir: Path to the project to index.
        scope: For Claude: "local" or "user". Ignored for others.
    """
    if target == "claude":
        return install_claude(project_dir, scope=scope)
    elif target in ("cursor", "windsurf"):
        return install_json_config(target, project_dir)
    else:
        print(f"Error: Unknown target '{target}'. Use: claude, cursor, windsurf", file=sys.stderr)
        return False


def uninstall(target: str, project_dir: str = ".", scope: str = "local") -> bool:
    """Uninstall from the given target."""
    if target == "claude":
        return uninstall_claude(scope=scope)
    elif target in ("cursor", "windsurf"):
        return uninstall_json_config(target, project_dir)
    else:
        print(f"Error: Unknown target '{target}'. Use: claude, cursor, windsurf", file=sys.stderr)
        return False
