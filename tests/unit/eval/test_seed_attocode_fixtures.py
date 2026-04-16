"""Unit tests for the fixture-seed scaffolder."""

from __future__ import annotations

import pytest

from eval.rule_harness.scripts.seed_attocode_fixtures import (
    LANG_INFO,
    _annotate_block,
    render_fixture,
)


class TestAnnotateBlock:
    def test_appends_marker_to_first_code_line(self) -> None:
        out = _annotate_block(
            "x = 1\ny = 2\n", marker="#", kind="expect", rule_id="r-foo",
        )
        first = out.splitlines()[0]
        assert "# expect: r-foo" in first

    def test_skips_blank_leading_lines(self) -> None:
        out = _annotate_block(
            "\n\nactual = 1\n", marker="#", kind="expect", rule_id="r",
        )
        # Annotation goes on `actual = 1`, not the blank lines
        for line in out.splitlines():
            if "actual = 1" in line:
                assert "# expect: r" in line

    def test_empty_input_unchanged(self) -> None:
        assert _annotate_block("", marker="#", kind="expect", rule_id="r") == ""


class TestRenderFixture:
    def test_python_fixture_has_both_blocks(self) -> None:
        rule = {
            "examples": [
                {"bad": "result += '!'", "good": "result = ''.join(parts)"},
            ],
        }
        body = render_fixture("py-test", rule, "python")
        assert "# expect: py-test" in body
        assert "# ok: py-test" in body
        assert "BAD: rule MUST fire" in body
        assert "GOOD: rule must NOT fire" in body

    def test_go_fixture_uses_double_slash(self) -> None:
        rule = {"examples": [{"bad": "x := y", "good": "x = y"}]}
        body = render_fixture("go-test", rule, "go")
        assert "// expect: go-test" in body
        assert "// ok: go-test" in body

    def test_unknown_language_raises(self) -> None:
        rule = {"examples": [{"bad": "x", "good": "y"}]}
        with pytest.raises(ValueError, match="Unknown language"):
            render_fixture("r", rule, "klingon")

    def test_no_examples_raises(self) -> None:
        with pytest.raises(ValueError, match="no examples"):
            render_fixture("r", {"examples": []}, "python")


class TestLangInfo:
    def test_supports_five_target_langs(self) -> None:
        for lang in ("python", "go", "typescript", "rust", "java"):
            assert lang in LANG_INFO

    def test_python_uses_hash_marker(self) -> None:
        ext, marker = LANG_INFO["python"]
        assert ext == ".py"
        assert marker == "#"

    def test_go_uses_slash_marker(self) -> None:
        ext, marker = LANG_INFO["go"]
        assert ext == ".go"
        assert marker == "//"
