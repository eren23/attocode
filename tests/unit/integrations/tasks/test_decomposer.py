"""Tests for task decomposer (complexity classification and simple decomposition)."""

from __future__ import annotations

from attocode.integrations.tasks.decomposer import (
    ComplexityAssessment,
    ComplexityTier,
    DecomposedTask,
    DecompositionResult,
    classify_complexity,
    decompose_simple,
)


class TestComplexityTierOrdering:
    def test_tier_values(self) -> None:
        assert ComplexityTier.SIMPLE == "simple"
        assert ComplexityTier.MEDIUM == "medium"
        assert ComplexityTier.COMPLEX == "complex"
        assert ComplexityTier.DEEP_RESEARCH == "deep_research"

    def test_all_tiers_exist(self) -> None:
        tiers = list(ComplexityTier)
        assert len(tiers) == 4
        assert ComplexityTier.SIMPLE in tiers
        assert ComplexityTier.MEDIUM in tiers
        assert ComplexityTier.COMPLEX in tiers
        assert ComplexityTier.DEEP_RESEARCH in tiers


class TestClassifyComplexitySimple:
    def test_short_question_is_simple(self) -> None:
        result = classify_complexity("What is this file?")
        assert result.tier == ComplexityTier.SIMPLE

    def test_explain_is_simple(self) -> None:
        result = classify_complexity("Explain how this works")
        assert result.tier == ComplexityTier.SIMPLE

    def test_find_is_simple(self) -> None:
        result = classify_complexity("Find the config file")
        assert result.tier == ComplexityTier.SIMPLE

    def test_fix_typo_is_simple(self) -> None:
        result = classify_complexity("Fix typo in readme")
        assert result.tier == ComplexityTier.SIMPLE

    def test_rename_is_simple(self) -> None:
        result = classify_complexity("Rename the variable")
        assert result.tier == ComplexityTier.SIMPLE

    def test_check_is_simple(self) -> None:
        result = classify_complexity("Check the status")
        assert result.tier == ComplexityTier.SIMPLE


class TestClassifyComplexityComplex:
    def test_refactor_is_at_least_medium(self) -> None:
        result = classify_complexity(
            "Refactor the authentication module to use JWT tokens and implement proper session management"
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX, ComplexityTier.DEEP_RESEARCH)

    def test_multi_step_task(self) -> None:
        result = classify_complexity(
            "First analyze the codebase structure, then refactor the database layer, "
            "after that implement caching, and finally write comprehensive tests"
        )
        assert result.tier in (ComplexityTier.COMPLEX, ComplexityTier.DEEP_RESEARCH)

    def test_build_and_implement(self) -> None:
        result = classify_complexity(
            "Build a REST API with authentication, implement rate limiting, "
            "create database migrations, and develop comprehensive tests"
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX, ComplexityTier.DEEP_RESEARCH)

    def test_investigate_and_benchmark(self) -> None:
        result = classify_complexity(
            "Investigate the performance regression, benchmark the current implementation, "
            "compare with alternatives, and optimize the hot paths"
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX, ComplexityTier.DEEP_RESEARCH)


class TestClassifyComplexityReturnType:
    def test_returns_complexity_assessment(self) -> None:
        result = classify_complexity("Do something")
        assert isinstance(result, ComplexityAssessment)

    def test_has_tier(self) -> None:
        result = classify_complexity("Test")
        assert isinstance(result.tier, ComplexityTier)

    def test_has_confidence(self) -> None:
        result = classify_complexity("Test")
        assert 0.0 <= result.confidence <= 1.0

    def test_has_reasoning(self) -> None:
        result = classify_complexity("Test")
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_has_signals(self) -> None:
        result = classify_complexity("Test")
        assert isinstance(result.signals, list)
        assert len(result.signals) > 0

    def test_signals_have_expected_keys(self) -> None:
        result = classify_complexity("Refactor the module")
        for signal in result.signals:
            assert "name" in signal
            assert "value" in signal
            assert "weight" in signal

    def test_reasoning_contains_weighted_score(self) -> None:
        result = classify_complexity("Something")
        assert "Weighted score:" in result.reasoning


class TestClassifyComplexitySignals:
    def test_short_task_low_length_score(self) -> None:
        result = classify_complexity("Fix bug")
        length_signal = next(s for s in result.signals if s["name"] == "task_length")
        assert length_signal["value"] == 0.0

    def test_long_task_high_length_score(self) -> None:
        # 80+ words
        long_task = " ".join(["word"] * 100)
        result = classify_complexity(long_task)
        length_signal = next(s for s in result.signals if s["name"] == "task_length")
        assert length_signal["value"] == 3.0

    def test_question_word_negative_signal(self) -> None:
        result = classify_complexity("What is happening?")
        q_signal = next(s for s in result.signals if s["name"] == "question_vs_action")
        assert q_signal["value"] == -1.0

    def test_action_word_positive_signal(self) -> None:
        result = classify_complexity("Refactor the module")
        q_signal = next(s for s in result.signals if s["name"] == "question_vs_action")
        assert q_signal["value"] == 1.0

    def test_simple_keyword_negative_signal(self) -> None:
        result = classify_complexity("What is this variable?")
        simple_signal = next(s for s in result.signals if s["name"] == "simple_keywords")
        assert simple_signal["value"] == -2.0

    def test_no_simple_keyword_zero_signal(self) -> None:
        result = classify_complexity("Refactor auth module")
        simple_signal = next(s for s in result.signals if s["name"] == "simple_keywords")
        assert simple_signal["value"] == 0.0

    def test_dependency_pattern_detected(self) -> None:
        result = classify_complexity("First read the file then edit it")
        dep_signal = next(s for s in result.signals if s["name"] == "dependency_patterns")
        assert dep_signal["value"] > 0.0


class TestDecomposeSimple:
    def test_returns_decomposition_result(self) -> None:
        result = decompose_simple("Fix the bug")
        assert isinstance(result, DecompositionResult)

    def test_original_task_preserved(self) -> None:
        task = "Fix the bug in auth.py"
        result = decompose_simple(task)
        assert result.original_task == task

    def test_has_complexity(self) -> None:
        result = decompose_simple("Fix the bug")
        assert isinstance(result.complexity, ComplexityAssessment)

    def test_has_subtasks(self) -> None:
        result = decompose_simple("Fix the bug")
        assert isinstance(result.subtasks, list)
        assert len(result.subtasks) >= 1

    def test_subtasks_are_decomposed_tasks(self) -> None:
        result = decompose_simple("Fix the bug")
        for st in result.subtasks:
            assert isinstance(st, DecomposedTask)

    def test_simple_task_single_subtask(self) -> None:
        result = decompose_simple("Fix typo in readme")
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "Fix typo in readme"
        assert result.strategy == "single_task"

    def test_sequential_split_with_then(self) -> None:
        result = decompose_simple(
            "First analyze the codebase structure, then refactor the database layer. "
            "After that, implement caching. Finally, write comprehensive tests"
        )
        # Should split into multiple subtasks
        assert len(result.subtasks) >= 2
        assert result.strategy == "sequential_split"

    def test_sequential_subtasks_have_dependencies(self) -> None:
        result = decompose_simple(
            "First analyze the code, then refactor it. "
            "After that, add tests. Finally, update docs"
        )
        if len(result.subtasks) > 1:
            # First subtask has no dependencies
            assert result.subtasks[0].dependencies == []
            # Subsequent subtasks depend on the previous one
            for i in range(1, len(result.subtasks)):
                assert result.subtasks[i].dependencies == [i - 1]

    def test_numbered_steps_split(self) -> None:
        # The numbered step regex only triggers for non-SIMPLE tasks.
        # Use a task with enough complexity keywords to avoid SIMPLE classification.
        result = decompose_simple(
            "1) Analyze the existing configuration and investigate its structure. "
            "2) Refactor the database schema to implement new constraints. "
            "3) Build and run the migration scripts"
        )
        assert len(result.subtasks) >= 2

    def test_no_split_single_sentence(self) -> None:
        result = decompose_simple(
            "Implement a comprehensive authentication system with JWT and OAuth support"
        )
        # Even if complex, if no sequential markers, may return single subtask
        assert len(result.subtasks) >= 1

    def test_has_strategy_field(self) -> None:
        result = decompose_simple("Fix the typo")
        assert isinstance(result.strategy, str)
        assert len(result.strategy) > 0

    def test_subtask_defaults(self) -> None:
        result = decompose_simple("Fix the bug")
        subtask = result.subtasks[0]
        assert subtask.estimated_complexity == ComplexityTier.SIMPLE
        assert subtask.tools_needed == []
