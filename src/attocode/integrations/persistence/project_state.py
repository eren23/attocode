"""File-driven project state management.

Manages persistent project state in `.attocode/project/` that
survives restarts, compaction, and context refreshes.

Files:
- STATE.md — Cross-session decisions, architecture choices, blockers
- PLAN.md — Current task plan (Milestone → Slice → Task)
- CONVENTIONS.md — Auto-detected or manual code conventions
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProjectState:
    """Loaded project state."""
    state_content: str = ""
    plan_content: str = ""
    conventions_content: str = ""
    loaded_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not (self.state_content or self.plan_content or self.conventions_content)

    def as_context_block(self) -> str:
        """Format project state for injection into system prompt."""
        parts: list[str] = []
        if self.state_content:
            parts.append(f"## Project State\n{self.state_content}")
        if self.plan_content:
            parts.append(f"## Current Plan\n{self.plan_content}")
        if self.conventions_content:
            parts.append(f"## Code Conventions\n{self.conventions_content}")
        return "\n\n".join(parts)


class ProjectStateManager:
    """Manages file-driven project state.

    Reads and writes to `.attocode/project/` directory,
    providing persistent state that survives agent restarts
    and context compaction.
    """

    STATE_FILE = "STATE.md"
    PLAN_FILE = "PLAN.md"
    CONVENTIONS_FILE = "CONVENTIONS.md"

    def __init__(self, project_root: Path) -> None:
        self._project_dir = project_root / ".attocode" / "project"
        self._state: ProjectState | None = None

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def state(self) -> ProjectState | None:
        return self._state

    def load(self) -> ProjectState:
        """Load all project state files.

        Returns ProjectState even if directory doesn't exist
        (with empty content).
        """
        state = ProjectState(loaded_at=time.monotonic())

        if not self._project_dir.exists():
            self._state = state
            return state

        state.state_content = self._read_file(self.STATE_FILE)
        state.plan_content = self._read_file(self.PLAN_FILE)
        state.conventions_content = self._read_file(self.CONVENTIONS_FILE)

        self._state = state
        logger.debug(
            "Loaded project state: state=%d chars, plan=%d chars, conventions=%d chars",
            len(state.state_content),
            len(state.plan_content),
            len(state.conventions_content),
        )
        return state

    def update_state(self, entry: str) -> None:
        """Append an entry to STATE.md.

        Creates the file and directory if they don't exist.
        Each entry is timestamped and appended.
        """
        self._ensure_dir()
        path = self._project_dir / self.STATE_FILE

        timestamp = time.strftime("%Y-%m-%d %H:%M")
        formatted = f"\n### [{timestamp}]\n{entry}\n"

        existing = self._read_file(self.STATE_FILE)
        if not existing:
            content = f"# Project State\n\nDecisions, architecture choices, and blockers.\n{formatted}"
        else:
            content = existing + formatted

        path.write_text(content, encoding="utf-8")
        if self._state:
            self._state.state_content = content

    def update_plan(self, plan_content: str) -> None:
        """Write the current plan to PLAN.md.

        Overwrites the entire file — plans are replaced, not appended.
        """
        self._ensure_dir()
        path = self._project_dir / self.PLAN_FILE
        path.write_text(plan_content, encoding="utf-8")
        if self._state:
            self._state.plan_content = plan_content

    def update_conventions(self, conventions: str) -> None:
        """Write conventions to CONVENTIONS.md."""
        self._ensure_dir()
        path = self._project_dir / self.CONVENTIONS_FILE
        path.write_text(conventions, encoding="utf-8")
        if self._state:
            self._state.conventions_content = conventions

    def clear_plan(self) -> None:
        """Remove the plan file."""
        path = self._project_dir / self.PLAN_FILE
        if path.exists():
            path.unlink()
        if self._state:
            self._state.plan_content = ""

    def get_state_entries(self) -> list[dict[str, str]]:
        """Parse STATE.md into structured entries.

        Returns list of {timestamp, content} dicts.
        """
        content = self._read_file(self.STATE_FILE)
        if not content:
            return []

        entries: list[dict[str, str]] = []
        current_ts = ""
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("### [") and line.endswith("]"):
                if current_ts and current_lines:
                    entries.append({
                        "timestamp": current_ts,
                        "content": "\n".join(current_lines).strip(),
                    })
                current_ts = line[5:-1]
                current_lines = []
            elif current_ts:
                current_lines.append(line)

        if current_ts and current_lines:
            entries.append({
                "timestamp": current_ts,
                "content": "\n".join(current_lines).strip(),
            })

        return entries

    def exists(self) -> bool:
        """Whether the project state directory exists."""
        return self._project_dir.exists()

    def _ensure_dir(self) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)

    def _read_file(self, filename: str) -> str:
        path = self._project_dir / filename
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
