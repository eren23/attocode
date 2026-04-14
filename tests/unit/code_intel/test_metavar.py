"""Tests for metavariable pattern compilation and constraint evaluation."""

from __future__ import annotations

import re

import pytest

from attocode.code_intel.rules.metavar import (
    apply_metavar_fix,
    check_metavar_constraints,
    compile_metavar_pattern,
    has_metavars,
    interpolate_message,
)


class TestHasMetavars:
    def test_detects_simple_metavar(self):
        assert has_metavars("$FUNC()")

    def test_detects_multi_metavar(self):
        assert has_metavars("$FUNC($ARG)")

    def test_detects_ellipsis(self):
        assert has_metavars("$FUNC($...)")

    def test_no_metavars(self):
        assert not has_metavars("simple_regex")
        assert not has_metavars(r"eval\s*\(")

    def test_lowercase_dollar_not_metavar(self):
        assert not has_metavars("$100")  # starts with digit


class TestCompileMetavarPattern:
    def test_single_identifier(self):
        pat, names = compile_metavar_pattern("$FUNC()")
        assert names == ["FUNC"]
        m = pat.search("execute()")
        assert m and m.group("FUNC") == "execute"

    def test_two_metavars(self):
        pat, names = compile_metavar_pattern("$FUNC($ARG)")
        assert names == ["FUNC", "ARG"]
        m = pat.search("query(user_input)")
        assert m
        assert m.group("FUNC") == "query"
        assert m.group("ARG") == "user_input"

    def test_str_metavar_matches_string_literal(self):
        pat, _ = compile_metavar_pattern("$FUNC($STR)")
        m = pat.search('query("SELECT * FROM users")')
        assert m
        assert '"SELECT * FROM users"' in m.group("STR")

    def test_num_metavar_matches_number(self):
        pat, _ = compile_metavar_pattern("timeout=$NUM")
        m = pat.search("timeout=3000")
        assert m and m.group("NUM") == "3000"

    def test_num_metavar_matches_float(self):
        pat, _ = compile_metavar_pattern("rate=$NUM")
        m = pat.search("rate=0.95")
        assert m and m.group("NUM") == "0.95"

    def test_type_metavar(self):
        pat, _ = compile_metavar_pattern("var x $TYPE")
        m = pat.search("var x []string")
        assert m and m.group("TYPE") == "[]string"

    def test_ellipsis(self):
        pat, names = compile_metavar_pattern("$FUNC($..., $ARG)")
        assert "..." in names
        m = pat.search("exec(a, b, c, dangerous)")
        assert m
        assert m.group("ARG") == "dangerous"

    def test_back_reference(self):
        pat, names = compile_metavar_pattern("$VAR == $VAR")
        assert names == ["VAR", "VAR"]
        assert pat.search("x == x")
        assert not pat.search("x == y")

    def test_literal_text_escaped(self):
        pat, _ = compile_metavar_pattern("os.system($ARG)")
        assert pat.search("os.system(cmd)")
        assert not pat.search("os_system(cmd)")  # dot is literal

    def test_numbered_metavar(self):
        pat, _ = compile_metavar_pattern("$FUNC1 and $FUNC2")
        m = pat.search("foo and bar")
        assert m
        assert m.group("FUNC1") == "foo"
        assert m.group("FUNC2") == "bar"

    def test_expr_metavar_is_non_greedy(self):
        pat, _ = compile_metavar_pattern("$EXPR)")
        m = pat.search("a + b)")
        assert m and m.group("EXPR") == "a + b"


class TestInterpolateMessage:
    def test_basic_substitution(self):
        msg = interpolate_message("$FUNC called with $ARG", {"FUNC": "eval", "ARG": "input"})
        assert msg == "eval called with input"

    def test_missing_var_kept_as_is(self):
        msg = interpolate_message("$FUNC detected", {})
        assert msg == "$FUNC detected"

    def test_ellipsis_passthrough(self):
        msg = interpolate_message("call with $...", {"FUNC": "x"})
        assert "$..." in msg

    def test_no_metavars(self):
        msg = interpolate_message("no vars here", {"FUNC": "x"})
        assert msg == "no vars here"


class TestApplyMetavarFix:
    def test_basic_fix(self):
        s, r = apply_metavar_fix(
            "strings.ToLower($EXPR)",
            "strings.EqualFold($EXPR)",
            {"EXPR": "name"},
        )
        assert s == "strings.ToLower(name)"
        assert r == "strings.EqualFold(name)"

    def test_multiple_vars(self):
        s, r = apply_metavar_fix(
            "$FUNC($ARG)",
            "safe_$FUNC($ARG)",
            {"FUNC": "query", "ARG": "sql"},
        )
        assert s == "query(sql)"
        assert r == "safe_query(sql)"


class TestCheckMetavarConstraints:
    def test_no_constraints_passes(self):
        assert check_metavar_constraints({"FUNC": "anything"})

    def test_regex_match(self):
        assert check_metavar_constraints(
            {"FUNC": "query"},
            metavar_regex={"FUNC": "^(query|execute)$"},
        )

    def test_regex_no_match(self):
        assert not check_metavar_constraints(
            {"FUNC": "print"},
            metavar_regex={"FUNC": "^(query|execute)$"},
        )

    def test_regex_with_dollar_prefix(self):
        assert check_metavar_constraints(
            {"FUNC": "run"},
            metavar_regex={"$FUNC": "^run$"},
        )

    def test_comparison_gt(self):
        assert check_metavar_constraints(
            {"NUM": "2000"},
            metavar_comparison={"NUM": "> 1000"},
        )

    def test_comparison_gt_fails(self):
        assert not check_metavar_constraints(
            {"NUM": "500"},
            metavar_comparison={"NUM": "> 1000"},
        )

    def test_comparison_lte(self):
        assert check_metavar_constraints(
            {"NUM": "5"},
            metavar_comparison={"NUM": "<= 5"},
        )

    def test_comparison_eq(self):
        assert check_metavar_constraints(
            {"NUM": "42"},
            metavar_comparison={"NUM": "== 42"},
        )

    def test_comparison_ne(self):
        assert check_metavar_constraints(
            {"NUM": "0"},
            metavar_comparison={"NUM": "!= 1"},
        )

    def test_non_numeric_value_fails(self):
        assert not check_metavar_constraints(
            {"NUM": "abc"},
            metavar_comparison={"NUM": "> 0"},
        )

    def test_unrecognized_operator_fails(self):
        assert not check_metavar_constraints(
            {"NUM": "5"},
            metavar_comparison={"NUM": "=> 0"},
        )

    def test_combined_regex_and_comparison(self):
        assert check_metavar_constraints(
            {"FUNC": "query", "NUM": "100"},
            metavar_regex={"FUNC": "^query$"},
            metavar_comparison={"NUM": ">= 50"},
        )

    def test_missing_capture_fails_regex(self):
        assert not check_metavar_constraints(
            {},
            metavar_regex={"FUNC": "^query$"},
        )
