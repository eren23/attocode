"""Install/uninstall attocode-code-intel MCP server into coding assistants.

Supports:
- Claude Code: via `claude mcp add` CLI
- Cursor: via `.cursor/mcp.json`
- Windsurf: via `.windsurf/mcp.json`
- VS Code: via `.vscode/mcp.json`
- Codex: via `.codex/config.toml`
- Claude Desktop: via platform-specific `claude_desktop_config.json`
- Cline: via VS Code globalStorage `cline_mcp_settings.json`
- Zed: via `.zed/settings.json` or `~/.config/zed/settings.json`
- IntelliJ / OpenCode: manual instructions
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import tomli_w

# ---------------------------------------------------------------------------
# Target constants
# ---------------------------------------------------------------------------

#: Targets that can be auto-installed via config file manipulation or CLI.
AUTO_INSTALL_TARGETS: tuple[str, ...] = (
    "claude", "cursor", "windsurf", "vscode", "codex",
    "claude-desktop", "cline", "zed",
)

#: Targets that only support manual setup instructions.
MANUAL_TARGETS: tuple[str, ...] = ("intellij", "opencode")

#: All recognised target names.
ALL_TARGETS: tuple[str, ...] = AUTO_INSTALL_TARGETS + MANUAL_TARGETS

#: Friendly string for error messages.
ALL_TARGETS_STR: str = ", ".join(ALL_TARGETS)


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
    """Install into Cursor, Windsurf, or VS Code via .mcp.json file.

    Args:
        target: "cursor", "windsurf", or "vscode".
        project_dir: Path to the project to index.

    Returns:
        True if installation succeeded.
    """
    config_dirs = {
        "cursor": ".cursor",
        "windsurf": ".windsurf",
        "vscode": ".vscode",
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
    """Uninstall from Cursor, Windsurf, or VS Code."""
    config_dirs = {
        "cursor": ".cursor",
        "windsurf": ".windsurf",
        "vscode": ".vscode",
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


def install_codex(project_dir: str = ".", scope: str = "local") -> bool:
    """Install into OpenAI Codex CLI via `.codex/config.toml`.

    Args:
        project_dir: Path to the project to index.
        scope: "local" (project) or "user" (global ~/.codex/).

    Returns:
        True if installation succeeded.
    """
    if scope == "user":
        config_path = Path.home() / ".codex" / "config.toml"
    else:
        config_path = Path(project_dir) / ".codex" / "config.toml"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    existing: dict = {}
    if config_path.exists():
        import contextlib
        with contextlib.suppress(tomllib.TOMLDecodeError, OSError):
            existing = tomllib.loads(config_path.read_text(encoding="utf-8"))

    entry = _build_server_entry(project_dir)
    servers = existing.setdefault("mcp_servers", {})
    servers["attocode-code-intel"] = {
        "command": entry["command"],
        "args": entry["args"],
    }

    config_path.write_text(
        tomli_w.dumps(existing),
        encoding="utf-8",
    )
    print(f"Installed attocode-code-intel into {config_path}")
    return True


def uninstall_codex(project_dir: str = ".", scope: str = "local") -> bool:
    """Uninstall from OpenAI Codex CLI."""
    if scope == "user":
        config_path = Path.home() / ".codex" / "config.toml"
    else:
        config_path = Path(project_dir) / ".codex" / "config.toml"

    if not config_path.exists():
        print(f"No config found at {config_path}")
        return True

    try:
        existing = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return True

    servers = existing.get("mcp_servers", {})
    if "attocode-code-intel" in servers:
        del servers["attocode-code-intel"]
        config_path.write_text(
            tomli_w.dumps(existing),
            encoding="utf-8",
        )
        print(f"Removed attocode-code-intel from {config_path}")

    return True


# ---------------------------------------------------------------------------
# Platform-specific config path resolver
# ---------------------------------------------------------------------------


def _get_user_config_dir(app: str) -> Path | None:
    """Return the platform-specific user config directory for *app*.

    Supported apps:
      - ``"claude-desktop"`` — Claude Desktop's config dir
      - ``"cline"``         — Cline extension globalStorage inside VS Code

    Returns ``None`` for unsupported (app, platform) combinations.
    """
    system = platform.system()  # "Darwin", "Linux", "Windows"

    if app == "claude-desktop":
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Claude"
        if system == "Linux":
            return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude"
        if system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                return Path(appdata) / "Claude"
        return None

    if app == "cline":
        if system == "Darwin":
            return (
                Path.home()
                / "Library"
                / "Application Support"
                / "Code"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
            )
        if system == "Linux":
            return (
                Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
                / "Code"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
            )
        if system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                return (
                    Path(appdata)
                    / "Code"
                    / "User"
                    / "globalStorage"
                    / "saoudrizwan.claude-dev"
                )
        return None

    return None


# ---------------------------------------------------------------------------
# Claude Desktop
# ---------------------------------------------------------------------------


def install_claude_desktop(project_dir: str = ".") -> bool:
    """Install into Claude Desktop via ``claude_desktop_config.json``.

    Returns True if installation succeeded.
    """
    config_dir = _get_user_config_dir("claude-desktop")
    if config_dir is None:
        print(
            f"Error: Claude Desktop config path not supported on {platform.system()}",
            file=sys.stderr,
        )
        return False

    config_path = config_dir / "claude_desktop_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

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


def uninstall_claude_desktop() -> bool:
    """Uninstall from Claude Desktop."""
    config_dir = _get_user_config_dir("claude-desktop")
    if config_dir is None:
        print(
            f"Error: Claude Desktop config path not supported on {platform.system()}",
            file=sys.stderr,
        )
        return False

    config_path = config_dir / "claude_desktop_config.json"
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


# ---------------------------------------------------------------------------
# Cline (VS Code extension)
# ---------------------------------------------------------------------------


def install_cline(project_dir: str = ".") -> bool:
    """Install into Cline via ``cline_mcp_settings.json``.

    Returns True if installation succeeded.
    """
    config_dir = _get_user_config_dir("cline")
    if config_dir is None:
        print(
            f"Error: Cline config path not supported on {platform.system()}",
            file=sys.stderr,
        )
        return False

    config_path = config_dir / "cline_mcp_settings.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

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


def uninstall_cline() -> bool:
    """Uninstall from Cline."""
    config_dir = _get_user_config_dir("cline")
    if config_dir is None:
        print(
            f"Error: Cline config path not supported on {platform.system()}",
            file=sys.stderr,
        )
        return False

    config_path = config_dir / "cline_mcp_settings.json"
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


# ---------------------------------------------------------------------------
# Zed
# ---------------------------------------------------------------------------


def _build_zed_server_entry(project_dir: str) -> dict:
    """Build the MCP server config dict for Zed's ``context_servers`` format.

    Zed uses a nested ``{"command": {"path": ..., "args": [...]}}`` schema.
    """
    cmd = _find_command()
    parts = cmd.split()
    command = parts[0]
    args = parts[1:] + ["--project", os.path.abspath(project_dir)]
    return {
        "command": {
            "path": command,
            "args": args,
        },
    }


def install_zed(project_dir: str = ".", scope: str = "local") -> bool:
    """Install into Zed via ``settings.json``.

    Args:
        project_dir: Path to the project to index.
        scope: "local" writes to ``.zed/settings.json`` (project),
               "user" writes to ``~/.config/zed/settings.json``.

    Returns True if installation succeeded.
    """
    if scope == "user":
        config_path = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "zed" / "settings.json"
    else:
        config_path = Path(project_dir) / ".zed" / "settings.json"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if config_path.exists():
        import contextlib
        with contextlib.suppress(json.JSONDecodeError, OSError):
            existing = json.loads(config_path.read_text(encoding="utf-8"))

    servers = existing.setdefault("context_servers", {})
    servers["attocode-code-intel"] = _build_zed_server_entry(project_dir)

    config_path.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Installed attocode-code-intel into {config_path}")
    return True


def uninstall_zed(project_dir: str = ".", scope: str = "local") -> bool:
    """Uninstall from Zed."""
    if scope == "user":
        config_path = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "zed" / "settings.json"
    else:
        config_path = Path(project_dir) / ".zed" / "settings.json"

    if not config_path.exists():
        print(f"No config found at {config_path}")
        return True

    try:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    servers = existing.get("context_servers", {})
    if "attocode-code-intel" in servers:
        del servers["attocode-code-intel"]
        config_path.write_text(
            json.dumps(existing, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Removed attocode-code-intel from {config_path}")

    return True


# ---------------------------------------------------------------------------
# Manual instruction targets (IntelliJ, OpenCode)
# ---------------------------------------------------------------------------

_MANUAL_INSTRUCTIONS: dict[str, str] = {
    "intellij": (
        "IntelliJ IDEA does not support file-based MCP configuration.\n"
        "\n"
        "To set up attocode-code-intel in IntelliJ:\n"
        "  1. Open Settings > Tools > AI Assistant > MCP Servers\n"
        "  2. Click '+' to add a new server\n"
        "  3. Set transport to 'stdio'\n"
        "  4. Set command to: {command}\n"
        "  5. Set arguments to: {args}\n"
        "  6. Click OK and restart the AI Assistant\n"
    ),
    "opencode": (
        "OpenCode MCP configuration varies by version.\n"
        "\n"
        "To set up attocode-code-intel in OpenCode:\n"
        "  1. Open your OpenCode config file (usually ~/.config/opencode/config.json)\n"
        "  2. Add the following to the 'mcpServers' section:\n"
        '     "attocode-code-intel": {{\n'
        '       "command": "{command}",\n'
        '       "args": {args_json}\n'
        "     }}\n"
        "  3. Restart OpenCode\n"
    ),
}


def print_manual_instructions(target: str, project_dir: str = ".") -> bool:
    """Print manual setup instructions for targets without file-based config.

    Returns True (always succeeds — just prints instructions).
    """
    template = _MANUAL_INSTRUCTIONS.get(target)
    if template is None:
        print(f"Error: No manual instructions for '{target}'", file=sys.stderr)
        return False

    entry = _build_server_entry(project_dir)
    print(
        template.format(
            command=entry["command"],
            args=" ".join(entry["args"]),
            args_json=json.dumps(entry["args"]),
        )
    )
    return True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def install(target: str, project_dir: str = ".", scope: str = "local") -> bool:
    """Install into the given target.

    Args:
        target: One of :data:`ALL_TARGETS`.
        project_dir: Path to the project to index.
        scope: For Claude/Codex/Zed: "local" or "user". Ignored for others.
    """
    if target == "claude":
        return install_claude(project_dir, scope=scope)
    elif target in ("cursor", "windsurf", "vscode"):
        return install_json_config(target, project_dir)
    elif target == "codex":
        return install_codex(project_dir, scope=scope)
    elif target == "claude-desktop":
        return install_claude_desktop(project_dir)
    elif target == "cline":
        return install_cline(project_dir)
    elif target == "zed":
        return install_zed(project_dir, scope=scope)
    elif target in MANUAL_TARGETS:
        return print_manual_instructions(target, project_dir)
    else:
        print(
            f"Error: Unknown target '{target}'. Use: {ALL_TARGETS_STR}",
            file=sys.stderr,
        )
        return False


def uninstall(target: str, project_dir: str = ".", scope: str = "local") -> bool:
    """Uninstall from the given target."""
    if target == "claude":
        return uninstall_claude(scope=scope)
    elif target in ("cursor", "windsurf", "vscode"):
        return uninstall_json_config(target, project_dir)
    elif target == "codex":
        return uninstall_codex(project_dir, scope=scope)
    elif target == "claude-desktop":
        return uninstall_claude_desktop()
    elif target == "cline":
        return uninstall_cline()
    elif target == "zed":
        return uninstall_zed(project_dir, scope=scope)
    elif target in MANUAL_TARGETS:
        print(f"Nothing to uninstall — {target} uses manual configuration.")
        return True
    else:
        print(
            f"Error: Unknown target '{target}'. Use: {ALL_TARGETS_STR}",
            file=sys.stderr,
        )
        return False


# ---------------------------------------------------------------------------
# Hooks installation (Claude Code PostToolUse)
# ---------------------------------------------------------------------------

#: The hook matcher pattern — matches file-editing tools.
_HOOK_MATCHER = "Edit|Write|NotebookEdit"

#: Tag used to identify our hooks in settings.local.json.
_HOOK_TAG = "attocode-code-intel"


def _build_hook_config() -> dict:
    """Build the Claude Code PostToolUse hook configuration."""
    return {
        "matcher": _HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": "attocode-code-intel notify --stdin",
            },
        ],
    }


def install_hooks(target: str, project_dir: str = ".") -> bool:
    """Install PostToolUse hooks for automatic index updates.

    Currently only supported for Claude Code (``claude`` target).
    Writes hooks to ``.claude/settings.local.json``.

    Args:
        target: Installation target (only "claude" is supported).
        project_dir: Project directory.

    Returns:
        True if hooks were installed.
    """
    if target != "claude":
        print(
            f"Hooks not supported for {target}. "
            "The file watcher handles automatic updates. "
            "Alternatively, have your agent call the `notify_file_changed` "
            "MCP tool after edits.",
        )
        return False

    settings_path = Path(project_dir) / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if settings_path.exists():
        import contextlib
        with contextlib.suppress(json.JSONDecodeError, OSError):
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

    hooks = existing.setdefault("hooks", {})
    post_tool_use = hooks.setdefault("PostToolUse", [])

    # Remove any existing attocode hooks (handles old formats too)
    filtered = [
        entry for entry in post_tool_use
        if not any(_HOOK_TAG in h.get("command", "") for h in entry.get("hooks", []))
    ]

    expected = _build_hook_config()

    # Already up-to-date?
    if len(filtered) < len(post_tool_use) and expected in post_tool_use:
        print("Hooks already installed in .claude/settings.local.json")
        return True

    hooks["PostToolUse"] = filtered + [expected]

    settings_path.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Installed PostToolUse hooks in {settings_path}")
    return True


def uninstall_hooks(target: str, project_dir: str = ".") -> bool:
    """Remove attocode PostToolUse hooks.

    Args:
        target: Installation target (only "claude" is supported).
        project_dir: Project directory.

    Returns:
        True if hooks were removed (or didn't exist).
    """
    if target != "claude":
        return True

    settings_path = Path(project_dir) / ".claude" / "settings.local.json"
    if not settings_path.exists():
        return True

    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    hooks = existing.get("hooks", {})
    post_tool_use = hooks.get("PostToolUse", [])
    if not post_tool_use:
        return True

    # Remove entries that reference attocode-code-intel
    filtered = []
    removed = False
    for entry in post_tool_use:
        is_ours = False
        for h in entry.get("hooks", []):
            if _HOOK_TAG in h.get("command", ""):
                is_ours = True
                break
        if is_ours:
            removed = True
        else:
            filtered.append(entry)

    if removed:
        hooks["PostToolUse"] = filtered
        settings_path.write_text(
            json.dumps(existing, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Removed attocode hooks from {settings_path}")

    return True
