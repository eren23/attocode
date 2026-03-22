"""Tests for progressive disclosure skill loading."""

from __future__ import annotations

import pytest

from attocode.integrations.skills.progressive_loader import (
    ProgressiveSkillLoader,
    SkillInstructions,
    SkillLevel,
    SkillMetadata,
    SkillResources,
)


class TestProgressiveSkillLoader:
    def _make_loader_with_skills(self) -> ProgressiveSkillLoader:
        loader = ProgressiveSkillLoader()
        loader.register(
            "debug",
            "Debug and fix bugs",
            triggers=["debug", "fix bug", "error"],
            instructions="Step 1: Reproduce. Step 2: Isolate. Step 3: Fix.",
            examples=["debug the login failure"],
        )
        loader.register(
            "refactor",
            "Refactor code for clarity",
            triggers=["refactor", "clean up", "simplify"],
            instructions="Identify code smells. Apply patterns.",
            templates={"rename": "Rename {old} to {new}"},
        )
        loader.register(
            "deploy",
            "Deploy to production",
            triggers=["deploy", "ship", "release"],
            category="ops",
        )
        return loader

    def test_register_and_count(self) -> None:
        loader = self._make_loader_with_skills()
        assert loader.skill_count == 3

    def test_get_all_metadata(self) -> None:
        loader = self._make_loader_with_skills()
        metadata = loader.get_all_metadata()
        assert len(metadata) == 3
        names = {m.name for m in metadata}
        assert names == {"debug", "refactor", "deploy"}

    def test_metadata_context_string(self) -> None:
        loader = self._make_loader_with_skills()
        ctx = loader.get_metadata_context()
        assert "debug" in ctx
        assert "refactor" in ctx
        assert "deploy" in ctx

    def test_match_by_trigger(self) -> None:
        loader = self._make_loader_with_skills()
        result = loader.match("I need to debug this error")
        assert result is not None
        assert result.skill_name == "debug"
        assert result.confidence >= 0.8

    def test_match_by_name(self) -> None:
        loader = self._make_loader_with_skills()
        result = loader.match("refactor the authentication module")
        assert result is not None
        assert result.skill_name == "refactor"

    def test_no_match(self) -> None:
        loader = self._make_loader_with_skills()
        result = loader.match("what time is it")
        assert result is None

    def test_match_returns_instructions(self) -> None:
        loader = self._make_loader_with_skills()
        result = loader.match("debug this")
        assert result is not None
        assert result.level == SkillLevel.INSTRUCTIONS
        assert isinstance(result.content, SkillInstructions)
        assert "Reproduce" in result.content.instructions

    def test_load_level_metadata(self) -> None:
        loader = self._make_loader_with_skills()
        content = loader.load_level("debug", SkillLevel.METADATA)
        assert isinstance(content, SkillMetadata)

    def test_load_level_instructions(self) -> None:
        loader = self._make_loader_with_skills()
        content = loader.load_level("debug", SkillLevel.INSTRUCTIONS)
        assert isinstance(content, SkillInstructions)

    def test_load_level_resources(self) -> None:
        loader = self._make_loader_with_skills()
        content = loader.load_level("refactor", SkillLevel.RESOURCES)
        assert isinstance(content, SkillResources)
        assert "rename" in content.templates

    def test_load_level_updates_tracking(self) -> None:
        loader = self._make_loader_with_skills()
        assert loader.loaded_skills["debug"] == SkillLevel.METADATA
        loader.load_level("debug", SkillLevel.INSTRUCTIONS)
        assert loader.loaded_skills["debug"] == SkillLevel.INSTRUCTIONS

    def test_load_unknown_skill(self) -> None:
        loader = ProgressiveSkillLoader()
        with pytest.raises(KeyError, match="Unknown"):
            loader.load_level("nonexistent", SkillLevel.METADATA)

    def test_unload(self) -> None:
        loader = self._make_loader_with_skills()
        loader.load_level("debug", SkillLevel.INSTRUCTIONS)
        assert loader.loaded_skills["debug"] == SkillLevel.INSTRUCTIONS
        loader.unload("debug")
        assert loader.loaded_skills["debug"] == SkillLevel.METADATA

    def test_context_tokens_estimate(self) -> None:
        loader = self._make_loader_with_skills()
        # All at Level 1 — should be minimal
        tokens_l1 = loader.get_context_tokens_estimate()

        # Load one to Level 2
        loader.load_level("debug", SkillLevel.INSTRUCTIONS)
        tokens_l2 = loader.get_context_tokens_estimate()
        assert tokens_l2 > tokens_l1

    def test_empty_loader(self) -> None:
        loader = ProgressiveSkillLoader()
        assert loader.skill_count == 0
        assert loader.get_metadata_context() == ""
        assert loader.match("anything") is None

    def test_no_instructions_skill(self) -> None:
        loader = ProgressiveSkillLoader()
        loader.register("simple", "A simple skill")
        # Loading L2 for skill without instructions returns metadata
        content = loader.load_level("simple", SkillLevel.INSTRUCTIONS)
        assert isinstance(content, SkillMetadata)
