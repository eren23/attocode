"""Skill execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from attocode.integrations.skills.loader import SkillDefinition, SkillLoader


@dataclass
class SkillExecutionResult:
    """Result of executing a skill."""

    success: bool
    output: str = ""
    error: str | None = None
    skill_name: str = ""


class SkillExecutor:
    """Executes loaded skills by injecting their content as context."""

    def __init__(self, loader: SkillLoader) -> None:
        self._loader = loader

    def execute(self, skill_name: str, args: str = "") -> SkillExecutionResult:
        """Execute a skill by name.

        Returns the skill content for injection into the agent context.
        Skills are essentially prompt templates that get injected.
        """
        skill = self._loader.get(skill_name)
        if skill is None:
            return SkillExecutionResult(
                success=False,
                error=f"Skill '{skill_name}' not found",
                skill_name=skill_name,
            )

        if not skill.has_content:
            return SkillExecutionResult(
                success=False,
                error=f"Skill '{skill_name}' has no content",
                skill_name=skill_name,
            )

        # Inject args into content if present
        content = skill.content
        if args:
            content = f"{content}\n\nArguments: {args}"

        return SkillExecutionResult(
            success=True,
            output=content,
            skill_name=skill_name,
        )

    def list_available(self) -> list[dict[str, str]]:
        """List available skills with their descriptions."""
        return [
            {"name": s.name, "description": s.description, "source": s.source}
            for s in self._loader.list_skills()
        ]
