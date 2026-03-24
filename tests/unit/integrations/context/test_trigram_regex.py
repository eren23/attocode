"""Tests for trigram regex extraction."""

from __future__ import annotations

import zlib

from attocode.integrations.context.trigram_regex import (
    extract_required_trigrams,
    longest_literal_run,
)


def _hash(s: str) -> int:
    """Compute the CRC32 trigram hash for a 3-char string."""
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# extract_required_trigrams
# ---------------------------------------------------------------------------
class TestExtractRequiredTrigrams:
    def test_simple_literal(self) -> None:
        hashes = extract_required_trigrams("grep_search")
        assert len(hashes) > 0
        # "gre" should be one of the trigrams
        assert _hash("gre") in hashes

    def test_wildcard_returns_empty(self) -> None:
        assert extract_required_trigrams(".*") == []

    def test_dot_star_middle(self) -> None:
        hashes = extract_required_trigrams("parse.*Config")
        # Should have trigrams from both "parse" and "Config"
        assert _hash("par") in hashes
        assert _hash("Con") in hashes

    def test_short_pattern(self) -> None:
        # "ab" is too short for any trigram
        assert extract_required_trigrams("ab") == []

    def test_exactly_three_chars(self) -> None:
        hashes = extract_required_trigrams("abc")
        assert len(hashes) == 1
        assert _hash("abc") in hashes

    def test_character_class(self) -> None:
        # [abc]def -> only "def" is a guaranteed literal run
        hashes = extract_required_trigrams("[abc]defgh")
        assert _hash("def") in hashes
        # "abc" should NOT be in hashes (it's a character class)
        assert _hash("abc") not in hashes

    def test_alternation_no_common(self) -> None:
        # foo|bar -> no common prefix >= 3 chars
        assert extract_required_trigrams("foo|bar") == []

    def test_group(self) -> None:
        hashes = extract_required_trigrams("(hello)world")
        assert _hash("hel") in hashes
        assert _hash("wor") in hashes

    def test_quantifier_min_zero(self) -> None:
        # x? means x may not appear, so "x" doesn't contribute
        hashes = extract_required_trigrams("x?hello")
        assert _hash("hel") in hashes

    def test_quantifier_min_one(self) -> None:
        # x+ means x appears at least once
        hashes = extract_required_trigrams("hello+world")
        assert _hash("hel") in hashes

    def test_case_insensitive(self) -> None:
        hashes = extract_required_trigrams("Hello", case_insensitive=True)
        assert _hash("hel") in hashes
        # "Hel" should NOT be present (lowercased)
        assert _hash("Hel") not in hashes

    def test_invalid_regex(self) -> None:
        assert extract_required_trigrams("(?P<unclosed") == []

    def test_anchor_ignored(self) -> None:
        hashes_with = extract_required_trigrams("^hello$")
        hashes_without = extract_required_trigrams("hello")
        assert set(hashes_with) == set(hashes_without)

    def test_returns_deduplicated(self) -> None:
        hashes = extract_required_trigrams("aaaaaa")
        # "aaa" appears 4 times but should be deduplicated
        assert hashes.count(_hash("aaa")) <= 1

    def test_dot_pattern(self) -> None:
        # Single dot matches any char -> breaks literal run
        hashes = extract_required_trigrams("hel.o_world")
        # "hel" is too short? No: "hel" is only 3 chars -> 1 trigram
        # But the dot breaks the run, so we get nothing >= 3 from "hel"
        # Actually "hel" is exactly 3 chars -> 1 trigram
        # The dot breaks it, so we have "hel" (nope, only 3 chars before dot)
        # Let's check: "hel" before dot -> 3 chars -> 1 trigram
        # Actually the sre_parse will see LITERAL h, LITERAL e, LITERAL l, ANY .
        # So we get "hel" as a run of 3 -> yields 1 trigram
        # And "o_world" after dot -> "o_w", "wor", "orl", "rld" -> 5 chars, multiple trigrams
        # Wait, after the dot: "o_world" -> 7 chars -> 5 trigrams
        assert len(hashes) > 0


# ---------------------------------------------------------------------------
# longest_literal_run
# ---------------------------------------------------------------------------
class TestLongestLiteralRun:
    def test_simple(self) -> None:
        assert longest_literal_run("def hello") == "def hello"

    def test_split(self) -> None:
        result = longest_literal_run("foo.*bar")
        assert result in ("foo", "bar")

    def test_empty(self) -> None:
        assert longest_literal_run(".*") == ""

    def test_longer_wins(self) -> None:
        result = longest_literal_run("ab.*longer_string")
        assert result == "longer_string"

    def test_invalid_pattern(self) -> None:
        assert longest_literal_run("(?P<bad") == ""
