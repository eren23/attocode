"""MCP server scaffolder — generates local MCP servers from specs.

Allows the agent to create custom MCP servers at runtime,
which are saved to `.attocode/mcp-servers/` and can be
auto-registered with the MCP client.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MCPToolSpec:
    """Specification for a tool in the MCP server."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    returns: str = "string"
    implementation: str = ""  # Python code for the handler


@dataclass(slots=True)
class MCPServerSpec:
    """Full specification for an MCP server."""
    name: str
    description: str
    tools: list[MCPToolSpec] = field(default_factory=list)
    version: str = "0.1.0"


class MCPScaffolderError(Exception):
    """Error during MCP server scaffolding."""


class MCPScaffolder:
    """Scaffolds MCP servers from specifications.

    Generates a Python MCP server using the `mcp` package,
    writes it to disk, and provides registration info.
    """

    def __init__(self, *, servers_dir: Path | None = None) -> None:
        self._servers_dir = servers_dir
        self._scaffolded: dict[str, Path] = {}

    @property
    def servers_dir(self) -> Path | None:
        return self._servers_dir

    @property
    def scaffolded_servers(self) -> dict[str, Path]:
        return dict(self._scaffolded)

    def scaffold(self, spec: MCPServerSpec) -> Path:
        """Generate an MCP server from a specification.

        Creates a directory with:
        - server.py — the MCP server implementation
        - spec.json — the original specification for reload

        Args:
            spec: Server specification.

        Returns:
            Path to the generated server directory.

        Raises:
            MCPScaffolderError: If scaffolding fails.
        """
        if not spec.name.isidentifier():
            raise MCPScaffolderError(f"Invalid server name: {spec.name!r}")
        if not spec.tools:
            raise MCPScaffolderError("Server must have at least one tool")

        if self._servers_dir is None:
            raise MCPScaffolderError("No servers directory configured")

        server_dir = self._servers_dir / spec.name
        server_dir.mkdir(parents=True, exist_ok=True)

        # Generate server.py
        server_code = self._generate_server_code(spec)
        (server_dir / "server.py").write_text(server_code, encoding="utf-8")

        # Save spec for reload
        spec_data = {
            "name": spec.name,
            "description": spec.description,
            "version": spec.version,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "returns": t.returns,
                    "implementation": t.implementation,
                }
                for t in spec.tools
            ],
        }
        (server_dir / "spec.json").write_text(
            json.dumps(spec_data, indent=2) + "\n",
            encoding="utf-8",
        )

        self._scaffolded[spec.name] = server_dir
        logger.info("Scaffolded MCP server: %s at %s", spec.name, server_dir)
        return server_dir

    def list_servers(self) -> list[dict[str, Any]]:
        """List all scaffolded servers."""
        if not self._servers_dir or not self._servers_dir.exists():
            return []

        servers: list[dict[str, Any]] = []
        for child in sorted(self._servers_dir.iterdir()):
            spec_path = child / "spec.json"
            if spec_path.exists():
                try:
                    data = json.loads(spec_path.read_text(encoding="utf-8"))
                    servers.append({
                        "name": data.get("name", child.name),
                        "description": data.get("description", ""),
                        "tools": len(data.get("tools", [])),
                        "path": str(child),
                    })
                except (json.JSONDecodeError, OSError):
                    pass
        return servers

    def get_server_command(self, name: str) -> list[str] | None:
        """Get the command to start a scaffolded server."""
        if self._servers_dir is None:
            return None
        server_dir = self._servers_dir / name
        server_py = server_dir / "server.py"
        if not server_py.exists():
            return None
        return ["python3", str(server_py)]

    def _generate_server_code(self, spec: MCPServerSpec) -> str:
        """Generate the Python MCP server code."""
        lines = [
            '"""Auto-generated MCP server: {name}."""'.format(name=spec.name),
            "",
            "from mcp.server.fastmcp import FastMCP",
            "",
            f'mcp = FastMCP("{spec.name}")',
            "",
        ]

        for tool in spec.tools:
            # Generate parameter signature
            params = []
            props = tool.parameters.get("properties", {})
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "str")
                type_map = {"string": "str", "number": "float", "integer": "int", "boolean": "bool"}
                py_type = type_map.get(ptype, "str")
                default = pinfo.get("default")
                if default is not None:
                    params.append(f"{pname}: {py_type} = {default!r}")
                else:
                    params.append(f"{pname}: {py_type} = {_default_for_type(py_type)!r}")

            param_str = ", ".join(params)

            lines.append(f'@mcp.tool(description="{tool.description}")')
            lines.append(f"def {tool.name}({param_str}) -> str:")

            if tool.implementation:
                for impl_line in tool.implementation.split("\n"):
                    lines.append(f"    {impl_line}")
            else:
                lines.append(f'    return "Tool {tool.name} called"')
            lines.append("")

        lines.extend([
            "",
            'if __name__ == "__main__":',
            "    mcp.run()",
            "",
        ])

        return "\n".join(lines)


def _default_for_type(py_type: str) -> Any:
    """Return a sensible default for a Python type string."""
    defaults = {"str": "", "int": 0, "float": 0.0, "bool": False}
    return defaults.get(py_type, "")
