"""Tests for feature_initializer helpers."""

from __future__ import annotations

from attocode.agent.feature_initializer import _init_feature_flags


def test_init_feature_flags_loads_registry() -> None:
    out = _init_feature_flags()
    assert out == {"feature_flags": True}
