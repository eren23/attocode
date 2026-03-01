"""Tests for attocode.integrations.swarm.roles."""

from __future__ import annotations

import pytest

from attocode.integrations.swarm.roles import (
    BUILTIN_ROLES,
    RoleConfig,
    build_role_map,
    get_critic_config,
    get_judge_model,
    get_role_config,
    get_scout_config,
)


# ---------------------------------------------------------------------------
# BUILTIN_ROLES
# ---------------------------------------------------------------------------


class TestBuiltinRoles:
    """Verify all 7 built-in roles exist with expected properties."""

    def test_all_seven_roles_present(self) -> None:
        expected = {"orchestrator", "judge", "critic", "scout", "builder", "tester", "merger"}
        assert set(BUILTIN_ROLES.keys()) == expected

    def test_orchestrator_properties(self) -> None:
        role = BUILTIN_ROLES["orchestrator"]
        assert role.name == "orchestrator"
        assert role.capabilities == ["orchestrate"]
        assert role.max_per_swarm == 1
        assert role.read_only is False
        assert role.model is None

    def test_judge_properties(self) -> None:
        role = BUILTIN_ROLES["judge"]
        assert role.name == "judge"
        assert role.read_only is True
        assert role.capabilities == ["review"]
        assert role.max_per_swarm == 1

    def test_critic_properties(self) -> None:
        role = BUILTIN_ROLES["critic"]
        assert role.name == "critic"
        assert role.read_only is True
        assert role.capabilities == ["review"]
        assert role.persona != ""
        assert role.max_per_swarm is None

    def test_scout_properties(self) -> None:
        role = BUILTIN_ROLES["scout"]
        assert role.name == "scout"
        assert role.read_only is True
        assert role.capabilities == ["research"]
        assert role.persona != ""

    def test_builder_properties(self) -> None:
        role = BUILTIN_ROLES["builder"]
        assert role.name == "builder"
        assert role.read_only is False
        assert role.capabilities == ["code", "test"]
        assert role.max_per_swarm is None

    def test_tester_properties(self) -> None:
        role = BUILTIN_ROLES["tester"]
        assert role.name == "tester"
        assert role.capabilities == ["test"]
        assert role.read_only is False

    def test_merger_properties(self) -> None:
        role = BUILTIN_ROLES["merger"]
        assert role.name == "merger"
        assert role.capabilities == ["code", "write"]
        assert role.read_only is False


# ---------------------------------------------------------------------------
# get_role_config
# ---------------------------------------------------------------------------


class TestGetRoleConfig:
    """Tests for get_role_config()."""

    def test_builtin_role_returns_copy(self) -> None:
        cfg = get_role_config("builder")
        assert cfg.name == "builder"
        assert cfg.capabilities == ["code", "test"]
        # Verify it is a copy, not the same object
        assert cfg is not BUILTIN_ROLES["builder"]
        # Mutating the copy must not affect the builtin
        cfg.capabilities.append("write")
        assert "write" not in BUILTIN_ROLES["builder"].capabilities

    def test_unknown_role_gets_generic_config(self) -> None:
        cfg = get_role_config("custom_worker")
        assert cfg.name == "custom_worker"
        # Generic defaults from RoleConfig dataclass
        assert cfg.capabilities == ["code"]
        assert cfg.read_only is False
        assert cfg.model is None
        assert cfg.persona == ""
        assert cfg.max_per_swarm is None

    def test_override_model(self) -> None:
        cfg = get_role_config("builder", overrides={"model": "gpt-4o"})
        assert cfg.model == "gpt-4o"
        # Other fields unchanged
        assert cfg.capabilities == ["code", "test"]

    def test_override_persona(self) -> None:
        cfg = get_role_config("scout", overrides={"persona": "Custom scout persona"})
        assert cfg.persona == "Custom scout persona"
        assert cfg.read_only is True  # Inherited from builtin

    def test_override_capabilities(self) -> None:
        cfg = get_role_config("builder", overrides={"capabilities": ["code", "deploy"]})
        assert cfg.capabilities == ["code", "deploy"]

    def test_override_ignores_unknown_fields(self) -> None:
        cfg = get_role_config("builder", overrides={"nonexistent_field": 42})
        assert not hasattr(cfg, "nonexistent_field")
        assert cfg.name == "builder"

    def test_override_none_is_noop(self) -> None:
        cfg = get_role_config("judge", overrides=None)
        assert cfg.name == "judge"
        assert cfg.read_only is True


# ---------------------------------------------------------------------------
# build_role_map
# ---------------------------------------------------------------------------


class TestBuildRoleMap:
    """Tests for build_role_map()."""

    def test_no_config_returns_four_defaults(self) -> None:
        roles = build_role_map()
        assert set(roles.keys()) == {"orchestrator", "judge", "builder", "critic"}

    def test_no_config_has_correct_types(self) -> None:
        roles = build_role_map()
        for name, cfg in roles.items():
            assert isinstance(cfg, RoleConfig)
            assert cfg.name == name

    def test_custom_config_adds_role(self) -> None:
        roles = build_role_map({"scout": {}})
        assert "scout" in roles
        assert roles["scout"].read_only is True
        # Defaults still present
        assert "orchestrator" in roles
        assert "judge" in roles
        assert "builder" in roles
        assert "critic" in roles

    def test_custom_config_overrides_existing_role(self) -> None:
        roles = build_role_map({"builder": {"model": "claude-sonnet-4-6"}})
        assert roles["builder"].model == "claude-sonnet-4-6"
        assert roles["builder"].capabilities == ["code", "test"]

    def test_custom_config_with_unknown_role(self) -> None:
        roles = build_role_map({"deployer": {"capabilities": ["deploy"]}})
        assert "deployer" in roles
        assert roles["deployer"].capabilities == ["deploy"]
        assert roles["deployer"].name == "deployer"

    def test_builder_not_duplicated_when_in_config(self) -> None:
        roles = build_role_map({"builder": {"persona": "Fast builder"}})
        assert roles["builder"].persona == "Fast builder"
        # Only one builder entry
        assert list(roles.keys()).count("builder") == 1

    def test_critic_not_duplicated_when_in_config(self) -> None:
        roles = build_role_map({"critic": {"model": "gpt-4o"}})
        assert roles["critic"].model == "gpt-4o"
        assert list(roles.keys()).count("critic") == 1


# ---------------------------------------------------------------------------
# get_judge_model
# ---------------------------------------------------------------------------


class TestGetJudgeModel:
    """Tests for get_judge_model()."""

    def test_falls_back_to_orchestrator_model(self) -> None:
        roles = build_role_map()
        # Judge has no model override by default
        model = get_judge_model(roles, "claude-opus-4-6")
        assert model == "claude-opus-4-6"

    def test_returns_judge_model_when_set(self) -> None:
        roles = build_role_map({"judge": {"model": "gpt-4o"}})
        model = get_judge_model(roles, "claude-opus-4-6")
        assert model == "gpt-4o"

    def test_no_judge_in_map_falls_back(self) -> None:
        # Edge case: roles map without judge key
        roles: dict[str, RoleConfig] = {}
        model = get_judge_model(roles, "fallback-model")
        assert model == "fallback-model"


# ---------------------------------------------------------------------------
# get_critic_config / get_scout_config
# ---------------------------------------------------------------------------


class TestGetCriticConfig:
    """Tests for get_critic_config()."""

    def test_returns_critic_when_present(self) -> None:
        roles = build_role_map()  # critic included by default
        cfg = get_critic_config(roles)
        assert cfg is not None
        assert cfg.name == "critic"
        assert cfg.read_only is True

    def test_returns_none_when_absent(self) -> None:
        roles: dict[str, RoleConfig] = {"orchestrator": get_role_config("orchestrator")}
        assert get_critic_config(roles) is None


class TestGetScoutConfig:
    """Tests for get_scout_config()."""

    def test_returns_scout_when_present(self) -> None:
        roles = build_role_map({"scout": {}})
        cfg = get_scout_config(roles)
        assert cfg is not None
        assert cfg.name == "scout"
        assert cfg.read_only is True

    def test_returns_none_when_absent(self) -> None:
        roles = build_role_map()  # scout not included by default
        assert get_scout_config(roles) is None
