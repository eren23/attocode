"""Tests for complexity-aware goal decomposition."""

from __future__ import annotations

import pytest

from attoswarm.coordinator.decompose import (
    build_decompose_prompt,
    classify_goal_complexity,
    validate_decomposition,
)


class TestClassifyGoalComplexity:
    def test_simple_goal(self) -> None:
        assert classify_goal_complexity("Fix a typo in README") == "simple"

    def test_medium_goal_by_word_count(self) -> None:
        goal = " ".join(["word"] * 100)  # 100 words → score 1.0
        assert classify_goal_complexity(goal) in ("medium", "complex")

    def test_medium_goal_by_keywords(self) -> None:
        goal = "Add authentication and authorization to the API"
        result = classify_goal_complexity(goal)
        assert result in ("medium", "complex")

    def test_complex_goal_many_keywords(self) -> None:
        goal = (
            "Build a distributed microservice with authentication, "
            "authorization, caching, load balancing, and circuit breaker. "
            "Add sharding, partitioning, fault-tolerant websocket streaming."
        )
        result = classify_goal_complexity(goal)
        assert result in ("complex", "deep_research")

    def test_deep_research_goal(self) -> None:
        goal = (
            "Build a distributed system with consensus protocol using Raft, "
            "sharding, partitioning, fault-tolerant load balancing, "
            "circuit breaker, event sourcing, CQRS, saga pattern, "
            "websocket streaming, real-time concurrent processing, "
            "authentication via OAuth and JWT, encryption with TLS.\n"
            + "\n".join(f"- Module {i}: detailed subsystem" for i in range(10))
        )
        result = classify_goal_complexity(goal)
        assert result == "deep_research"

    def test_keywords_match_full_words(self) -> None:
        """Verify keyword stems like 'cach' match 'cache', 'caching', etc."""
        goal = "Implement caching layer with cache invalidation"
        hits = classify_goal_complexity(goal)
        # 'caching' and 'cache' should both match via cach\w*
        assert hits in ("medium", "complex", "simple")  # at least not erroring
        # More targeted: verify the regex actually matches
        from attoswarm.coordinator.decompose import _COMPLEX_KEYWORDS
        assert _COMPLEX_KEYWORDS.search("cache") is not None
        assert _COMPLEX_KEYWORDS.search("caching") is not None
        assert _COMPLEX_KEYWORDS.search("cached") is not None

    def test_keywords_match_load_balancer(self) -> None:
        from attoswarm.coordinator.decompose import _COMPLEX_KEYWORDS
        assert _COMPLEX_KEYWORDS.search("load balancer") is not None
        assert _COMPLEX_KEYWORDS.search("load balancing") is not None

    def test_keywords_match_event_sourcing(self) -> None:
        from attoswarm.coordinator.decompose import _COMPLEX_KEYWORDS
        assert _COMPLEX_KEYWORDS.search("event sourcing") is not None
        assert _COMPLEX_KEYWORDS.search("event source") is not None

    def test_keywords_match_microservices(self) -> None:
        from attoswarm.coordinator.decompose import _COMPLEX_KEYWORDS
        assert _COMPLEX_KEYWORDS.search("microservice") is not None
        assert _COMPLEX_KEYWORDS.search("microservices") is not None

    def test_subsystem_markers_boost_score(self) -> None:
        goal = (
            "Build a system:\n"
            "- Module A\n"
            "- Module B\n"
            "- Module C\n"
            "- Module D\n"
        )
        result = classify_goal_complexity(goal)
        assert result != "simple"

    def test_empty_goal_is_simple(self) -> None:
        assert classify_goal_complexity("") == "simple"


class TestValidateDecomposition:
    def test_no_warnings_for_adequate_tasks(self) -> None:
        tasks = [
            {"task_id": f"t{i}", "title": f"Task {i}", "description": "desc"}
            for i in range(6)
        ]
        warnings = validate_decomposition(tasks, "complex")
        assert warnings == []

    def test_too_few_tasks_warning(self) -> None:
        tasks = [
            {"task_id": "t1", "title": "Task 1", "description": "desc"},
        ]
        warnings = validate_decomposition(tasks, "complex")
        assert any(w["type"] == "too_few_tasks" for w in warnings)

    def test_no_too_few_warning_for_simple(self) -> None:
        tasks = [{"task_id": "t1", "title": "Single task", "description": "desc"}]
        warnings = validate_decomposition(tasks, "simple")
        assert not any(w["type"] == "too_few_tasks" for w in warnings)

    def test_bundled_features_detected_with_commas(self) -> None:
        """Commas in title should be detected as bundled features."""
        tasks = [
            {
                "task_id": "t1",
                "title": "Implement auth, caching, logging",
                "description": "desc",
            }
        ]
        warnings = validate_decomposition(tasks, "complex")
        bundled = [w for w in warnings if w["type"] == "bundled_features"]
        assert len(bundled) == 1
        assert bundled[0]["and_count"] >= 2

    def test_bundled_features_detected_with_and(self) -> None:
        """'and' in title should be detected as bundled features."""
        tasks = [
            {
                "task_id": "t1",
                "title": "Build auth and caching and logging",
                "description": "desc",
            }
        ]
        warnings = validate_decomposition(tasks, "simple")
        bundled = [w for w in warnings if w["type"] == "bundled_features"]
        assert len(bundled) == 1

    def test_single_feature_no_warning(self) -> None:
        tasks = [
            {"task_id": "t1", "title": "Implement authentication", "description": "desc"}
        ]
        warnings = validate_decomposition(tasks, "simple")
        assert not any(w["type"] == "bundled_features" for w in warnings)


class TestBuildDecomposePrompt:
    def test_prompt_contains_goal(self) -> None:
        prompt = build_decompose_prompt(
            "Build a REST API",
            complexity="medium",
            max_tasks=5,
        )
        assert "Build a REST API" in prompt

    def test_prompt_contains_task_count(self) -> None:
        prompt = build_decompose_prompt(
            "Build an app",
            complexity="medium",
            max_tasks=10,
        )
        assert "3" in prompt and "5" in prompt  # medium range is (3, 5)

    def test_complex_prompt_has_granularity_guidelines(self) -> None:
        prompt = build_decompose_prompt(
            "Build a distributed system",
            complexity="complex",
            max_tasks=15,
        )
        assert "Granularity Guidelines" in prompt
        assert "ONE specific subsystem" in prompt

    def test_simple_prompt_no_granularity_guidelines(self) -> None:
        prompt = build_decompose_prompt(
            "Fix a bug",
            complexity="simple",
            max_tasks=5,
        )
        assert "Granularity Guidelines" not in prompt
        assert "Task Count" in prompt

    def test_no_complexity_label_in_prompt(self) -> None:
        """Complexity tier should NOT appear as a header to avoid LLM anchoring."""
        for tier in ("simple", "medium", "complex", "deep_research"):
            prompt = build_decompose_prompt(
                "Build something",
                complexity=tier,
                max_tasks=10,
            )
            assert "Goal Complexity:" not in prompt

    def test_custom_instructions_included(self) -> None:
        prompt = build_decompose_prompt(
            "Build a thing",
            complexity="medium",
            max_tasks=5,
            custom_instructions="Always use TypeScript",
        )
        assert "Always use TypeScript" in prompt

    def test_role_descriptions_included(self) -> None:
        prompt = build_decompose_prompt(
            "Build a thing",
            complexity="medium",
            max_tasks=5,
            role_descriptions="impl: worker, judge: reviewer",
        )
        assert "impl: worker" in prompt

    def test_output_format_present(self) -> None:
        prompt = build_decompose_prompt(
            "Build something",
            complexity="simple",
            max_tasks=3,
        )
        assert "JSON array" in prompt
        assert "task_id" in prompt
