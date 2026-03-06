"""Rules manager for loading .attocode/rules.md files.

Rules are markdown files containing project-specific instructions
that are injected into the system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RulesManager:
    """Loads and manages rules from .attocode/rules.md files.

    Supports a priority hierarchy:
    1. Built-in defaults (lowest)
    2. User-level (~/.attocode/rules.md)
    3. Project-level (.attocode/rules.md) (highest)
    """

    project_root: str | Path = "."
    _rules: list[str] = field(default_factory=list, repr=False)
    _loaded: bool = field(default=False, repr=False)

    def load(self) -> None:
        """Load rules from all sources."""
        self._rules.clear()
        root = Path(self.project_root)

        # User-level rules
        user_rules = Path.home() / ".attocode" / "rules.md"
        if user_rules.is_file():
            self._load_file(user_rules)

        # Project-level rules (overrides user-level)
        project_rules = root / ".attocode" / "rules.md"
        if project_rules.is_file():
            self._load_file(project_rules)

        # Legacy path support
        legacy_rules = root / ".agent" / "rules.md"
        if legacy_rules.is_file() and not project_rules.is_file():
            self._load_file(legacy_rules)

        self._loaded = True

    def _load_file(self, path: Path) -> None:
        """Load rules from a single file."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                self._rules.append(text)
        except OSError:
            pass

    @property
    def rules(self) -> list[str]:
        """Get all loaded rules."""
        if not self._loaded:
            self.load()
        return list(self._rules)

    @property
    def combined(self) -> str:
        """Get all rules combined as a single string."""
        if not self._loaded:
            self.load()
        return "\n\n---\n\n".join(self._rules)

    @property
    def has_rules(self) -> bool:
        """Check if any rules are loaded."""
        if not self._loaded:
            self.load()
        return len(self._rules) > 0
