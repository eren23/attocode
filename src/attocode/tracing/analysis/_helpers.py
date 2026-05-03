"""Internal helpers shared across trace analysis modules."""

from __future__ import annotations

from typing import Any


def safe_int(d: dict[str, Any], key: str) -> int:
    """Safely extract an integer from a data dict (0 on missing/invalid)."""
    v = d.get(key)
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def safe_float(d: dict[str, Any], key: str) -> float:
    """Safely extract a float from a data dict (0.0 on missing/invalid)."""
    v = d.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
