"""Build the real package configuration with seeded generated metadata on CI."""
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


def test_sdist_excludes_root_and_nested_project_state(tmp_path):
    package = Path(__file__).resolve().parents[1]
    project = tmp_path / 'package'
    project.mkdir()
    for name in ['pyproject.toml', 'README.md']:
        shutil.copyfile(package / name, project / name)
    source = project / 'src/attocode_intel'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('"""Source archive fixture."""\n')
    files = {
        '.attocode/local-index.json': '{"generated": true}\n',
        'tests/fixtures/sample/.attocode/.gitignore': '# Generated fixture metadata\n*\n',
        'tests/fixtures/sample/example.py': 'VALUE = 7\n',
        'evals/retained-in-git-only.txt': 'study\n',
    }
    for name, text in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    rule = Path('tests/fixtures/rule_violations/.attocode/rules/team-preferences.yaml')
    (project / rule).parent.mkdir(parents=True)
    shutil.copyfile(package / rule, project / rule)
    cache = tmp_path / 'build-cache'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('UV_', 'PIP_'))}
    env.update(UV_CACHE_DIR=str(cache), UV_NO_CONFIG='1', UV_NO_PROGRESS='1')
    subprocess.run(['uv', 'build', '--sdist', '--out-dir', str(tmp_path / 'dist')],
                   cwd=project, env=env, check=True, capture_output=True, text=True, timeout=120)
    with tarfile.open(next((tmp_path / 'dist').glob('*.tar.gz'))) as archive:
        names = [Path(m.name).parts[1:] for m in archive.getmembers() if m.isfile()]
        member = next(m for m in archive.getmembers() if m.name.endswith('/' + rule.as_posix()))
        assert archive.extractfile(member).read() == (package / rule).read_bytes()
    assert not [p for p in names if '.attocode' in p and p != rule.parts], 'Generated project state leaked into source archive'
    assert ('src', 'attocode_intel', '__init__.py') in names
    assert ('tests', 'fixtures', 'sample', 'example.py') in names
    assert not any(p and p[0] == 'evals' for p in names), 'Historical study exclusion lost'
