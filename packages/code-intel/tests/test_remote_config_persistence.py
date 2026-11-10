"""Owned POSIX filesystem witnesses for remote-settings publication failures."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import tomllib

import pytest
from attocode_intel.config import RemoteConfig, load_remote_config, save_remote_config

OLD = (b'title = "keep"\n[perl]\nmodule_roots = ["dist/Carp/lib"]\n'
       b'[remote]\nserver = "https://old.invalid"\ntoken = "authored-fake-old"\n')


def _remote():
    return RemoteConfig(server='https://new.invalid', token='authored-fake-new',
                        repo_id='authored-repo', branch_auto_detect=False)


def _previous(project):
    path = project / '.attocode/config.toml'
    path.parent.mkdir(parents=True)
    path.write_bytes(OLD)
    return path


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(autouse=True)
def _synthetic_only(monkeypatch, record_property):
    for name in ['ATTOCODE_REMOTE_URL', 'ATTOCODE_REMOTE_TOKEN', 'ATTOCODE_REMOTE_REPO_ID']:
        monkeypatch.delenv(name, raising=False)
    record_property('credential_origin', 'authored-fake-only')


def test_failed_write_preserves_previous_config(tmp_path, record_property):
    """An actual EFBIG after partial data must not truncate the live config."""
    path = _previous(tmp_path)
    child = '''
import errno, hashlib, json, resource, signal, sys
from pathlib import Path
from attocode_intel.config import RemoteConfig, save_remote_config
project = Path(sys.argv[1])
path = project / '.attocode/config.toml'
before = path.read_bytes()
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (64, 64))
error = None
try:
    save_remote_config(str(project), RemoteConfig(server='https://new.invalid',
        token='authored-fake-' + 'x' * 4096, repo_id='authored-repo'))
except OSError as exc:
    error = exc.errno
after = path.read_bytes()
print(json.dumps({'errno': error, 'limit': resource.getrlimit(resource.RLIMIT_FSIZE)[0],
    'before_sha256': hashlib.sha256(before).hexdigest(),
    'after_sha256': hashlib.sha256(after).hexdigest(), 'after_bytes': len(after),
    'previous_preserved': before == after,
    'files': sorted(p.name for p in path.parent.iterdir())}))
'''
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(p) for p in sys.path if p))
    run = subprocess.run([sys.executable, '-c', child, str(tmp_path)], env=env,
                         capture_output=True, text=True, timeout=15, check=True)
    proof = json.loads(run.stdout)
    assert proof['errno'] == errno.EFBIG and proof['limit'] == 64
    assert proof['before_sha256'] == _sha(OLD)
    assert path.read_bytes() and proof['after_sha256'] == _sha(path.read_bytes())
    record_property('qualified_input', 'true')
    record_property('actual_filesystem_fault', 'EFBIG')
    record_property('child_exit_code', str(run.returncode))
    record_property('filesystem_receipt', json.dumps(proof))
    assert proof['previous_preserved'], 'REGRESSION: failed settings write truncates previous valid config'
    assert proof['files'] == ['config.toml']
    assert load_remote_config(str(tmp_path)).token == 'authored-fake-old'


@pytest.mark.parametrize('kind', ['directory', 'file', 'dangling-file'])
def test_save_rejects_symlink_destination(tmp_path, record_property, kind):
    project = tmp_path / 'project'
    outside = tmp_path / 'outside'
    project.mkdir()
    outside.mkdir()
    target = outside / 'config.toml'
    if kind != 'dangling-file':
        target.write_bytes(OLD)
    if kind == 'directory':
        link = project / '.attocode'
        link.symlink_to(outside, target_is_directory=True)
    else:
        (project / '.attocode').mkdir()
        link = project / '.attocode/config.toml'
        link.symlink_to(target)
    assert link.is_symlink() and link.resolve().is_relative_to(outside)
    before = target.read_bytes() if target.exists() else None
    rejected = False
    try:
        save_remote_config(str(project), _remote())
    except (OSError, ValueError):
        rejected = True
    after = target.read_bytes() if target.exists() else None
    record_property('qualified_input', 'true')
    record_property('destination_kind', kind)
    record_property('outside_before_sha256', _sha(before) if before is not None else 'absent')
    record_property('outside_after_sha256', _sha(after) if after is not None else 'absent')
    assert rejected and after == before, 'REGRESSION: settings save follows an outward symlink'
    assert link.is_symlink()


@pytest.mark.parametrize('kind', ['new', 'existing'])
def test_save_publishes_private_complete_config(tmp_path, record_property, kind):
    path = tmp_path / '.attocode/config.toml'
    if kind == 'existing':
        path = _previous(tmp_path)
        path.chmod(0o644)
    previous_umask = os.umask(0)
    try:
        saved = save_remote_config(str(tmp_path), _remote())
    finally:
        os.umask(previous_umask)
    assert saved == path
    data = tomllib.loads(path.read_text())
    assert data['remote'] == {'server': 'https://new.invalid', 'token': 'authored-fake-new',
                              'repo_id': 'authored-repo', 'branch_auto_detect': False}
    mode = stat.S_IMODE(path.stat().st_mode)
    record_property('qualified_input', 'true')
    record_property('file_mode', oct(mode))
    record_property('permissive_umask_restored', 'true')
    assert mode == 0o600, 'REGRESSION: saved remote settings expose credentials to other users'


@pytest.mark.parametrize('kind', ['malformed', 'invalid-utf8', 'oversized'])
def test_save_refuses_unreadable_existing_config(tmp_path, record_property, kind):
    path = _previous(tmp_path)
    raw = {'malformed': OLD + b'broken = "', 'invalid-utf8': OLD + b'\xff',
           'oversized': OLD + b'#' + b'x' * 1_000_001}[kind]
    path.write_bytes(raw)
    if kind == 'oversized':
        assert len(raw) > 1_000_000 and tomllib.loads(raw.decode())['title'] == 'keep'
    else:
        with pytest.raises((ValueError, UnicodeError)):
            tomllib.loads(raw.decode())
    rejected = False
    try:
        save_remote_config(str(tmp_path), _remote())
    except (OSError, ValueError):
        rejected = True
    after = path.read_bytes()
    record_property('qualified_input', 'true')
    record_property('invalid_kind', kind)
    record_property('before_bytes', str(len(raw)))
    record_property('before_sha256', _sha(raw))
    record_property('after_sha256', _sha(after))
    assert rejected and after == raw, 'REGRESSION: settings save discards unreadable existing data'


def test_invalid_new_unicode_preserves_previous_config(tmp_path):
    path = _previous(tmp_path)
    with pytest.raises(UnicodeError):
        save_remote_config(str(tmp_path), RemoteConfig(server='bad-\ud800'))
    assert path.read_bytes() == OLD
    assert list(path.parent.iterdir()) == [path]


def test_save_preserves_toml_and_connection_behavior(tmp_path, monkeypatch):
    path = _previous(tmp_path)
    assert save_remote_config(str(tmp_path), _remote()) == path
    data = tomllib.loads(path.read_text())
    assert data['title'] == 'keep' and data['perl'] == {'module_roots': ['dist/Carp/lib']}
    loaded = load_remote_config(str(tmp_path))
    assert loaded == _remote()
    monkeypatch.setenv('ATTOCODE_REMOTE_TOKEN', 'authored-fake-env')
    assert load_remote_config(str(tmp_path)).token == 'authored-fake-env'


def test_save_through_project_alias(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(project, target_is_directory=True)
    saved = save_remote_config(str(alias), _remote())
    assert saved == alias / '.attocode/config.toml'
    assert load_remote_config(str(project)) == _remote()


def test_save_creates_nested_project(tmp_path):
    project = tmp_path / 'new/nested/project'
    saved = save_remote_config(str(project), _remote())
    assert saved == project / '.attocode/config.toml'
    assert load_remote_config(str(project)) == _remote()
