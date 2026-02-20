"""Theme system for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ThemeName(StrEnum):
    """Available theme names."""

    DARK = "dark"
    LIGHT = "light"
    HIGH_CONTRAST = "high_contrast"


@dataclass(frozen=True)
class ThemeColors:
    """Color palette for a theme."""

    # Backgrounds
    bg: str
    bg_surface: str
    bg_panel: str

    # Foregrounds
    fg: str
    fg_dim: str
    fg_muted: str

    # Accents
    accent: str
    accent_dim: str

    # Semantic
    success: str
    warning: str
    error: str
    info: str

    # Status
    status_idle: str
    status_processing: str
    status_approving: str

    # Diff
    diff_added: str
    diff_removed: str
    diff_context: str

    # Border
    border: str
    border_focus: str


DARK_THEME = ThemeColors(
    bg="#1e1e2e",
    bg_surface="#282a36",
    bg_panel="#313244",
    fg="#cdd6f4",
    fg_dim="#a6adc8",
    fg_muted="#6c7086",
    accent="#89b4fa",
    accent_dim="#45475a",
    success="#a6e3a1",
    warning="#f9e2af",
    error="#f38ba8",
    info="#89dceb",
    status_idle="#a6e3a1",
    status_processing="#89b4fa",
    status_approving="#f9e2af",
    diff_added="#a6e3a1",
    diff_removed="#f38ba8",
    diff_context="#6c7086",
    border="#45475a",
    border_focus="#89b4fa",
)

LIGHT_THEME = ThemeColors(
    bg="#eff1f5",
    bg_surface="#e6e9ef",
    bg_panel="#dce0e8",
    fg="#4c4f69",
    fg_dim="#5c5f77",
    fg_muted="#8c8fa1",
    accent="#1e66f5",
    accent_dim="#bcc0cc",
    success="#40a02b",
    warning="#df8e1d",
    error="#d20f39",
    info="#209fb5",
    status_idle="#40a02b",
    status_processing="#1e66f5",
    status_approving="#df8e1d",
    diff_added="#40a02b",
    diff_removed="#d20f39",
    diff_context="#8c8fa1",
    border="#bcc0cc",
    border_focus="#1e66f5",
)

HIGH_CONTRAST_THEME = ThemeColors(
    bg="#000000",
    bg_surface="#1a1a1a",
    bg_panel="#262626",
    fg="#ffffff",
    fg_dim="#cccccc",
    fg_muted="#999999",
    accent="#00ffff",
    accent_dim="#333333",
    success="#00ff00",
    warning="#ffff00",
    error="#ff0000",
    info="#00ccff",
    status_idle="#00ff00",
    status_processing="#00ffff",
    status_approving="#ffff00",
    diff_added="#00ff00",
    diff_removed="#ff0000",
    diff_context="#666666",
    border="#666666",
    border_focus="#ffffff",
)

THEMES: dict[ThemeName, ThemeColors] = {
    ThemeName.DARK: DARK_THEME,
    ThemeName.LIGHT: LIGHT_THEME,
    ThemeName.HIGH_CONTRAST: HIGH_CONTRAST_THEME,
}


def get_theme(name: ThemeName | str = ThemeName.DARK) -> ThemeColors:
    """Get a theme by name."""
    if isinstance(name, str):
        name = ThemeName(name)
    return THEMES.get(name, DARK_THEME)
