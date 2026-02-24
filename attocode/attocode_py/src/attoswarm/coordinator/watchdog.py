"""Watchdog for agent crash/stall detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class WatchdogResult:
    restart_agents: list[str]
    stale_agents: list[str]


def parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(UTC)


def evaluate_watchdog(
    heartbeat_map: dict[str, str],
    running_map: dict[str, bool],
    timeout_seconds: float = 30.0,
) -> WatchdogResult:
    now = datetime.now(UTC)
    stale: list[str] = []
    restart: list[str] = []
    for agent_id, ts in heartbeat_map.items():
        dt = parse_iso(ts)
        if (now - dt).total_seconds() > timeout_seconds:
            stale.append(agent_id)
            if not running_map.get(agent_id, False):
                restart.append(agent_id)
    return WatchdogResult(restart_agents=restart, stale_agents=stale)
