"""Whole query constructs expand; existing source scopes remain supported."""
import pytest
from attocode_intel._internal.integrations.context.semantic_search import _expand_query
from attocode_intel.focused_evidence import task_terms


@pytest.mark.parametrize("query,negative", [
    ("bootstrap without swarm", {"swarm"}),
    ("bootstrap without unrelated swarm modules", {"swarm", "module"}),
    ("cleanup upload without cache", {"cache"}),
    ("bootstrap excluding examples", {"example"}),
    ("Exclude examples from bootstrap", {"example"}),
])
def test_explicit_scopes_still_downrank(query, negative):
    positive, excluded = task_terms(query)
    assert negative <= excluded
    assert not negative & positive


@pytest.mark.parametrize("word", ["latest", "contest", "testimony", "configuration", "capital", "author"])
def test_construct_expansion_does_not_match_substrings(word):
    assert _expand_query(word) == word


def test_whole_construct_words_and_plurals_still_expand():
    assert "settings" in _expand_query("config parser")
    assert "expect" in _expand_query("tests for routing")
    assert "login" in _expand_query("auth middleware")
    assert "test" in _expand_query("test")
