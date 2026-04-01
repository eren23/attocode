"""Tests for lifecycle utilities (generation counter)."""

from __future__ import annotations

from attocode.integrations.lifecycle import GenerationCounter


def test_generation_counter_advance_and_is_current() -> None:
    g = GenerationCounter()
    assert g.current == 0
    first = g.advance()
    assert first == 1
    assert g.is_current(1) is True
    assert g.is_current(0) is False
    g.advance()
    assert g.is_current(1) is False
    assert g.is_current(2) is True
