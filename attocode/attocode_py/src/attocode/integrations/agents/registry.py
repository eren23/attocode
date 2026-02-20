"""Agent registry for loading and managing agent definitions.

Loads agent definitions from .attocode/agents/ directories
with support for user-level and project-level agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AgentDefinition:
    """Definition of a named agent."""

    name: str
    description: str = ""
    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    max_iterations: int = 50
    temperature: float | None = None
    source: str = "builtin"  # builtin, user, project
    metadata: dict[str, Any] = field(default_factory=dict)


# Built-in agents
BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    "coder": AgentDefinition(
        name="coder",
        description="General-purpose coding agent",
        tools=["read_file", "write_file", "edit_file", "bash", "glob", "grep"],
    ),
    "researcher": AgentDefinition(
        name="researcher",
        description="Read-only research agent for codebase exploration",
        tools=["read_file", "glob", "grep", "list_files"],
        max_iterations=30,
    ),
    "reviewer": AgentDefinition(
        name="reviewer",
        description="Code review agent",
        tools=["read_file", "glob", "grep"],
        max_iterations=20,
    ),
}


class AgentRegistry:
    """Manages agent definitions from multiple sources.

    Priority: builtin < user (~/.attocode/agents/) < project (.attocode/agents/)
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._loaded = False

    def load(self) -> None:
        """Load agent definitions from all sources."""
        # Start with builtins
        self._agents = dict(BUILTIN_AGENTS)

        # User-level agents (~/.attocode/agents/)
        user_dir = Path.home() / ".attocode" / "agents"
        self._load_from_directory(user_dir, source="user")

        # Project-level agents (.attocode/agents/)
        project_dir = self._project_root / ".attocode" / "agents"
        self._load_from_directory(project_dir, source="project")

        # Legacy path (.agent/agents/)
        legacy_dir = self._project_root / ".agent" / "agents"
        if legacy_dir.is_dir() and not project_dir.is_dir():
            self._load_from_directory(legacy_dir, source="project")

        self._loaded = True

    def get(self, name: str) -> AgentDefinition | None:
        """Get an agent definition by name."""
        if not self._loaded:
            self.load()
        return self._agents.get(name)

    def list_agents(self) -> list[AgentDefinition]:
        """List all registered agents."""
        if not self._loaded:
            self.load()
        return list(self._agents.values())

    def register(self, agent: AgentDefinition) -> None:
        """Register an agent definition programmatically."""
        self._agents[agent.name] = agent

    def has(self, name: str) -> bool:
        """Check if an agent is registered."""
        if not self._loaded:
            self.load()
        return name in self._agents

    def _load_from_directory(self, directory: Path, source: str) -> None:
        """Load agent definitions from a directory."""
        if not directory.is_dir():
            return

        for agent_dir in directory.iterdir():
            if not agent_dir.is_dir():
                continue

            # Look for AGENT.yaml or AGENT.yml
            for name in ("AGENT.yaml", "AGENT.yml", "agent.yaml", "agent.yml"):
                yaml_path = agent_dir / name
                if yaml_path.is_file():
                    self._load_agent_file(yaml_path, source)
                    break

    def _load_agent_file(self, path: Path, source: str) -> None:
        """Load a single agent definition from a YAML file."""
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}

            name = data.get("name", path.parent.name)
            agent = AgentDefinition(
                name=name,
                description=data.get("description", ""),
                model=data.get("model"),
                system_prompt=data.get("system_prompt") or data.get("systemPrompt"),
                tools=data.get("tools"),
                max_iterations=data.get("max_iterations", 50),
                temperature=data.get("temperature"),
                source=source,
                metadata=data.get("metadata", {}),
            )
            self._agents[name] = agent
        except Exception:
            pass  # Skip invalid agent files
