"""Phase tracking for agent execution.

Tracks the agent's phase transitions through exploration → planning → acting → verifying.
Generates contextual nudges when the agent appears stuck.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AgentPhase(StrEnum):
    """The current phase of agent execution."""

    EXPLORATION = "exploration"
    PLANNING = "planning"
    ACTING = "acting"
    VERIFYING = "verifying"


# Tools that indicate each phase
_EXPLORATION_TOOLS = frozenset({
    "read_file", "glob", "grep", "list_files", "search_files",
})
_ACTING_TOOLS = frozenset({
    "write_file", "edit_file", "bash",
})
_VERIFYING_TOOLS = frozenset({
    "bash",  # running tests
})

# Nudge templates
NUDGES = {
    "exploration_saturation": (
        "You've read {files_read} files without making edits. "
        "Consider transitioning to the action phase. "
        "If you need more information, ask for clarification."
    ),
    "acting_without_plan": (
        "You're making edits without a clear plan. "
        "Consider reviewing your approach before continuing."
    ),
    "stuck_in_loop": (
        "You appear to be repeating the same actions. "
        "Try a different approach or ask for help."
    ),
}


@dataclass(slots=True)
class PhaseTransition:
    """Record of a phase transition."""

    from_phase: AgentPhase
    to_phase: AgentPhase
    trigger: str
    iteration: int


@dataclass
class PhaseTracker:
    """Tracks agent execution phases and generates nudges.

    Monitors tool usage patterns to determine what phase the agent
    is in, and generates contextual nudges when it appears stuck.
    """

    current_phase: AgentPhase = AgentPhase.EXPLORATION
    files_read: int = 0
    files_edited: int = 0
    edits_since_last_verify: int = 0
    _transitions: list[PhaseTransition] = field(default_factory=list, repr=False)
    _iteration: int = 0
    exploration_nudge_threshold: int = 10
    verify_nudge_threshold: int = 5

    def record_tool_use(self, tool_name: str, iteration: int) -> str | None:
        """Record a tool use and return a nudge message if warranted.

        Args:
            tool_name: Name of the tool that was used.
            iteration: Current iteration number.

        Returns:
            A nudge message string, or None if no nudge needed.
        """
        self._iteration = iteration
        old_phase = self.current_phase

        # Update counters
        if tool_name in _EXPLORATION_TOOLS:
            if tool_name == "read_file":
                self.files_read += 1
        elif tool_name in _ACTING_TOOLS and tool_name != "bash":
            self.files_edited += 1
            self.edits_since_last_verify += 1

        # Detect phase transitions
        new_phase = self._detect_phase(tool_name)
        if new_phase != old_phase:
            self._transitions.append(PhaseTransition(
                from_phase=old_phase,
                to_phase=new_phase,
                trigger=tool_name,
                iteration=iteration,
            ))
            self.current_phase = new_phase

        # Generate nudges
        return self._check_nudges()

    def _detect_phase(self, tool_name: str) -> AgentPhase:
        """Detect the current phase based on tool usage."""
        if tool_name in _ACTING_TOOLS and tool_name != "bash":
            return AgentPhase.ACTING
        if tool_name == "bash" and self.files_edited > 0:
            # Bash after edits = probably running tests
            return AgentPhase.VERIFYING
        if tool_name in _EXPLORATION_TOOLS:
            if self.files_edited == 0:
                return AgentPhase.EXPLORATION
        return self.current_phase

    def _check_nudges(self) -> str | None:
        """Check if any nudge should be generated."""
        # Exploration saturation
        if (
            self.current_phase == AgentPhase.EXPLORATION
            and self.files_read >= self.exploration_nudge_threshold
            and self.files_edited == 0
        ):
            return NUDGES["exploration_saturation"].format(
                files_read=self.files_read,
            )

        return None

    def reset(self) -> None:
        """Reset all tracking state."""
        self.current_phase = AgentPhase.EXPLORATION
        self.files_read = 0
        self.files_edited = 0
        self.edits_since_last_verify = 0
        self._transitions.clear()
        self._iteration = 0

    @property
    def transitions(self) -> list[PhaseTransition]:
        return list(self._transitions)

    @property
    def summary(self) -> str:
        """A brief summary of current state."""
        return (
            f"Phase: {self.current_phase.value} | "
            f"Files read: {self.files_read} | "
            f"Files edited: {self.files_edited}"
        )
