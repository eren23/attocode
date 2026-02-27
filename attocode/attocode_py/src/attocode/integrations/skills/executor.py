"""Skill execution engine with lifecycle support.

Supports two skill lifecycle modes:
- simple: One-shot prompt injection (default, backward compatible)
- long_running: Init → execute (multi-turn) → cleanup

Long-running skills maintain state across turns via SkillStateStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from attocode.integrations.skills.loader import SkillDefinition, SkillLoader

if TYPE_CHECKING:
    from attocode.integrations.skills.dependency_graph import SkillDependencyGraph


@dataclass
class SkillExecutionResult:
    """Result of executing a skill."""

    success: bool
    output: str = ""
    error: str | None = None
    skill_name: str = ""
    phase: str = "execute"  # init | execute | cleanup
    state_updates: dict[str, Any] = field(default_factory=dict)


class SkillExecutor:
    """Executes loaded skills with optional lifecycle management.

    For simple skills (default), behavior is unchanged — content is
    injected as context. For long_running skills, the executor manages
    init/execute/cleanup phases and state persistence.
    """

    def __init__(
        self,
        loader: SkillLoader,
        state_store: Any = None,
        dependency_graph: SkillDependencyGraph | None = None,
    ) -> None:
        self._loader = loader
        self._state_store = state_store
        self._dependency_graph = dependency_graph
        self._active_skills: dict[str, str] = {}  # skill_name → phase

    def execute(
        self,
        skill_name: str,
        args: str = "",
        *,
        phase: str | None = None,
    ) -> SkillExecutionResult:
        """Execute a skill by name.

        Args:
            skill_name: Name of the skill to execute.
            args: Arguments to pass to the skill.
            phase: For long_running skills, specify "init", "execute", or "cleanup".
                   Defaults to auto-detect based on current state.

        Returns:
            SkillExecutionResult with the skill content for context injection.
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

        lifecycle = skill.metadata.get("lifecycle", "simple")

        if lifecycle == "long_running":
            return self._execute_long_running(skill, args, phase)

        # Simple skill: one-shot content injection
        content = skill.content
        if args:
            content = f"{content}\n\nArguments: {args}"

        return SkillExecutionResult(
            success=True,
            output=content,
            skill_name=skill_name,
        )

    def _execute_long_running(
        self,
        skill: SkillDefinition,
        args: str,
        phase: str | None,
    ) -> SkillExecutionResult:
        """Execute a long-running skill with lifecycle management."""
        name = skill.name
        current_phase = self._active_skills.get(name)

        # Auto-detect phase
        if phase is None:
            if current_phase is None:
                phase = "init"
            elif current_phase == "init":
                phase = "execute"
            else:
                phase = "execute"

        # Load skill state
        state: dict[str, Any] = {}
        if self._state_store:
            state = self._state_store.get_all(name)

        content = skill.content
        if args:
            content = f"{content}\n\nArguments: {args}"

        # Phase-specific behavior
        if phase == "init":
            content = f"[SKILL INIT: {name}]\n{content}\n\n[State: new session]"
            self._active_skills[name] = "init"
        elif phase == "execute":
            state_summary = ", ".join(f"{k}={v}" for k, v in state.items()) if state else "empty"
            content = f"[SKILL CONTINUE: {name}]\n{content}\n\n[State: {state_summary}]"
            self._active_skills[name] = "execute"
        elif phase == "cleanup":
            content = f"[SKILL CLEANUP: {name}]\nFinalize and clean up skill state."
            self._active_skills.pop(name, None)
            if self._state_store:
                self._state_store.clear(name)
                self._state_store.save()

        return SkillExecutionResult(
            success=True,
            output=content,
            skill_name=name,
            phase=phase,
            state_updates=state,
        )

    def update_skill_state(self, skill_name: str, key: str, value: Any) -> None:
        """Update state for a long-running skill."""
        if self._state_store:
            self._state_store.set(skill_name, key, value)
            self._state_store.save()

    def get_active_skills(self) -> dict[str, str]:
        """Return currently active long-running skills and their phases."""
        return dict(self._active_skills)

    def cleanup_all(self) -> None:
        """Clean up all active long-running skills."""
        for name in list(self._active_skills):
            skill = self._loader.get(name)
            if skill:
                self._execute_long_running(skill, "", "cleanup")

    def execute_ordered(
        self,
        skill_names: list[str],
        args: str = "",
    ) -> list[SkillExecutionResult]:
        """Execute multiple skills in dependency order.

        Uses the dependency graph to resolve execution order.
        Falls back to input order if no graph is available.
        """
        if self._dependency_graph and len(skill_names) > 1:
            try:
                ordered = self._dependency_graph.resolve_order(skill_names)
            except Exception:
                ordered = skill_names
        else:
            ordered = skill_names
        return [self.execute(name, args) for name in ordered]

    def list_available(self) -> list[dict[str, str]]:
        """List available skills with their descriptions."""
        result = []
        for s in self._loader.list_skills():
            info: dict[str, str] = {
                "name": s.name,
                "description": s.description,
                "source": s.source,
            }
            lifecycle = s.metadata.get("lifecycle", "simple")
            if lifecycle != "simple":
                info["lifecycle"] = lifecycle
            version = s.metadata.get("version", "")
            if version:
                info["version"] = version
            deps = s.metadata.get("depends_on", [])
            if deps:
                info["depends_on"] = ", ".join(deps)
            result.append(info)
        return result
