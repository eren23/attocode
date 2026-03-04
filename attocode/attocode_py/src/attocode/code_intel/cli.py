"""CLI subcommands for attocode code-intel.

Dispatched from the main CLI when the first positional argument is "code-intel".

Usage::

    attocode code-intel install claude [--global] [--project .]
    attocode code-intel install codex [--global] [--project .]
    attocode code-intel uninstall claude
    attocode code-intel serve [--project .]
    attocode code-intel status
"""

from __future__ import annotations

import os
import shutil
import sys


def dispatch_code_intel(parts: tuple[str, ...] | list[str], *, debug: bool = False) -> None:
    """Dispatch code-intel subcommands.

    Args:
        parts: Remaining CLI arguments after "code-intel".
        debug: Whether debug mode is enabled.
    """
    args = list(parts)

    if not args or args[0] in ("--help", "-h", "help"):
        _print_help()
        return

    cmd = args[0]

    if cmd == "install":
        _cmd_install(args[1:])
    elif cmd == "uninstall":
        _cmd_uninstall(args[1:])
    elif cmd == "serve":
        _cmd_serve(args[1:], debug=debug)
    elif cmd == "status":
        _cmd_status()
    elif cmd == "notify":
        _cmd_notify(args[1:])
    else:
        print(f"Unknown code-intel command: {cmd}", file=sys.stderr)
        _print_help()
        sys.exit(1)


def _print_help() -> None:
    print(
        "Usage: attocode code-intel <command>\n"
        "\n"
        "Commands:\n"
        "  install <target>    Install MCP server into a coding assistant\n"
        "  uninstall <target>  Remove MCP server from a coding assistant\n"
        "  serve               Run MCP server directly (stdio)\n"
        "  status              Check installation status across all targets\n"
        "  notify              Notify server about changed files (for hooks)\n"
        "\n"
        "Targets (auto-install):\n"
        "  claude              Claude Code (via `claude mcp add` CLI)\n"
        "  cursor              Cursor (.cursor/mcp.json)\n"
        "  windsurf            Windsurf (.windsurf/mcp.json)\n"
        "  vscode              VS Code / GitHub Copilot (.vscode/mcp.json)\n"
        "  codex               OpenAI Codex CLI (.codex/config.toml)\n"
        "  claude-desktop      Claude Desktop (platform-specific config)\n"
        "  cline               Cline VS Code extension (globalStorage)\n"
        "  zed                 Zed (.zed/settings.json)\n"
        "\n"
        "Targets (manual instructions):\n"
        "  intellij            IntelliJ IDEA (prints setup steps)\n"
        "  opencode            OpenCode (prints setup steps)\n"
        "\n"
        "Options:\n"
        "  --project <path>    Project directory to index (default: .)\n"
        "  --global            Install globally (Claude, Codex, Zed)\n"
        "  --hooks             Also install PostToolUse hooks (Claude Code)\n"
        "\n"
        "Notify options:\n"
        "  --file <path>       File that changed (repeatable)\n"
        "  --stdin             Read changed file paths from stdin (JSON or lines)\n"
    )


def _parse_opts(args: list[str]) -> tuple[str | None, str, str, bool]:
    """Parse target, --project, --global, and --hooks from args.

    Returns:
        (target, project_dir, scope, hooks)
    """
    target = None
    project_dir = "."
    scope = "local"
    hooks = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
            i += 2
        elif arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
            i += 1
        elif arg == "--global":
            scope = "user"
            i += 1
        elif arg == "--hooks":
            hooks = True
            i += 1
        elif not arg.startswith("-") and target is None:
            target = arg
            i += 1
        else:
            i += 1

    return target, project_dir, scope, hooks


def _cmd_install(args: list[str]) -> None:
    from attocode.code_intel.installer import ALL_TARGETS_STR, install, install_hooks

    target, project_dir, scope, hooks = _parse_opts(args)
    if not target:
        print(f"Error: specify a target ({ALL_TARGETS_STR})", file=sys.stderr)
        sys.exit(1)

    success = install(target, project_dir=project_dir, scope=scope)
    if not success:
        sys.exit(1)

    if hooks:
        install_hooks(target, project_dir=project_dir)


def _cmd_uninstall(args: list[str]) -> None:
    from attocode.code_intel.installer import ALL_TARGETS_STR, uninstall, uninstall_hooks

    target, project_dir, scope, _hooks = _parse_opts(args)
    if not target:
        print(f"Error: specify a target ({ALL_TARGETS_STR})", file=sys.stderr)
        sys.exit(1)

    # Always attempt to remove hooks on uninstall
    uninstall_hooks(target, project_dir=project_dir)

    success = uninstall(target, project_dir=project_dir, scope=scope)
    if not success:
        sys.exit(1)


def _cmd_serve(args: list[str], *, debug: bool = False) -> None:
    _, project_dir, _, _ = _parse_opts(args)

    os.environ["ATTOCODE_PROJECT_DIR"] = os.path.abspath(project_dir)

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    from attocode.code_intel.server import mcp

    abs_dir = os.path.abspath(project_dir)
    print(f"Starting attocode-code-intel server for {abs_dir}", file=sys.stderr)
    mcp.run(transport="stdio")


def _cmd_status() -> None:
    """Check if the MCP server is installed in known targets."""
    import json
    from pathlib import Path

    from attocode.code_intel.installer import _get_user_config_dir

    print("attocode-code-intel status:\n")

    # Check Claude Code
    has_claude = shutil.which("claude") is not None
    if has_claude:
        try:
            result = __import__("subprocess").run(
                ["claude", "mcp", "list"],
                capture_output=True, text=True, timeout=10,
            )
            if "attocode-code-intel" in result.stdout:
                print("  Claude Code: installed")
            else:
                print("  Claude Code: not installed")
        except Exception:
            print("  Claude Code: unable to check")
    else:
        print("  Claude Code: CLI not found")

    # Check JSON-config targets (Cursor, Windsurf, VS Code)
    for name, config_dir in [("Cursor", ".cursor"), ("Windsurf", ".windsurf"), ("VS Code", ".vscode")]:
        cfg = Path(config_dir) / "mcp.json"
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text())
                if "attocode-code-intel" in data.get("mcpServers", {}):
                    print(f"  {name}: installed")
                else:
                    print(f"  {name}: not installed")
            except Exception:
                print(f"  {name}: unable to check")
        else:
            print(f"  {name}: not installed")

    # Check Codex (project-level)
    codex_cfg = Path(".codex/config.toml")
    if codex_cfg.exists():
        try:
            import tomllib
            data = tomllib.loads(codex_cfg.read_text())
            if "attocode-code-intel" in data.get("mcp_servers", {}):
                print("  Codex: installed")
            else:
                print("  Codex: not installed")
        except Exception:
            print("  Codex: unable to check")
    else:
        # Also check user-level
        codex_user_cfg = Path.home() / ".codex" / "config.toml"
        if codex_user_cfg.exists():
            try:
                import tomllib
                data = tomllib.loads(codex_user_cfg.read_text())
                if "attocode-code-intel" in data.get("mcp_servers", {}):
                    print("  Codex: installed (user)")
                else:
                    print("  Codex: not installed")
            except Exception:
                print("  Codex: unable to check")
        else:
            print("  Codex: not installed")

    # Check Claude Desktop
    claude_desktop_dir = _get_user_config_dir("claude-desktop")
    if claude_desktop_dir is not None:
        cfg = claude_desktop_dir / "claude_desktop_config.json"
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text())
                if "attocode-code-intel" in data.get("mcpServers", {}):
                    print("  Claude Desktop: installed")
                else:
                    print("  Claude Desktop: not installed")
            except Exception:
                print("  Claude Desktop: unable to check")
        else:
            print("  Claude Desktop: not installed")
    else:
        print("  Claude Desktop: not supported on this platform")

    # Check Cline
    cline_dir = _get_user_config_dir("cline")
    if cline_dir is not None:
        cfg = cline_dir / "cline_mcp_settings.json"
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text())
                if "attocode-code-intel" in data.get("mcpServers", {}):
                    print("  Cline: installed")
                else:
                    print("  Cline: not installed")
            except Exception:
                print("  Cline: unable to check")
        else:
            print("  Cline: not installed")
    else:
        print("  Cline: not supported on this platform")

    # Check Zed (project-level, then user-level)
    zed_local = Path(".zed/settings.json")
    zed_user = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "zed" / "settings.json"
    zed_found = False
    for zed_path, label in [(zed_local, "installed"), (zed_user, "installed (user)")]:
        if zed_path.exists():
            try:
                data = json.loads(zed_path.read_text())
                if "attocode-code-intel" in data.get("context_servers", {}):
                    print(f"  Zed: {label}")
                    zed_found = True
                    break
            except Exception:
                pass
    if not zed_found:
        print("  Zed: not installed")

    # Check if entry point is available
    print()
    if shutil.which("attocode-code-intel"):
        print("  Entry point: attocode-code-intel (on PATH)")
    else:
        print(f"  Entry point: {sys.executable} -m attocode.code_intel.server")


def _cmd_notify(args: list[str]) -> None:
    """Notify the server about changed files via the notification queue.

    Writes file paths to .attocode/cache/file_changes for the server to pick up.
    """
    import json as json_mod
    from pathlib import Path

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    files: list[str] = []

    # Parse --file flags
    i = 0
    while i < len(args):
        if args[i] == "--file" and i + 1 < len(args):
            files.append(args[i + 1])
            i += 2
        elif args[i].startswith("--file="):
            files.append(args[i].split("=", 1)[1])
            i += 1
        elif args[i] == "--stdin":
            # Read from stdin: support both raw lines and JSON with tool_input
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        data = json_mod.loads(line)
                        fp = (
                            data.get("tool_input", {}).get("file_path")
                            or data.get("file_path")
                        )
                        if fp:
                            files.append(fp)
                    except json_mod.JSONDecodeError:
                        pass
                else:
                    files.append(line)
            i += 1
        else:
            i += 1

    if not files:
        print("No files specified. Use --file <path> or --stdin.", file=sys.stderr)
        sys.exit(1)

    # Resolve to relative paths and write to queue
    queue_path = Path(project_dir) / ".attocode" / "cache" / "file_changes"
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    rel_paths: list[str] = []
    for f in files:
        p = Path(f)
        if p.is_absolute():
            try:
                rel = os.path.relpath(str(p), project_dir)
            except ValueError:
                rel = str(p)
        else:
            rel = str(p)
        rel_paths.append(rel)

    # Append to queue file under exclusive lock
    try:
        import fcntl
        with queue_path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            for rp in rel_paths:
                fh.write(rp + "\n")
    except ImportError:
        # Windows: fall back to non-locked append
        with queue_path.open("a", encoding="utf-8") as fh:
            for rp in rel_paths:
                fh.write(rp + "\n")

    print(f"Queued {len(rel_paths)} file(s) for index update.")
