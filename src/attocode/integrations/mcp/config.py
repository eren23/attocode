"""MCP server configuration loading with hierarchy support.

Loads MCP server configs from multiple locations with a priority system:
1. ~/.attocode/mcp.json (user-level defaults)
2. ~/.gsd/mcp.json (GSD global defaults)
3. <project_dir>/.attocode/mcp.json (project-level overrides)
4. <project_dir>/.gsd/mcp.json (GSD project-level)
5. <project_dir>/.mcp.json (backward compatibility)

Later entries override earlier entries by server name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MCPServerConfig:
    """Configuration for a single MCP server.

    Supports three transport types:
    - stdio: command + args (existing)
    - sse: url + optional headers
    - http: url + optional headers (StreamableHTTP)

    When transport is 'stdio', command/args/env are used.
    When transport is 'sse' or 'http', url/headers/timeout are used.
    """

    name: str
    # Stdio transport
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # HTTP transports
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # Common
    enabled: bool = True
    lazy_load: bool = False
    timeout: float = 60.0
    poll_interval: float = 0.5

    def get_transport_config(self) -> dict[str, Any]:
        """Return a config dict for create_transport()."""
        if self.url:
            if self._is_sse:
                return {"type": "sse", "url": self.url, "headers": self.headers}
            return {"type": "http", "url": self.url, "headers": self.headers}
        return {"type": "stdio", "command": self.command, "args": self.args, "env": self.env}

    @property
    def _is_sse(self) -> bool:
        """Heuristic: SSE if url ends with /events or contains sse=true."""
        return "/events" in self.url or "sse=true" in self.url

    def __post_init__(self) -> None:
        # Support legacy format where 'command' is the URL
        if not self.command and not self.url:
            self.command = ""

        # Backward compat: if args is a string (from old JSON), convert
        if isinstance(self.args, str):
            self.args = [self.args]


def _parse_servers_dict(
    servers: dict[str, Any],
) -> list[MCPServerConfig]:
    """Parse a servers dictionary from JSON config into MCPServerConfig list."""
    configs: list[MCPServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue

        # Support both legacy (command-based) and modern (url-based) formats
        command = entry.get("command", "")
        url = entry.get("url", "")
        transport = entry.get("transport", "")

        # If url is explicitly set or transport is http/sse, use URL config
        if url or transport in ("sse", "http", "streamablehttp"):
            if not url and transport in ("sse", "http", "streamablehttp"):
                raise ValueError(
                    f"MCP server '{name}': transport '{transport}' requires a non-empty url"
                )
            configs.append(
                MCPServerConfig(
                    name=name,
                    url=url,
                    headers=entry.get("headers", {}),
                    enabled=entry.get("enabled", True),
                    lazy_load=entry.get("lazy_load", False),
                    timeout=float(entry.get("timeout", 60.0)),
                    poll_interval=float(entry.get("poll_interval", 0.5)),
                )
            )
        else:
            # Legacy stdio config
            args = entry.get("args", [])
            if isinstance(args, str):
                args = [args]
            configs.append(
                MCPServerConfig(
                    name=name,
                    command=command,
                    args=args,
                    env=entry.get("env", {}),
                    enabled=entry.get("enabled", True),
                    lazy_load=entry.get("lazy_load", False),
                )
            )
    return configs


def _load_config_file(path: Path) -> list[MCPServerConfig]:
    """Load server configs from a single JSON file.

    Expected format::

        {
          "servers": {
            "server-name": {
              "command": "npx",
              "args": ["-y", "@some/mcp-server"],
              "env": {"KEY": "value"},
              "enabled": true,
              "lazy_load": false
            }
          }
        }
    """
    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    servers = data.get("servers", {})
    if not isinstance(servers, dict):
        return []

    return _parse_servers_dict(servers)


def load_mcp_configs(project_dir: str) -> list[MCPServerConfig]:
    """Load MCP server configurations from the hierarchy.

    Priority (later overrides earlier by server name):
    1. ``~/.attocode/mcp.json`` -- user-level defaults
    2. ``~/.gsd/mcp.json`` -- GSD global defaults
    3. ``<project_dir>/.attocode/mcp.json`` -- project-level overrides
    4. ``<project_dir>/.gsd/mcp.json`` -- GSD project-level
    5. ``<project_dir>/.mcp.json`` -- backward compatibility

    Returns:
        Deduplicated list of server configs with the highest-priority
        version of each server name winning.
    """
    project = Path(project_dir)
    home = Path.home()

    sources = [
        home / ".attocode" / "mcp.json",          # user-level
        home / ".gsd" / "mcp.json",                # GSD global
        project / ".attocode" / "mcp.json",        # project-level
        project / ".gsd" / "mcp.json",              # GSD project-level
        project / ".mcp.json",                      # backward compat
    ]

    # Build merged dict keyed by server name -- last write wins
    merged: dict[str, MCPServerConfig] = {}
    for source in sources:
        for cfg in _load_config_file(source):
            merged[cfg.name] = cfg

    return list(merged.values())
