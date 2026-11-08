"""Real subprocess controls for the nonpublishing Registry install probe."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_registry_install.py'
MISSING = 'No solution found when resolving tool dependencies\nBecause there is no version of attocode-code-intel==1.2.3 and you require it, requirements are unsatisfiable.\n'


def probe():
    assert SCRIPT.exists(), 'Registry install probe lacks bounded retry and isolation'
    spec = importlib.util.spec_from_file_location('registry_install_probe', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_uvx(tmp_path, outcomes, pause=0):
    executable = tmp_path / 'uvx'
    state = tmp_path / 'calls.json'
    executable.write_text(f'''#!{sys.executable}
import json,os,sys,time
from pathlib import Path
p=Path({str(state)!r})
calls=json.loads(p.read_text()) if p.exists() else []
position=len(calls)
calls.append({{'argv':sys.argv[1:],'cwd':os.getcwd(),'keys':sorted(os.environ),
              'cache':os.environ.get('UV_CACHE_DIR'),'home':os.environ.get('HOME'),
              'tools':os.environ.get('UV_TOOL_DIR')}})
p.write_text(json.dumps(calls))
time.sleep({pause!r})
outcomes={outcomes!r}
code,out,err=outcomes[min(position,len(outcomes)-1)]
sys.stdout.write(out);sys.stderr.write(err)
raise SystemExit(code)
''')
    executable.chmod(0o755)
    return executable, state


def test_transient_resolution_retries_in_owned_environment(tmp_path, monkeypatch):
    uvx, state = fake_uvx(tmp_path, [(1, '', MISSING), (0, 'attocode-code-intel 1.2.3\n', '')])
    monkeypatch.setenv('UV_INDEX_URL', 'https://unexpected.invalid')
    monkeypatch.setenv('PYTHONPATH', '/wrong/source')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'remote')
    result = probe().probe_install('1.2.3', uvx=str(uvx), attempts=3, seconds=5, delay=0)
    assert result['status'] == 'passed' and len(result['attempts']) == 2
    assert result['attempts'][0]['reason'] == 'version_unavailable'
    assert result['owned_scratch_removed']
    calls = json.loads(state.read_text())
    assert len(calls) == 2
    for call in calls:
        assert 'UV_INDEX_URL' not in call['keys'] and 'PYTHONPATH' not in call['keys']
        assert 'ATTOCODE_INTEL_RANKING_PROVIDER' not in call['keys']
        assert '--python' in call['argv'] and '--from' in call['argv']
        assert 'attocode-code-intel==1.2.3' in call['argv']
        for name in ['cache', 'home', 'tools', 'cwd']:
            assert call[name] and not Path(call[name]).exists(), 'Owned probe state was retained'


@pytest.mark.parametrize('code,out,err,reason', [
    (0, 'attocode-code-intel 1.2.2\n', '', 'unexpected_version'),
    (1, '', 'Certificate verification failed', 'install_failed'),
    (1, '', MISSING.replace('1.2.3', '1.2.30'), 'install_failed'),
])
def test_permanent_failures_are_not_retried(tmp_path, code, out, err, reason):
    uvx, state = fake_uvx(tmp_path, [(code, out, err)])
    result = probe().probe_install('1.2.3', uvx=str(uvx), attempts=3, seconds=5, delay=0)
    assert result['status'] == 'failed' and result['reason'] == reason
    assert len(json.loads(state.read_text())) == 1
    assert result['owned_scratch_removed']


def test_missing_version_exhausts_attempt_budget(tmp_path):
    uvx, state = fake_uvx(tmp_path, [(1, '', MISSING)])
    result = probe().probe_install('1.2.3', uvx=str(uvx), attempts=3, seconds=5, delay=0)
    assert result['status'] == 'failed' and result['reason'] == 'attempts_exhausted'
    assert len(result['attempts']) == len(json.loads(state.read_text())) == 3
    assert result['owned_scratch_removed']


def test_shared_deadline_terminates_owned_process(tmp_path):
    uvx, state = fake_uvx(tmp_path, [(0, 'attocode-code-intel 1.2.3\n', '')], pause=2)
    result = probe().probe_install('1.2.3', uvx=str(uvx), attempts=3, seconds=.2, delay=0)
    assert result['status'] == 'failed' and result['reason'] == 'deadline_exceeded'
    assert len(result['attempts']) == 1
    assert result['owned_scratch_removed']
    if state.exists():
        assert len(json.loads(state.read_text())) <= 1


def test_process_creation_time_does_not_grant_a_new_wait_budget(tmp_path, monkeypatch):
    uvx, _ = fake_uvx(tmp_path, [(0, 'attocode-code-intel 1.2.3\n', '')])
    module = probe()
    launch = module.subprocess.Popen
    def delayed_launch(*args, **kwargs):
        # OS process creation cannot be preempted, but its time must consume the
        # existing budget instead of granting a fresh communicate() allowance.
        time.sleep(1.1)
        return launch(*args, **kwargs)
    monkeypatch.setattr(module.subprocess, 'Popen', delayed_launch)
    result = module.probe_install('1.2.3', uvx=str(uvx), attempts=3, seconds=1, delay=0)
    assert result['status'] == 'failed' and result['reason'] == 'deadline_exceeded'
    assert len(result['attempts']) == 1 and result['seconds'] >= 1
    assert result['owned_scratch_removed']


@pytest.mark.parametrize('option,value', [('attempts', 9), ('seconds', 301)])
def test_documented_limits_are_hard_ceilings(tmp_path, monkeypatch, option, value):
    uvx, state = fake_uvx(tmp_path, [(0, 'attocode-code-intel 1.2.3\n', '')])
    module = probe()
    with pytest.raises(ValueError):
        module.probe_install('1.2.3', uvx=str(uvx), **{option: value})
    assert not state.exists()
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    assert module.main(['--version', '1.2.3', '--report', str(tmp_path / 'limits.json'),
                        '--allow-downloads', '--' + option, str(value)]) == 1
    assert not state.exists(), 'Rejected CLI budgets still launched an installer'


def test_documented_maximum_budget_is_accepted(tmp_path):
    uvx, _ = fake_uvx(tmp_path, [(0, 'attocode-code-intel 1.2.3\n', '')])
    result = probe().probe_install('1.2.3', uvx=str(uvx), attempts=8, seconds=300, delay=0)
    assert result['status'] == 'passed' and result['owned_scratch_removed']


@pytest.mark.parametrize('option,value', [('attempts', 0), ('seconds', 0),
                                         ('seconds', float('nan')), ('delay', -1)])
def test_invalid_budgets_are_rejected_before_launch(option, value):
    with pytest.raises(ValueError):
        probe().probe_install('1.2.3', **{option: value})


def test_report_is_durable_and_never_overwritten(tmp_path, monkeypatch):
    _, state = fake_uvx(tmp_path, [(1, '', MISSING), (0, 'attocode-code-intel 1.2.3\n', '')])
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    module = probe()
    path = tmp_path / 'report.json'
    arguments = ['--version', '1.2.3', '--report', str(path), '--allow-downloads',
                 '--attempts', '3', '--seconds', '5', '--delay', '0']
    assert module.main(arguments) == 0
    raw = path.read_bytes()
    assert json.loads(raw)['attempts'][0]['stderr'] == MISSING
    assert module.main(arguments) == 1 and path.read_bytes() == raw
    assert len(json.loads(state.read_text())) == 2
