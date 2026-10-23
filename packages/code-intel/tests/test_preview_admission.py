"""Actual durable captures must substantiate the preview summaries."""
import hashlib
import json
import os
import zlib

import pytest

from eval.quality.experiment_evidence import Journal, encode
from eval.quality.fixture_identity import pinned_manifest, source_manifest
from eval.quality.preview_experiment import admit_worker


@pytest.mark.parametrize('change', ['edit', 'add', 'remove', 'link'])
def test_unlabelled_fixture_drift_cannot_hide_behind_stable_label_files(tmp_path, change):
    root = tmp_path / 'work'
    root.mkdir()
    (root / 'label.py').write_bytes(b'alpha\n')
    (root / 'other.py').write_bytes(b'beta\n')
    (root / 'alias.py').symlink_to('other.py')
    before = source_manifest(root)
    state = root / '.attocode'
    state.mkdir()
    (state / 'index.db').write_bytes(b'runtime')
    assert source_manifest(root) == before
    if change == 'edit':
        (root / 'other.py').write_bytes(b'gamma\n')
    elif change == 'add':
        (root / 'extra.py').write_bytes(b'delta\n')
    elif change == 'remove':
        (root / 'other.py').unlink()
    else:
        (root / 'alias.py').unlink()
        (root / 'alias.py').symlink_to('label.py')
    assert source_manifest(root) != before


def test_actual_inventory_matches_committed_blobs_and_link_targets(tmp_path):
    cache, root = tmp_path / 'cache', tmp_path / 'work'
    root.mkdir()
    entries = []
    for name, mode, body in [('test.py', '100644', b'alpha\n'), ('alias.py', '120000', b'test.py')]:
        oid = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        blob = cache / 'blobs' / oid[:2] / oid[2:]
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(zlib.compress(body))
        entries.append([name, mode, oid, len(body)])
        if mode == '120000':
            (root / name).symlink_to(os.fsdecode(body))
        else:
            (root / name).write_bytes(body)
    assert source_manifest(root) == pinned_manifest(cache, {'entries': entries})


def capture(tmp_path, *, alias=False):
    root, evidence = tmp_path / 'work', tmp_path / 'evidence'
    root.mkdir()
    (root / 'test.py').write_bytes(b'alpha\n')
    selected = 'alias.py' if alias else 'test.py'
    if alias:
        (root / 'alias.py').symlink_to('test.py')
    spec = {'id': 'toy', 'questions': [{'id': 'q', 'query': 'alpha', 'kind': 'behavior',
            'split': 'development', 'file': selected, 'anchors': [{'line': 1, 'quote': 'alpha'}]}]}
    design = {'rounds': [['baseline', 'candidate']], 'requests': {'depths': [5], 'budgets': [2000],
              'scoped_depth': 5, 'scoped_budget': 2000}}
    journal = Journal(evidence / 'journal', 128 * 1024)
    journal.response({'event': 'fixture_pinned'}, source_manifest(root))
    fixture_ref = journal.response({'event': 'fixture_before'}, source_manifest(root))
    from eval.quality.preview_experiment import page_identity
    pages = []
    for arm in design['rounds'][0]:
        for scope in ('', selected):
            hit = {'file_path': selected, 'name': 'alpha', 'chunk_type': 'function', 'score': 1,
                   'line': 1, 'end_line': 1, 'snippet_start_line': 1, 'snippet_end_line': 1, 'snippet': 'alpha'}
            identity = [selected, 'alpha', 'function', 1, 1]
            policy = {'producer': 'body_index', 'errors': 'replace', 'newlines': 'universal',
                      'source_sha256': hashlib.sha256(b'alpha\n').hexdigest()}
            journal.response({'event': 'source_lineage', 'identity': identity}, policy)
            args = {'query': 'alpha', 'top_k': 5, 'max_tokens': 2000, 'file_filter': scope}
            page = {'data': {'results': [hit], 'ranking': {'index': {'status': 'ready', 'warmup_stage': 'ready'}}}}
            raw = {'content': [{'type': 'text', 'text': json.dumps(page)}], 'isError': False}
            ref = journal.response({'event': 'mcp_response', 'tool': 'semantic_search', 'arguments': args}, raw)
            row = {'round': 0, 'arm': arm, 'question': 'q', 'kind': 'behavior', 'split': 'development',
                   'arguments': args, 'response_ref': ref, 'milliseconds': 1, 'identity': page_identity(page),
                   'data_sha256': hashlib.sha256(encode(page['data'])).hexdigest(),
                   'judgment': {'file': True, 'visible': True}}
            journal.response({'event': 'validated_page'}, row)
            pages.append(row)
    journal.response({'event': 'gateway_close'}, {'status': 'complete'})
    journal.response({'event': 'fixture_after'}, source_manifest(root))
    observation = {'status': 'complete', 'pack': 'toy', 'pages': pages, 'fixture_ref': fixture_ref}
    return root, evidence, spec, design, observation


def test_valid_capture_replays_from_raw_response_and_source(tmp_path):
    root, evidence, spec, design, observation = capture(tmp_path)
    assert admit_worker(evidence, root, spec, design, observation) == observation


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'rebound', 'judgment', 'identity', 'data_hash', 'request'])
def test_raw_capture_damage_is_incomplete_before_next_worker(tmp_path, damage):
    root, evidence, spec, design, observation = capture(tmp_path)
    row = observation['pages'][0]
    blob = evidence / 'journal' / row['response_ref']['path']
    if damage == 'missing':
        blob.unlink()
    elif damage == 'corrupt':
        blob.write_bytes(blob.read_bytes() + b' ')
    elif damage == 'rebound':
        row['response_ref'] = {'path': 'blobs/' + '0' * 64 + '.json', 'sha256': '0' * 64, 'bytes': 1}
    elif damage == 'judgment':
        row['judgment']['visible'] = False
    elif damage == 'identity':
        row['identity'] = []
    elif damage == 'data_hash':
        row['data_sha256'] = '0' * 64
    else:
        row['arguments']['query'] = 'beta'
    with pytest.raises((ValueError, FileNotFoundError)):
        admit_worker(evidence, root, spec, design, observation)


def test_source_alias_hash_is_checked_against_its_pinned_target(tmp_path):
    root, evidence, spec, design, observation = capture(tmp_path, alias=True)
    assert admit_worker(evidence, root, spec, design, observation) == observation
