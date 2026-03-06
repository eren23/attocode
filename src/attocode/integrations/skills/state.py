"""Skill state persistence across turns.

Provides a simple key-value store for skills to maintain
state between execution turns within a session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SkillStateStore:
    """Persists skill state across turns.

    State is organized per-skill and per-session, stored as JSON files
    in the session directory.

    Usage::

        store = SkillStateStore(session_dir=".attocode/sessions/abc")
        store.set("my-skill", "counter", 42)
        value = store.get("my-skill", "counter")  # 42
        store.save()
    """

    def __init__(self, session_dir: str | Path | None = None) -> None:
        self._session_dir = Path(session_dir) if session_dir else None
        self._state: dict[str, dict[str, Any]] = {}
        self._dirty = False

        # Load existing state from disk
        if self._session_dir:
            self._load()

    def get(self, skill_name: str, key: str, default: Any = None) -> Any:
        """Get a state value for a skill."""
        return self._state.get(skill_name, {}).get(key, default)

    def set(self, skill_name: str, key: str, value: Any) -> None:
        """Set a state value for a skill."""
        if skill_name not in self._state:
            self._state[skill_name] = {}
        self._state[skill_name][key] = value
        self._dirty = True

    def delete(self, skill_name: str, key: str) -> bool:
        """Delete a state value. Returns True if it existed."""
        skill_state = self._state.get(skill_name, {})
        if key in skill_state:
            del skill_state[key]
            self._dirty = True
            return True
        return False

    def get_all(self, skill_name: str) -> dict[str, Any]:
        """Get all state for a skill."""
        return dict(self._state.get(skill_name, {}))

    def clear(self, skill_name: str) -> None:
        """Clear all state for a skill."""
        if skill_name in self._state:
            self._state[skill_name] = {}
            self._dirty = True

    def clear_all(self) -> None:
        """Clear all skill state."""
        self._state.clear()
        self._dirty = True

    def save(self) -> None:
        """Persist state to disk (if session_dir is set)."""
        if not self._session_dir or not self._dirty:
            return

        state_dir = self._session_dir / "skill_state"
        state_dir.mkdir(parents=True, exist_ok=True)

        for skill_name, data in self._state.items():
            if data:
                state_file = state_dir / f"{skill_name}.json"
                try:
                    state_file.write_text(
                        json.dumps(data, indent=2, default=str),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

        self._dirty = False

    def _load(self) -> None:
        """Load state from disk."""
        if not self._session_dir:
            return

        state_dir = self._session_dir / "skill_state"
        if not state_dir.is_dir():
            return

        for state_file in state_dir.glob("*.json"):
            skill_name = state_file.stem
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._state[skill_name] = data
            except Exception:
                pass
