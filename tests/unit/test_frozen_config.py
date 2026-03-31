"""Tests for AttoConfig.freeze() and FrozenAttoConfig."""

from __future__ import annotations

from attocode.config import AttoConfig, FrozenAttoConfig


def test_freeze_creates_independent_copy() -> None:
    """Mutating the original config after freeze does not affect the frozen copy."""
    cfg = AttoConfig(provider="anthropic", model="claude-sonnet-4", max_tokens=4096)
    frozen = cfg.freeze()

    # Mutate the original
    cfg.provider = "openai"
    cfg.model = "gpt-5"
    cfg.max_tokens = 9999

    # Frozen copy retains original values
    assert frozen.provider == "anthropic"
    assert frozen.model == "claude-sonnet-4"
    assert frozen.max_tokens == 4096


def test_frozen_raises_on_setattr() -> None:
    """Setting an attribute on a frozen config raises AttributeError."""
    frozen = AttoConfig().freeze()

    try:
        frozen.model = "x"  # type: ignore[misc]
    except AttributeError as exc:
        assert "immutable" in str(exc).lower()
        assert "model" in str(exc)
    else:
        raise AssertionError("Expected AttributeError was not raised")


def test_frozen_reads_all_fields() -> None:
    """Frozen config delegates reads for all key fields."""
    cfg = AttoConfig(
        provider="openrouter",
        model="anthropic/claude-opus-4",
        max_tokens=16384,
        temperature=0.7,
    )
    frozen = cfg.freeze()

    assert frozen.provider == "openrouter"
    assert frozen.model == "anthropic/claude-opus-4"
    assert frozen.max_tokens == 16384
    assert frozen.temperature == 0.7


def test_frozen_repr() -> None:
    """repr() output includes 'FrozenAttoConfig'."""
    frozen = AttoConfig(provider="anthropic").freeze()
    r = repr(frozen)
    assert "FrozenAttoConfig" in r
