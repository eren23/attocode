"""Mode manager for agent execution modes.

Implements 4 modes that restrict tool access:
- Build (default): All tools available
- Plan: Read-only + intercepts writes → queues as proposed changes
- Review: Read-only access only
- Debug: Read-only + test execution tools
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentMode(StrEnum):
    """Agent execution mode."""

    BUILD = "build"
    PLAN = "plan"
    REVIEW = "review"
    DEBUG = "debug"


# Tool access groups
READ_TOOLS = frozenset({
    "read_file", "glob_files", "list_files", "grep", "search",
})

WRITE_TOOLS = frozenset({
    "write_file", "edit_file",
})

EXEC_TOOLS = frozenset({
    "bash",
})

TEST_TOOLS = frozenset({
    "bash",  # Allowed in debug for running tests only
})

AGENT_TOOLS = frozenset({
    "spawn_agent", "delegate",
})

# Mode → allowed tool sets
MODE_TOOL_ACCESS: dict[AgentMode, frozenset[str]] = {
    AgentMode.BUILD: READ_TOOLS | WRITE_TOOLS | EXEC_TOOLS | AGENT_TOOLS,
    AgentMode.PLAN: READ_TOOLS,
    AgentMode.REVIEW: READ_TOOLS,
    AgentMode.DEBUG: READ_TOOLS | TEST_TOOLS,
}

# System prompt supplements per mode
MODE_PROMPTS: dict[AgentMode, str] = {
    AgentMode.BUILD: "",
    AgentMode.PLAN: (
        "\n\n[MODE: PLAN]\n"
        "You are in PLAN mode. You can read files and explore the codebase, "
        "but you CANNOT write or edit files directly. Instead, describe the "
        "changes you would make as a step-by-step plan. Any write/edit "
        "operations will be intercepted and queued as proposed changes for "
        "user approval."
    ),
    AgentMode.REVIEW: (
        "\n\n[MODE: REVIEW]\n"
        "You are in REVIEW mode. You can only read files and search the codebase. "
        "You CANNOT write, edit, or execute any commands. Focus on reviewing "
        "code quality, identifying bugs, and suggesting improvements."
    ),
    AgentMode.DEBUG: (
        "\n\n[MODE: DEBUG]\n"
        "You are in DEBUG mode. You can read files and run test commands. "
        "You CANNOT write or edit files. Focus on diagnosing issues by "
        "reading code, running tests, and analyzing outputs."
    ),
}


@dataclass(slots=True)
class ProposedChange:
    """A proposed file change (queued in plan mode)."""

    tool_name: str
    path: str
    description: str
    arguments: dict[str, Any]
    approved: bool = False
    rejected: bool = False


@dataclass(slots=True)
class ModeCheckResult:
    """Result of checking a tool against the current mode."""

    allowed: bool
    reason: str = ""
    intercepted: bool = False  # True if the call was intercepted (plan mode)


@dataclass
class ModeManager:
    """Manages agent execution modes.

    Controls which tools are available based on the current mode,
    intercepts write operations in plan mode, and provides mode-aware
    system prompt supplements.
    """

    mode: AgentMode = AgentMode.BUILD
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    _mode_history: list[AgentMode] = field(default_factory=list, repr=False)

    def switch_mode(self, new_mode: AgentMode | str) -> str:
        """Switch to a new mode.

        Args:
            new_mode: The mode to switch to.

        Returns:
            Status message.
        """
        if isinstance(new_mode, str):
            try:
                new_mode = AgentMode(new_mode.lower())
            except ValueError:
                return f"Unknown mode: {new_mode}. Valid modes: {', '.join(m.value for m in AgentMode)}"

        old_mode = self.mode
        self._mode_history.append(old_mode)
        self.mode = new_mode
        return f"Switched from {old_mode.value} to {new_mode.value} mode"

    def previous_mode(self) -> str:
        """Switch back to the previous mode."""
        if not self._mode_history:
            return "No previous mode to switch to"
        prev = self._mode_history.pop()
        old = self.mode
        self.mode = prev
        return f"Switched from {old.value} back to {prev.value} mode"

    def check_tool_access(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ModeCheckResult:
        """Check if a tool is allowed in the current mode.

        Args:
            tool_name: Name of the tool.
            arguments: Tool arguments (used for plan mode interception).

        Returns:
            ModeCheckResult indicating if the tool is allowed.
        """
        # Build mode allows everything
        if self.mode == AgentMode.BUILD:
            return ModeCheckResult(allowed=True)

        # Plan mode: intercept writes instead of blocking
        if self.mode == AgentMode.PLAN and tool_name in WRITE_TOOLS:
            if arguments:
                path = arguments.get("path", arguments.get("file_path", "unknown"))
                self.proposed_changes.append(ProposedChange(
                    tool_name=tool_name,
                    path=str(path),
                    description=f"{tool_name} on {path}",
                    arguments=dict(arguments),
                ))
            return ModeCheckResult(
                allowed=False,
                reason="Write operation intercepted in plan mode. Queued as proposed change.",
                intercepted=True,
            )

        # Plan mode: block exec
        if self.mode == AgentMode.PLAN and tool_name in EXEC_TOOLS:
            return ModeCheckResult(
                allowed=False,
                reason="Execution not allowed in plan mode",
            )

        # Review mode: only reads
        if self.mode == AgentMode.REVIEW:
            if tool_name in READ_TOOLS:
                return ModeCheckResult(allowed=True)
            return ModeCheckResult(
                allowed=False,
                reason=f"Tool '{tool_name}' not allowed in review mode (read-only)",
            )

        # Debug mode: reads + controlled bash (test commands)
        if self.mode == AgentMode.DEBUG:
            if tool_name in READ_TOOLS:
                return ModeCheckResult(allowed=True)
            if tool_name == "bash" and arguments:
                cmd = arguments.get("command", "")
                if _is_test_command(cmd):
                    return ModeCheckResult(allowed=True)
                return ModeCheckResult(
                    allowed=False,
                    reason="Only test commands allowed in debug mode",
                )
            return ModeCheckResult(
                allowed=False,
                reason=f"Tool '{tool_name}' not allowed in debug mode",
            )

        # Check general tool access
        allowed_tools = MODE_TOOL_ACCESS.get(self.mode, frozenset())
        if tool_name in allowed_tools:
            return ModeCheckResult(allowed=True)

        return ModeCheckResult(
            allowed=False,
            reason=f"Tool '{tool_name}' not allowed in {self.mode.value} mode",
        )

    def get_system_prompt_supplement(self) -> str:
        """Get the mode-specific system prompt supplement."""
        return MODE_PROMPTS.get(self.mode, "")

    def approve_change(self, index: int) -> str:
        """Approve a proposed change by index."""
        if index < 0 or index >= len(self.proposed_changes):
            return f"Invalid change index: {index}"
        change = self.proposed_changes[index]
        change.approved = True
        return f"Approved: {change.description}"

    def reject_change(self, index: int) -> str:
        """Reject a proposed change by index."""
        if index < 0 or index >= len(self.proposed_changes):
            return f"Invalid change index: {index}"
        change = self.proposed_changes[index]
        change.rejected = True
        return f"Rejected: {change.description}"

    def approve_all_changes(self) -> str:
        """Approve all proposed changes."""
        count = 0
        for change in self.proposed_changes:
            if not change.approved and not change.rejected:
                change.approved = True
                count += 1
        return f"Approved {count} changes"

    def reject_all_changes(self) -> str:
        """Reject all proposed changes."""
        count = 0
        for change in self.proposed_changes:
            if not change.approved and not change.rejected:
                change.rejected = True
                count += 1
        return f"Rejected {count} changes"

    def get_pending_changes(self) -> list[ProposedChange]:
        """Get changes that are neither approved nor rejected."""
        return [
            c for c in self.proposed_changes
            if not c.approved and not c.rejected
        ]

    def get_approved_changes(self) -> list[ProposedChange]:
        """Get approved changes."""
        return [c for c in self.proposed_changes if c.approved]

    def clear_changes(self) -> None:
        """Clear all proposed changes."""
        self.proposed_changes.clear()

    def format_changes_summary(self) -> str:
        """Format a summary of all proposed changes."""
        if not self.proposed_changes:
            return "No proposed changes."

        lines = [f"Proposed changes ({len(self.proposed_changes)} total):"]
        for i, change in enumerate(self.proposed_changes):
            status = "pending"
            if change.approved:
                status = "approved"
            elif change.rejected:
                status = "rejected"
            lines.append(f"  [{i}] [{status}] {change.description}")
        return "\n".join(lines)


def _is_test_command(command: str) -> bool:
    """Check if a command is a test-related command (allowed in debug mode)."""
    test_prefixes = (
        "pytest", "python -m pytest", "python3 -m pytest",
        "npm test", "npm run test", "npx jest",
        "cargo test", "go test", "make test",
        "mypy", "ruff check", "ruff format --check",
        "tsc --noEmit", "eslint", "python -m mypy",
    )
    stripped = command.strip()
    return any(stripped.startswith(prefix) for prefix in test_prefixes)
