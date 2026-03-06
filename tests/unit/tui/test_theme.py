"""Tests for theme system."""

from __future__ import annotations

import pytest

from attocode.tui.theme import (
    DARK_THEME,
    HIGH_CONTRAST_THEME,
    LIGHT_THEME,
    THEMES,
    ThemeColors,
    ThemeName,
    get_theme,
)


class TestThemeColors:
    def test_dark_theme_has_all_fields(self) -> None:
        t = DARK_THEME
        assert t.bg
        assert t.fg
        assert t.accent
        assert t.success
        assert t.error
        assert t.warning
        assert t.border

    def test_light_theme_different_from_dark(self) -> None:
        assert DARK_THEME.bg != LIGHT_THEME.bg
        assert DARK_THEME.fg != LIGHT_THEME.fg

    def test_high_contrast_extreme_values(self) -> None:
        assert HIGH_CONTRAST_THEME.bg == "#000000"
        assert HIGH_CONTRAST_THEME.fg == "#ffffff"

    def test_theme_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DARK_THEME.bg = "#000000"  # type: ignore[misc]


class TestGetTheme:
    def test_get_dark(self) -> None:
        assert get_theme(ThemeName.DARK) is DARK_THEME

    def test_get_light(self) -> None:
        assert get_theme(ThemeName.LIGHT) is LIGHT_THEME

    def test_get_high_contrast(self) -> None:
        assert get_theme(ThemeName.HIGH_CONTRAST) is HIGH_CONTRAST_THEME

    def test_get_by_string(self) -> None:
        assert get_theme("dark") is DARK_THEME

    def test_all_themes_registered(self) -> None:
        assert len(THEMES) == 3
        for name in ThemeName:
            assert name in THEMES
