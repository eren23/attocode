"""Reversible client configuration and end-to-end installation diagnostics."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import tomlkit

from attocode_intel.catalog import INSTRUCTIONS

NAME = "attocode-code-intel"
REMOTE_NAME = NAME + "-remote"
START = "<!-- attocode-code-intel:start -->"
END = "<!-- attocode-code-intel:end -->"


def client_paths(client: str, project: Path, global_scope: bool):
    home = Path.home()
    if client == "codex":
        base = home / ".codex" if global_scope else project / ".codex"
        return (
            base / "config.toml",
            (base / "AGENTS.md" if global_scope else project / "AGENTS.md"),
            "mcp_servers",
        )
    if client == "claude":
        return (
            (home / ".claude.json" if global_scope else project / ".mcp.json"),
            (home / ".claude/CLAUDE.md" if global_scope else project / "CLAUDE.md"),
            "mcpServers",
        )
    if client == "cursor":
        return (
            (home if global_scope else project) / ".cursor/mcp.json",
            project / ".cursor/rules/attocode-code-intel.mdc",
            "mcpServers",
        )
    raise ValueError(f"Unsupported client: {client}")


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".intel-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _instruction_text(path: Path, client: str, remove=False):
    text = path.read_text() if path.exists() else ""
    if (START in text) != (END in text):
        raise ValueError(f"Incomplete managed instruction block in {path}")
    block = f"{START}\n{INSTRUCTIONS}\n{END}"
    if START in text:
        first = text.index(START)
        last = text.index(END, first) + len(END)
        text = text[:first] + ("" if remove else block) + text[last:]
    elif not remove:
        if not text and client == "cursor":
            text = "---\nalwaysApply: true\n---\n"
        text = text.rstrip() + "\n\n" + block + "\n"
    return text


def configure_client(
    client,
    project=".",
    *,
    global_scope=False,
    profile="daily",
    dry_run=False,
    remove=False,
    server="",
    token_env="ATTOCODE_API_KEY",
    repo="",
):
    if repo and not server and not remove:
        raise ValueError("Remote installation requires --server; use --remote only with doctor or --remove")
    root = Path(project).resolve()
    config, guidance, key = client_paths(client, root, global_scope)
    entry_name = REMOTE_NAME if server or repo else NAME
    state_path = config.parent / ".attocode-intelligence-install.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    is_toml = config.suffix == ".toml"
    if config.exists():
        raw = config.read_text()
        document = tomlkit.parse(raw) if is_toml else json.loads(raw)
        if not isinstance(document, dict) and not is_toml:
            raise ValueError(f"Expected an object in {config}")
    else:
        document = tomlkit.document() if is_toml else {}
    servers = document.setdefault(key, {})
    if remove:
        saved = state.get(entry_name)
        if saved and servers.get(entry_name) != saved["installed"]:
            raise ValueError(
                f"{entry_name} was edited after installation; preserve those edits before removing it"
            )
        if saved and saved["previous"] is not None:
            servers[entry_name] = saved["previous"]
        else:
            servers.pop(entry_name, None)
        state.pop(entry_name, None)
    elif server:
        from urllib.parse import urlsplit

        url = urlsplit(server)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
            raise ValueError("Server must be an HTTP(S) URL without embedded credentials")
        endpoint = server.rstrip("/")
        entry = {"url": endpoint + ("/" if endpoint.endswith("/mcp") else "/mcp/")}
        if client == "claude":
            entry["type"] = "http"
        if client == "codex":
            entry["bearer_token_env_var"] = token_env
        else:
            env_ref = "${" + token_env + "}" if client == "claude" else "${env:" + token_env + "}"
            entry["headers"] = {"Authorization": "Bearer " + env_ref}
        if repo:
            entry.setdefault("http_headers" if client == "codex" else "headers", {})[
                "X-Attocode-Workspace"
            ] = repo
        entry.setdefault("http_headers" if client == "codex" else "headers", {})[
            "X-Attocode-Profile"
        ] = profile
        previous = state.get(entry_name, {}).get("previous", servers.get(entry_name))
        state[entry_name] = {"previous": previous, "installed": entry}
        servers[entry_name] = entry
    else:
        executable = Path(sys.executable).parent / NAME
        command = str(executable) if executable.is_file() else None
        entry = {
            "command": command or sys.executable,
            "args": ([] if command else ["-m", "attocode_intel.entrypoint"])
            + ["--profile", profile],
        }
        if not global_scope:
            entry["args"] += ["--project", str(root)]
        if client == "cursor":
            entry["type"] = "stdio"
        previous = state.get(entry_name, {}).get("previous", servers.get(entry_name))
        state[entry_name] = {"previous": previous, "installed": entry}
        servers[entry_name] = entry
    output = tomlkit.dumps(document) if is_toml else json.dumps(document, indent=2) + "\n"
    instruction = _instruction_text(
        guidance, client, remove=remove and not any(name in servers for name in (NAME, REMOTE_NAME))
    )
    # Prepare everything before writing either file; previews contain no credential values.
    if dry_run:
        return {
            "config": str(config),
            "entry": entry_name,
            "configuration": servers.get(entry_name),
            "guidance": str(guidance),
            "instructions": instruction,
        }
    atomic_write(config, output)
    if not remove or guidance.exists():
        atomic_write(guidance, instruction)
    atomic_write(state_path, json.dumps(state, indent=2) + "\n")
    return {"client": client, "config": str(config), "guidance": str(guidance), "removed": remove}


async def diagnose(client, project=".", *, global_scope=False, remote=False):
    import httpx
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    root = Path(project).resolve()
    config, _, key = client_paths(client, root, global_scope)
    text = config.read_text()
    doc = tomlkit.parse(text) if config.suffix == ".toml" else json.loads(text)
    name = REMOTE_NAME if remote else NAME
    entry = doc.get(key, {}).get(name)
    if not entry:
        raise ValueError(f"No {name} entry in {config}")

    async def probe(streams):
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            catalog = await session.list_tools()
            result = await session.call_tool(
                "capabilities", {"workspace": str(root)} if "url" not in entry else {}
            )
            if result.isError:
                raise RuntimeError(result.content)
            metadata = (result.structuredContent or {}).get("metadata", {})
            if "url" not in entry and metadata.get("workspace") != str(root):
                raise RuntimeError("Server selected a different workspace")
            query = await session.call_tool(
                "project_summary", {"workspace": metadata["workspace"], "max_tokens": 128}
            )
            if query.isError:
                raise RuntimeError("Bounded project query failed")
            return {
                "client": client,
                "tools": len(catalog.tools),
                "metadata": metadata,
                "status": "ok",
                "languages": (result.structuredContent or {}).get("capabilities", {}).get("languages", {}),
                "precision_hint": "Optional installed language servers improve reference lookup. Restart the agent after setup; ATTOCODE_INTEL_PRECISION=off disables enrichment.",
            }

    async with asyncio.timeout(30):
        if "url" in entry:
            headers = dict(entry.get("http_headers", entry.get("headers", {})))
            for name, value in headers.items():
                for env_name, env_value in os.environ.items():
                    value = value.replace("${env:" + env_name + "}", env_value).replace(
                        "${" + env_name + "}", env_value
                    )
                headers[name] = value
            if entry.get("bearer_token_env_var"):
                token = os.environ.get(entry["bearer_token_env_var"], "")
                headers["Authorization"] = "Bearer " + token
            async with (
                httpx.AsyncClient(headers=headers) as http,
                streamable_http_client(entry["url"], http_client=http) as streams,
            ):
                return await probe(streams)
        else:
            params = StdioServerParameters(
                command=entry["command"],
                args=list(entry.get("args", [])),
                env={**os.environ, **dict(entry.get("env", {}))},
                cwd=str(root),
            )
            async with stdio_client(params) as streams:
                return await probe(streams)
