"""Tests for UX overhaul pure functions (Tier 1).

Covers:
- _parse_activity_label (cli.py)
- build_per_task_costs (stores.py)
- _agent_color (event_timeline.py)
"""

from __future__ import annotations

import pytest

from attoswarm.cli import _parse_activity_label
from attoswarm.tui.stores import StateStore
from attoswarm.tui.widgets import _AGENT_COLORS, _agent_color, _agent_color_cache


# ── _parse_activity_label ─────────────────────────────────────────────


class TestParseActivityLabel:
    def test_read(self) -> None:
        assert _parse_activity_label("Reading src/main.ts") == "Reading main.ts"

    def test_edit(self) -> None:
        assert _parse_activity_label("Editing foo.py") == "Editing foo.py"

    def test_bash(self) -> None:
        assert _parse_activity_label("Running npm test") == "Running npm test"

    def test_grep(self) -> None:
        assert _parse_activity_label("Searching for pattern") == "Searching pattern"

    def test_no_match(self) -> None:
        assert _parse_activity_label("random line") == ""

    def test_empty(self) -> None:
        assert _parse_activity_label("") == ""

    def test_long_path(self) -> None:
        result = _parse_activity_label("Reading very/long/nested/path/file.ts")
        assert result == "Reading file.ts"


# ── build_per_task_costs ──────────────────────────────────────────────


class TestBuildPerTaskCosts:
    def test_empty(self) -> None:
        state: dict = {"dag": {"nodes": []}}
        result = StateStore.build_per_task_costs(None, state)  # type: ignore[arg-type]
        assert result == []

    def test_sorted_descending(self) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t1", "cost_usd": 0.10},
                    {"task_id": "t2", "cost_usd": 0.50},
                    {"task_id": "t3", "cost_usd": 0.30},
                ]
            }
        }
        result = StateStore.build_per_task_costs(None, state)  # type: ignore[arg-type]
        assert [r["task_id"] for r in result] == ["t2", "t3", "t1"]

    def test_zero_cost_excluded(self) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t1", "cost_usd": 0.0},
                    {"task_id": "t2", "cost_usd": 0.50},
                ]
            }
        }
        result = StateStore.build_per_task_costs(None, state)  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0]["task_id"] == "t2"


# ── Budget key regression ─────────────────────────────────────────────


class TestBudgetKeyName:
    """Verify TUI reads the same key that BudgetCounter.as_dict() writes."""

    def test_budget_key_matches_budget_counter(self) -> None:
        from attoswarm.coordinator.budget import BudgetCounter

        counter = BudgetCounter(max_tokens=1_000_000, max_cost_usd=50.0)
        d = counter.as_dict()
        # The TUI reads "cost_max_usd" — this must exist in as_dict output
        assert "cost_max_usd" in d
        assert d["cost_max_usd"] == 50.0
        # And "cost_used_usd" for the used cost
        assert "cost_used_usd" in d

    def test_budget_display_uses_correct_key(self) -> None:
        """Simulate the TUI budget extraction logic."""
        from attoswarm.coordinator.budget import BudgetCounter

        counter = BudgetCounter(max_tokens=1_000_000, max_cost_usd=42.0)
        budget = counter.as_dict()
        # This is the exact line from app.py:298
        max_cost = float(budget.get("cost_max_usd", 1.0)) or 1.0
        assert max_cost == 42.0


# ── _agent_color ──────────────────────────────────────────────────────


class TestAgentColor:
    def setup_method(self) -> None:
        _agent_color_cache.clear()

    def test_consistency(self) -> None:
        c1 = _agent_color("agent-1")
        c2 = _agent_color("agent-1")
        assert c1 == c2

    def test_cycling(self) -> None:
        """7 unique IDs should cycle through the 6-color palette, wrapping."""
        colors = [_agent_color(f"agent-{i}") for i in range(7)]
        assert colors[0] == colors[6]  # 7th wraps to first
        assert len(set(colors[:6])) == 6  # first 6 are distinct
