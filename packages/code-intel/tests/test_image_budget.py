"""Reject image growth and invalid comparisons using independent measured inputs."""
import json
import os
import sys

import pytest

from eval.quality.image_budget import Measurement, check_comparison, check_growth


def baseline():
    return {'schema_version': 1, 'image_size_bytes': 1000, 'allowed_growth_percent': 5,
            'source_commit': 'a' * 40, 'review': 'Measured passing same-runner runtime image comparison.'}


def test_image_growth_ceiling_accepts_boundary_and_rejects_one_byte_more():
    check_growth(1050, baseline())
    with pytest.raises(ValueError, match='image_growth'):
        check_growth(1051, baseline())


@pytest.mark.parametrize('size', [0, -1, True, 1000.5])
def test_invalid_measured_size_cannot_pass_growth_guard(size):
    with pytest.raises(ValueError):
        check_growth(size, baseline())


@pytest.mark.parametrize('missing', ['review', 'source_commit', 'image_size_bytes'])
def test_size_baseline_requires_reviewed_source_provenance(missing):
    record = baseline()
    record.pop(missing)
    with pytest.raises(ValueError):
        check_growth(1000, record)


def measured(size=1000):
    return {'size_bytes': size, 'identity': {'dependencies': [['example', '1.0']],
            'runtime_layers': ['sha256:base'], 'static_sha256': 'fixed'},
            'runtime_checks': {'health': True, 'dashboard': True, 'mcp_auth': True,
                               'navigation': True, 'cli': True, 'writable_state': True}}


def test_only_strictly_smaller_equivalent_passing_image_can_be_adopted():
    check_comparison(measured(), measured(999))
    with pytest.raises(ValueError, match='not_smaller'):
        check_comparison(measured(), measured())
    changed = measured(999)
    changed['identity']['dependencies'] = [['example', '2.0']]
    with pytest.raises(ValueError, match='identity'):
        check_comparison(measured(), changed)


def test_missing_or_failed_runtime_check_prevents_image_adoption():
    for missing in (True, False):
        changed = measured(999)
        if missing:
            changed['runtime_checks'].pop('cli')
        else:
            changed['runtime_checks']['cli'] = False
        with pytest.raises(ValueError, match='runtime'):
            check_comparison(measured(), changed)


def test_parent_cleanup_waits_for_automatic_removal_already_in_progress(tmp_path, monkeypatch):
    # A deterministic external CLI double replays Docker's observed async race.
    # Production cleanup, subprocess execution and flushed logs remain real.
    docker = tmp_path / 'docker'
    state = tmp_path / 'state.json'
    state.write_text('{"phase":"running","polls":0}')
    docker.write_text('#!' + sys.executable + '\n' + '''
import json,sys
from pathlib import Path
state=Path(__file__).with_name('state.json'); row=json.loads(state.read_text())
if sys.argv[1]=='ps':
    assert sys.argv[-1]=='label=attocode.quality.owner=owned-fixture'
    if row['phase']=='removing':
        row['polls']+=1
        if row['polls']>=2: row['phase']='gone'
    if row['phase']!='gone': print('012345abcdef')
    state.write_text(json.dumps(row))
elif sys.argv[1]=='rm':
    assert sys.argv[2:]==['--force','012345abcdef']
    row['phase']='removing'; state.write_text(json.dumps(row))
    print('Error response from daemon: removal of container 012345abcdef is already in progress')
    sys.exit(1)
else: sys.exit(42)
''')
    docker.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    result = Measurement(tmp_path).cleanup_owner('owned-fixture')
    assert result == {'owner': 'owned-fixture', 'verified': True}
    assert json.loads(state.read_bytes()) == {'phase': 'gone', 'polls': 2}
    assert 'already in progress' in (tmp_path / 'owned-fixture-cleanup-remove.log').read_text()
