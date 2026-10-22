"""Release checks reject wrong bytes before attempting isolated installs."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_release.py'


@pytest.fixture
def verifier():
    assert SCRIPT.exists(), 'maintained release verifier is missing'
    spec = importlib.util.spec_from_file_location('check_release', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path / 'source'
    package = source / 'packages/code-intel'
    (package / 'src/attocode_intel').mkdir(parents=True)
    (package / 'pyproject.toml').write_text('[project]\nname="attocode-code-intel"\nversion="1.2.3"\n')
    (package / 'src/attocode_intel/__init__.py').write_text('__version__ = "1.2.3"\n')
    (package / 'src/attocode_intel/helper.py').write_text('VALUE = 7\n')
    return source


def wheel(tmp_path, source, *, change=None, version='1.2.3'):
    path = tmp_path / 'attocode_code_intel-1.2.3-py3-none-any.whl'
    rows = {str(p.relative_to(source / 'packages/code-intel/src')): p.read_bytes()
            for p in (source / 'packages/code-intel/src').rglob('*.py')}
    rows['attocode_code_intel-1.2.3.dist-info/METADATA'] = (
        f'Metadata-Version: 2.3\nName: attocode-code-intel\nVersion: {version}\n').encode()
    if change:
        change(rows)
    with zipfile.ZipFile(path, 'w') as out:
        for name, body in rows.items():
            out.writestr(name, body)
    return path


@pytest.mark.parametrize('mutation', ['changed', 'missing', 'extra', 'version', 'duplicate'])
def test_rejects_corrupted_wheel(verifier, artifact, tmp_path, mutation):
    def mutate(rows):
        if mutation == 'changed':
            rows['attocode_intel/helper.py'] = b'VALUE = 8\n'
        elif mutation == 'missing':
            del rows['attocode_intel/helper.py']
        elif mutation == 'extra':
            rows['attocode_intel/extra.py'] = b'VALUE = 0\n'
    path = wheel(tmp_path, artifact, change=mutate,
                 version='9.9.9' if mutation == 'version' else '1.2.3')
    if mutation == 'duplicate':
        with zipfile.ZipFile(path, 'a') as archive, pytest.warns(UserWarning):
            archive.writestr('attocode_intel/helper.py', b'VALUE = 7\n')
    with pytest.raises(ValueError):
        verifier.verify_artifacts(artifact, path, '1.2.3')


def test_binds_every_source_python_file(verifier, artifact, tmp_path):
    result = verifier.verify_artifacts(artifact, wheel(tmp_path, artifact), '1.2.3')
    assert set(result['python_hashes']) == {'attocode_intel/__init__.py', 'attocode_intel/helper.py'}
    assert result['version'] == '1.2.3'
    assert len(result['wheel_sha256']) == 64
    (artifact / 'packages/code-intel/src/attocode_intel/helper.py').write_text('VALUE = 8\n')
    with pytest.raises(ValueError, match='identity'):
        verifier.verify_artifacts(artifact, tmp_path / 'attocode_code_intel-1.2.3-py3-none-any.whl', '1.2.3')


def test_rejects_unsafe_sdist_without_extracting(verifier, artifact, tmp_path):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        member = tarfile.TarInfo('../outside.py')
        member.size = 1
        archive.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(ValueError, match='Unsafe'):
        verifier.verify_artifacts(artifact, wheel(tmp_path, artifact), '1.2.3', path)
    assert not (tmp_path / 'outside.py').exists()


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c',
                                   'user.name=Release test', '-c',
                                   'user.email=release@example.invalid', *args], cwd=root, text=True).strip()


def test_published_requires_clean_exact_tag(verifier, artifact):
    git(artifact, 'init', '-q')
    git(artifact, 'add', '.')
    git(artifact, 'commit', '-qm', 'fixture')
    with pytest.raises(ValueError, match='tag'):
        verifier.source_identity(artifact, 'published', '1.2.3')
    git(artifact, 'tag', 'intel-v1.2.3')
    assert verifier.source_identity(artifact, 'published', '1.2.3')['kind'] == 'clean_tagged_tree'
    (artifact / 'packages/code-intel/src/attocode_intel/helper.py').write_text('VALUE = 8\n')
    with pytest.raises(ValueError, match='dirty'):
        verifier.source_identity(artifact, 'published', '1.2.3')
    assert verifier.source_identity(artifact, 'candidate', '1.2.3')['dirty']


def test_published_refuses_network_without_consent_and_writes_report(tmp_path):
    assert SCRIPT.exists(), 'maintained release verifier is missing'
    report = tmp_path / 'report.json'
    result = subprocess.run([sys.executable, str(SCRIPT), 'published', '--version', '1.2.3',
                             '--baseline-version', '1.2.2', '--source', str(tmp_path),
                             '--report', str(report)], capture_output=True, text=True)
    assert result.returncode == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'failed'
    assert '--allow-downloads' in data['error']
    assert data['checks'] == []
    assert data['cleanup_verified']


def test_offline_refuses_missing_wheelhouse_before_launch(verifier, artifact, tmp_path):
    report = tmp_path / 'report.json'
    assert verifier.main(['candidate', '--version', '1.2.3', '--baseline-version', '1.2.2',
                          '--source', str(artifact), '--wheel', str(wheel(tmp_path, artifact)),
                          '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'failed'
    assert 'wheelhouse' in data['error']
    assert not data['checks']
    assert data['cleanup_verified']


def test_source_runtime_version_must_match_project_metadata(verifier, artifact, tmp_path):
    (artifact / 'packages/code-intel/src/attocode_intel/__init__.py').write_text('__version__ = "9.9.9"\n')
    with pytest.raises(ValueError, match='Source runtime version'):
        verifier.verify_artifacts(artifact, wheel(tmp_path, artifact), '1.2.3')


@pytest.mark.parametrize('mutation', [None, 'changed', 'missing', 'extra', 'version', 'metadata'])
def test_installed_worker_rejects_changed_environment(verifier, artifact, tmp_path, mutation):
    import venv

    path = wheel(tmp_path, artifact)
    manifest = tmp_path / 'identity.json'
    manifest.write_text(json.dumps(verifier.verify_artifacts(artifact, path, '1.2.3')))
    env = tmp_path / 'environment'
    venv.EnvBuilder(with_pip=False).create(env)
    python = env / 'bin/python'
    site = Path(subprocess.check_output([str(python), '-c',
                'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip())
    with zipfile.ZipFile(path) as archive:
        archive.extractall(site)
    if mutation == 'changed':
        (site / 'attocode_intel/helper.py').write_text('VALUE = 8\n')
    elif mutation == 'missing':
        (site / 'attocode_intel/helper.py').unlink()
    elif mutation == 'extra':
        (site / 'attocode_intel/extra.py').write_text('VALUE = 8\n')
    elif mutation == 'version':
        (site / 'attocode_code_intel-1.2.3.dist-info/METADATA').write_text(
            'Name: attocode-code-intel\nVersion: 9.9.9\n')
    elif mutation == 'metadata':
        metadata = site / 'attocode_code_intel-1.2.3.dist-info/METADATA'
        metadata.write_bytes(metadata.read_bytes() + b'Summary: silently changed\n')
    completed = subprocess.run([str(python), '-I', str(SCRIPT), '_identity', str(manifest)],
                               capture_output=True, text=True)
    assert (completed.returncode == 0) == (mutation is None), completed.stderr
    if mutation is None:
        assert json.loads(completed.stdout)['python_file_count'] == 2


def test_temporary_environment_ignores_real_home_and_uv_settings(verifier, tmp_path, monkeypatch):
    monkeypatch.setenv('UV_INDEX_URL', 'https://unexpected.invalid')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'remote')
    monkeypatch.setenv('PYTHONPATH', '/wrong/source')
    monkeypatch.setenv('OPENAI_API_KEY', 'private')
    (tmp_path / 'work').mkdir()
    env = verifier.isolated_environment(tmp_path, False)
    assert env['HOME'] == str(tmp_path / 'work/home')
    assert 'PYTHONPATH' not in env and 'UV_INDEX_URL' not in env
    assert 'OPENAI_API_KEY' not in env
    assert env['UV_OFFLINE'] == '1'
    assert env['ATTOCODE_INTEL_RANKING_PROVIDER'] == 'off'


def test_partial_run_preserves_failure_report_and_cleans_owned_storage(verifier, artifact, tmp_path):
    baseline = wheel(tmp_path, artifact, version='1.2.2')
    baseline = baseline.rename(tmp_path / 'attocode_code_intel-1.2.2-py3-none-any.whl')
    target = wheel(tmp_path, artifact)
    wheelhouse = tmp_path / 'wheelhouse'
    wheelhouse.mkdir()
    report = tmp_path / 'verification.json'
    result = verifier.main(['candidate', '--version', '1.2.3', '--baseline-version', '1.2.2',
                            '--source', str(artifact), '--wheel', str(target),
                            '--baseline-wheel', str(baseline), '--wheelhouse', str(wheelhouse),
                            '--report', str(report), '--seconds', '0.001'])
    assert result == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'incomplete'
    assert data['checks'][0]['reason'] == 'admission_budget'
    assert data['cleanup_verified']
    assert data['operator_hashes']


def test_download_worker_refuses_without_explicit_flag(tmp_path):
    completed = subprocess.run([sys.executable, str(SCRIPT), '_download', '1.2.3', str(tmp_path)],
                               capture_output=True, text=True)
    assert completed.returncode != 0
    assert '--allow-downloads' in completed.stderr
    assert not list(tmp_path.iterdir())


def test_baseline_must_be_previous_version(verifier, artifact, tmp_path):
    report = tmp_path / 'report.json'
    assert verifier.main(['candidate', '--version', '1.2.3', '--baseline-version', '9.9.9',
                          '--source', str(artifact), '--report', str(report)]) == 1
    assert 'previous' in json.loads(report.read_text())['error']



@pytest.mark.parametrize('child_cleanup', [True, False])
def test_changed_source_is_incomplete_and_keeps_both_hashes(
        verifier, artifact, tmp_path, monkeypatch, child_cleanup):
    from eval.quality import runner

    target = wheel(tmp_path, artifact)
    baseline = wheel(tmp_path, artifact, version='1.2.2').rename(
        tmp_path / 'attocode_code_intel-1.2.2-py3-none-any.whl')
    target = wheel(tmp_path, artifact)
    wheelhouse = tmp_path / 'wheelhouse'
    wheelhouse.mkdir()
    report = tmp_path / 'changed-source.json'

    def blocked_command(*args, **kwargs):
        (artifact / 'packages/code-intel/src/attocode_intel/helper.py').write_text('VALUE = 8\n')
        return {'status': 'incomplete', 'reason': 'process_inspection_unavailable',
                'cleanup_verified': child_cleanup}

    monkeypatch.setattr(runner, 'supervise', blocked_command)
    assert verifier.main(['candidate', '--version', '1.2.3', '--baseline-version', '1.2.2',
                          '--source', str(artifact), '--wheel', str(target),
                          '--baseline-wheel', str(baseline), '--wheelhouse', str(wheelhouse),
                          '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'incomplete' and data['source_changed']
    assert data['source_sha256_before'] != data['source_sha256_after']
    assert data['cleanup_verified'] is child_cleanup


@pytest.mark.parametrize('ignored', [False, True])
def test_published_rejects_python_inputs_absent_from_tag(verifier, artifact, tmp_path, ignored):
    if ignored:
        (artifact / '.gitignore').write_text('packages/code-intel/src/attocode_intel/extra.py\n')
    git(artifact, 'init', '-q')
    git(artifact, 'add', '.')
    git(artifact, 'commit', '-qm', 'fixture')
    git(artifact, 'tag', 'intel-v1.2.3')
    (artifact / 'AGENTS.md').write_text('Allowed local notes\n')
    assert verifier.source_identity(artifact, 'published', '1.2.3')['kind'] == 'clean_tagged_tree'
    (artifact / 'packages/code-intel/src/attocode_intel/extra.py').write_text('VALUE = 8\n')
    # Candidate source and wheel agree, yet this file was never in the release tag.
    assert verifier.verify_artifacts(artifact, wheel(tmp_path, artifact), '1.2.3')['python_file_count'] == 3
    with pytest.raises(ValueError, match='tag.*identity'):
        verifier.source_identity(artifact, 'published', '1.2.3')


def test_published_rejects_skip_worktree_source_changes(verifier, artifact):
    git(artifact, 'init', '-q')
    git(artifact, 'add', '.')
    git(artifact, 'commit', '-qm', 'fixture')
    git(artifact, 'tag', 'intel-v1.2.3')
    project = 'packages/code-intel/pyproject.toml'
    git(artifact, 'update-index', '--skip-worktree', project)
    (artifact / project).write_text('[project]\nname="attocode-code-intel"\nversion="1.2.3"\n# changed\n')
    assert not git(artifact, 'status', '--porcelain', '--untracked-files=no')
    with pytest.raises(ValueError, match='tag.*identity'):
        verifier.source_identity(artifact, 'published', '1.2.3')
