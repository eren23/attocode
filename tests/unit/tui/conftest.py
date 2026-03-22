"""TUI test configuration — stabilize Textual SVG snapshots.

Textual SVG snapshots are flaky because Rich's global style registry assigns
different CSS class numbers depending on which modules imported Rich before the
test ran.  In full-suite runs, prior test imports register extra styles,
changing the class-to-color mapping.

Fix: use a custom syrupy extension that normalizes SVG before comparison by
stripping all variable parts (hash IDs, style class numbers, style definitions).
Only the structural text content is compared.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode


# Regex patterns for normalization
_TERMINAL_HASH_RE = re.compile(r'terminal-\d+(-)')
_STYLE_CLASS_RE = re.compile(r' class="terminal-\d+-r\d+"')
_STYLE_BLOCK_RE = re.compile(r'<style>.*?</style>', re.DOTALL)
_CLIP_ID_RE = re.compile(r'terminal-\d+(-line-\d+)')


def _normalize_svg(svg: str) -> str:
    """Strip all variable style information from Textual SVG output.

    Normalizes:
    - terminal-HASH-... → terminal-0-...
    - class="terminal-*-rN" → stripped (style classes vary between runs)
    - <style>...</style> → stripped (CSS definitions vary)
    - clip-path IDs → normalized hash
    """
    svg = _TERMINAL_HASH_RE.sub(r'terminal-0\1', svg)
    svg = _STYLE_CLASS_RE.sub('', svg)
    svg = _STYLE_BLOCK_RE.sub('<style>/* normalized */</style>', svg)
    return svg


class StableTextualExtension(SingleFileSnapshotExtension):
    """Syrupy extension that normalizes Textual SVG before comparison."""

    _file_extension = "raw"
    _write_mode = WriteMode.TEXT

    def serialize(self, data, **kwargs):
        """Normalize SVG when writing snapshot to disk."""
        if isinstance(data, str):
            data = _normalize_svg(data)
        return data

    def matches(self, *, serialized_data, snapshot_data) -> bool:
        """Compare normalized versions of both sides."""
        if isinstance(serialized_data, str) and isinstance(snapshot_data, str):
            return _normalize_svg(serialized_data) == _normalize_svg(snapshot_data)
        return serialized_data == snapshot_data


@pytest.fixture
def snap_compare(snap_compare, snapshot):
    """Override snap_compare to use our stable extension."""
    stable_snapshot = snapshot.use_extension(StableTextualExtension)

    def _stable_compare(app, press=(), terminal_size=(80, 24), run_before=None):
        from textual._doc import take_svg_screenshot
        from textual.app import App

        if isinstance(app, App):
            actual = take_svg_screenshot(
                app=app,
                press=press,
                terminal_size=terminal_size,
                run_before=run_before,
            )
        else:
            from textual._import_app import import_app
            app_instance = import_app(str(app))
            actual = take_svg_screenshot(
                app=app_instance,
                press=press,
                terminal_size=terminal_size,
                run_before=run_before,
            )

        return stable_snapshot == _normalize_svg(actual)

    return _stable_compare
