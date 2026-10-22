"""Evidence must survive validation failures and obey the producing source policy."""
import json
import subprocess
import sys
import time

import pytest

from eval.quality.experiment_evidence import Journal, read_source, validate_excerpt
from eval.quality.runner import GIB, environment, managed_root, supervise


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


def test_malformed_source_response_is_retained_before_rejection(tmp_path):
    journal = Journal(tmp_path, max_bytes=4096)
    ref = journal.response('malformed', ['not an object'])
    with pytest.raises(ValueError, match='snippet'):
        validate_excerpt('alpha\n', ['alpha'], 1, 1)
    assert json.loads((tmp_path / ref['path']).read_bytes()) == ['not an object']


def test_experiment_memory_ceiling_includes_supervising_controller(tmp_path):
    root = managed_root(tmp_path / 'managed')
    row = supervise([sys.executable, '-c', 'import time; time.sleep(10)'],
                    cwd=tmp_path, env=environment(root), root=root, log=root / 'log',
                    deadline=time.monotonic() + 5, max_bytes=GIB, max_rss=1,
                    include_controller=True)
    assert row['reason'] == 'memory_budget' and row['cleanup_verified']
    assert row['peak_rss_bytes'] > 1


def test_evidence_ceiling_stops_worker_without_deleting_retained_response(tmp_path):
    root = managed_root(tmp_path / 'managed')
    evidence = root / 'evidence'
    evidence.mkdir()
    (evidence / 'retained').write_text('keep this observation')
    script = ('import pathlib,sys,time; '
              "pathlib.Path(sys.argv[1]).write_bytes(b'x'*65536); time.sleep(10)")
    row = supervise([sys.executable, '-c', script, str(evidence / 'large')],
                    cwd=tmp_path, env=environment(root), root=root, log=root / 'log',
                    deadline=time.monotonic() + 5, max_bytes=GIB,
                    evidence_root=evidence, max_evidence_bytes=32768)
    assert row['reason'] == 'evidence_budget' and row['cleanup_verified']
    assert (evidence / 'retained').read_text() == 'keep this observation'


@pytest.mark.parametrize('changed', ['eval/matrix/run.py', 'pyproject.toml'])
def test_dirty_transitive_operator_or_workspace_configuration_refuses_admission(tmp_path, monkeypatch, changed):
    from eval.quality import experiments

    for name, body in {'eval/quality/experiments/preflight.json': '{}',
                       'eval/matrix/run.py': 'value = 1\n',
                       'pyproject.toml': '[project]\nname = "fixture"\n'}.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    for args in [('init', '-q'), ('add', '.'), ('commit', '-qm', 'synthetic committed inputs')]:
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false',
                        '-c', 'user.name=Harness test', '-c', 'user.email=harness@example.invalid',
                        *args], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(experiments, 'REPO', tmp_path)
    design = tmp_path / 'eval/quality/experiments/preflight.json'
    assert experiments.identity(design)['files']
    with (tmp_path / changed).open('a') as stream:
        stream.write('\n# dirty dependency\n')
    with pytest.raises(subprocess.CalledProcessError):
        experiments.identity(design)
