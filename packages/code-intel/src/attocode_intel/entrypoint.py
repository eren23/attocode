"""Standalone CLI; importing it does not load the agent or analysis engines."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


def main(argv=None):
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
        parser.add_argument("--profile", choices=["daily", "full"], default="daily")
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
        failed = False
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
            except Exception as exc:
                print(f"{client}: {exc}", file=sys.stderr)
                failed = True
        if failed:
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
        description="Codebase intelligence for coding agents. Use init to configure clients; doctor verifies them.",
    )
    parser.add_argument("--project", default=os.environ.get("ATTOCODE_PROJECT_DIR", ""))
    parser.add_argument("--profile", choices=["daily", "full"], default="full")
    parser.add_argument(
        "--transport", choices=["stdio", "sse", "http", "streamable-http"], default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--no-watch", action="store_true")
    parser.add_argument("--watch-debounce", type=int, default=500)
    parser.add_argument("--version", action="version", version="attocode-code-intel 0.1.0")
    opts = parser.parse_args(args)
    if opts.transport in {"http", "streamable-http"}:
        from attocode_intel.cli import _serve_http

        os.environ["ATTOCODE_MCP_PROFILE"] = opts.profile
        os.environ["ATTOCODE_INTEL_WATCH"] = "0" if opts.no_watch else "1"
        os.environ["ATTOCODE_INTEL_WATCH_DEBOUNCE"] = str(opts.watch_debounce)
        _serve_http(opts.project, host=opts.host, port=opts.port, debug=False)
    elif opts.transport == "sse":
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
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await gateway.close()


if __name__ == "__main__":
    main()
