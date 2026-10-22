"""Evidence must survive validation failures and obey the producing source policy."""
import json
import subprocess
import sys

import pytest

from eval.quality.experiment_evidence import Journal, assert_engine, read_source, validate_excerpt


def test_response_is_durable_before_validator_raises_and_blob_is_not_duplicated(tmp_path):
    journal = Journal(tmp_path, max_bytes=65536)
    response = {'results': [{'snippet': 'actual response', 'start_line': 999}]}
    ref = journal.response('request-1', response)
    with pytest.raises(ValueError, match='coordinates'):
        validate_excerpt('source\n', 'actual response', 999, 999)
    assert json.loads((tmp_path / ref['path']).read_bytes()) == response
    again = journal.response('request-2', response)
    assert again['path'] == ref['path']
    rows = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
    assert [row['request'] for row in rows] == ['request-1', 'request-2']
    assert len(list((tmp_path / 'blobs').iterdir())) == 1


def test_oversized_response_preserves_prior_evidence_and_refuses_partial_blob(tmp_path):
    journal = Journal(tmp_path, max_bytes=2048)
    ref = journal.response('first', {'ok': True})
    with pytest.raises(RuntimeError, match='evidence_budget'):
        journal.response('oversize', {'body': 'x' * 4096})
    assert json.loads((tmp_path / ref['path']).read_bytes()) == {'ok': True}
    assert len(list((tmp_path / 'blobs').iterdir())) == 1
    assert len((tmp_path / 'events.jsonl').read_text().splitlines()) == 1


def test_exclusive_journal_refuses_to_adopt_previous_attempt(tmp_path):
    Journal(tmp_path, max_bytes=4096).response('old', {'preserve': True})
    with pytest.raises((FileExistsError, ValueError)):
        Journal(tmp_path, max_bytes=4096)


@pytest.mark.parametrize('policy,want', [('strict', None), ('replace', 'alpha\n\ufffdbeta\n')])
def test_source_decoding_and_universal_newlines_match_producer(tmp_path, policy, want):
    path = tmp_path / 'source'
    path.write_bytes(b'alpha\r\n\xffbeta\r\n')
    if want is None:
        with pytest.raises(UnicodeDecodeError):
            read_source(path, errors=policy, newlines='universal')
    else:
        assert read_source(path, errors=policy, newlines='universal') == want
        validate_excerpt(want, '\ufffdbeta', 2, 2)
    assert read_source(path, errors='replace', newlines='raw') == 'alpha\r\n\ufffdbeta\r\n'


def test_metadata_only_is_explicit_and_does_not_claim_source_evidence():
    assert validate_excerpt(None, '', None, None) == {'kind': 'metadata_only'}
    with pytest.raises(ValueError, match='source'):
        validate_excerpt(None, 'invented', 1, 1)


@pytest.mark.parametrize('snippet,start,end', [('beta', 1, 1), ('alpha\ngamma', 1, 3),
                                             ('alpha', 0, 1), ('alpha', True, 1),
                                             ('alpha', 1, 99)])
def test_wrong_coordinates_and_noncontiguous_source_are_rejected(snippet, start, end):
    with pytest.raises(ValueError):
        validate_excerpt('alpha\nbeta\ngamma\n', snippet, start, end)


def test_long_single_line_partial_excerpt_retains_real_line_coordinates():
    assert validate_excerpt('header\n' + 'x' * 10000 + 'needle\n', 'xxxneedle', 2, 2) == {
        'kind': 'source', 'start_line': 2, 'end_line': 2}


def test_wrong_engine_origin_is_rejected_in_fresh_subprocess(tmp_path):
    fake = tmp_path / 'attocode_intel'
    fake.mkdir()
    (fake / '__init__.py').write_text('')
    script = ('import sys; sys.path.insert(0,sys.argv[1]); '
              'from eval.quality.experiment_evidence import assert_engine; '
              'assert_engine(sys.argv[2])')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), '/wrong/engine'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'engine_origin' in result.stderr
