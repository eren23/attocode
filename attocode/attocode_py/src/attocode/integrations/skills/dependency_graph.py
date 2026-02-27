"""Skill dependency resolution using topological sort.

Parses `depends_on` metadata from SKILL.md frontmatter and
resolves execution order using Kahn's algorithm.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.skills.loader import SkillDefinition


class SkillDependencyError(Exception):
    """Raised when skill dependencies cannot be resolved."""


@dataclass(slots=True)
class DependencyInfo:
    """Dependency information for a skill."""

    skill_name: str
    depends_on: list[str] = field(default_factory=list)
    version: str = ""
    compatible_versions: dict[str, str] = field(default_factory=dict)


class SkillDependencyGraph:
    """Directed acyclic graph of skill dependencies.

    Supports:
    - Topological ordering for execution
    - Cycle detection
    - Missing dependency detection
    - Version compatibility checks
    """

    def __init__(self) -> None:
        self._deps: dict[str, DependencyInfo] = {}

    def add_skill(self, skill: SkillDefinition) -> DependencyInfo:
        """Register a skill and its dependency metadata."""
        meta = skill.metadata or {}
        depends_on = meta.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [d.strip() for d in depends_on.split(",") if d.strip()]

        info = DependencyInfo(
            skill_name=skill.name,
            depends_on=depends_on,
            version=meta.get("version", ""),
            compatible_versions=meta.get("compatible_versions", {}),
        )
        self._deps[skill.name] = info
        return info

    def resolve_order(self, skill_names: list[str] | None = None) -> list[str]:
        """Resolve execution order via topological sort (Kahn's algorithm).

        Args:
            skill_names: Optional subset to resolve. If None, resolves all.

        Returns:
            List of skill names in dependency order (dependencies first).

        Raises:
            SkillDependencyError: On cycles or missing dependencies.
        """
        targets = set(skill_names) if skill_names else set(self._deps.keys())

        # Collect all skills needed (transitively)
        needed: set[str] = set()
        queue: deque[str] = deque(targets)
        while queue:
            name = queue.popleft()
            if name in needed:
                continue
            needed.add(name)
            info = self._deps.get(name)
            if info:
                for dep in info.depends_on:
                    if dep not in needed:
                        queue.append(dep)

        # Check for missing dependencies
        all_known = set(self._deps.keys())
        missing = needed - all_known
        if missing:
            raise SkillDependencyError(
                f"Missing skill dependencies: {', '.join(sorted(missing))}"
            )

        # Build adjacency list and in-degree count
        graph: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {name: 0 for name in needed}
        for name in needed:
            info = self._deps[name]
            for dep in info.depends_on:
                if dep in needed:
                    graph[dep].append(name)
                    in_degree[name] += 1

        # Kahn's algorithm
        result: list[str] = []
        zero_queue: deque[str] = deque(
            name for name, deg in in_degree.items() if deg == 0
        )

        while zero_queue:
            current = zero_queue.popleft()
            result.append(current)
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    zero_queue.append(neighbor)

        if len(result) != len(needed):
            cycle_members = needed - set(result)
            raise SkillDependencyError(
                f"Circular dependency detected among: {', '.join(sorted(cycle_members))}"
            )

        return result

    def get_dependencies(self, skill_name: str) -> list[str]:
        """Get direct dependencies for a skill."""
        info = self._deps.get(skill_name)
        return list(info.depends_on) if info else []

    def get_dependents(self, skill_name: str) -> list[str]:
        """Get skills that depend on the given skill."""
        return [
            name for name, info in self._deps.items()
            if skill_name in info.depends_on
        ]

    def check_version_compatibility(self, skill_name: str) -> list[str]:
        """Check version compatibility for a skill's dependencies.

        Returns a list of warning messages for incompatible versions.
        """
        info = self._deps.get(skill_name)
        if not info:
            return []

        warnings: list[str] = []
        for dep_name, required_version in info.compatible_versions.items():
            dep_info = self._deps.get(dep_name)
            if dep_info and dep_info.version and required_version:
                if dep_info.version != required_version:
                    warnings.append(
                        f"{skill_name} requires {dep_name} v{required_version} "
                        f"but found v{dep_info.version}"
                    )
        return warnings

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dependency graph."""
        return {
            name: {
                "depends_on": info.depends_on,
                "version": info.version,
            }
            for name, info in self._deps.items()
        }
