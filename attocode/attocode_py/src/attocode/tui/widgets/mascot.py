"""Mascot ASCII art and startup banner."""

from __future__ import annotations

from enum import Enum

from rich.text import Text


class GhostExpression(Enum):
    """Mascot eye positions."""

    CENTER = "center"
    LEFT = "left"
    RIGHT = "right"


# Mascot body (shared across expressions) — 6 lines, 18 chars wide
_GHOST_TOP = "     ▄██████▄     "
_GHOST_ROW2 = "   ██░░░░░░░░██   "
_GHOST_BODY = "   █░░░░░░░░░░█   "
_GHOST_MOUTH = "   █░░░╰──╯░░░█   "
_GHOST_FEET = "    ▀▄  ▀▄  ▀▄    "

# Eye rows per expression
_EYES = {
    GhostExpression.CENTER: "   █░░◕░░░◕░░░█   ",
    GhostExpression.LEFT:   "   █░◕░░░◕░░░░█   ",
    GhostExpression.RIGHT:  "   █░░░◕░░░░◕░█   ",
}

# Figlet-style "attocode" (~5 lines)
_FIGLET = [
    "        _   _                    _      ",
    "   __ _| |_| |_ ___   ___ ___  __| | ___",
    "  / _` | __| __/ _ \\ / __/ _ \\/ _` |/ _ \\",
    " | (_| | |_| || (_) | (_| (_) | (_| |  __/",
    "  \\__,_|\\__|\\__\\___/ \\___\\___/ \\__,_|\\___|",
]


def render_ghost(expression: GhostExpression = GhostExpression.CENTER) -> list[str]:
    """Return ghost ASCII art as a list of lines."""
    return [
        _GHOST_TOP,
        _GHOST_ROW2,
        _EYES[expression],
        _GHOST_BODY,
        _GHOST_MOUTH,
        _GHOST_FEET,
    ]


def render_startup_banner(
    model: str = "",
    git_branch: str = "",
    version: str = "",
    accent_color: str = "#89b4fa",
) -> Text:
    """Compose the full startup banner as a Rich Text object.

    Layout:
        Ghost art (left, colored) + figlet text (right, bold) side-by-side
        Info line below (dim)
        Thin separator
    """
    ghost_lines = render_ghost(GhostExpression.CENTER)
    figlet_lines = _FIGLET

    # Pad to equal height (ghost=6, figlet=5 → pad figlet top with 1 blank)
    max_lines = max(len(ghost_lines), len(figlet_lines))
    while len(ghost_lines) < max_lines:
        ghost_lines.append(" " * len(ghost_lines[0]))
    while len(figlet_lines) < max_lines:
        figlet_lines.insert(0, "")

    text = Text()
    gap = "  "

    # Side-by-side: ghost (colored) + figlet (bold)
    for g_line, f_line in zip(ghost_lines, figlet_lines):
        text.append(g_line, style=accent_color)
        text.append(gap)
        text.append(f_line, style="bold")
        text.append("\n")

    # Info line
    parts: list[str] = []
    if version:
        parts.append(f"v{version}")
    if model:
        parts.append(model)
    if git_branch:
        parts.append(f"⎇ {git_branch}")

    # Align info under figlet area
    info_indent = " " * (len(ghost_lines[0]) + len(gap))
    text.append(info_indent)
    text.append(" │ ".join(parts), style="dim")
    text.append("\n")

    return text
