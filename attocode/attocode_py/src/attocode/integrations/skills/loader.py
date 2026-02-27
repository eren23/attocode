"""Skill loader for .attocode/skills/ directories.

Loads skill definitions from user-level and project-level
skill directories with SKILL.md files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillDefinition:
    """A loaded skill definition."""

    name: str
    description: str = ""
    content: str = ""
    source: str = "project"  # builtin, user, project
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.content.strip())


class SkillLoader:
    """Loads skill definitions from the filesystem.

    Priority: user (~/.attocode/skills/) < project (.attocode/skills/)
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._skills: dict[str, SkillDefinition] = {}
        self._loaded = False

    def load(self) -> None:
        """Load skills from all sources."""
        self._skills.clear()

        # User-level skills
        user_dir = Path.home() / ".attocode" / "skills"
        self._load_from_directory(user_dir, source="user")

        # Project-level skills (override user)
        project_dir = self._project_root / ".attocode" / "skills"
        self._load_from_directory(project_dir, source="project")

        # Legacy path
        legacy_dir = self._project_root / ".agent" / "skills"
        if legacy_dir.is_dir() and not project_dir.is_dir():
            self._load_from_directory(legacy_dir, source="project")

        self._loaded = True

    def get(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        if not self._loaded:
            self.load()
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """List all loaded skills."""
        if not self._loaded:
            self.load()
        return list(self._skills.values())

    def has(self, name: str) -> bool:
        """Check if a skill exists."""
        if not self._loaded:
            self.load()
        return name in self._skills

    def reload(self) -> None:
        """Reload skills from disk."""
        self._loaded = False
        self.load()

    def _load_from_directory(self, directory: Path, source: str) -> None:
        """Load skills from a directory."""
        if not directory.is_dir():
            return

        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue

            # Look for SKILL.md
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
                name = skill_dir.name
                description, body, metadata = _parse_skill_content(content)

                self._skills[name] = SkillDefinition(
                    name=name,
                    description=description,
                    content=body,
                    source=source,
                    path=str(skill_file),
                    metadata=metadata,
                )
            except Exception:
                pass


def _parse_skill_content(content: str) -> tuple[str, str, dict[str, Any]]:
    """Parse a SKILL.md file, extracting description, body, and metadata.

    Returns (description, body, metadata).

    Metadata keys from frontmatter:
    - description: Human-readable description
    - version: Semantic version string
    - depends_on: Comma-separated or list of dependency skill names
    - compatible_versions: Dict of skill_name → required_version
    - lifecycle: "simple" | "long_running" (default: "simple")
    """
    lines = content.strip().splitlines()
    if not lines:
        return "", "", {}

    description = ""
    body_start = 0
    metadata: dict[str, Any] = {}

    if lines[0].startswith("---"):
        # YAML frontmatter
        frontmatter_lines: list[str] = []
        for i, line in enumerate(lines[1:], 1):
            if line.startswith("---"):
                body_start = i + 1
                break
            frontmatter_lines.append(line)

        # Parse frontmatter key-value pairs
        for fm_line in frontmatter_lines:
            if ":" not in fm_line:
                continue
            key, _, value = fm_line.partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")

            if key == "description":
                description = value
            elif key == "version":
                metadata["version"] = value
            elif key == "depends_on":
                # Accept comma-separated or YAML list
                deps = [d.strip() for d in value.split(",") if d.strip()]
                metadata["depends_on"] = deps
            elif key == "lifecycle":
                metadata["lifecycle"] = value
            else:
                metadata[key] = value

    elif lines[0].startswith("# "):
        # First heading is description
        description = lines[0][2:].strip()
        body_start = 1

    body = "\n".join(lines[body_start:]).strip()
    return description, body, metadata
