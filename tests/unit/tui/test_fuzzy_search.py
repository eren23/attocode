"""Tests for fuzzy matching and repo overview search filtering."""

from __future__ import annotations

from attocode.tui.widgets.command_palette import fuzzy_match


class TestFuzzyMatch:
    """Tests for the fuzzy_match() function."""

    def test_empty_query_returns_1(self) -> None:
        assert fuzzy_match("", "anything") == 1.0

    def test_exact_match(self) -> None:
        score = fuzzy_match("agent.py", "agent.py")
        assert score > 0.8

    def test_substring_match_high_score(self) -> None:
        score = fuzzy_match("agent", "agent.py")
        assert score > 0.8

    def test_sequential_char_match(self) -> None:
        # "agpy" matches a-g-p-y in "agent.py" sequentially
        score = fuzzy_match("agpy", "agent.py")
        assert score > 0.0

    def test_no_match_returns_zero(self) -> None:
        assert fuzzy_match("xyz", "agent.py") == 0.0

    def test_case_insensitive(self) -> None:
        score = fuzzy_match("AGENT", "agent.py")
        assert score > 0.8

    def test_word_boundary_bonus(self) -> None:
        # "cp" should score higher on "command_palette" (word boundaries)
        # than on "accepting" (mid-word)
        boundary_score = fuzzy_match("cp", "command_palette")
        mid_score = fuzzy_match("cp", "accepting_pool")
        assert boundary_score > mid_score

    def test_consecutive_bonus(self) -> None:
        # "age" consecutive in "agent" should score higher than "aet" scattered
        consec_score = fuzzy_match("age", "agent")
        scatter_score = fuzzy_match("aet", "agent")
        assert consec_score > scatter_score

    def test_single_char_substring_high_score(self) -> None:
        # Single char "a" in "agent.py" hits substring branch
        score = fuzzy_match("a", "agent.py")
        assert score > 0.5

    def test_empty_text_returns_zero(self) -> None:
        assert fuzzy_match("a", "") == 0.0

    def test_path_separator_match(self) -> None:
        """Fuzzy match should work across path separators."""
        score = fuzzy_match("agent", "src/agent.py")
        assert score > 0.5

    def test_underscore_word_boundary(self) -> None:
        """Underscore-separated words should benefit from boundary bonuses."""
        score = fuzzy_match("ft", "fuzzy_threshold")
        assert score > 0.0


class TestBestMatchScore:
    """Tests for _best_match_score via the repo overview widget."""

    def test_path_match_without_symbols(self) -> None:
        """Score should come from path alone when no symbols available."""
        from attocode.tui.widgets.repo_overview import RepoOverviewWidget

        widget = RepoOverviewWidget()
        score = widget._best_match_score("src/agent.py", "agent", {})
        assert score > 0.5

    def test_symbol_match_beats_path(self) -> None:
        """A strong symbol match should produce higher score than weak path match."""
        from attocode.tui.widgets.repo_overview import RepoOverviewWidget

        widget = RepoOverviewWidget()
        symbol_map = {"src/utils.py": ["fuzzy_match", "CommandRegistry"]}
        score = widget._best_match_score("src/utils.py", "fuzzy_match", symbol_map)
        # "fuzzy_match" is an exact substring match on the symbol name
        assert score > 0.8

    def test_no_match_low_score(self) -> None:
        from attocode.tui.widgets.repo_overview import RepoOverviewWidget

        widget = RepoOverviewWidget()
        score = widget._best_match_score("src/utils.py", "zzzznothing", {"src/utils.py": ["foo"]})
        assert score < 0.3

    def test_symbol_map_with_unrelated_symbols(self) -> None:
        """When symbol_map has symbols that don't match, score comes from path."""
        from attocode.tui.widgets.repo_overview import RepoOverviewWidget

        widget = RepoOverviewWidget()
        symbol_map = {"src/utils.py": ["unrelated_func", "AnotherClass"]}
        path_only = widget._best_match_score("src/utils.py", "utils", {})
        with_symbols = widget._best_match_score("src/utils.py", "utils", symbol_map)
        # Score should be at least as good with symbols (path match dominates)
        assert with_symbols >= path_only


class TestSingleCharAutoExpand:
    """Verify single-char queries don't trigger auto-expand storm."""

    def test_single_char_scores_above_threshold(self) -> None:
        """Single chars hit substring branch, proving the guard is needed."""
        from attocode.tui.widgets.repo_overview import _FUZZY_THRESHOLD

        score = fuzzy_match("a", "agent.py")
        assert score >= _FUZZY_THRESHOLD, (
            "Single-char queries score above threshold, confirming "
            "the len(q) >= 2 guard in _rebuild_tree is necessary"
        )

    def test_two_char_query_scores_above_threshold(self) -> None:
        """Two-char queries should pass both the threshold and len guard."""
        from attocode.tui.widgets.repo_overview import _FUZZY_THRESHOLD

        score = fuzzy_match("ag", "agent.py")
        assert score >= _FUZZY_THRESHOLD


class TestTopLevelVarsInSymbolMap:
    """Verify that top_level_vars are included in fuzzy search."""

    def test_get_symbols_includes_top_level_vars(self) -> None:
        from attocode.integrations.context.codebase_ast import ClassDef, FileAST, FunctionDef

        ast = FileAST(
            path="test.py",
            language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=5)],
            classes=[ClassDef(name="Bar", start_line=6, end_line=10)],
            top_level_vars=["_FUZZY_THRESHOLD", "MAX_RETRIES"],
        )
        symbols = ast.get_symbols()
        assert "foo" in symbols
        assert "Bar" in symbols
        assert "_FUZZY_THRESHOLD" in symbols
        assert "MAX_RETRIES" in symbols

    def test_symbol_count_includes_top_level_vars(self) -> None:
        """symbol_count should be consistent with len(get_symbols())."""
        from attocode.integrations.context.codebase_ast import ClassDef, FileAST, FunctionDef

        ast = FileAST(
            path="test.py",
            language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=5)],
            classes=[ClassDef(name="Bar", start_line=6, end_line=10)],
            top_level_vars=["_FUZZY_THRESHOLD", "MAX_RETRIES"],
        )
        assert ast.symbol_count == len(ast.get_symbols())

    def test_constant_detection_regex_parser(self) -> None:
        """Verify regex parser captures underscore-prefixed uppercase constants."""
        from attocode.integrations.context.codebase_ast import parse_python

        code = """
_FUZZY_THRESHOLD = 0.3
MAX_RETRIES = 5
_TS_AVAILABLE = True
logger = logging.getLogger(__name__)
some_var = 42
"""
        ast = parse_python(code, "test.py")
        assert "_FUZZY_THRESHOLD" in ast.top_level_vars
        assert "MAX_RETRIES" in ast.top_level_vars
        assert "_TS_AVAILABLE" in ast.top_level_vars
        # Lowercase vars should NOT be captured
        assert "logger" not in ast.top_level_vars
        assert "some_var" not in ast.top_level_vars
