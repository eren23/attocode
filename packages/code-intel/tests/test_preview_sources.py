"""Real source bytes and provider calls must survive encoding and metadata cases."""
import copy

import pytest
from attocode_intel import gateway as gateway_module
from attocode_intel import search_evidence
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult

from eval.quality.experiment_evidence import Journal
from eval.quality.preview_sources import SourceTracker, source_spans


def hit(snippet, first=1, last=2):
    return {'file_path': 'target.py', 'name': 'target.py', 'chunk_type': 'file', 'score': 1.0,
            'line': 1, 'end_line': 2, 'snippet': snippet,
            'snippet_start_line': first, 'snippet_end_line': last}


@pytest.mark.parametrize('raw,snippet,policy', [
    (b'alpha\r\n\xff beta\r\n', 'alpha\n\ufffd beta\n',
     {'producer': 'body_index', 'errors': 'replace', 'newlines': 'universal'}),
    (b'alpha\r\nbeta\r\n', 'alpha\r\nbeta\r\n',
     {'producer': 'hydrated_metadata', 'errors': 'strict', 'newlines': 'raw'}),
    (b'alpha\r\n\xff beta\r\n', 'alpha\r\n\ufffd beta\r\n',
     {'producer': 'exact_scoped_source', 'errors': 'replace', 'newlines': 'raw'}),
])
def test_source_span_validation_uses_declared_producer_policy(tmp_path, raw, snippet, policy):
    (tmp_path / 'target.py').write_bytes(raw)
    result = source_spans({'data': {'results': [hit(snippet)]}}, tmp_path, [policy])
    assert result[0]['kind'] == 'source'
    assert result[0]['spans'] == [(0, len(snippet))]


def test_metadata_text_has_no_claimed_source_span_even_without_source_file(tmp_path):
    row = hit('class Metadata', None, None)
    row.update(line=None, end_line=None)
    result = source_spans({'data': {'results': [row]}}, tmp_path, [{'producer': 'metadata'}])
    assert result[0]['kind'] == 'metadata_only' and result[0]['spans'] == []
    assert not (tmp_path / 'target.py').exists()


@pytest.mark.parametrize('changes', [
    {'snippet_start_line': 0},
    {'snippet': 'alpha\nlast\n'},
    {'snippet_start_line': True},
])
def test_invalid_source_or_coordinate_cannot_become_an_excerpt(tmp_path, changes):
    (tmp_path / 'target.py').write_text('alpha\nbeta\nlast\n')
    row = hit('alpha\nbeta\n')
    row.update(changes)
    with pytest.raises(ValueError):
        source_spans({'data': {'results': [row]}}, tmp_path,
                     [{'producer': 'body_index', 'errors': 'replace', 'newlines': 'universal'}])


@pytest.mark.parametrize('producer', ['body_index', 'hydrated_metadata', 'exact_scoped_source', 'metadata'])
def test_passive_provider_tracking_preserves_results_and_source_lineage(tmp_path, producer):
    raw = b'alpha\r\n\xff beta\r\n' if producer in {'body_index', 'exact_scoped_source', 'metadata'} else b'alpha\r\nbeta\r\n'
    (tmp_path / 'target.py').write_bytes(raw)
    candidate = SemanticSearchResult(file_path='target.py', chunk_type='file', name='target.py',
                                     score=1.0, text='class Metadata')
    if producer == 'body_index':
        candidate.start_line, candidate.end_line = 1, 2
        candidate.text = 'target.py:1-2\nalpha\n\ufffd beta\n'
    original = copy.deepcopy(candidate)
    journal = Journal(tmp_path / 'evidence', 64 * 1024)
    tracker = SourceTracker(tmp_path, journal)
    with tracker.capture():
        if producer == 'exact_scoped_source':
            selected = search_evidence.exact_scoped_source(str(tmp_path), 'alpha', 'target.py', {'target.py'})
        else:
            selected = gateway_module.hydrate_selected_sources(str(tmp_path), [candidate])[0]
    # Evaluate the same real provider without instrumentation for equivalence.
    plain = (search_evidence.exact_scoped_source(str(tmp_path), 'alpha', 'target.py', {'target.py'})
             if producer == 'exact_scoped_source' else
             gateway_module.hydrate_selected_sources(str(tmp_path), [original])[0])
    assert selected == plain
    row = {'file_path': selected.file_path, 'name': selected.name, 'chunk_type': selected.chunk_type,
           'score': selected.score, 'line': selected.start_line or None, 'end_line': selected.end_line or None,
           **search_evidence.search_snippet(selected, 'alpha beta', 320)}
    page = {'data': {'results': [row]}}
    policies = tracker.policies(page)
    assert policies[0]['producer'] == producer
    validated = source_spans(page, tmp_path, policies)
    assert validated[0]['kind'] == ('metadata_only' if producer == 'metadata' else 'source')
    assert (tmp_path / 'evidence/events.jsonl').read_bytes()
