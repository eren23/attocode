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
    elif cmd == "index":
        _cmd_index(args[1:])
    elif cmd == "connect":
        _cmd_connect(args[1:])
    elif cmd == "test-connection":
        _cmd_test_connection(args[1:])
    elif cmd == "watch":
        _cmd_watch(args[1:])
    elif cmd == "setup":
        _cmd_setup(args[1:])
    elif cmd == "query":
        _cmd_query(args[1:])
    elif cmd == "symbols":
        _cmd_symbols(args[1:])
    elif cmd == "impact":
        _cmd_impact(args[1:])
    elif cmd == "hotspots":
        _cmd_hotspots(args[1:])
    elif cmd == "deps":
        _cmd_deps(args[1:])
    elif cmd == "gc":
        _cmd_gc(args[1:])
    elif cmd == "verify":
        _cmd_verify(args[1:])
    elif cmd == "reindex":
        _cmd_reindex(args[1:])
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
        "  connect             Connect project to a running code-intel server\n"
        "  serve               Run MCP server directly (stdio or SSE)\n"
        "  index               Build or check embedding index for semantic search\n"
        "  status              Check installation status across all targets\n"
        "  notify              Notify server about changed files (for hooks)\n"
        "  test-connection     Verify connectivity to the remote server\n"
        "  watch               Watch filesystem for changes and notify remote server\n"
        "  setup               [Dev] Bootstrap local infrastructure for development\n"
        "\n"
        "Query commands:\n"
        "  query <text>        Semantic search across the codebase\n"
        "  symbols <file>      List symbols in a file (or --search <name>)\n"
        "  impact <file> ...   Show blast radius of file changes\n"
        "  hotspots            Show risk/complexity hotspots\n"
        "  deps <file>         Show file dependencies and dependents\n"
        "\n"
        "Maintenance commands:\n"
        "  gc                  Run garbage collection (orphaned embeddings + content)\n"
        "  verify              Run integrity checks on the index\n"
        "  reindex             Force a full reindex of the project\n"
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
        "Serve options:\n"
        "  --transport <type>  Transport protocol: stdio (default), sse, or http\n"
        "  --host <addr>       Server host address (default: 127.0.0.1)\n"
        "  --port <num>        Server port number (default: 8080)\n"
        "  --no-watch          Disable filesystem watcher (watcher is on by default)\n"
        "  --watch-debounce N  File-change debounce in milliseconds (default: 500)\n"
        "\n"
        "Notify options:\n"
        "  --file <path>       File that changed (repeatable)\n"
        "  --stdin             Read changed file paths from stdin (JSON or lines)\n"
        "\n"
        "Connect options:\n"
        "  --server <url>      Remote server URL (e.g. https://code.example.com)\n"
        "  --token <token>     JWT or API key (skip interactive login)\n"
        "  --email <email>     Email for register/login (skip prompt)\n"
        "  --password <pass>   Password for register/login (skip prompt)\n"
        "  --org <slug-or-id>  Organization slug or ID (skip selection)\n"
        "  --repo <repo_id>    Repository UUID on the remote server\n"
        "  --name <repo-name>  Override auto-detected repository name\n"
        "\n"
        "Watch options:\n"
        "  --debounce <ms>     Debounce interval in milliseconds (default: 500)\n"
        "\n"
        "Setup options (dev):\n"
        "  --reset             Wipe Docker volumes and dev state, then re-bootstrap\n"
        "  --skip-deps         Skip uv sync (use if deps already installed)\n"
        "  --project <path>    Project directory (default: .)\n"
        "\n"
        "Query options:\n"
        "  --top <N>           Number of results (query: default 10, hotspots: default 15)\n"
        "  --filter <glob>     File filter glob for semantic search (e.g. '*.py')\n"
        "  --search <name>     Search for symbol by name (symbols command)\n"
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

    # Parse transport flags and watcher options
    transport = "stdio"
    host = "127.0.0.1"
    port = 8080
    no_watch = False
    watch_debounce = 500
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
            i += 2
        elif arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
            i += 1
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
            i += 1
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
            i += 1
        elif arg == "--no-watch":
            no_watch = True
            i += 1
        elif arg == "--watch-debounce" and i + 1 < len(args):
            watch_debounce = int(args[i + 1])
            i += 2
        elif arg.startswith("--watch-debounce="):
            watch_debounce = int(arg.split("=", 1)[1])
            i += 1
        else:
            i += 1

    abs_dir = os.path.abspath(project_dir)
    os.environ["ATTOCODE_PROJECT_DIR"] = abs_dir

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    from attocode.code_intel.server import (
        _start_file_watcher,
        _start_queue_poller,
        _stop_file_watcher,
        mcp,
    )

    print(f"Starting attocode-code-intel server for {abs_dir} (transport={transport})", file=sys.stderr)

    # Start file watcher and notification queue poller for stdio/sse transports.
    # (HTTP transport manages its own lifecycle via the FastAPI app.)
    if transport != "http" and not no_watch:
        _start_file_watcher(abs_dir, debounce_ms=watch_debounce)
        _start_queue_poller(abs_dir)

    try:
        if transport == "http":
            _serve_http(abs_dir, host=host, port=port, debug=debug)
        elif transport == "sse":
            mcp.run(transport="sse", host=host, port=port)
        else:
            mcp.run(transport="stdio")
    finally:
        if transport != "http" and not no_watch:
            _stop_file_watcher()


def _serve_http(project_dir: str, *, host: str, port: int, debug: bool) -> None:
    """Start the FastAPI HTTP server."""
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn not installed. Install with: pip install 'attocode[code-intel]'",
            file=sys.stderr,
        )
        sys.exit(1)

    from attocode.code_intel.api.app import create_app
    from attocode.code_intel.config import CodeIntelConfig

    config = CodeIntelConfig.from_env()
    config.project_dir = project_dir
    config.host = host
    config.port = port
    if debug:
        config.log_level = "debug"
    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level=config.log_level)


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

    # Check if remote server is configured — POST instead of local queue
    from attocode.code_intel.config import load_remote_config

    remote_cfg = load_remote_config(project_dir)
    if remote_cfg.is_configured:
        _notify_remote(remote_cfg, rel_paths, project_dir)
        return

    # Fallback: local queue file for MCP server to pick up
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


def _notify_remote(remote_cfg, rel_paths: list[str], project_dir: str) -> None:
    """POST file changes to the remote server, including file contents."""
    import base64
    import subprocess

    try:
        import httpx
    except ImportError:
        print(
            "Error: httpx not installed. Install with: pip install httpx",
            file=sys.stderr,
        )
        sys.exit(1)

    # Auto-detect branch from git
    branch = "main"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except Exception:
        pass

    # Read file contents and base64-encode them
    files: dict[str, str] = {}
    for rel_path in rel_paths:
        full = os.path.join(project_dir, rel_path)
        if os.path.isfile(full):
            try:
                with open(full, "rb") as f:
                    files[rel_path] = base64.b64encode(f.read()).decode("ascii")
            except (OSError, PermissionError):
                pass  # deleted or unreadable — omit, server treats as deleted

    server = remote_cfg.server.rstrip("/")
    try:
        resp = httpx.post(
            f"{server}/api/v1/notify/file-changed",
            json={
                "paths": rel_paths,
                "files": files,
                "project": remote_cfg.repo_id,
                "branch": branch,
            },
            headers={"Authorization": f"Bearer {remote_cfg.token}"},
            timeout=30,
        )
        if resp.status_code in (200, 202):
            data = resp.json()
            print(f"Notified remote server: {data.get('accepted', len(rel_paths))} file(s) accepted.")
        else:
            print(
                f"Remote server returned {resp.status_code}: {resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)
    except httpx.ConnectError:
        print(f"Error: cannot connect to {server}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print(f"Error: request to {server} timed out", file=sys.stderr)
        sys.exit(1)


def _prompt(label: str, *, default: str = "", secret: bool = False) -> str:
    """Prompt user for input. Uses getpass for secrets."""
    if secret:
        import getpass

        suffix = f" [{default}]" if default else ""
        val = getpass.getpass(f"{label}{suffix}: ")
        return val or default
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or default


def _bootstrap_user_and_project(
    api_base: str,
    project_dir: str,
    state_path: str,
    *,
    email: str = "",
    password: str = "",
    org_slug: str = "",
    repo_name: str = "",
    interactive: bool = True,
) -> dict:
    """Register/login, select org, add repo. Returns state dict.

    Shared logic used by both ``connect`` (user-provided credentials) and
    ``setup`` (hardcoded dev credentials).
    """
    import json
    from pathlib import Path

    try:
        import httpx
    except ImportError:
        print("Error: httpx not installed. Install with: uv sync --extra service", file=sys.stderr)
        sys.exit(1)

    # Load existing state for idempotency
    state: dict = {}
    if os.path.isfile(state_path):
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        except Exception:
            pass

    # --- Auth: register or login ---
    if not state.get("token"):
        if not email:
            if not interactive:
                print("Error: --email required in non-interactive mode", file=sys.stderr)
                sys.exit(1)
            email = _prompt("Email")
        if not password:
            if not interactive:
                print("Error: --password required in non-interactive mode", file=sys.stderr)
                sys.exit(1)
            password = _prompt("Password", secret=True)
        if not email or not password:
            print("Error: email and password are required", file=sys.stderr)
            sys.exit(1)

        # Try register first, fall back to login
        resp = httpx.post(
            f"{api_base}/api/v1/auth/register",
            json={"email": email, "password": password, "name": email.split("@")[0]},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            state["token"] = data["access_token"]
            state["user_id"] = data.get("user_id", data.get("id", ""))
            print("Registered new account.", file=sys.stderr)
        elif resp.status_code == 409:
            resp2 = httpx.post(
                f"{api_base}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=10,
            )
            if resp2.status_code == 200:
                data = resp2.json()
                state["token"] = data["access_token"]
                state["user_id"] = data.get("user_id", data.get("id", ""))
                print("Logged in.", file=sys.stderr)
            else:
                print(f"Error logging in: {resp2.status_code} {resp2.text}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Error registering: {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)

    headers = {"Authorization": f"Bearer {state['token']}"}

    # --- Org selection ---
    if not state.get("org_id"):
        resp = httpx.get(f"{api_base}/api/v1/orgs", headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"Error listing orgs: {resp.status_code}", file=sys.stderr)
            sys.exit(1)

        orgs_raw = resp.json()
        orgs = orgs_raw if isinstance(orgs_raw, list) else (orgs_raw.get("organizations") or orgs_raw.get("items", []))

        # Filter by slug if provided
        if org_slug:
            match = [o for o in orgs if o.get("slug") == org_slug or o.get("id") == org_slug]
            if match:
                state["org_id"] = match[0]["id"]
                print(f"Using org: {match[0].get('name', org_slug)}", file=sys.stderr)
            else:
                # Create it
                resp2 = httpx.post(
                    f"{api_base}/api/v1/orgs",
                    json={"name": org_slug, "slug": org_slug},
                    headers=headers,
                    timeout=10,
                )
                if resp2.status_code in (200, 201):
                    state["org_id"] = resp2.json()["id"]
                    print(f"Created org: {org_slug}", file=sys.stderr)
                else:
                    print(f"Error creating org: {resp2.status_code} {resp2.text}", file=sys.stderr)
                    sys.exit(1)
        elif len(orgs) == 1:
            state["org_id"] = orgs[0]["id"]
            print(f"Using org: {orgs[0].get('name', orgs[0]['id'])}", file=sys.stderr)
        elif len(orgs) > 1:
            if not interactive:
                print("Error: multiple orgs found, specify --org", file=sys.stderr)
                sys.exit(1)
            print("\nAvailable organizations:", file=sys.stderr)
            for idx, org in enumerate(orgs, 1):
                print(f"  {idx}. {org.get('name', '?')} ({org.get('slug', '')})", file=sys.stderr)
            choice = _prompt("Select org number", default="1")
            try:
                state["org_id"] = orgs[int(choice) - 1]["id"]
            except (ValueError, IndexError):
                print("Invalid selection.", file=sys.stderr)
                sys.exit(1)
        else:
            # No orgs — create one
            if interactive:
                slug = _prompt("No orgs found. Create one — slug", default="my-org")
            else:
                slug = org_slug or "default"
            resp2 = httpx.post(
                f"{api_base}/api/v1/orgs",
                json={"name": slug, "slug": slug},
                headers=headers,
                timeout=10,
            )
            if resp2.status_code in (200, 201):
                state["org_id"] = resp2.json()["id"]
                print(f"Created org: {slug}", file=sys.stderr)
            elif resp2.status_code == 409:
                # Org exists but user isn't a member — look it up by slug
                resp3 = httpx.get(
                    f"{api_base}/api/v1/orgs",
                    headers=headers,
                    params={"slug": slug},
                    timeout=10,
                )
                found = False
                if resp3.status_code == 200:
                    orgs3 = resp3.json() if isinstance(resp3.json(), list) else resp3.json().get("items", [])
                    for o in orgs3:
                        if o.get("slug") == slug:
                            state["org_id"] = o["id"]
                            print(f"Joined existing org: {slug}", file=sys.stderr)
                            found = True
                            break
                if not found:
                    # Last resort: parse the 409 response for org id, or just re-list all
                    resp4 = httpx.get(f"{api_base}/api/v1/orgs", headers=headers, timeout=10)
                    if resp4.status_code == 200:
                        orgs4 = resp4.json() if isinstance(resp4.json(), list) else resp4.json().get("items", [])
                        for o in orgs4:
                            if o.get("slug") == slug or o.get("name") == slug:
                                state["org_id"] = o["id"]
                                print(f"Using existing org: {slug}", file=sys.stderr)
                                found = True
                                break
                if not found:
                    print(f"Error: org '{slug}' exists but could not resolve its ID.", file=sys.stderr)
                    sys.exit(1)
            else:
                print(f"Error creating org: {resp2.status_code} {resp2.text}", file=sys.stderr)
                sys.exit(1)

    # --- Repo selection ---
    if not state.get("repo_id"):
        resp = httpx.get(
            f"{api_base}/api/v1/orgs/{state['org_id']}/repos",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"Error listing repos: {resp.status_code}", file=sys.stderr)
            sys.exit(1)

        repos_raw = resp.json()
        repos = repos_raw if isinstance(repos_raw, list) else (repos_raw.get("repositories") or repos_raw.get("items", []))

        # Detect local git remote origin for matching and repo creation
        local_clone_url = None
        try:
            import subprocess
            origin = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_dir, capture_output=True, text=True, timeout=5,
            )
            if origin.returncode == 0 and origin.stdout.strip():
                local_clone_url = origin.stdout.strip()
        except Exception:
            pass

        # Try auto-match by local_path
        for repo in repos:
            if repo.get("local_path") == project_dir:
                state["repo_id"] = repo["id"]
                print(f"Matched existing repo: {repo.get('name', repo['id'])}", file=sys.stderr)
                break

        # Try auto-match by clone_url
        if not state.get("repo_id") and local_clone_url:
            for repo in repos:
                repo_url = repo.get("clone_url", "")
                if repo_url and _urls_match(local_clone_url, repo_url):
                    state["repo_id"] = repo["id"]
                    print(f"Matched existing repo by remote URL: {repo.get('name', repo['id'])}", file=sys.stderr)
                    break

        if not state.get("repo_id"):
            # Add current project as a new repo
            if not repo_name:
                repo_name = os.path.basename(project_dir)
            default_branch = _detect_default_branch(project_dir)

            clone_url = local_clone_url

            repo_payload: dict = {
                "name": repo_name,
                "local_path": project_dir,
                "default_branch": default_branch,
            }
            if clone_url:
                repo_payload["clone_url"] = clone_url

            resp2 = httpx.post(
                f"{api_base}/api/v1/orgs/{state['org_id']}/repos",
                json=repo_payload,
                headers=headers,
                timeout=10,
            )
            if resp2.status_code in (200, 201):
                state["repo_id"] = resp2.json()["id"]
                print(f"Added repo: {repo_name} ({state['repo_id']})", file=sys.stderr)
            elif resp2.status_code == 409:
                # Already exists — search by name
                for repo in repos:
                    if repo.get("name") == repo_name:
                        state["repo_id"] = repo["id"]
                        break
                if state.get("repo_id"):
                    print(f"Using existing repo: {state['repo_id']}", file=sys.stderr)
                else:
                    print("Error: repo conflict but could not find existing.", file=sys.stderr)
                    sys.exit(1)
            else:
                print(f"Error adding repo: {resp2.status_code} {resp2.text}", file=sys.stderr)
                sys.exit(1)

    # --- Save state ---
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state, indent=2), encoding="utf-8")

    return state


def _urls_match(url_a: str, url_b: str) -> bool:
    """Compare git URLs, normalizing protocol and .git suffix."""

    def _normalize(u: str) -> str:
        u = u.strip().rstrip("/")
        if u.endswith(".git"):
            u = u[:-4]
        if u.startswith("git@"):
            u = u[4:].replace(":", "/", 1)
        for prefix in ("https://", "http://", "ssh://"):
            if u.startswith(prefix):
                u = u[len(prefix):]
                break
        return u.lower()

    return _normalize(url_a) == _normalize(url_b)


_SYNC_CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
    ".toml", ".yaml", ".yml", ".json", ".md", ".txt", ".cfg",
    ".sh", ".bash", ".zsh", ".fish", ".sql", ".graphql",
}


def _initial_sync(remote_cfg, project_dir: str, batch_size: int = 50) -> None:
    """Push all git-tracked code files to the server after connect.

    Uses ``git ls-files`` to enumerate tracked files, filters by extension,
    and POSTs them in batches via the notify endpoint (same path as watch/notify).
    """
    import base64
    import subprocess

    try:
        import httpx
    except ImportError:
        return

    # Get git-tracked files
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print("  [skip] Could not list git files for initial sync.", file=sys.stderr)
            return
    except Exception:
        return

    all_files = [f for f in result.stdout.strip().splitlines() if f]
    # Filter to code files
    code_files = [
        f for f in all_files
        if os.path.splitext(f)[1].lower() in _SYNC_CODE_EXTENSIONS
    ]
    if not code_files:
        print("  [skip] No code files to sync.", file=sys.stderr)
        return

    # Detect branch
    branch = "main"
    try:
        br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=5,
        )
        if br.returncode == 0:
            branch = br.stdout.strip()
    except Exception:
        pass

    server = remote_cfg.server.rstrip("/")
    headers = {"Authorization": f"Bearer {remote_cfg.token}"}
    client = httpx.Client(timeout=60)

    total = len(code_files)
    synced = 0
    bulk_batch_size = 500  # Bulk sync supports up to 500 files
    print(f"\n  Initial sync: pushing {total} tracked files...", file=sys.stderr)

    # Try bulk-sync endpoint first (faster, no debounce)
    use_bulk = True
    try:
        for i in range(0, total, bulk_batch_size):
            batch = code_files[i : i + bulk_batch_size]
            files: dict[str, str] = {}
            for rel_path in batch:
                full = os.path.join(project_dir, rel_path)
                if os.path.isfile(full):
                    try:
                        with open(full, "rb") as f:
                            files[rel_path] = base64.b64encode(f.read()).decode("ascii")
                    except (OSError, PermissionError):
                        pass

            if not files:
                continue

            if use_bulk:
                try:
                    resp = client.post(
                        f"{server}/api/v1/notify/bulk-sync",
                        json={
                            "files": files,
                            "project": remote_cfg.repo_id,
                            "branch": branch,
                        },
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        synced += len(files)
                        print(f"    [{synced}/{total}] synced (bulk)", file=sys.stderr)
                        continue
                    elif resp.status_code == 404:
                        # Server doesn't support bulk-sync, fall back
                        use_bulk = False
                    else:
                        print(f"    Bulk sync error: {resp.status_code}", file=sys.stderr)
                        use_bulk = False
                except Exception:
                    use_bulk = False

            # Fallback: regular notify in smaller batches
            for j in range(0, len(files), batch_size):
                sub_files = dict(list(files.items())[j : j + batch_size])
                try:
                    resp = client.post(
                        f"{server}/api/v1/notify/file-changed",
                        json={
                            "paths": list(sub_files.keys()),
                            "files": sub_files,
                            "project": remote_cfg.repo_id,
                            "branch": branch,
                        },
                        headers=headers,
                    )
                    if resp.status_code in (200, 202):
                        synced += len(sub_files)
                        print(f"    [{synced}/{total}] synced", file=sys.stderr)
                    else:
                        print(f"    Batch error: server returned {resp.status_code}", file=sys.stderr)
                except Exception as e:
                    print(f"    Batch error: {e}", file=sys.stderr)
    finally:
        # Flush debouncer if we used regular notify
        if synced > 0 and not use_bulk:
            try:
                client.post(
                    f"{server}/api/v1/notify/flush",
                    json={"project": remote_cfg.repo_id, "branch": branch},
                    headers=headers,
                )
            except Exception:
                pass  # best-effort flush
        client.close()

    print(f"  Initial sync complete: {synced}/{total} files pushed.", file=sys.stderr)

    # Push recent commit history for DB-backed commits page
    _push_commit_history(remote_cfg, project_dir, branch)

    # Push blame data for recently changed files
    _push_blame_data(remote_cfg, project_dir, branch)


def _push_commit_history(remote_cfg, project_dir: str, branch: str, limit: int = 100) -> None:
    """Push recent commit metadata to the server for DB-backed commits page.

    Includes --name-status to capture changed files per commit.
    """
    import subprocess

    try:
        import httpx
    except ImportError:
        return

    # Use a separator to split commit header from name-status output
    separator = "---COMMIT_END---"
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--format=%H%n%s%n%an%n%ae%n%at%n%P%n{separator}",
                "--name-status",
                "-n", str(limit),
            ],
            cwd=project_dir, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
    except Exception:
        return

    # Parse commits with changed files
    commits = []
    blocks = result.stdout.split(separator)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        if len(lines) < 6:
            continue

        oid = lines[0].strip()
        message = lines[1].strip()
        author_name = lines[2].strip()
        author_email = lines[3].strip()
        timestamp_str = lines[4].strip()
        parent_line = lines[5].strip()

        if not oid:
            continue
        try:
            ts = int(timestamp_str)
        except ValueError:
            ts = 0
        parent_oids = parent_line.split() if parent_line else []

        # Parse name-status lines (after the 6 header lines)
        changed_files = []
        for ns_line in lines[6:]:
            ns_line = ns_line.strip()
            if not ns_line:
                continue
            parts = ns_line.split("\t", 1)
            if len(parts) == 2:
                status_code = parts[0].strip()
                file_path = parts[1].strip()
                # Map git status codes to our format
                status_map = {"A": "A", "M": "M", "D": "D", "R": "R", "C": "C"}
                status = status_map.get(status_code[0], status_code[0]) if status_code else "M"
                changed_files.append({"path": file_path, "status": status})

        commits.append({
            "oid": oid,
            "message": message,
            "author_name": author_name,
            "author_email": author_email,
            "timestamp": ts,
            "parent_oids": parent_oids,
            "changed_files": changed_files if changed_files else None,
        })

    if not commits:
        return

    server = remote_cfg.server.rstrip("/")
    headers = {"Authorization": f"Bearer {remote_cfg.token}"}

    try:
        resp = httpx.post(
            f"{server}/api/v1/notify/commits",
            json={
                "commits": commits,
                "project": remote_cfg.repo_id,
                "branch": branch,
            },
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Pushed {data.get('stored', 0)} commits to server.", file=sys.stderr)
        else:
            print(f"  [warn] Commit push returned {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"  [warn] Commit push failed: {e}", file=sys.stderr)


def _push_blame_data(remote_cfg, project_dir: str, branch: str, paths: list[str] | None = None) -> None:
    """Push blame data for specified files (or top files) to the server."""
    import subprocess

    try:
        import httpx
    except ImportError:
        return

    if paths is None:
        # Default: blame top 20 most-recently-changed files
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~10", "HEAD"],
                cwd=project_dir, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                paths = result.stdout.strip().splitlines()[:20]
            else:
                return
        except Exception:
            return

    if not paths:
        return

    server = remote_cfg.server.rstrip("/")
    headers = {"Authorization": f"Bearer {remote_cfg.token}"}
    client = httpx.Client(timeout=30)
    pushed = 0

    try:
        for file_path in paths:
            try:
                result = subprocess.run(
                    ["git", "blame", "--porcelain", file_path],
                    cwd=project_dir, capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    continue
            except Exception:
                continue

            hunks = _parse_git_blame_porcelain(result.stdout)
            if not hunks:
                continue

            try:
                resp = client.post(
                    f"{server}/api/v1/notify/blame",
                    json={
                        "hunks": hunks,
                        "project": remote_cfg.repo_id,
                        "branch": branch,
                        "path": file_path,
                    },
                    headers=headers,
                )
                if resp.status_code == 200:
                    pushed += 1
            except Exception:
                pass
    finally:
        client.close()

    if pushed:
        print(f"  Pushed blame data for {pushed} file(s).", file=sys.stderr)


def _parse_git_blame_porcelain(output: str) -> list[dict]:
    """Parse git blame --porcelain output into structured hunks."""
    hunks: list[dict] = []
    lines = output.splitlines()
    i = 0
    current: dict = {}

    while i < len(lines):
        line = lines[i]
        # Skip content lines (porcelain format prefixes them with \t)
        if line.startswith("\t"):
            i += 1
            continue
        # Header line: <sha> <orig_line> <final_line> [<num_lines>]
        parts = line.split()
        if (
            len(parts) >= 3
            and len(parts[0]) == 40
            and all(c in "0123456789abcdef" for c in parts[0])
            and parts[1].isdigit()
            and parts[2].isdigit()
        ):
            start_line = int(parts[2])
            num_lines = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1
            if current:
                hunks.append(current)
            commit_oid = parts[0]
            current = {
                "commit_oid": commit_oid,
                "start_line": start_line,
                "end_line": start_line + num_lines - 1,
                "author_name": "",
                "author_email": "",
                "timestamp": 0,
            }
        elif line.startswith("author "):
            current["author_name"] = line[7:]
        elif line.startswith("author-mail "):
            email = line[12:].strip("<>")
            current["author_email"] = email
        elif line.startswith("author-time "):
            try:
                current["timestamp"] = int(line[12:])
            except ValueError:
                pass
        i += 1

    if current:
        hunks.append(current)

    # Merge consecutive hunks from the same commit
    merged: list[dict] = []
    for h in hunks:
        if merged and merged[-1]["commit_oid"] == h["commit_oid"] and merged[-1]["end_line"] + 1 == h["start_line"]:
            merged[-1]["end_line"] = h["end_line"]
        else:
            merged.append(h)

    return merged


def _cmd_connect(args: list[str]) -> None:
    """Connect a local project to a running code-intel server.

    Primary onboarding flow for service mode. Handles authentication
    (interactive register/login or explicit --token), org/repo selection,
    and writes .attocode/config.toml for subsequent notify/watch commands.
    """
    from attocode.code_intel.config import RemoteConfig, save_remote_config

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    server = ""
    token = ""
    repo_id = ""
    email = ""
    password = ""
    org_slug = ""
    repo_name_override = ""
    ci_mode = False
    skip_sync = False
    state_file_override = ""

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--ci":
            ci_mode = True
            i += 1
            continue
        elif arg == "--skip-sync":
            skip_sync = True
            i += 1
            continue
        elif arg == "--state-file" and i + 1 < len(args):
            state_file_override = args[i + 1]
            i += 2
            continue
        elif arg.startswith("--state-file="):
            state_file_override = arg.split("=", 1)[1]
            i += 1
            continue
        elif arg == "--server" and i + 1 < len(args):
            server = args[i + 1]
            i += 2
        elif arg.startswith("--server="):
            server = arg.split("=", 1)[1]
            i += 1
        elif arg == "--token" and i + 1 < len(args):
            token = args[i + 1]
            i += 2
        elif arg.startswith("--token="):
            token = arg.split("=", 1)[1]
            i += 1
        elif arg == "--repo" and i + 1 < len(args):
            repo_id = args[i + 1]
            i += 2
        elif arg.startswith("--repo="):
            repo_id = arg.split("=", 1)[1]
            i += 1
        elif arg == "--email" and i + 1 < len(args):
            email = args[i + 1]
            i += 2
        elif arg.startswith("--email="):
            email = arg.split("=", 1)[1]
            i += 1
        elif arg == "--password" and i + 1 < len(args):
            password = args[i + 1]
            i += 2
        elif arg.startswith("--password="):
            password = arg.split("=", 1)[1]
            i += 1
        elif arg == "--org" and i + 1 < len(args):
            org_slug = args[i + 1]
            i += 2
        elif arg.startswith("--org="):
            org_slug = arg.split("=", 1)[1]
            i += 1
        elif arg == "--name" and i + 1 < len(args):
            repo_name_override = args[i + 1]
            i += 2
        elif arg.startswith("--name="):
            repo_name_override = arg.split("=", 1)[1]
            i += 1
        elif arg == "--force":
            # Will clear cached state below
            i += 1
        else:
            i += 1

    force = "--force" in args

    if not server:
        print("Error: --server <url> is required", file=sys.stderr)
        sys.exit(1)

    server = server.rstrip("/")
    interactive = sys.stdin.isatty() and not ci_mode

    # --- Health check ---
    try:
        import httpx
    except ImportError:
        print("Error: httpx not installed. Install with: pip install httpx", file=sys.stderr)
        sys.exit(1)

    try:
        resp = httpx.get(f"{server}/health", timeout=10)
        if resp.status_code != 200:
            print(f"Error: server at {server} returned status {resp.status_code}", file=sys.stderr)
            sys.exit(1)
        print(f"Server reachable at {server}", file=sys.stderr)
    except Exception as e:
        print(f"Error: cannot reach server at {server}: {e}", file=sys.stderr)
        sys.exit(1)

    state_path = state_file_override or os.path.join(project_dir, ".attocode", "dev-state.json")

    # --force: nuke cached state so everything re-runs
    # --name without --force: just clear repo_id to add a new repo
    if force and os.path.isfile(state_path):
        os.remove(state_path)
        print("Cleared cached state (--force).", file=sys.stderr)
    elif repo_name_override and os.path.isfile(state_path):
        import json as _json
        try:
            _state = _json.loads(open(state_path, encoding="utf-8").read())
            _state.pop("repo_id", None)
            open(state_path, "w", encoding="utf-8").write(_json.dumps(_state, indent=2))
            print("Cleared cached repo_id (--name forces new repo).", file=sys.stderr)
        except Exception:
            pass

    if token:
        # --- Non-interactive token path (original behavior + optional repo) ---
        rc = RemoteConfig(
            server=server,
            token=token,
            repo_id=repo_id,
            branch_auto_detect=True,
        )
    else:
        # --- Interactive (or scripted via --email/--password) auth path ---
        state = _bootstrap_user_and_project(
            api_base=server,
            project_dir=project_dir,
            state_path=state_path,
            email=email,
            password=password,
            org_slug=org_slug,
            repo_name=repo_name_override,
            interactive=interactive,
        )
        rc = RemoteConfig(
            server=server,
            token=state["token"],
            repo_id=repo_id or state.get("repo_id", ""),
            branch_auto_detect=True,
        )

    config_path = save_remote_config(project_dir, rc)

    # --- Auto-verify connection ---
    print(file=sys.stderr)
    errors = 0
    headers = {"Authorization": f"Bearer {rc.token}"}
    try:
        resp = httpx.get(f"{server}/api/v1/auth/me", headers=headers, timeout=10)
        if resp.status_code == 200:
            me = resp.json()
            print(f"  [ok] Authenticated as {me.get('email', '?')}", file=sys.stderr)
        else:
            print(f"  [FAIL] Auth check returned {resp.status_code}", file=sys.stderr)
            errors += 1
    except Exception as e:
        print(f"  [FAIL] Auth check: {e}", file=sys.stderr)
        errors += 1

    if rc.repo_id:
        try:
            resp = httpx.get(
                f"{server}/api/v2/repos/{rc.repo_id}/files",
                headers=headers,
                params={"limit": "1"},
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"  [ok] Repo {rc.repo_id} accessible", file=sys.stderr)
            else:
                print(f"  [FAIL] Repo check returned {resp.status_code}", file=sys.stderr)
                errors += 1
        except Exception as e:
            print(f"  [FAIL] Repo check: {e}", file=sys.stderr)
            errors += 1

    # --- Initial sync: push all tracked files so the server has content ---
    if rc.repo_id and not errors and not skip_sync:
        _initial_sync(rc, project_dir)

    # --- Summary ---
    print(
        f"\nConnection saved to {config_path}\n"
        f"  Server:  {rc.server}\n"
        f"  Repo ID: {rc.repo_id or '(auto-detect)'}\n",
        file=sys.stderr,
    )
    if errors:
        print(
            "Some checks failed. Run 'attocode code-intel test-connection' for details.",
            file=sys.stderr,
        )
    else:
        print(
            "Next steps:\n"
            "  attocode code-intel watch           # auto-notify on file save\n"
            "  attocode code-intel install claude   # install MCP server\n",
            file=sys.stderr,
        )


def _cmd_test_connection(args: list[str]) -> None:
    """Verify connectivity to the remote code-intel server.

    Checks: server reachable, auth valid, repo exists, notify endpoint works,
    WebSocket connection, index stats.
    """
    import subprocess

    try:
        import httpx
    except ImportError:
        print("Error: httpx not installed. Install with: pip install httpx", file=sys.stderr)
        sys.exit(1)

    from attocode.code_intel.config import load_remote_config

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    rc = load_remote_config(project_dir)
    if not rc.is_configured:
        print("Error: no remote connection configured.", file=sys.stderr)
        print("Run 'attocode code-intel connect --server <url>' first.", file=sys.stderr)
        sys.exit(1)

    server = rc.server.rstrip("/")
    headers = {"Authorization": f"Bearer {rc.token}"}
    errors = 0

    # 1. Server reachable
    try:
        resp = httpx.get(f"{server}/health", timeout=10)
        if resp.status_code == 200:
            print(f"  [ok] Server reachable at {server}")
        else:
            print(f"  [FAIL] Server returned {resp.status_code}")
            errors += 1
    except Exception as e:
        print(f"  [FAIL] Cannot connect to {server}: {e}")
        errors += 1
        # Can't continue without connectivity
        print(f"\n{errors} check(s) failed.")
        sys.exit(1)

    # 2. Authentication valid
    try:
        resp = httpx.get(f"{server}/api/v1/auth/me", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            email = data.get("email", data.get("username", "unknown"))
            print(f"  [ok] Authentication valid (user: {email})")
        else:
            print(f"  [FAIL] Authentication failed ({resp.status_code})")
            errors += 1
    except Exception as e:
        print(f"  [FAIL] Auth check error: {e}")
        errors += 1

    # 3. Repository registered
    if rc.repo_id:
        try:
            resp = httpx.get(
                f"{server}/api/v1/repos/{rc.repo_id}",
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                repo_name = data.get("name", rc.repo_id)
                print(f"  [ok] Repository registered ({repo_name}, repo_id: {rc.repo_id})")
            else:
                print(f"  [FAIL] Repository not found ({resp.status_code})")
                errors += 1
        except Exception as e:
            print(f"  [FAIL] Repo check error: {e}")
            errors += 1
    else:
        print("  [skip] No repo_id configured — use --repo to set")

    # 4. Branch tracked
    branch = "main"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except Exception:
        pass

    if rc.repo_id:
        try:
            resp = httpx.get(
                f"{server}/api/v1/repos/{rc.repo_id}/branches",
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                branches = resp.json()
                names = [b.get("name") for b in branches] if isinstance(branches, list) else []
                if branch in names:
                    print(f"  [ok] Branch tracked ({branch})")
                else:
                    print(f"  [warn] Branch '{branch}' not yet tracked (will be auto-created on first notify)")
            else:
                print(f"  [skip] Could not check branches ({resp.status_code})")
        except Exception:
            print("  [skip] Branch check skipped")

    # 5. Notify endpoint accepts changes
    try:
        resp = httpx.post(
            f"{server}/api/v1/notify/file-changed",
            json={"paths": [], "project": rc.repo_id, "branch": branch},
            headers=headers, timeout=10,
        )
        if resp.status_code in (200, 202, 422):
            # 422 is expected with empty paths — endpoint is reachable
            print("  [ok] Notify endpoint accepts changes")
        else:
            print(f"  [FAIL] Notify endpoint returned {resp.status_code}")
            errors += 1
    except Exception as e:
        print(f"  [FAIL] Notify endpoint error: {e}")
        errors += 1

    # 6. WebSocket connection
    try:
        import websockets.sync.client  # type: ignore[import-untyped]

        ws_url = server.replace("https://", "wss://").replace("http://", "ws://")
        if rc.repo_id:
            ws_url = f"{ws_url}/ws/repos/{rc.repo_id}/events?token={rc.token}"
            ws = websockets.sync.client.connect(ws_url, close_timeout=3, open_timeout=5)
            ws.close()
            print("  [ok] WebSocket connection established")
        else:
            print("  [skip] WebSocket check requires repo_id")
    except ImportError:
        print("  [skip] WebSocket check requires 'websockets' package")
    except Exception as e:
        print(f"  [warn] WebSocket connection failed: {e}")

    # 7. Index stats
    if rc.repo_id:
        try:
            resp = httpx.get(
                f"{server}/api/v2/repos/{rc.repo_id}/stats",
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                files = data.get("total_files", "?")
                embedded = data.get("embedded_files", "?")
                print(f"  [ok] {files} files indexed, {embedded} embedded")
            else:
                print("  [skip] Could not retrieve index stats")
        except Exception:
            print("  [skip] Index stats check skipped")

    print()
    if errors == 0:
        print("All checks passed!")
    else:
        print(f"{errors} check(s) failed.")
        sys.exit(1)


def _cmd_watch(args: list[str]) -> None:
    """Watch filesystem for changes and notify the remote server.

    Uses watchfiles (Rust-based, fast) to detect changes and batch-POSTs
    them to the remote server's notify endpoint.
    """
    import signal
    import subprocess
    import time

    try:
        import httpx
    except ImportError:
        print("Error: httpx not installed. Install with: pip install httpx", file=sys.stderr)
        sys.exit(1)

    try:
        from watchfiles import Change, watch
    except ImportError:
        print(
            "Error: watchfiles not installed. Install with: pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from attocode.code_intel.config import load_remote_config

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    # Parse debounce
    debounce_ms = 500
    for i, arg in enumerate(args):
        if arg == "--debounce" and i + 1 < len(args):
            debounce_ms = int(args[i + 1])
        elif arg.startswith("--debounce="):
            debounce_ms = int(arg.split("=", 1)[1])

    rc = load_remote_config(project_dir)
    if not rc.is_configured:
        print("Error: no remote connection configured.", file=sys.stderr)
        print("Run 'attocode code-intel connect --server <url>' first.", file=sys.stderr)
        sys.exit(1)

    # Detect branch
    branch = "main"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except Exception:
        pass

    code_extensions = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
        ".rb", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
    }

    import base64

    server = rc.server.rstrip("/")
    headers = {"Authorization": f"Bearer {rc.token}"}
    client = httpx.Client(timeout=30)

    # Run initial sync to catch up any files not yet pushed
    _initial_sync(rc, project_dir)

    stop_event = __import__("threading").Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    print(f"Watching {project_dir} for changes (branch: {branch}, debounce: {debounce_ms}ms)")
    print(f"Server: {server}")
    print("Press Ctrl+C to stop.\n")

    try:
        for changes in watch(
            project_dir,
            stop_event=stop_event,
            recursive=True,
            debounce=debounce_ms,
            watch_filter=lambda _, path: (
                not any(
                    part.startswith(".") or part in ("node_modules", "__pycache__", ".git")
                    for part in Path(path).parts
                )
                and Path(path).suffix.lower() in code_extensions
            ),
        ):
            if stop_event.is_set():
                break

            # Re-detect branch (may have changed)
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=project_dir,
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    branch = result.stdout.strip()
            except Exception:
                pass

            rel_paths = []
            for change_type, path_str in changes:
                if change_type in (Change.modified, Change.added, Change.deleted):
                    try:
                        rel = os.path.relpath(path_str, project_dir)
                        rel_paths.append(rel)
                    except ValueError:
                        pass

            if not rel_paths:
                continue

            # Read file contents and base64-encode them
            files: dict[str, str] = {}
            for rel_path in rel_paths:
                full = os.path.join(project_dir, rel_path)
                if os.path.isfile(full):
                    try:
                        with open(full, "rb") as f:
                            files[rel_path] = base64.b64encode(f.read()).decode("ascii")
                    except (OSError, PermissionError):
                        pass  # deleted or unreadable — omit, server treats as deleted

            try:
                resp = client.post(
                    f"{server}/api/v1/notify/file-changed",
                    json={
                        "paths": rel_paths,
                        "files": files,
                        "project": rc.repo_id,
                        "branch": branch,
                    },
                    headers=headers,
                )
                if resp.status_code in (200, 202):
                    print(f"  Notified: {len(rel_paths)} file(s) on {branch}")
                else:
                    print(f"  Error: server returned {resp.status_code}", file=sys.stderr)
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)

    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        print("\nStopped watching.")


def _cmd_index(args: list[str]) -> None:
    """Build or check the semantic search embedding index.

    Modes:
      --status       Print current index status and exit
      --foreground   Blocking full index (default if no --background)
      --background   Start daemon, poll progress, print status
    """
    import time

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    mode = "foreground"
    for arg in args:
        if arg == "--status":
            mode = "status"
        elif arg == "--background":
            mode = "background"
        elif arg == "--foreground":
            mode = "foreground"

    os.environ.setdefault("ATTOCODE_PROJECT_DIR", project_dir)

    from attocode.integrations.context.semantic_search import SemanticSearchManager

    mgr = SemanticSearchManager(root_dir=project_dir)

    if mode == "status":
        progress = mgr.get_index_progress()
        print(f"Provider: {mgr.provider_name}")
        print(f"Status: {progress.status}")
        print(f"Coverage: {progress.coverage:.0%} ({progress.indexed_files}/{progress.total_files} files)")
        if progress.elapsed_seconds > 0:
            print(f"Elapsed: {progress.elapsed_seconds:.1f}s")
        print(f"Vector search active: {mgr.is_index_ready()}")
        mgr.close()
        return

    if not mgr.is_available:
        print(
            "No embedding provider available. Install sentence-transformers:\n"
            "  pip install 'attocode[semantic]'",
            file=sys.stderr,
        )
        mgr.close()
        sys.exit(1)

    if mode == "foreground":
        print(f"Indexing {project_dir} (foreground)...", file=sys.stderr)
        count = mgr.index()
        print(f"Indexed {count} chunks.", file=sys.stderr)
        mgr.close()
        return

    # Parse --timeout flag (default: 30 minutes)
    timeout_seconds = 1800
    for i, arg in enumerate(args):
        if arg == "--timeout" and i + 1 < len(args):
            timeout_seconds = int(args[i + 1])
        elif arg.startswith("--timeout="):
            timeout_seconds = int(arg.split("=", 1)[1])

    # Background mode
    print(f"Starting background indexing for {project_dir}...", file=sys.stderr)
    progress = mgr.start_background_indexing()
    deadline = time.time() + timeout_seconds

    try:
        while progress.status == "running":
            if time.time() > deadline:
                print(
                    f"\nTimeout: indexing did not complete within {timeout_seconds}s. "
                    "Use --timeout to increase.",
                    file=sys.stderr,
                )
                mgr.stop_background_indexing()
                break
            progress = mgr.get_index_progress()
            print(
                f"\r  {progress.indexed_files}/{progress.total_files} files "
                f"({progress.coverage:.0%}) — {progress.elapsed_seconds:.0f}s",
                end="", file=sys.stderr, flush=True,
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        mgr.stop_background_indexing()

    progress = mgr.get_index_progress()
    print(f"\nDone: {progress.status} ({progress.indexed_files}/{progress.total_files} files)", file=sys.stderr)
    mgr.close()


# ---------------------------------------------------------------------------
# setup command helpers
# ---------------------------------------------------------------------------


def _load_env_file(path: str) -> dict[str, str]:
    """Parse a .env file into os.environ. Returns parsed key-value pairs."""
    import re

    pairs: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            pairs[key] = val
            os.environ[key] = val
    return pairs


def _run(
    cmd: list[str], *, check: bool = True, capture: bool = False,
) -> "subprocess.CompletedProcess[str]":
    """Run a subprocess with visible logging."""
    import subprocess

    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def _detect_default_branch(project_dir: str) -> str:
    """Detect the git default branch via symbolic-ref, fallback 'main'."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            # refs/remotes/origin/main -> main
            return result.stdout.strip().rsplit("/", 1)[-1]
    except Exception:
        pass
    return "main"


def _cmd_setup(args: list[str]) -> None:
    """[Dev] Bootstrap local infrastructure for contributing to attocode.

    Phase 1 (infra): Docker, deps, migrations — no API needed.
    Phase 2 (bootstrap): Register dev user, create org, add repo — requires running API.

    To connect to an existing server, use ``attocode code-intel connect`` instead.
    """
    import subprocess

    try:
        import httpx
    except ImportError:
        print(
            "Error: httpx not installed. Install with: uv sync --extra service",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- parse flags ---
    reset = False
    skip_deps = False
    project_dir = "."

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--reset":
            reset = True
            i += 1
        elif arg == "--skip-deps":
            skip_deps = True
            i += 1
        elif arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
            i += 2
        elif arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
            i += 1
        else:
            i += 1

    project_dir = os.path.abspath(project_dir)
    compose_file = os.path.join(project_dir, "docker", "code-intel", "docker-compose.dev.yml")
    env_dev = os.path.join(project_dir, ".env.dev")
    state_path = os.path.join(project_dir, ".attocode", "dev-state.json")
    alembic_ini = os.path.join(
        project_dir, "src", "attocode", "code_intel", "migrations", "alembic.ini",
    )

    # =========================================================
    # Phase 1 — Infrastructure (no API needed)
    # =========================================================
    print("\n=== Phase 1: Infrastructure ===\n", file=sys.stderr)

    # 1. Reset if requested
    if reset:
        print("Resetting...", file=sys.stderr)
        _run(
            ["docker", "compose", "-f", compose_file, "down", "-v"],
            check=False,
        )
        if os.path.exists(state_path):
            os.remove(state_path)
            print(f"Removed {state_path}", file=sys.stderr)

    # 2. Check prerequisites
    for tool in ("docker", "uv"):
        if not shutil.which(tool):
            print(f"Error: '{tool}' not found on PATH.", file=sys.stderr)
            sys.exit(1)

    for required in (compose_file, env_dev):
        if not os.path.isfile(required):
            print(f"Error: required file not found: {required}", file=sys.stderr)
            sys.exit(1)

    # 3. Start Postgres + Redis
    _run(["docker", "compose", "-f", compose_file, "up", "-d", "--wait"])

    # 4. Install deps
    if not skip_deps:
        _run(["uv", "sync", "--extra", "service", "--extra", "semantic"])

    # 5. Load .env.dev
    env_vars = _load_env_file(env_dev)
    print(f"Loaded {len(env_vars)} env vars from {env_dev}", file=sys.stderr)

    # 6. Run migrations
    _run(["uv", "run", "alembic", "-c", alembic_ini, "upgrade", "head"])

    print("\nPhase 1 complete.", file=sys.stderr)

    # =========================================================
    # Phase 2 — Bootstrap (requires running API)
    # =========================================================
    print("\n=== Phase 2: Bootstrap ===\n", file=sys.stderr)

    api_base = f"http://127.0.0.1:{env_vars.get('ATTOCODE_PORT', '8080')}"

    # 7. Health check
    try:
        resp = httpx.get(f"{api_base}/health", timeout=5)
        if resp.status_code != 200:
            raise httpx.ConnectError("unhealthy")
    except Exception:
        print(
            f"API server not reachable at {api_base}.\n"
            "Start it in another terminal:\n\n"
            f"  source {env_dev} && uvicorn attocode.code_intel.api.app:create_app "
            "--factory --reload --port 8080\n\n"
            "Then re-run:  attocode code-intel setup\n",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"API reachable at {api_base}", file=sys.stderr)

    # 8. Register dev user, create org, add repo (shared helper)
    state = _bootstrap_user_and_project(
        api_base=api_base,
        project_dir=project_dir,
        state_path=state_path,
        email="dev@localhost",
        password="dev-password-123",
        org_slug="dev-org",
        interactive=False,
    )

    # 9. Write .attocode/config.toml for notify/watch
    from attocode.code_intel.config import RemoteConfig, save_remote_config

    rc = RemoteConfig(
        server=api_base,
        token=state["token"],
        repo_id=state["repo_id"],
        branch_auto_detect=True,
    )
    config_path = save_remote_config(project_dir, rc)

    # 10. Summary
    print(
        f"\n=== Setup complete ===\n\n"
        f"  API:    {api_base}\n"
        f"  Org:    {state['org_id']}\n"
        f"  Repo:   {state['repo_id']}\n"
        f"  Config: {config_path}\n\n"
        "Next steps:\n"
        f"  # Worker (processes indexing jobs)\n"
        f"  source {env_dev} && python -m attocode.code_intel.workers.run\n\n"
        f"  # Frontend (optional)\n"
        f"  cd frontend && npm run dev\n\n"
        f"  # Auto-notify on file save\n"
        f"  attocode code-intel watch\n",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# CLI Query Commands
# ---------------------------------------------------------------------------


def _cmd_query(args: list[str]) -> None:
    """Semantic search across the codebase."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    # Parse positional query text and flags
    query_parts: list[str] = []
    top_k = 10
    file_filter = ""

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--top" and i + 1 < len(args):
            top_k = int(args[i + 1])
            i += 2
        elif arg.startswith("--top="):
            top_k = int(arg.split("=", 1)[1])
            i += 1
        elif arg == "--filter" and i + 1 < len(args):
            file_filter = args[i + 1]
            i += 2
        elif arg.startswith("--filter="):
            file_filter = arg.split("=", 1)[1]
            i += 1
        elif arg == "--project" and i + 1 < len(args):
            i += 2  # already parsed by _parse_opts
        elif arg.startswith("--project="):
            i += 1
        elif not arg.startswith("-"):
            query_parts.append(arg)
            i += 1
        else:
            i += 1

    query = " ".join(query_parts)
    if not query:
        print("Usage: attocode code-intel query <text> [--top N] [--filter '*.py'] [--project <path>]", file=sys.stderr)
        sys.exit(1)

    from attocode.code_intel.service import CodeIntelService

    svc = CodeIntelService(project_dir)
    data = svc.semantic_search_data(query, top_k=top_k, file_filter=file_filter)
    _print_search_results(data)


def _cmd_symbols(args: list[str]) -> None:
    """List symbols in a file or search symbols by name."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    # Parse positional file and --search flag
    target_file: str | None = None
    search_name: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--search" and i + 1 < len(args):
            search_name = args[i + 1]
            i += 2
        elif arg.startswith("--search="):
            search_name = arg.split("=", 1)[1]
            i += 1
        elif arg == "--project" and i + 1 < len(args):
            i += 2
        elif arg.startswith("--project="):
            i += 1
        elif not arg.startswith("-") and target_file is None:
            target_file = arg
            i += 1
        else:
            i += 1

    if not target_file and not search_name:
        print("Usage: attocode code-intel symbols <file> [--search <name>] [--project <path>]", file=sys.stderr)
        sys.exit(1)

    from attocode.code_intel.service import CodeIntelService

    svc = CodeIntelService(project_dir)

    if search_name:
        data = svc.search_symbols_data(search_name)
        _print_symbols_table(data, title=f"Search results for '{search_name}'")
    else:
        assert target_file is not None
        data = svc.symbols_data(target_file)
        _print_symbols_table(data, title=f"Symbols in {target_file}")


def _cmd_impact(args: list[str]) -> None:
    """Show blast radius of file changes."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    # Collect positional file arguments
    files: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            i += 2
        elif arg.startswith("--project="):
            i += 1
        elif not arg.startswith("-"):
            files.append(arg)
            i += 1
        else:
            i += 1

    if not files:
        print("Usage: attocode code-intel impact <file> [file2 ...] [--project <path>]", file=sys.stderr)
        sys.exit(1)

    from attocode.code_intel.service import CodeIntelService

    svc = CodeIntelService(project_dir)
    data = svc.impact_analysis_data(files)
    _print_impact_analysis(data)


def _cmd_hotspots(args: list[str]) -> None:
    """Show risk/complexity hotspots."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    top_n = 15

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--top" and i + 1 < len(args):
            top_n = int(args[i + 1])
            i += 2
        elif arg.startswith("--top="):
            top_n = int(arg.split("=", 1)[1])
            i += 1
        elif arg == "--project" and i + 1 < len(args):
            i += 2
        elif arg.startswith("--project="):
            i += 1
        else:
            i += 1

    from attocode.code_intel.service import CodeIntelService

    svc = CodeIntelService(project_dir)
    data = svc.hotspots_data(top_n=top_n)
    _print_hotspots(data)


def _cmd_deps(args: list[str]) -> None:
    """Show file dependencies and dependents."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    target_file: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            i += 2
        elif arg.startswith("--project="):
            i += 1
        elif not arg.startswith("-") and target_file is None:
            target_file = arg
            i += 1
        else:
            i += 1

    if not target_file:
        print("Usage: attocode code-intel deps <file> [--project <path>]", file=sys.stderr)
        sys.exit(1)

    from attocode.code_intel.service import CodeIntelService

    svc = CodeIntelService(project_dir)
    data = svc.dependencies_data(target_file)
    _print_dependencies(data)


def _cmd_gc(args: list[str]) -> None:
    """Run garbage collection on orphaned embeddings and unreferenced content."""
    import asyncio

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    from attocode.code_intel.config import CodeIntelConfig, load_remote_config

    remote_cfg = load_remote_config(project_dir)

    if remote_cfg.is_configured:
        # Remote mode: trigger GC jobs via API
        try:
            import httpx
        except ImportError:
            print("Error: httpx not installed. Install with: pip install httpx", file=sys.stderr)
            sys.exit(1)

        base_url = remote_cfg.server.rstrip("/")
        headers = {"Authorization": f"Bearer {remote_cfg.token}"}
        print(f"Triggering GC on remote server {base_url}...", file=sys.stderr)

        try:
            with httpx.Client(timeout=60) as client:
                # Trigger gc_orphaned_embeddings job
                resp = client.post(
                    f"{base_url}/api/v1/jobs/enqueue",
                    json={"function": "gc_orphaned_embeddings"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    print("  Enqueued gc_orphaned_embeddings job")
                else:
                    print(f"  Warning: could not enqueue gc_orphaned_embeddings: {resp.status_code}", file=sys.stderr)

                # Trigger gc_unreferenced_content job
                resp = client.post(
                    f"{base_url}/api/v1/jobs/enqueue",
                    json={"function": "gc_unreferenced_content"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    print("  Enqueued gc_unreferenced_content job")
                else:
                    print(f"  Warning: could not enqueue gc_unreferenced_content: {resp.status_code}", file=sys.stderr)
        except httpx.HTTPError as exc:
            print(f"Error contacting remote server: {exc}", file=sys.stderr)
            sys.exit(1)

        print("GC jobs enqueued on remote server.")
        return

    # Local mode: run GC directly against the database
    config = CodeIntelConfig.from_env()
    if not config.database_url:
        # Pure local mode (SQLite / no DB) — clear AST cache
        print("Local mode: clearing AST cache...", file=sys.stderr)
        from pathlib import Path

        cache_dir = Path(project_dir) / ".attocode" / "cache"
        if cache_dir.exists():
            removed = 0
            for f in cache_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    removed += 1
            print(f"  Removed {removed} cached file(s).")
        else:
            print("  No cache directory found.")
        print("GC complete.")
        return

    # Service mode with database: run GC operations
    async def _run_gc() -> None:
        from attocode.code_intel.db.engine import get_session
        from attocode.code_intel.storage.content_store import ContentStore
        from attocode.code_intel.storage.embedding_store import EmbeddingStore

        print("Running garbage collection...", file=sys.stderr)

        async for session in get_session():
            # 1. GC orphaned embeddings
            emb_store = EmbeddingStore(session)
            emb_count = await emb_store.gc_orphaned(
                min_age_minutes=config.gc_content_min_age_minutes,
            )
            print(f"  Orphaned embeddings removed: {emb_count}")

            # 2. GC unreferenced content
            content_store = ContentStore(session)
            content_count = await content_store.gc_unreferenced(
                min_age_minutes=config.gc_content_min_age_minutes,
            )
            print(f"  Unreferenced content removed: {content_count}")

            await session.commit()
            print("GC complete.")
            return

    asyncio.run(_run_gc())


def _cmd_verify(args: list[str]) -> None:
    """Run integrity checks on the code-intel index."""
    import asyncio

    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    from attocode.code_intel.config import CodeIntelConfig

    config = CodeIntelConfig.from_env()

    if not config.database_url:
        # Pure local mode — verify local index files exist
        from pathlib import Path

        print("Running local integrity checks...", file=sys.stderr)

        cache_dir = Path(project_dir) / ".attocode" / "cache"
        index_file = Path(project_dir) / ".attocode" / "index.json"

        issues: list[str] = []
        if not cache_dir.exists():
            issues.append("Cache directory missing (.attocode/cache)")
        if not index_file.exists():
            issues.append("Index file missing (.attocode/index.json)")

        if issues:
            print(f"\nFound {len(issues)} issue(s):")
            for issue in issues:
                print(f"  [!] {issue}")
            print("\nRun 'attocode code-intel reindex' to rebuild the index.")
        else:
            cache_files = list(cache_dir.iterdir()) if cache_dir.exists() else []
            print(f"\nLocal index OK:")
            print(f"  Cache files: {len(cache_files)}")
            print(f"  Index file:  {index_file}")
        return

    # Service mode: run integrity checks against the database
    async def _run_verify() -> None:
        from sqlalchemy import func as sa_func
        from sqlalchemy import select, text

        from attocode.code_intel.db.engine import get_session
        from attocode.code_intel.db.models import Branch, BranchFile, Embedding, FileContent, Symbol

        print("Running integrity checks...\n", file=sys.stderr)
        issues: list[str] = []
        stats: dict[str, int] = {}

        async for session in get_session():
            # 1. Orphaned BranchFile entries (content_sha not in file_contents)
            result = await session.execute(text("""
                SELECT COUNT(*) FROM branch_files
                WHERE content_sha IS NOT NULL
                  AND content_sha NOT IN (SELECT sha256 FROM file_contents)
            """))
            orphaned_bf = result.scalar() or 0
            stats["orphaned_branch_files"] = orphaned_bf
            if orphaned_bf > 0:
                issues.append(f"{orphaned_bf} branch_files reference missing file_contents")

            # 2. Orphaned embeddings (content_sha not in any branch manifest)
            result = await session.execute(text("""
                SELECT COUNT(*) FROM embeddings
                WHERE content_sha NOT IN (
                    SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
                )
            """))
            orphaned_emb = result.scalar() or 0
            stats["orphaned_embeddings"] = orphaned_emb
            if orphaned_emb > 0:
                issues.append(f"{orphaned_emb} embeddings reference content not in any branch manifest")

            # 3. Missing embeddings (content_sha in branch manifest but no embedding)
            result = await session.execute(text("""
                SELECT COUNT(DISTINCT bf.content_sha) FROM branch_files bf
                WHERE bf.content_sha IS NOT NULL
                  AND bf.content_sha NOT IN (SELECT DISTINCT content_sha FROM embeddings)
            """))
            missing_emb = result.scalar() or 0
            stats["missing_embeddings"] = missing_emb
            if missing_emb > 0:
                issues.append(f"{missing_emb} content SHAs in branch manifests have no embeddings")

            # 4. Broken parent_branch_id references
            result = await session.execute(text("""
                SELECT COUNT(*) FROM branches
                WHERE parent_branch_id IS NOT NULL
                  AND parent_branch_id NOT IN (SELECT id FROM branches)
            """))
            broken_parents = result.scalar() or 0
            stats["broken_parent_branch_refs"] = broken_parents
            if broken_parents > 0:
                issues.append(f"{broken_parents} branches reference non-existent parent branches")

            # 5. Orphaned symbols (content_sha not in file_contents)
            result = await session.execute(text("""
                SELECT COUNT(*) FROM symbols
                WHERE content_sha NOT IN (SELECT sha256 FROM file_contents)
            """))
            orphaned_sym = result.scalar() or 0
            stats["orphaned_symbols"] = orphaned_sym
            if orphaned_sym > 0:
                issues.append(f"{orphaned_sym} symbols reference missing file_contents")

            # Print results
            print("Integrity check results:")
            print(f"  Orphaned branch_files:      {stats['orphaned_branch_files']}")
            print(f"  Orphaned embeddings:        {stats['orphaned_embeddings']}")
            print(f"  Missing embeddings:         {stats['missing_embeddings']}")
            print(f"  Broken parent_branch refs:  {stats['broken_parent_branch_refs']}")
            print(f"  Orphaned symbols:           {stats['orphaned_symbols']}")

            if issues:
                print(f"\nFound {len(issues)} issue(s):")
                for issue in issues:
                    print(f"  [!] {issue}")
                print("\nRun 'attocode code-intel gc' to clean up orphaned data.")
                print("Run 'attocode code-intel reindex' to rebuild missing embeddings.")
            else:
                print("\nAll checks passed.")

            return

    asyncio.run(_run_verify())


def _cmd_reindex(args: list[str]) -> None:
    """Force a full reindex of the project."""
    _, project_dir, _, _ = _parse_opts(args)
    project_dir = os.path.abspath(project_dir)

    from attocode.code_intel.config import load_remote_config

    remote_cfg = load_remote_config(project_dir)

    if remote_cfg.is_configured:
        # Remote mode: trigger index_repository job via API
        try:
            import httpx
        except ImportError:
            print("Error: httpx not installed. Install with: pip install httpx", file=sys.stderr)
            sys.exit(1)

        base_url = remote_cfg.server.rstrip("/")
        headers = {"Authorization": f"Bearer {remote_cfg.token}"}
        repo_id = remote_cfg.repo_id
        if not repo_id:
            print("Error: no repo_id configured. Run 'attocode code-intel connect' first.", file=sys.stderr)
            sys.exit(1)

        print(f"Triggering full reindex on remote server {base_url}...", file=sys.stderr)

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{base_url}/api/v1/repos/{repo_id}/index",
                    headers=headers,
                )
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    print(f"  Reindex job enqueued: {data}")
                else:
                    print(f"  Error: server returned {resp.status_code}: {resp.text}", file=sys.stderr)
                    sys.exit(1)
        except httpx.HTTPError as exc:
            print(f"Error contacting remote server: {exc}", file=sys.stderr)
            sys.exit(1)

        print("Reindex triggered on remote server.")
        return

    # Local mode: clear cache and reinitialize
    from pathlib import Path

    print(f"Reindexing {project_dir}...", file=sys.stderr)

    # 1. Clear AST cache
    cache_dir = Path(project_dir) / ".attocode" / "cache"
    if cache_dir.exists():
        removed = 0
        for f in cache_dir.iterdir():
            if f.is_file():
                f.unlink()
                removed += 1
        print(f"  Cleared {removed} cached file(s).")

    # 2. Remove stale index file to force full rebuild
    index_file = Path(project_dir) / ".attocode" / "index.json"
    if index_file.exists():
        index_file.unlink()
        print("  Removed stale index file.")

    # 3. Run full index
    os.environ.setdefault("ATTOCODE_PROJECT_DIR", project_dir)

    from attocode.integrations.context.semantic_search import SemanticSearchManager

    mgr = SemanticSearchManager(root_dir=project_dir)

    if not mgr.is_available:
        print(
            "No embedding provider available. Install sentence-transformers:\n"
            "  pip install 'attocode[semantic]'",
            file=sys.stderr,
        )
        mgr.close()
        sys.exit(1)

    count = mgr.index()
    print(f"  Indexed {count} chunks.")
    mgr.close()
    print("Reindex complete.")


# ---------------------------------------------------------------------------
# Terminal formatters for query commands
# ---------------------------------------------------------------------------


def _print_search_results(data: dict) -> None:
    """Print semantic search results as a numbered list with file, score, snippet."""
    results = data.get("results", [])
    total = data.get("total", len(results))
    query = data.get("query", "")

    print(f"Semantic search: \"{query}\" ({total} result(s))\n")

    if not results:
        print("  No results found.")
        return

    for idx, r in enumerate(results, 1):
        file_path = r.get("file_path", "?")
        score = r.get("score", 0.0)
        snippet = r.get("snippet", "")
        line = r.get("line")

        loc = f"{file_path}:{line}" if line else file_path
        print(f"  {idx:>3}. {loc}  (score: {score:.4f})")

        if snippet:
            # Indent snippet lines, truncate long ones
            for sline in snippet.strip().splitlines()[:3]:
                truncated = sline[:120] + "..." if len(sline) > 120 else sline
                print(f"       {truncated}")
        print()


def _print_symbols_table(data: list[dict], title: str = "Symbols") -> None:
    """Print symbols as a fixed-width table with name, kind, file, line."""
    print(f"{title} ({len(data)} symbol(s))\n")

    if not data:
        print("  No symbols found.")
        return

    # Compute column widths
    name_w = max(len(s.get("name", "")) for s in data)
    name_w = max(name_w, 4)  # minimum "Name"
    name_w = min(name_w, 40)  # cap width

    kind_w = max(len(s.get("kind", "")) for s in data)
    kind_w = max(kind_w, 4)
    kind_w = min(kind_w, 15)

    # Header
    header = f"  {'Name':<{name_w}}  {'Kind':<{kind_w}}  {'File':<50}  {'Line':>5}"
    print(header)
    print(f"  {'-' * name_w}  {'-' * kind_w}  {'-' * 50}  {'-' * 5}")

    for s in data:
        name = s.get("name", "")[:name_w]
        kind = s.get("kind", "")[:kind_w]
        file_path = s.get("file_path", "")
        if len(file_path) > 50:
            file_path = "..." + file_path[-47:]
        start_line = s.get("start_line", "")

        print(f"  {name:<{name_w}}  {kind:<{kind_w}}  {file_path:<50}  {start_line:>5}")


def _print_impact_analysis(data: dict) -> None:
    """Print impact analysis as a tree of affected files."""
    changed = data.get("changed_files", [])
    impacted = data.get("impacted_files", [])
    total = data.get("total_impacted", len(impacted))
    layers = data.get("layers", [])

    print(f"Impact analysis: {len(changed)} changed file(s), {total} impacted file(s)\n")

    print("  Changed files:")
    for f in changed:
        print(f"    * {f}")

    if not layers:
        print("\n  No downstream impact detected.")
        return

    print()
    for layer in layers:
        depth = layer.get("depth", "?")
        files = layer.get("files", [])
        print(f"  Depth {depth} ({len(files)} file(s)):")
        for f in files:
            print(f"    {'|' * depth} {f}")


def _print_hotspots(data: dict) -> None:
    """Print hotspots as a ranked table with file, categories, score."""
    file_hotspots = data.get("file_hotspots", [])
    fn_hotspots = data.get("function_hotspots", [])
    orphans = data.get("orphan_files", [])

    # File hotspots
    print(f"File hotspots ({len(file_hotspots)} file(s))\n")

    if file_hotspots:
        header = f"  {'#':>3}  {'File':<55}  {'Lines':>5}  {'Score':>6}  Categories"
        print(header)
        print(f"  {'-' * 3}  {'-' * 55}  {'-' * 5}  {'-' * 6}  {'-' * 25}")

        for idx, h in enumerate(file_hotspots, 1):
            path = h.get("path", "")
            if len(path) > 55:
                path = "..." + path[-52:]
            lines = h.get("line_count", 0)
            score = h.get("composite", 0.0)
            cats = ", ".join(h.get("categories", []))

            print(f"  {idx:>3}  {path:<55}  {lines:>5}  {score:>6.2f}  {cats}")
    else:
        print("  No file hotspots found.")

    # Function hotspots
    if fn_hotspots:
        print(f"\nFunction hotspots ({len(fn_hotspots)} function(s))\n")
        header = f"  {'Name':<35}  {'File':<40}  {'Lines':>5}  {'Params':>6}"
        print(header)
        print(f"  {'-' * 35}  {'-' * 40}  {'-' * 5}  {'-' * 6}")

        for fh in fn_hotspots:
            name = fh.get("name", "")[:35]
            fp = fh.get("file_path", "")
            if len(fp) > 40:
                fp = "..." + fp[-37:]
            lc = fh.get("line_count", 0)
            pc = fh.get("param_count", 0)
            print(f"  {name:<35}  {fp:<40}  {lc:>5}  {pc:>6}")

    # Orphan files
    if orphans:
        print(f"\nOrphan files ({len(orphans)} file(s) — no imports/importers)\n")
        for o in orphans:
            path = o.get("path", "")
            lines = o.get("line_count", 0)
            print(f"    {path}  ({lines} lines)")


def _print_dependencies(data: dict) -> None:
    """Print dependency information: imports and imported-by lists."""
    path = data.get("path", "?")
    imports = data.get("imports", [])
    imported_by = data.get("imported_by", [])

    print(f"Dependencies for {path}\n")

    print(f"  Imports ({len(imports)}):")
    if imports:
        for dep in imports:
            print(f"    -> {dep}")
    else:
        print("    (none)")

    print(f"\n  Imported by ({len(imported_by)}):")
    if imported_by:
        for dep in imported_by:
            print(f"    <- {dep}")
    else:
        print("    (none)")
