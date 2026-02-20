"""MCP server configuration loading with hierarchy support.

Loads MCP server configs from multiple locations with a priority system:
1. ~/.attocode/mcp.json (user-level defaults)
2. <project_dir>/.attocode/mcp.json (project-level overrides)
3. <project_dir>/.mcp.json (backward compatibility)

Later entries override earlier entries by server name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    lazy_load: bool = False


def _parse_servers_dict(
    servers: dict[str, Any],
) -> list[MCPServerConfig]:
    """Parse a servers dictionary from JSON config into MCPServerConfig list."""
    configs: list[MCPServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        configs.append(
            MCPServerConfig(
                name=name,
                command=entry.get("command", ""),
                args=entry.get("args", []),
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
    2. ``<project_dir>/.attocode/mcp.json`` -- project-level overrides
    3. ``<project_dir>/.mcp.json`` -- backward compatibility

    Returns:
        Deduplicated list of server configs with the highest-priority
        version of each server name winning.
    """
    project = Path(project_dir)
    home = Path.home()

    sources = [
        home / ".attocode" / "mcp.json",          # user-level
        project / ".attocode" / "mcp.json",        # project-level
        project / ".mcp.json",                      # backward compat
    ]

    # Build merged dict keyed by server name -- last write wins
    merged: dict[str, MCPServerConfig] = {}
    for source in sources:
        for cfg in _load_config_file(source):
            merged[cfg.name] = cfg

    return list(merged.values())
