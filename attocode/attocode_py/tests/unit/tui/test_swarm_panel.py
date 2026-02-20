"""Tests for the SwarmPanel widget."""

from __future__ import annotations

import pytest

from attocode.integrations.swarm.types import (
    SwarmBudgetStatus,
    SwarmPhase,
    SwarmQueueStats,
    SwarmStatus,
    SwarmWorkerStatus,
)
from attocode.tui.widgets.swarm_panel import (
    SwarmPanel,
    format_elapsed,
    format_tokens,
    phase_info,
    progress_bar,
)


# =============================================================================
# progress_bar()
# =============================================================================


class TestProgressBar:
    def test_zero_percent(self) -> None:
        result = progress_bar(0.0, 10)
        assert result == "[░░░░░░░░░░]"

    def test_hundred_percent(self) -> None:
        result = progress_bar(1.0, 10)
        assert result == "[██████████]"

    def test_fifty_percent(self) -> None:
        result = progress_bar(0.5, 10)
        assert "█" in result
        assert "░" in result

    def test_negative_clamped(self) -> None:
        result = progress_bar(-0.5, 10)
        assert result == "[░░░░░░░░░░]"

    def test_over_one_clamped(self) -> None:
        result = progress_bar(1.5, 10)
        assert result == "[██████████]"

    def test_default_width(self) -> None:
        result = progress_bar(0.5)
        # Default width is 12
        inner = result[1:-1]
        assert len(inner) == 12


# =============================================================================
# format_tokens()
# =============================================================================


class TestFormatTokens:
    def test_small_number(self) -> None:
        assert format_tokens(500) == "500"

    def test_thousands(self) -> None:
        assert format_tokens(1_000) == "1k"
        assert format_tokens(5_500) == "6k"  # rounds

    def test_millions(self) -> None:
        assert format_tokens(1_000_000) == "1.0M"
        assert format_tokens(5_500_000) == "5.5M"

    def test_zero(self) -> None:
        assert format_tokens(0) == "0"

    def test_boundary_999(self) -> None:
        assert format_tokens(999) == "999"


# =============================================================================
# format_elapsed()
# =============================================================================


class TestFormatElapsed:
    def test_seconds(self) -> None:
        assert format_elapsed(5_000) == "5s"
        assert format_elapsed(45_000) == "45s"

    def test_minutes(self) -> None:
        assert format_elapsed(90_000) == "1m30s"
        assert format_elapsed(120_000) == "2m00s"

    def test_zero(self) -> None:
        assert format_elapsed(0) == "0s"

    def test_sub_second(self) -> None:
        assert format_elapsed(500) == "0s"  # 0.5s rounds to 0


# =============================================================================
# phase_info()
# =============================================================================


class TestPhaseInfo:
    def test_idle(self) -> None:
        text, style = phase_info(SwarmPhase.IDLE)
        assert text == "Idle"
        assert style == "dim"

    def test_executing(self) -> None:
        text, style = phase_info(SwarmPhase.EXECUTING)
        assert text == "Executing"
        assert "green" in style

    def test_failed(self) -> None:
        text, style = phase_info(SwarmPhase.FAILED)
        assert text == "Failed"
        assert "red" in style

    def test_completed(self) -> None:
        text, style = phase_info(SwarmPhase.COMPLETED)
        assert text == "Completed"
        assert "green" in style

    def test_all_phases_covered(self) -> None:
        """Every SwarmPhase should have a phase_info entry."""
        for phase in SwarmPhase:
            text, style = phase_info(phase)
            assert isinstance(text, str)
            assert isinstance(style, str)


# =============================================================================
# SwarmPanel
# =============================================================================


class TestSwarmPanel:
    def test_default_hidden(self) -> None:
        panel = SwarmPanel()
        assert panel._status is None

    def test_update_status_none_hides(self) -> None:
        panel = SwarmPanel()
        panel.update_status(None)
        assert panel._status is None

    def test_update_status_sets_status(self) -> None:
        panel = SwarmPanel()
        status = SwarmStatus(phase=SwarmPhase.EXECUTING)
        panel.update_status(status)
        assert panel._status is status

    def test_render_empty_when_no_status(self) -> None:
        panel = SwarmPanel()
        result = panel.render()
        assert str(result) == ""

    def test_render_shows_phase(self) -> None:
        panel = SwarmPanel()
        panel.update_status(SwarmStatus(phase=SwarmPhase.EXECUTING))
        result = str(panel.render())
        assert "SWARM" in result
        assert "Executing" in result

    def test_render_shows_wave_progress(self) -> None:
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(
                phase=SwarmPhase.EXECUTING,
                current_wave=2,
                total_waves=4,
            )
        )
        result = str(panel.render())
        assert "Wave 2/4" in result
        assert "50%" in result

    def test_render_shows_queue(self) -> None:
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(
                phase=SwarmPhase.EXECUTING,
                queue=SwarmQueueStats(ready=2, running=1, completed=3, failed=0, total=6),
            )
        )
        result = str(panel.render())
        assert "Ready: 2" in result
        assert "Running: 1" in result
        assert "Done: 3" in result

    def test_render_shows_workers(self) -> None:
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(
                phase=SwarmPhase.EXECUTING,
                active_workers=[
                    SwarmWorkerStatus(
                        task_id="t1",
                        task_description="Implement auth module",
                        model="anthropic/claude-sonnet",
                        worker_name="coder-0",
                        elapsed_ms=45_000,
                        started_at=0.0,
                    ),
                ],
            )
        )
        result = str(panel.render())
        assert "coder-0" in result
        assert "Implement auth" in result
        assert "1 active" in result

    def test_render_shows_budget(self) -> None:
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(
                phase=SwarmPhase.EXECUTING,
                budget=SwarmBudgetStatus(
                    tokens_used=125_000,
                    tokens_total=5_000_000,
                    cost_used=0.12,
                    cost_total=10.0,
                ),
            )
        )
        result = str(panel.render())
        assert "125k" in result
        assert "5.0M" in result
        assert "$0.12" in result
        assert "$10.00" in result

    def test_render_no_wave_when_zero_total(self) -> None:
        panel = SwarmPanel()
        panel.update_status(SwarmStatus(phase=SwarmPhase.IDLE, total_waves=0))
        result = str(panel.render())
        assert "Wave" not in result

    def test_render_no_budget_when_zero_total(self) -> None:
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(
                phase=SwarmPhase.EXECUTING,
                budget=SwarmBudgetStatus(tokens_total=0),
            )
        )
        result = str(panel.render())
        assert "Budget" not in result

    def test_render_truncates_many_workers(self) -> None:
        workers = [
            SwarmWorkerStatus(
                task_id=f"t{i}",
                task_description=f"Task {i}",
                model="model",
                worker_name=f"w-{i}",
            )
            for i in range(6)
        ]
        panel = SwarmPanel()
        panel.update_status(
            SwarmStatus(phase=SwarmPhase.EXECUTING, active_workers=workers)
        )
        result = str(panel.render())
        assert "w-0" in result
        assert "w-3" in result
        assert "w-5" not in result  # only 4 shown
        assert "2 more" in result
