"""Shared path-formatting helpers for TUI widgets."""

from __future__ import annotations


def short_path(path: str, max_len: int = 45) -> str:
    """Shorten a file path for display, preserving start and end.

    Returns the path unchanged when it fits in ``max_len`` characters.
    Otherwise produces ``first_dir/.../last_two`` and falls back to a
    plain truncation with an ellipsis if even that is too long.
    """
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) <= 3:
        return path
    short = "/".join(parts[:1]) + "/…/" + "/".join(parts[-2:])
    if len(short) <= max_len:
        return short
    return path[: max_len - 1] + "…"
