"""Tests for feature flag registry and ``feature()`` helper."""

from __future__ import annotations

import os

import pytest

from attocode.integrations.feature_flags import ALL_FLAGS, feature, registry


class TestFeatureFlags:
    def setup_method(self) -> None:
        registry.clear_override("MCP_SSE_TRANSPORT")
        registry._resolved.pop("MCP_SSE_TRANSPORT", None)

    def teardown_method(self) -> None:
        registry.clear_override("MCP_SSE_TRANSPORT")
        env_key = registry.list_all()["MCP_SSE_TRANSPORT"]["env_var"]
        os.environ.pop(env_key, None)
        registry._resolved.pop("MCP_SSE_TRANSPORT", None)

    def test_feature_helper_matches_registry_boolean(self) -> None:
        registry.set_override("MCP_SSE_TRANSPORT", True)
        assert feature("MCP_SSE_TRANSPORT") is True
        assert registry.is_enabled("MCP_SSE_TRANSPORT") is True

    def test_env_override_boolean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        env_key = registry.list_all()["MCP_SSE_TRANSPORT"]["env_var"]
        monkeypatch.setenv(env_key, "1")
        registry._resolved.pop("MCP_SSE_TRANSPORT", None)
        assert registry.get("MCP_SSE_TRANSPORT") is True
        assert feature("MCP_SSE_TRANSPORT") is True

    def test_unknown_flag_keyerror(self) -> None:
        with pytest.raises(KeyError, match="Unknown feature flag"):
            registry.get("NOT_A_REAL_FLAG_NAME_XYZ")

    def test_all_flags_registered(self) -> None:
        assert "CALL_HIERARCHY" in ALL_FLAGS
        assert "UNC_PATH_BLOCK" in ALL_FLAGS
        snapshot = registry.list_all()
        assert len(snapshot) == len(ALL_FLAGS)
        assert snapshot["CALL_HIERARCHY"]["kind"] == "boolean"
