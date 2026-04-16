"""Watch mode — monitors files for inline AI trigger comments.

Watches source files for `# AI:` or `// AI:` comments,
processes them with the agent, removes the trigger comment,
and optionally auto-commits the result.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Trigger patterns for different comment styles
TRIGGER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"#\s*AI:\s*(.+)$", re.MULTILINE),
    re.compile(r"//\s*AI:\s*(.+)$", re.MULTILINE),
    re.compile(r"/\*\s*AI:\s*(.+?)\s*\*/", re.MULTILINE),
]


@dataclass(slots=True)
class TriggerMatch:
    """A matched trigger in a source file."""

    file_path: str
    line_number: int
    trigger_text: str
    full_match: str
    comment_style: str  # "#", "//", "/*"


@dataclass(slots=True)
class WatchConfig:
    """Configuration for watch mode."""

    watch_dirs: list[str] = field(default_factory=lambda: ["."])
    extensions: list[str] = field(
        default_factory=lambda: [".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".tsx", ".jsx"]
    )
    poll_interval: float = 2.0
    auto_commit: bool = False
    ignore_patterns: list[str] = field(
        default_factory=lambda: [
            "__pycache__", "node_modules", ".git", ".venv",
            "venv", ".attocode", "dist", "build",
        ]
    )


class FileWatcher:
    """Watches source files for inline AI trigger comments.

    Scans files for patterns like:
    - `# AI: refactor this function`
    - `// AI: add error handling`
    - `/* AI: write tests */`

    Uses polling (like ThemeWatcher) to detect changes.
    """

    def __init__(self, config: WatchConfig | None = None) -> None:
        self._config = config or WatchConfig()
        self._file_mtimes: dict[str, float] = {}
        self._processed_triggers: set[str] = set()

    @property
    def config(self) -> WatchConfig:
        return self._config

    def scan_file(self, file_path: Path) -> list[TriggerMatch]:
        """Scan a single file for AI trigger comments."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        matches: list[TriggerMatch] = []
        lines = content.split("\n")

        for i, line in enumerate(lines, start=1):
            for pattern in TRIGGER_PATTERNS:
                m = pattern.search(line)
                if m:
                    trigger_text = m.group(1).strip()
                    if not trigger_text:
                        continue

                    # Determine comment style
                    if line.strip().startswith("#"):
                        style = "#"
                    elif line.strip().startswith("//"):
                        style = "//"
                    else:
                        style = "/*"

                    matches.append(TriggerMatch(
                        file_path=str(file_path),
                        line_number=i,
                        trigger_text=trigger_text,
                        full_match=m.group(0),
                        comment_style=style,
                    ))
                    break  # Only first pattern match per line

        return matches

    def scan_directory(self, root: Path) -> list[TriggerMatch]:
        """Scan a directory tree for AI trigger comments."""
        all_matches: list[TriggerMatch] = []

        for ext in self._config.extensions:
            for file_path in root.rglob(f"*{ext}"):
                if self._should_ignore(file_path):
                    continue
                matches = self.scan_file(file_path)
                # Filter out already-processed triggers
                for m in matches:
                    key = f"{m.file_path}:{m.line_number}:{m.trigger_text}"
                    if key not in self._processed_triggers:
                        all_matches.append(m)

        return all_matches

    def scan_all(self) -> list[TriggerMatch]:
        """Scan all configured watch directories."""
        all_matches: list[TriggerMatch] = []
        for dir_path in self._config.watch_dirs:
            root = Path(dir_path).resolve()
            if root.exists():
                all_matches.extend(self.scan_directory(root))
        return all_matches

    def mark_processed(self, trigger: TriggerMatch) -> None:
        """Mark a trigger as processed so it won't be picked up again."""
        key = f"{trigger.file_path}:{trigger.line_number}:{trigger.trigger_text}"
        self._processed_triggers.add(key)

    def remove_trigger(self, trigger: TriggerMatch) -> bool:
        """Remove a trigger comment from its source file.

        Returns True if successfully removed.
        """
        try:
            path = Path(trigger.file_path)
            content = path.read_text(encoding="utf-8")
            lines = content.split("\n")

            if trigger.line_number <= len(lines):
                line = lines[trigger.line_number - 1]
                # Remove the trigger comment
                new_line = line.replace(trigger.full_match, "").rstrip()
                if not new_line.strip():
                    # If the line is now empty, remove it entirely
                    lines.pop(trigger.line_number - 1)
                else:
                    lines[trigger.line_number - 1] = new_line

                path.write_text("\n".join(lines), encoding="utf-8")
                self.mark_processed(trigger)
                return True
        except OSError:
            pass
        return False

    def check_for_changes(self) -> list[str]:
        """Check for file modifications since last check.

        Returns list of modified file paths.
        """
        changed: list[str] = []

        for dir_path in self._config.watch_dirs:
            root = Path(dir_path).resolve()
            if not root.exists():
                continue

            for ext in self._config.extensions:
                for file_path in root.rglob(f"*{ext}"):
                    if self._should_ignore(file_path):
                        continue
                    key = str(file_path)
                    try:
                        mtime = file_path.stat().st_mtime
                    except OSError:
                        continue

                    if key in self._file_mtimes:
                        if mtime > self._file_mtimes[key]:
                            changed.append(key)
                    self._file_mtimes[key] = mtime

        return changed

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path should be ignored."""
        parts = path.parts
        return any(
            ignore in parts
            for ignore in self._config.ignore_patterns
        )
