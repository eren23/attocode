"""Tests for system defaults and configuration presets."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from attocode.defaults import (
    BUDGET_PRESETS,
    DEEP_BUDGET,
    DEFAULT_HOOKS_CONFIG,
    DEFAULT_PLANNING_CONFIG,
    DEFAULT_SANDBOX_CONFIG,
    DEFAULT_SYSTEM_PROMPT,
    LARGE_BUDGET,
    QUICK_BUDGET,
    STANDARD_BUDGET,
    SUBAGENT_BUDGET,
    SUBAGENT_MAX_ITERATIONS,
    SUBAGENT_TIMEOUTS,
    SWARM_ORCHESTRATOR_BUDGET,
    SWARM_WORKER_BUDGET,
    UNLIMITED_BUDGET,
    EconomicsTuning,
    HooksConfig,
    PlanningConfig,
    SandboxConfig,
    get_subagent_max_iterations,
    get_subagent_timeout,
    is_feature_enabled,
    merge_config,
)
from attocode.types.budget import BudgetEnforcementMode


class TestBudgetPresets:
    def test_all_presets_exist(self) -> None:
        expected_keys = {
            "quick", "standard", "deep", "subagent",
            "large", "unlimited", "swarm_worker", "swarm_orchestrator",
        }
        assert set(BUDGET_PRESETS.keys()) == expected_keys

    def test_quick_budget_values(self) -> None:
        assert QUICK_BUDGET.max_tokens == 200_000
        assert QUICK_BUDGET.soft_token_limit == 160_000
        assert QUICK_BUDGET.max_iterations == 20

    def test_standard_budget_values(self) -> None:
        assert STANDARD_BUDGET.max_tokens == 1_000_000
        assert STANDARD_BUDGET.soft_token_limit == 800_000

    def test_subagent_budget_strict(self) -> None:
        assert SUBAGENT_BUDGET.enforcement_mode == BudgetEnforcementMode.STRICT

    def test_unlimited_budget(self) -> None:
        assert UNLIMITED_BUDGET.max_tokens == 0
        assert UNLIMITED_BUDGET.soft_token_limit is None
        assert UNLIMITED_BUDGET.max_iterations is None
        assert UNLIMITED_BUDGET.enforcement_mode == BudgetEnforcementMode.ADVISORY

    def test_budget_ordering(self) -> None:
        assert QUICK_BUDGET.max_tokens < STANDARD_BUDGET.max_tokens
        assert STANDARD_BUDGET.max_tokens < DEEP_BUDGET.max_tokens
        assert DEEP_BUDGET.max_tokens < LARGE_BUDGET.max_tokens

    def test_swarm_budgets(self) -> None:
        assert SWARM_WORKER_BUDGET.max_tokens == 300_000
        assert SWARM_ORCHESTRATOR_BUDGET.max_tokens == 2_000_000
        assert SWARM_WORKER_BUDGET.enforcement_mode == BudgetEnforcementMode.STRICT
        assert SWARM_ORCHESTRATOR_BUDGET.enforcement_mode == BudgetEnforcementMode.SOFT


class TestMergeConfig:
    def test_none_returns_defaults(self) -> None:
        result = merge_config(DEFAULT_HOOKS_CONFIG, None)
        assert result is DEFAULT_HOOKS_CONFIG

    def test_false_disables(self) -> None:
        result = merge_config(DEFAULT_HOOKS_CONFIG, False)
        assert result is False

    def test_override_fields(self) -> None:
        custom = HooksConfig(enabled=False, logging=True)
        result = merge_config(DEFAULT_HOOKS_CONFIG, custom)
        assert isinstance(result, HooksConfig)
        # False is falsy so merge_config uses default for it
        # but True overrides
        assert result.logging is True

    def test_non_dataclass_returns_user_value(self) -> None:
        result = merge_config("default_string", "custom_string")
        assert result == "custom_string"


class TestIsFeatureEnabled:
    def test_false_is_disabled(self) -> None:
        assert is_feature_enabled(False) is False

    def test_none_is_disabled(self) -> None:
        assert is_feature_enabled(None) is False

    def test_config_with_enabled_true(self) -> None:
        assert is_feature_enabled(DEFAULT_HOOKS_CONFIG) is True

    def test_config_with_enabled_false(self) -> None:
        config = HooksConfig(enabled=False)
        assert is_feature_enabled(config) is False

    def test_plain_value_is_enabled(self) -> None:
        assert is_feature_enabled("anything") is True
        assert is_feature_enabled(42) is True


class TestSubagentTimeouts:
    def test_known_agent_type(self) -> None:
        assert get_subagent_timeout("researcher") == 420_000
        assert get_subagent_timeout("coder") == 300_000

    def test_unknown_agent_type_returns_default(self) -> None:
        assert get_subagent_timeout("unknown_type") == SUBAGENT_TIMEOUTS["default"]

    def test_known_max_iterations(self) -> None:
        assert get_subagent_max_iterations("researcher") == 25
        assert get_subagent_max_iterations("documenter") == 10

    def test_unknown_max_iterations_returns_default(self) -> None:
        assert get_subagent_max_iterations("unknown") == SUBAGENT_MAX_ITERATIONS["default"]


class TestDefaultConfigs:
    def test_sandbox_has_allowed_commands(self) -> None:
        assert len(DEFAULT_SANDBOX_CONFIG.allowed_commands) > 10
        assert "git" in DEFAULT_SANDBOX_CONFIG.allowed_commands
        assert "python" in DEFAULT_SANDBOX_CONFIG.allowed_commands

    def test_economics_tuning_defaults(self) -> None:
        tuning = EconomicsTuning()
        assert tuning.doom_loop_threshold == 3
        assert tuning.exploration_file_threshold == 10

    def test_system_prompt_is_nonempty(self) -> None:
        assert len(DEFAULT_SYSTEM_PROMPT) > 100
        assert "Attocode" in DEFAULT_SYSTEM_PROMPT
