"""Hierarchical configuration loading.

Loads configuration from multiple levels with priority:
  built-in defaults < ~/.attocode/ (user) < .attocode/ (project)

Supports config.json, rules.md, and skill/agent directories at
each level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Default configuration values
DEFAULTS: dict[str, Any] = {
    "model": "claude-sonnet-4-20250514",
    "maxTokens": 200_000,
    "temperature": 0.0,
    "sandbox": {"mode": "auto"},
    "budget": {"preset": "standard"},
    "tui": {"theme": "default"},
    "compaction": {"warningThreshold": 0.7, "compactionThreshold": 0.8},
}


@dataclass(slots=True)
class ConfigLayer:
    """A single layer in the config hierarchy."""

    label: str  # e.g. "built-in", "user", "project"
    path: Path | None
    config: dict[str, Any] = field(default_factory=dict)
    rules: str = ""

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.exists()


@dataclass(slots=True)
class ResolvedConfig:
    """Fully resolved configuration from all layers."""

    config: dict[str, Any]
    rules: list[str]  # Merged rules from all layers
    layers_loaded: list[str]
    project_root: Path | None = None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay into base (overlay wins on conflicts)."""
    result = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning {} on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _load_text(path: Path) -> str:
    """Load a text file, returning '' on any error."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class HierarchicalConfigManager:
    """Loads and merges configuration from multiple directory levels.

    Priority (lowest to highest):
      1. Built-in defaults
      2. User-level: ``~/.attocode/``
      3. Project-level: ``.attocode/`` in the project root

    Args:
        project_root: Path to the project root (contains ``.attocode/``).
        user_dir: Override for the user config directory.
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        user_dir: Path | None = None,
    ) -> None:
        self._project_root = project_root
        self._user_dir = user_dir or Path.home() / ".attocode"
        self._project_dir = (
            project_root / ".attocode" if project_root else None
        )
        self._layers: list[ConfigLayer] = []
        self._resolved: ResolvedConfig | None = None

    @property
    def resolved(self) -> ResolvedConfig:
        """Get the resolved config, loading if needed."""
        if self._resolved is None:
            self._resolved = self.load()
        return self._resolved

    def load(self) -> ResolvedConfig:
        """Load and merge all configuration layers.

        Returns:
            A :class:`ResolvedConfig` with the merged result.
        """
        self._layers.clear()

        # Layer 0: built-in defaults
        builtin = ConfigLayer(label="built-in", path=None, config=dict(DEFAULTS))
        self._layers.append(builtin)

        # Layer 1: user-level (~/.attocode/)
        user_layer = self._load_layer("user", self._user_dir)
        self._layers.append(user_layer)

        # Layer 2: project-level (.attocode/)
        if self._project_dir:
            project_layer = self._load_layer("project", self._project_dir)
            self._layers.append(project_layer)

        # Merge configs
        merged: dict[str, Any] = {}
        rules: list[str] = []
        layers_loaded: list[str] = []

        for layer in self._layers:
            merged = _deep_merge(merged, layer.config)
            if layer.rules:
                rules.append(layer.rules)
            layers_loaded.append(layer.label)

        self._resolved = ResolvedConfig(
            config=merged,
            rules=rules,
            layers_loaded=layers_loaded,
            project_root=self._project_root,
        )
        return self._resolved

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by dotted key path.

        Supports dotted paths like ``"sandbox.mode"`` which resolves
        to ``config["sandbox"]["mode"]``.
        """
        config = self.resolved.config
        parts = key.split(".")
        current: Any = config
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return default
            else:
                return default
        return current

    def get_rules(self) -> str:
        """Get all rules merged from all layers."""
        return "\n\n---\n\n".join(self.resolved.rules)

    def list_skills_dirs(self) -> list[Path]:
        """List skill directories from all layers."""
        dirs: list[Path] = []
        if self._user_dir:
            skills_dir = self._user_dir / "skills"
            if skills_dir.is_dir():
                dirs.append(skills_dir)
        if self._project_dir:
            skills_dir = self._project_dir / "skills"
            if skills_dir.is_dir():
                dirs.append(skills_dir)
        return dirs

    def list_agents_dirs(self) -> list[Path]:
        """List agent directories from all layers."""
        dirs: list[Path] = []
        if self._user_dir:
            agents_dir = self._user_dir / "agents"
            if agents_dir.is_dir():
                dirs.append(agents_dir)
        if self._project_dir:
            agents_dir = self._project_dir / "agents"
            if agents_dir.is_dir():
                dirs.append(agents_dir)
        return dirs

    def reload(self) -> ResolvedConfig:
        """Force reload of all layers."""
        self._resolved = None
        return self.load()

    def _load_layer(self, label: str, dir_path: Path) -> ConfigLayer:
        """Load a single config layer from a directory."""
        layer = ConfigLayer(label=label, path=dir_path)
        if not dir_path.is_dir():
            return layer

        # config.json
        config_file = dir_path / "config.json"
        if config_file.is_file():
            layer.config = _load_json(config_file)

        # rules.md
        rules_file = dir_path / "rules.md"
        if rules_file.is_file():
            layer.rules = _load_text(rules_file)

        return layer
