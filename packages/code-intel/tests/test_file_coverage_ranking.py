"""File-level evidence unions must not alter narrow search contracts."""
import pytest
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult
from attocode_intel.query_ranking import rerank_broad_candidates


def hit(path, text, score=1.0, name='unit'):
    return SemanticSearchResult(path, 'function', name, text, score, 1, 2)


@pytest.fixture(autouse=True)
def default_ranking(monkeypatch):
    monkeypatch.delenv('ATTOCODE_INTEL_BROAD_RERANK', raising=False)


def pool():
    return [hit('a.py', 'alpha', .9), hit('b.py', 'alpha', .8),
            hit('b.py', 'beta', .7), hit('c.py', 'transitions', .6)]


def test_file_union_promotes_the_original_representative_of_distributed_evidence():
    rows = pool()
    before = list(rows)
    ranked = rerank_broad_candidates('Where are alpha beta transitions?', rows, 3)
    assert ranked[0].file_path == 'b.py'
    assert ranked == [rows[1], rows[0], rows[3]]
    assert ranked[0] is rows[1] and ranked[0].score == .8
    assert rows == before


def test_prose_question_words_do_not_outvote_source_concepts():
    rows = [hit('a.py', 'they still have given part produced computed'),
            hit('b.py', 'alpha beta', .5)]
    ranked = rerank_broad_candidates('Where have they still computed alpha beta transitions?', rows, 2)
    assert ranked[0].file_path == 'b.py'
    assert ranked == [rows[1], rows[0]]


def test_repeated_windows_do_not_turn_one_concept_into_two():
    rows = [hit('a.py', 'gamma'), hit('b.py', 'alpha'),
            hit('b.py', 'alpha alpha alpha'), hit('c.py', 'beta')]
    assert rerank_broad_candidates('Where are alpha beta gamma transitions?', rows, 4) == [
        rows[0], rows[1], rows[3], rows[2]]


def test_promotion_preserves_first_twenty_four_files_scores_and_deep_prefix():
    rows = [hit(f'file{n}.py', 'alpha', 1 / (n + 1)) for n in range(24)]
    rows += [hit('outside.py', 'alpha beta transitions', .001), hit('file1.py', 'beta', .0001)]
    before = [(id(row), row.score) for row in rows]
    shallow = rerank_broad_candidates('Where are alpha beta transitions?', rows, 5)
    deep = rerank_broad_candidates('Where are alpha beta transitions?', rows, 26)
    assert shallow == deep[:5]
    assert {row.file_path for row in deep[:24]} == {f'file{n}.py' for n in range(24)}
    assert deep[24] is rows[24] and deep[25] is rows[25]
    assert [(id(row), row.score) for row in rows] == before
    assert all(any(row is original for original in rows) for row in deep)


@pytest.mark.parametrize('query,scope,consecutive', [
    ('AlphaBetaTransitions', '', False),
    ('alpha beta transitions', '', False),
    ('Where are alpha beta?', '', False),
    ('Where are alpha beta transitions?', '*.py', True),
    ('Where are alpha beta transitions tests?', '', True),
    ('Where are alpha beta transitions without unrelated modules?', '', False),
], ids=['exact', 'nonquestion', 'two_concepts', 'scope', 'test_intent', 'exclusion'])
def test_narrow_and_ambiguous_queries_keep_existing_order(query, scope, consecutive):
    rows = pool()
    expected = rows[:3] if consecutive else [rows[0], rows[1], rows[3]]
    assert rerank_broad_candidates(query, rows, 3, scope) == expected


def test_prose_files_cannot_supply_a_source_coverage_promotion():
    rows = [hit('a.py', 'gamma'), hit('README.md', 'alpha beta transitions'), hit('b.py', 'alpha')]
    assert rerank_broad_candidates('Where are alpha beta gamma transitions?', rows, 3) == rows


def test_equal_file_coverage_preserves_original_file_and_chunk_order():
    rows = [hit('a.py', 'alpha beta'), hit('a.py', 'transitions'), hit('b.py', 'alpha beta')]
    assert rerank_broad_candidates('Where are alpha beta transitions?', rows, 3) == [rows[0], rows[2], rows[1]]


def test_repeated_object_occurrences_survive_promoting_another_file():
    first = hit('a.py', 'alpha')
    rows = [first, hit('b.py', 'alpha beta'), first]
    ranked = rerank_broad_candidates('Where are alpha beta transitions?', rows, 3)
    assert ranked[0].file_path == 'b.py'
    assert len(ranked) == 3 and sum(row is first for row in ranked) == 2


@pytest.mark.parametrize('padding', ['padding ' * 150000, 'é' * 600000], ids=['ascii', 'utf8'])
def test_excessive_retained_evidence_keeps_existing_order(padding):
    rows = [hit('a.py', 'alpha'), hit('b.py', 'alpha beta ' + padding)]
    assert rerank_broad_candidates('Where are alpha beta transitions?', rows, 2) == rows
