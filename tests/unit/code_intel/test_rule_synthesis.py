"""Tests for rules.synthesis — deterministic regex + LLM-assisted paths.

The LLM path is exercised with an injected ``llm_caller`` so the suite
stays deterministic and offline.
"""

from __future__ import annotations

from attocode.code_intel.rules.synthesis import (
    _build_regex_pattern,
    _lcs_2way,
    _lcs_across,
    _strip_code_fences,
    render_rule_yaml,
    synthesize_regex_rule,
    synthesize_rule,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestLcs:
    def test_lcs_2way_basic(self):
        assert _lcs_2way("abcdef", "zbcdez") == "bcde"
        assert _lcs_2way("abc", "xyz") == ""
        assert _lcs_2way("", "abc") == ""

    def test_lcs_across_reduces_pairwise(self):
        assert _lcs_across(["foobar", "fooqux", "foozzz"]) == "foo"
        assert _lcs_across(["abc", "def", "ghi"]) == ""
        assert _lcs_across([]) == ""
        assert _lcs_across(["only"]) == "only"


class TestBuildRegexPattern:
    def test_word_boundaries_added_for_word_edges(self):
        # Word-char start AND end → both boundaries added.
        assert _build_regex_pattern("forbidden") == r"\bforbidden\b"

    def test_no_boundaries_for_non_word_edges(self):
        assert _build_regex_pattern(".unwrap()") == r"\.unwrap\(\)"

    def test_partial_boundary(self):
        # leading word char, trailing punctuation
        assert _build_regex_pattern("forbidden(") == r"\bforbidden\("


# ---------------------------------------------------------------------------
# Deterministic regex synthesis
# ---------------------------------------------------------------------------


class TestSynthesizeRegexRule:
    def test_clean_anchor_emits_rule(self):
        positives = [
            'forbidden_call(user_input)',
            'forbidden_call(json_data)',
            'forbidden_call(payload)',
        ]
        negatives = [
            'safe_call(input)',           # different identifier
            'self.forbidden(local)',      # different shape (no _call suffix)
        ]
        rule, diags = synthesize_regex_rule(
            positives, negatives,
            rule_id="no-forbidden-call", language="python",
        )
        assert rule is not None, diags
        assert rule.id == "no-forbidden-call"
        assert rule.languages == ["python"]
        # All positives matched, no negatives matched.
        for p in positives:
            assert rule.pattern.search(p), p
        for n in negatives:
            assert not rule.pattern.search(n), n

    def test_anchor_too_short_aborts(self):
        # Common substring across these is just "x" — way below the floor.
        rule, diags = synthesize_regex_rule(
            positives=["xx", "xy", "xz"],
            negatives=[],
            rule_id="x", language="python",
        )
        assert rule is None
        assert any("anchor" in d.lower() or "min_anchor" in d for d in diags)

    def test_anchor_matches_negative_aborts(self):
        # Common literal "logger." matches both positives and negative.
        rule, diags = synthesize_regex_rule(
            positives=["logger.error", "logger.warn"],
            negatives=["logger.info"],
            rule_id="x", language="python",
        )
        assert rule is None
        assert any("negative" in d for d in diags)

    def test_no_positives_aborts(self):
        rule, diags = synthesize_regex_rule(
            positives=[], negatives=[],
            rule_id="x", language="python",
        )
        assert rule is None
        assert any("positive" in d for d in diags)

    def test_min_anchor_len_configurable(self):
        # With min_anchor_len=2, "xy" should suffice.
        rule, _diags = synthesize_regex_rule(
            positives=["xy_a", "xy_b"],
            negatives=["zz"],
            rule_id="xy", language="python",
            min_anchor_len=2,
        )
        assert rule is not None


# ---------------------------------------------------------------------------
# Top-level synthesize_rule + LLM mode (mocked)
# ---------------------------------------------------------------------------


class TestSynthesizeRuleDispatch:
    def test_auto_mode_returns_regex_when_anchor_clean(self):
        result = synthesize_rule(
            positives=["forbidden_call(x)", "forbidden_call(y)"],
            negatives=["safe_call(x)"],
            language="python",
            rule_id="r1",
        )
        assert result.method == "regex"
        assert result.rule is not None

    def test_llm_mode_explicit_with_mock(self):
        def fake_llm(prompt: str) -> str:
            assert "python" in prompt.lower()
            return (
                "id: only-via-llm\n"
                "message: matched via LLM\n"
                "severity: medium\n"
                "category: security\n"
                "languages: [python]\n"
                "pattern: '\\bforbidden\\b'\n"
            )

        result = synthesize_rule(
            positives=["forbidden(x)", "wrap(forbidden)"],
            negatives=["safe()"],
            language="python",
            mode="llm",
            llm_caller=fake_llm,
        )
        assert result.method == "llm"
        assert result.rule is not None
        assert result.rule.id == "only-via-llm"

    def test_llm_mode_with_code_fences(self):
        """LLMs often wrap responses in ```yaml fences — strip them."""
        def fake_llm(prompt: str) -> str:
            return (
                "```yaml\n"
                "id: fenced\n"
                "message: hi\n"
                "severity: low\n"
                "category: style\n"
                "languages: [python]\n"
                "pattern: '\\bforbidden\\b'\n"
                "```\n"
            )

        result = synthesize_rule(
            positives=["forbidden(1)"],
            negatives=[],
            language="python",
            mode="llm",
            llm_caller=fake_llm,
        )
        assert result.method == "llm", result.diagnostics
        assert result.rule is not None

    def test_llm_mode_invalid_yaml_returns_none(self):
        def bad_llm(prompt: str) -> str:
            return "not yaml :::"

        result = synthesize_rule(
            positives=["x"], negatives=[],
            language="python", mode="llm", llm_caller=bad_llm,
        )
        assert result.rule is None
        assert any("yaml" in d.lower() or "parse" in d.lower() for d in result.diagnostics)

    def test_llm_mode_pattern_fails_validation(self):
        """LLM emits a syntactically-valid rule whose pattern misses the
        positive — synthesizer rejects it."""
        def lying_llm(prompt: str) -> str:
            return (
                "id: wrong\n"
                "message: x\n"
                "severity: low\n"
                "category: style\n"
                "languages: [python]\n"
                "pattern: '\\bnever-matches-anything-zzzqqq\\b'\n"
            )

        result = synthesize_rule(
            positives=["forbidden_call(1)"],
            negatives=[],
            language="python", mode="llm", llm_caller=lying_llm,
        )
        assert result.rule is None
        assert any("validation" in d for d in result.diagnostics)

    def test_llm_call_failure_propagates_as_diagnostic(self):
        def boom(prompt: str) -> str:
            raise RuntimeError("network gone")

        result = synthesize_rule(
            positives=["xy", "xz"],  # too short to anchor → forces LLM
            negatives=[],
            language="python", mode="auto", llm_caller=boom,
        )
        assert result.rule is None
        assert any("network gone" in d for d in result.diagnostics)

    def test_unknown_mode_returns_diagnostic(self):
        result = synthesize_rule(
            positives=["x"], negatives=[], language="python", mode="bogus",
        )
        assert result.rule is None
        assert any("unknown mode" in d for d in result.diagnostics)

    def test_default_llm_caller_missing_module_returns_clean_diagnostic(
        self, monkeypatch,
    ):
        """I3 — when the dev meta-harness LLM client is not importable,
        the synthesizer must surface a useful RuntimeError diagnostic
        instead of letting ModuleNotFoundError crash the MCP tool."""
        import sys

        # Make ``eval.meta_harness._llm_client`` un-importable for this test.
        for mod_name in list(sys.modules):
            if mod_name.startswith("eval.meta_harness"):
                monkeypatch.delitem(sys.modules, mod_name, raising=False)
        monkeypatch.setitem(sys.modules, "eval.meta_harness._llm_client", None)

        # Force the LLM path: positives too short for regex synthesis.
        result = synthesize_rule(
            positives=["xy", "xz"],
            negatives=[],
            language="python",
            mode="llm",  # explicit so we don't get the regex fallback
        )
        assert result.rule is None
        assert any(
            "llm_caller" in d.lower() or "meta-harness" in d.lower()
            for d in result.diagnostics
        ), result.diagnostics


# ---------------------------------------------------------------------------
# YAML rendering
# ---------------------------------------------------------------------------


class TestRenderRuleYaml:
    def test_includes_pattern_and_metadata(self):
        result = synthesize_rule(
            positives=["forbidden(a)", "forbidden(b)"],
            negatives=["safe(a)"],
            language="python",
            rule_id="no-forbidden-call",
            description="block forbidden use",
        )
        assert result.rule is not None
        yaml = render_rule_yaml(result.rule)
        assert "id: no-forbidden-call" in yaml
        assert "languages: [python]" in yaml
        assert "pattern:" in yaml
        assert "severity:" in yaml


# ---------------------------------------------------------------------------
# Code-fence helper
# ---------------------------------------------------------------------------


class TestStripCodeFences:
    def test_yaml_fence(self):
        text = "```yaml\nid: x\nmessage: y\n```\n"
        assert _strip_code_fences(text) == "id: x\nmessage: y"

    def test_no_fence_passthrough(self):
        assert _strip_code_fences("id: x\n") == "id: x"

    def test_partial_fence(self):
        # No closing fence — accept and just drop the opening line.
        text = "```\nid: x"
        assert _strip_code_fences(text) == "id: x"


# ---------------------------------------------------------------------------
# MCP tool wrapper
# ---------------------------------------------------------------------------


class TestMcpToolWrapper:
    def test_synthesize_rule_tool_returns_yaml_on_success(self):
        from attocode.code_intel.tools.rule_tools import synthesize_rule as tool

        out = tool(
            positive_samples=["forbidden(x)", "forbidden(y)"],
            negative_samples=["safe(x)"],
            language="python",
            rule_id="no-forbidden",
        )
        assert "synthesised via regex" in out or "synthesised via llm" in out
        assert "id: no-forbidden" in out
        assert "pattern:" in out

    def test_synthesize_rule_tool_returns_diagnostics_on_failure(self):
        from attocode.code_intel.tools.rule_tools import synthesize_rule as tool

        # No positives → guaranteed failure, no LLM key needed because the
        # regex path bails before invoking the LLM.
        out = tool(
            positive_samples=[],
            negative_samples=[],
            language="python",
            mode="regex",
        )
        assert "Synthesis failed" in out
        assert "positive" in out.lower()
