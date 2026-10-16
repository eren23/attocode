"""Standalone CLI; importing it does not load the agent or analysis engines."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time

COMMANDS = """commands:
  init                Add the server to Codex, Claude Code or Cursor (--client)
  doctor              Start the configured server and check that it answers
  install <target>    Add the server to another client, for example vscode or zed
  share               Send a learning to a team server
  query <text>        Search the code
  symbols <file>      List the symbols of a file, or find one with --search <name>
  impact <file>...    Show the files that a change to these files can affect
  hotspots            Show the files with the most risk or complexity
  deps <file>         Show what a file imports and what imports it
  changes             Investigate a diff; export, check or refresh evidence
  trace <symbol>      Follow static caller paths with source evidence
  commands            Show all commands, with maintenance commands and targets
"""


def exit_when_client_exits(interval: float = 5.0) -> None:
    """Stop a stdio server when the client process that started it is gone.

    At end of input the MCP SDK still waits for running tool calls. A call
    that never ended kept an orphaned server alive, at full CPU, for days.
    SQLite indexes stay consistent after an abrupt exit. The watchdog does not
    write a message: stderr usually goes to the closed client, and a write
    error would stop the thread before the exit.
    """
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(interval)
        os._exit(0)

    threading.Thread(target=watch, name="client-watchdog", daemon=True).start()


def main(argv=None):
    from attocode_intel.catalog import PROFILES
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "share":
        from attocode_intel.sharing import share

        share(args[1:])
        return
    if args and args[0] in {"init", "doctor"}:
        command = args.pop(0)
        parser = argparse.ArgumentParser(prog=f"attocode-code-intel {command}")
        parser.add_argument("--client", choices=["codex", "claude", "cursor", "all"], default="all")
        parser.add_argument("--project", default=".")
        parser.add_argument("--global", dest="global_scope", action="store_true")
        parser.add_argument("--profile", choices=PROFILES, default="daily")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--remove", action="store_true")
        parser.add_argument("--server", default="")
        parser.add_argument("--repo", default="")
        parser.add_argument(
            "--remote", action="store_true", help="Doctor/remove: select the remote integration"
        )
        parser.add_argument("--token-env", default="ATTOCODE_API_KEY")
        opts = parser.parse_args(args)
        from attocode_intel.onboarding import configure_client, diagnose

        clients = ["codex", "claude", "cursor"] if opts.client == "all" else [opts.client]
        failed, ready = False, 0
        for client in clients:
            try:
                if command == "init":
                    result = configure_client(
                        client,
                        opts.project,
                        global_scope=opts.global_scope,
                        profile=opts.profile,
                        dry_run=opts.dry_run,
                        remove=opts.remove,
                        server=opts.server,
                        token_env=opts.token_env,
                        repo=opts.repo or ("remote" if opts.remote else ""),
                    )
                else:
                    result = asyncio.run(
                        diagnose(
                            client,
                            opts.project,
                            global_scope=opts.global_scope,
                            remote=bool(opts.remote or opts.server or opts.repo),
                        )
                    )
                print(json.dumps(result, indent=2))
                ready += result.get("status") != "not configured"
            except Exception as exc:
                # A timeout has no message of its own.
                reason = "the server did not answer in 30 s" if isinstance(exc, TimeoutError) else exc
                print(f"{client}: {reason}", file=sys.stderr)
                failed = True
        # With --client all, a client without configuration is not a failure, but one client must be ready.
        if failed or not ready:
            raise SystemExit(1)
        return
    if args and args[0] not in {"serve", "help"} and not args[0].startswith("-"):
        from attocode_intel.cli import dispatch_code_intel

        dispatch_code_intel(args)
        return
    if args and args[0] == "serve":
        args.pop(0)
    if args == ["help"]:
        args = ["--help"]
    parser = argparse.ArgumentParser(
        prog="attocode-code-intel",
        description="Code search and navigation for coding agents and for people. "
        "Without a command, it runs the MCP server.",
        epilog=COMMANDS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=os.environ.get("ATTOCODE_PROJECT_DIR", ""))
    parser.add_argument(
        "--profile", choices=PROFILES, default="daily",
        help="daily: default tool list; full: all tools; lean: experimental seven-tool local profile",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "sse", "http", "streamable-http"], default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--local-only", action="store_true", help="Accepted for old configurations; it has no effect"
    )
    parser.add_argument("--no-watch", action="store_true")
    parser.add_argument("--watch-debounce", type=int, default=500)
    from attocode_intel import __version__

    parser.add_argument("--version", action="version", version=f"attocode-code-intel {__version__}")
    opts = parser.parse_args(args)
    if opts.profile == "lean" and opts.transport == "sse":
        parser.error("lean requires stdio or local HTTP; legacy SSE lists all tools")
    if opts.transport in {"http", "streamable-http"}:
        from attocode_intel.cli import _serve_http

        os.environ["ATTOCODE_MCP_PROFILE"] = opts.profile
        os.environ["ATTOCODE_INTEL_WATCH"] = "0" if opts.no_watch else "1"
        os.environ["ATTOCODE_INTEL_WATCH_DEBOUNCE"] = str(opts.watch_debounce)
        _serve_http(opts.project, host=opts.host, port=opts.port, debug=False)
    elif opts.transport == "sse":
        from attocode_intel.config import is_loopback

        if not is_loopback(opts.host):
            # SSE has no sign-in, so any computer that reaches the port could read the index.
            raise SystemExit("Error: SSE serves only this computer. For other hosts, use "
                             "--transport http with ATTOCODE_API_KEY.")
        # ponytail: SSE runs the older server, which lists all tools. Use stdio or http for profiles.
        from attocode_intel.server import mcp

        mcp.settings.host, mcp.settings.port = opts.host, opts.port
        if opts.project:
            os.environ["ATTOCODE_PROJECT_DIR"] = opts.project
        mcp.run(transport="sse")
    else:
        asyncio.run(_stdio(opts))


async def _stdio(opts):
    from mcp.server.stdio import stdio_server

    from attocode_intel.gateway import OperationGateway, create_mcp_server

    gateway = OperationGateway(
        opts.project, opts.profile, watch=not opts.no_watch, watch_debounce=opts.watch_debounce
    )
    server = create_mcp_server(gateway)
    exit_when_client_exits()
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await gateway.close()


if __name__ == "__main__":
    main()
