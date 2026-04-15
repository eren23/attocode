"""Progressive disclosure skill loading.

Three-tier loading model that scales to 100+ skills
without context pressure:

- Level 1 (always): Name + description (~100 tokens each)
- Level 2 (on trigger): Full instructions (<5K tokens)
- Level 3 (on demand): Resources, templates, reference docs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class SkillLevel(IntEnum):
    """Skill loading level."""

    METADATA = 1  # Name + description only
    INSTRUCTIONS = 2  # Full instructions
    RESOURCES = 3  # Resources, templates, docs


@dataclass(slots=True)
class SkillMetadata:
    """Level 1: Minimal skill metadata."""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    category: str = "general"
    estimated_tokens: int = 0


@dataclass(slots=True)
class SkillInstructions:
    """Level 2: Full skill instructions."""

    metadata: SkillMetadata
    instructions: str = ""
    examples: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SkillResources:
    """Level 3: Skill resources and templates."""

    instructions: SkillInstructions
    templates: dict[str, str] = field(default_factory=dict)
    reference_docs: list[str] = field(default_factory=list)
    sample_code: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SkillMatchResult:
    """Result of matching user input to a skill."""

    skill_name: str
    confidence: float
    level: SkillLevel
    content: SkillMetadata | SkillInstructions | SkillResources


class ProgressiveSkillLoader:
    """Loads skills progressively based on need.

    All skills are registered at Level 1 (metadata only,
    ~100 tokens each). When a skill matches user input,
    Level 2 (instructions) is loaded. Level 3 (resources)
    is loaded only on explicit demand.
    """

    def __init__(self) -> None:
        self._metadata: dict[str, SkillMetadata] = {}
        self._instructions: dict[str, SkillInstructions] = {}
        self._resources: dict[str, SkillResources] = {}
        self._loaded_levels: dict[str, SkillLevel] = {}

    @property
    def skill_count(self) -> int:
        return len(self._metadata)

    @property
    def loaded_skills(self) -> dict[str, SkillLevel]:
        return dict(self._loaded_levels)

    def register(
        self,
        name: str,
        description: str,
        *,
        triggers: list[str] | None = None,
        category: str = "general",
        instructions: str = "",
        examples: list[str] | None = None,
        constraints: list[str] | None = None,
        templates: dict[str, str] | None = None,
        reference_docs: list[str] | None = None,
        sample_code: dict[str, str] | None = None,
    ) -> None:
        """Register a skill with all levels of content."""
        meta = SkillMetadata(
            name=name,
            description=description,
            triggers=triggers or [],
            category=category,
            estimated_tokens=len(instructions.split()) if instructions else 0,
        )
        self._metadata[name] = meta
        self._loaded_levels[name] = SkillLevel.METADATA

        if instructions:
            self._instructions[name] = SkillInstructions(
                metadata=meta,
                instructions=instructions,
                examples=examples or [],
                constraints=constraints or [],
            )

        if templates or reference_docs or sample_code:
            instr = self._instructions.get(name, SkillInstructions(metadata=meta))
            self._resources[name] = SkillResources(
                instructions=instr,
                templates=templates or {},
                reference_docs=reference_docs or [],
                sample_code=sample_code or {},
            )

    def get_all_metadata(self) -> list[SkillMetadata]:
        """Get Level 1 metadata for all skills (always available)."""
        return list(self._metadata.values())

    def get_metadata_context(self) -> str:
        """Format all skill metadata for injection into context.

        This is the always-loaded portion — minimal tokens.
        """
        if not self._metadata:
            return ""

        lines = ["Available skills:"]
        for meta in sorted(self._metadata.values(), key=lambda m: m.name):
            lines.append(f"- {meta.name}: {meta.description}")
        return "\n".join(lines)

    def match(self, user_input: str) -> SkillMatchResult | None:
        """Match user input to a skill and load appropriate level.

        Returns the best matching skill at Level 2 (instructions)
        if a match is found.
        """
        user_lower = user_input.lower()
        best_match: tuple[str, float] | None = None

        for name, meta in self._metadata.items():
            score = 0.0

            # Check trigger words
            for trigger in meta.triggers:
                if trigger.lower() in user_lower:
                    score = max(score, 0.9)

            # Check name
            if name.lower() in user_lower:
                score = max(score, 0.8)

            # Check description keywords
            desc_words = meta.description.lower().split()
            matches = sum(1 for w in desc_words if len(w) > 3 and w in user_lower)
            if matches > 0:
                score = max(score, 0.3 + 0.1 * min(matches, 5))

            if score > 0.3 and (best_match is None or score > best_match[1]):
                best_match = (name, score)

        if best_match is None:
            return None

        name, confidence = best_match
        content = self.load_level(name, SkillLevel.INSTRUCTIONS)
        return SkillMatchResult(
            skill_name=name,
            confidence=confidence,
            level=SkillLevel.INSTRUCTIONS,
            content=content,
        )

    def load_level(
        self,
        name: str,
        level: SkillLevel,
    ) -> SkillMetadata | SkillInstructions | SkillResources:
        """Load a specific level for a skill.

        Updates the tracked loaded level.
        """
        if name not in self._metadata:
            raise KeyError(f"Unknown skill: {name}")

        current = self._loaded_levels.get(name, SkillLevel.METADATA)
        if level.value > current.value:
            self._loaded_levels[name] = level

        if level == SkillLevel.RESOURCES and name in self._resources:
            return self._resources[name]
        if level >= SkillLevel.INSTRUCTIONS and name in self._instructions:
            return self._instructions[name]
        return self._metadata[name]

    def get_context_tokens_estimate(self) -> int:
        """Estimate total tokens currently loaded into context."""
        total = 0
        for name, level in self._loaded_levels.items():
            meta = self._metadata.get(name)
            if meta is None:
                continue
            if level == SkillLevel.METADATA:
                total += len(meta.name.split()) + len(meta.description.split()) + 5
            elif level == SkillLevel.INSTRUCTIONS:
                instr = self._instructions.get(name)
                total += instr.metadata.estimated_tokens + 50 if instr else 20
            else:
                total += (meta.estimated_tokens or 0) + 200
        return total

    def unload(self, name: str) -> None:
        """Unload a skill back to Level 1 (metadata only)."""
        if name in self._loaded_levels:
            self._loaded_levels[name] = SkillLevel.METADATA
