"""Shared defaults for live TUI refresh cadence."""

from __future__ import annotations

DEFAULT_LIVE_REFRESH_S = 0.25
MIN_LIVE_REFRESH_S = 0.05


def clamp_live_refresh_interval(seconds: float | int | None) -> float:
    """Normalize a live-refresh interval to a safe floor."""
    try:
        value = float(seconds if seconds is not None else DEFAULT_LIVE_REFRESH_S)
    except (TypeError, ValueError):
        value = DEFAULT_LIVE_REFRESH_S
    return max(MIN_LIVE_REFRESH_S, value)
