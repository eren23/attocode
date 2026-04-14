"""Tests for boolean pattern combinators."""

from __future__ import annotations

import re

import pytest

from attocode.code_intel.rules.combinators import (
    AllNode,
    CompositePattern,
    EitherNode,
    InsideNode,
    MatchContext,
    NotInsideNode,
    NotNode,
    RegexNode,
    build_composite_from_yaml,
)


def _ctx(line: str, line_no: int = 1, all_lines: list[str] | None = None) -> MatchContext:
    """Helper to build a MatchContext."""
    if all_lines is None:
        all_lines = [line]
    return MatchContext(line=line, line_no=line_no, all_lines=all_lines)


class TestRegexNode:
    def test_match(self):
        node = RegexNode(pattern=re.compile(r"panic\("))
        assert node.evaluate(_ctx("panic()"))

    def test_no_match(self):
        node = RegexNode(pattern=re.compile(r"panic\("))
        assert not node.evaluate(_ctx("safe()"))

    def test_captures_populated(self):
        node = RegexNode(
            pattern=re.compile(r"(?P<FUNC>\w+)\("),
            metavar_names=["FUNC"],
        )
        ctx = _ctx("execute()")
        assert node.evaluate(ctx)
        assert ctx.captures["FUNC"] == "execute"


class TestEitherNode:
    def test_first_child_matches(self):
        node = EitherNode(children=[
            RegexNode(pattern=re.compile("aaa")),
            RegexNode(pattern=re.compile("bbb")),
        ])
        assert node.evaluate(_ctx("aaa"))

    def test_second_child_matches(self):
        node = EitherNode(children=[
            RegexNode(pattern=re.compile("aaa")),
            RegexNode(pattern=re.compile("bbb")),
        ])
        assert node.evaluate(_ctx("bbb"))

    def test_no_child_matches(self):
        node = EitherNode(children=[
            RegexNode(pattern=re.compile("aaa")),
            RegexNode(pattern=re.compile("bbb")),
        ])
        assert not node.evaluate(_ctx("ccc"))


class TestAllNode:
    def test_all_match(self):
        node = AllNode(children=[
            RegexNode(pattern=re.compile("foo")),
            RegexNode(pattern=re.compile("bar")),
        ])
        assert node.evaluate(_ctx("foobar"))

    def test_one_fails(self):
        node = AllNode(children=[
            RegexNode(pattern=re.compile("foo")),
            RegexNode(pattern=re.compile("baz")),
        ])
        assert not node.evaluate(_ctx("foobar"))


class TestNotNode:
    def test_negation_when_child_matches(self):
        node = NotNode(child=RegexNode(pattern=re.compile("nolint")))
        assert not node.evaluate(_ctx("// nolint"))

    def test_negation_when_child_does_not_match(self):
        node = NotNode(child=RegexNode(pattern=re.compile("nolint")))
        assert node.evaluate(_ctx("normal code"))


class TestInsideNode:
    def test_finds_scope_above(self):
        lines = [
            "func bad() {",       # 0 (line 1)
            "    for i := range {",  # 1 (line 2)
            "        fmt.Sprintf()",  # 2 (line 3)
            "    }",                # 3
            "}",                    # 4
        ]
        node = InsideNode(scope_pattern=re.compile(r"for\s"))
        ctx = _ctx(lines[2], line_no=3, all_lines=lines)
        assert node.evaluate(ctx)

    def test_not_inside_when_scope_missing(self):
        lines = [
            "func clean() {",
            "    fmt.Sprintf()",
            "}",
        ]
        node = InsideNode(scope_pattern=re.compile(r"for\s"))
        ctx = _ctx(lines[1], line_no=2, all_lines=lines)
        assert not node.evaluate(ctx)

    def test_stops_at_function_boundary(self):
        lines = [
            "func bad() {",
            "    for i := range {",
            "        something()",
            "    }",
            "}",
            "",
            "func clean() {",        # line 7
            "    fmt.Sprintf()",      # line 8
            "}",
        ]
        node = InsideNode(scope_pattern=re.compile(r"for\s"))
        ctx = _ctx(lines[7], line_no=8, all_lines=lines)
        assert not node.evaluate(ctx)

    def test_indent_zero_code_never_matches(self):
        lines = [
            "for item in items:",
            "print(item)",  # indent 0 — not "inside" the for
        ]
        node = InsideNode(scope_pattern=re.compile(r"for\s"))
        ctx = _ctx(lines[1], line_no=2, all_lines=lines)
        assert not node.evaluate(ctx)


class TestNotInsideNode:
    def test_not_inside_scope(self):
        lines = [
            "def process():",
            "    print('debug')",
        ]
        node = NotInsideNode(scope_pattern=re.compile(r"def test_"))
        ctx = _ctx(lines[1], line_no=2, all_lines=lines)
        assert node.evaluate(ctx)

    def test_inside_scope(self):
        lines = [
            "def test_example():",
            "    print('ok')",
        ]
        node = NotInsideNode(scope_pattern=re.compile(r"def test_"))
        ctx = _ctx(lines[1], line_no=2, all_lines=lines)
        assert not node.evaluate(ctx)


class TestCompositePattern:
    def test_primary_only(self):
        cp = CompositePattern(
            primary=RegexNode(pattern=re.compile("foo")),
        )
        assert cp.evaluate(_ctx("foo"))
        assert not cp.evaluate(_ctx("bar"))

    def test_primary_with_not_constraint(self):
        cp = CompositePattern(
            primary=RegexNode(pattern=re.compile("Sprintf")),
            constraints=[NotNode(child=RegexNode(pattern=re.compile("nolint")))],
        )
        assert cp.evaluate(_ctx("fmt.Sprintf()"))
        assert not cp.evaluate(_ctx("fmt.Sprintf() // nolint"))


class TestBuildCompositeFromYaml:
    def test_patterns_list(self):
        cp = build_composite_from_yaml([
            {"pattern": r"fmt\.Sprintf"},
            {"pattern-not": "nolint"},
        ])
        assert cp is not None
        assert cp.evaluate(_ctx("fmt.Sprintf()"))
        assert not cp.evaluate(_ctx("fmt.Sprintf() // nolint"))

    def test_pattern_either_dict(self):
        cp = build_composite_from_yaml({
            "pattern-either": [r"md5\.New", r"sha1\.New"],
        })
        assert cp is not None
        assert cp.evaluate(_ctx("md5.New()"))
        assert cp.evaluate(_ctx("sha1.New()"))
        assert not cp.evaluate(_ctx("sha256.New()"))

    def test_empty_list_returns_none(self):
        assert build_composite_from_yaml([]) is None

    def test_no_primary_returns_none(self):
        assert build_composite_from_yaml([{"pattern-not": "x"}]) is None

    def test_invalid_input_returns_none(self):
        assert build_composite_from_yaml("not a list") is None

    def test_pattern_inside(self):
        cp = build_composite_from_yaml([
            {"pattern": "Sprintf"},
            {"pattern-inside": r"for\s"},
        ])
        assert cp is not None
        lines = [
            "func f() {",
            "    for i := range x {",
            "        Sprintf()",
            "    }",
            "}",
        ]
        ctx = _ctx(lines[2], line_no=3, all_lines=lines)
        assert cp.evaluate(ctx)

    def test_pattern_not_inside(self):
        cp = build_composite_from_yaml([
            {"pattern": "print"},
            {"pattern-not-inside": "def test_"},
        ])
        assert cp is not None
        lines = [
            "def process():",
            "    print('debug')",
        ]
        ctx = _ctx(lines[1], line_no=2, all_lines=lines)
        assert cp.evaluate(ctx)
