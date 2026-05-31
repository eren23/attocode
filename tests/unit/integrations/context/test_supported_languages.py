"""Coverage/readiness must count every language the chunker embeds.

Regression test for the bug where is_index_ready()/get_index_progress()
computed total_files over a hardcoded {python,javascript,typescript} set
while the indexer embeds a wider set (tree-sitter langs: Go, Rust, C, ...).
On a Go repo that made coverage read 0% despite a fully built index, so
is_index_ready() returned False and the eval reported vec_ready=False even
though vectors were being served.
"""
from __future__ import annotations

from unittest.mock import patch

from attocode.integrations.context.semantic_search import SemanticSearchManager


def test_supported_languages_includes_base_three():
    langs = SemanticSearchManager._supported_languages()
    assert {"python", "javascript", "typescript"} <= langs


def test_supported_languages_includes_tree_sitter_langs():
    """When tree-sitter is available, Go/Rust/C are indexable → must count."""
    with patch(
        "attocode.integrations.context.ts_parser.supported_languages",
        return_value=["go", "rust", "c"],
    ):
        langs = SemanticSearchManager._supported_languages()
    assert "go" in langs
    assert "rust" in langs
    assert "c" in langs
    assert {"python", "javascript", "typescript"} <= langs


def test_supported_languages_degrades_to_base_three_without_tree_sitter():
    """ImportError (no tree-sitter) → just the always-supported three."""
    with patch(
        "attocode.integrations.context.ts_parser.supported_languages",
        side_effect=ImportError,
    ):
        langs = SemanticSearchManager._supported_languages()
    assert langs == {"python", "javascript", "typescript"}
