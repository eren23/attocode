"""Verify a candidate or published release; never publish or change Git refs.

Offline candidate example (wheelhouse must contain all dependencies)::

    python packages/code-intel/scripts/check_release.py candidate \\
      --version 0.1.13 --baseline-version 0.1.12 --source . \\
      --wheel dist/attocode_code_intel-0.1.13-py3-none-any.whl \\
      --sdist dist/attocode_code_intel-0.1.13.tar.gz \\
      --baseline-wheel old.whl --wheelhouse wheels --report verification.json

Published mode requires explicit --allow-downloads and HEAD at intel-v<VERSION>
with a clean tracked tree. It downloads exact PyPI artifacts with verified hashes.
Reports/logs survive; only owned temporary environments and caches are removed.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import email
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
MAX_ARTIFACT = 32 * 1024**2


def digest(body):
    return hashlib.sha256(body).hexdigest()


def python_hashes(root):
    files = sorted(root.rglob('*.py'))
    if not files or any(p.is_symlink() for p in files):
        raise ValueError('Missing Python files or symlinked Python source')
    return {p.relative_to(root.parent).as_posix(): digest(p.read_bytes()) for p in files}


def source_digest(source):
    package = source / 'packages/code-intel'
    return digest(json.dumps({'python': python_hashes(package / 'src/attocode_intel'),
                              'pyproject': digest((package / 'pyproject.toml').read_bytes())},
                             sort_keys=True).encode())


def equal_identity(actual, expected, label):
    if actual != expected:
        raise ValueError(f'{label} identity mismatch: ' + json.dumps({
            'missing': sorted(expected.keys() - actual.keys()),
            'extra': sorted(actual.keys() - expected.keys()),
            'changed': sorted(k for k in actual.keys() & expected.keys()
                              if actual[k] != expected[k]),
        }))


def metadata_version(body, version):
    metadata = email.message_from_bytes(body)
    if (metadata.get_all('Version') != [version]
            or metadata.get_all('Name') != ['attocode-code-intel']):
        raise ValueError('Distribution metadata name/version mismatch')


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '..' not in path.parts and '\\' not in name


def wheel_identity(wheel, version):
    if wheel.stat().st_size > MAX_ARTIFACT:
        raise ValueError('Wheel exceeds compressed size limit')
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(set(names)) != len(names) or any(not safe_name(n) for n in names):
            raise ValueError('Unsafe or duplicate wheel members')
        if sum(m.file_size for m in members) > MAX_ARTIFACT:
            raise ValueError('Wheel exceeds uncompressed size limit')
        metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('Wheel needs exactly one METADATA')
        metadata_version(archive.read(metadata[0]), version)
        python = {n: digest(archive.read(n)) for n in names if n.endswith('.py')}
        if not python or any(not n.startswith('attocode_intel/') for n in python):
            raise ValueError('Unexpected or missing wheel Python package')
    return python


def verify_artifacts(source, wheel, version, sdist=None):
    package = source / 'packages/code-intel'
    project = tomllib.loads((package / 'pyproject.toml').read_text())['project']
    if project['name'] != 'attocode-code-intel' or project['version'] != version:
        raise ValueError('Source project version/name mismatch')
    assignments = ast.parse((package / 'src/attocode_intel/__init__.py').read_text()).body
    versions = [ast.literal_eval(node.value) for node in assignments if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == '__version__'
                        for target in node.targets)]
    if versions != [version]:
        raise ValueError('Source runtime version mismatch')
    expected = python_hashes(package / 'src/attocode_intel')
    actual = wheel_identity(wheel, version)
    equal_identity(actual, expected, 'Wheel/source')
    result = {'version': version, 'python_hashes': expected,
              'python_file_count': len(expected), 'wheel_sha256': digest(wheel.read_bytes()),
              'source_pyproject_sha256': digest((package / 'pyproject.toml').read_bytes()),
              'sdist_verified': False}
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        result.update(metadata_path=metadata_path,
                      metadata_sha256=digest(archive.read(metadata_path)))
    if sdist:
        if sdist.stat().st_size > MAX_ARTIFACT:
            raise ValueError('Sdist exceeds compressed size limit')
        with tarfile.open(sdist) as archive:
            members = archive.getmembers()
            names = [m.name for m in members]
            if (len(names) != len(set(names))
                    or any(not safe_name(m.name) or not (m.isfile() or m.isdir()) for m in members)
                    or sum(m.size for m in members) > MAX_ARTIFACT):
                raise ValueError('Unsafe or oversized sdist members')
            roots = {PurePosixPath(n).parts[0] for n in names}
            if len(roots) != 1:
                raise ValueError('Unsafe sdist root')
            prefix = next(iter(roots)) + '/'
            contents = {m.name.removeprefix(prefix): archive.extractfile(m).read()
                        for m in members if m.isfile()}
            metadata_version(contents.get('PKG-INFO', b''), version)
            equal_identity({n.removeprefix('src/'): digest(b) for n, b in contents.items()
                            if n.startswith('src/') and n.endswith('.py')}, expected, 'Sdist/source')
            if contents.get('pyproject.toml') != (package / 'pyproject.toml').read_bytes():
                raise ValueError('Sdist pyproject identity mismatch')
        result.update(sdist_verified=True, sdist_sha256=digest(sdist.read_bytes()))
    return result


def tagged_source_identity(source, commit):
    """Read exact Git blobs, unaffected by ignored files or export attributes."""
    prefix = 'packages/code-intel/src/'
    project = 'packages/code-intel/pyproject.toml'
    tree = subprocess.check_output(
        ['git', '-C', str(source), 'ls-tree', '-rz', commit, '--',
         project, prefix + 'attocode_intel'], timeout=10)
    selected = []
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        attributes, path = entry.split(b'\t', 1)
        mode, kind, blob = attributes.split()
        path = path.decode()
        if path == project or path.endswith('.py'):
            if kind != b'blob' or mode not in {b'100644', b'100755'}:
                raise ValueError('Source/tag identity includes unsupported file type')
            selected.append((path, blob))
    bodies = subprocess.run(['git', '-C', str(source), 'cat-file', '--batch'],
                            input=b''.join(blob + b'\n' for _, blob in selected),
                            capture_output=True, check=True, timeout=10).stdout
    expected = {}
    project_hash = None
    offset = 0
    for path, blob in selected:
        header_end = bodies.index(b'\n', offset)
        actual_blob, kind, size = bodies[offset:header_end].split()
        if actual_blob != blob or kind != b'blob':
            raise ValueError('Source/tag Git blob identity mismatch')
        offset = header_end + 1
        body = bodies[offset:offset + int(size)]
        offset += int(size) + 1
        if path == project:
            project_hash = digest(body)
        else:
            expected[path.removeprefix(prefix)] = digest(body)
    equal_identity(python_hashes(source / prefix / 'attocode_intel'), expected, 'Source/tag')
    if project_hash != digest((source / project).read_bytes()):
        raise ValueError('Source/tag pyproject identity mismatch')
    return {'tag_python_sha256': digest(json.dumps(expected, sort_keys=True).encode()),
            'tag_pyproject_sha256': project_hash, 'tag_python_file_count': len(expected)}


def source_identity(source, mode, version):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args],
                                       text=True, stderr=subprocess.PIPE, timeout=10).strip()
    try:
        head = git('rev-parse', 'HEAD')
        dirty = bool(git('status', '--porcelain', '--untracked-files=no'))
    except subprocess.CalledProcessError:
        if mode == 'published':
            raise ValueError('Published source requires a Git tag checkout') from None
        return {'kind': 'candidate_working_tree', 'commit': None, 'dirty': True}
    if mode == 'published':
        if dirty:
            raise ValueError('Published source tracked tree is dirty')
        try:
            tagged = git('rev-parse', f'intel-v{version}^{{commit}}')
        except subprocess.CalledProcessError:
            raise ValueError('Missing published source tag') from None
        if head != tagged:
            raise ValueError('Published source HEAD does not match tag')
    identity = {'kind': 'clean_tagged_tree' if mode == 'published' else 'candidate_working_tree',
                'commit': head, 'dirty': dirty}
    if mode == 'published':
        identity.update(tagged_source_identity(source, tagged))
    return identity


def installed_identity(manifest):
    import attocode_intel

    root = Path(attocode_intel.__file__).resolve().parent
    if not root.is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError('Package is not from isolated installation')
    expected = json.loads(Path(manifest).read_text())
    distribution = importlib.metadata.distribution('attocode-code-intel')
    if attocode_intel.__version__ != distribution.version or distribution.version != expected['version']:
        raise ValueError('Installed package/metadata version mismatch')
    metadata_path = Path(distribution.locate_file(expected['metadata_path'])).resolve()
    if (not metadata_path.is_relative_to(Path(sys.prefix).resolve())
            or digest(metadata_path.read_bytes()) != expected['metadata_sha256']):
        raise ValueError('Installed metadata bytes mismatch')
    equal_identity(python_hashes(root), expected['python_hashes'], 'Installed/wheel')
    print(json.dumps({'version': distribution.version, 'python_file_count': len(expected['python_hashes']),
                      'isolated_environment': True}))


async def installed_continuation():
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens

    with tempfile.TemporaryDirectory(prefix='release-search-') as tmp:
        root = Path(tmp)
        for i in range(60):
            (root / f'worker_{i:02}.py').write_text(
                f'def accept_request_{i}():\n    """Accept incoming request."""\n    return {i}\n')
        gateway = OperationGateway(str(root), profile='daily', watch=False)
        try:
            await gateway.execute_mcp('semantic_search', {'query': 'warmup', 'top_k': 5})
            key = next(iter(gateway._stores))
            manager = gateway._stores[key]['service']._get_semantic_search()
            ready = await asyncio.get_running_loop().run_in_executor(
                gateway._workers[key], lambda: manager.wait_for_body_index(timeout=30))
            if not ready:
                raise ValueError('Continuation body index did not become ready')
            arguments = {'query': 'accept request', 'top_k': 5, 'max_tokens': 2000}
            steps = []
            for _ in range(5):
                response = await gateway.execute_mcp('semantic_search', arguments)
                if response.isError or response_tokens(response) > arguments['max_tokens']:
                    raise ValueError('Installed continuation response failed/budget exceeded')
                data = json.loads(response.content[0].text)['data']
                if data['ranking']['delivered_count'] != len(data['results']):
                    raise ValueError('Incorrect delivered count')
                follow = data.get('follow_up')
                steps.append({'requested': arguments['top_k'], 'delivered': len(data['results']),
                              'next': follow['arguments']['top_k'] if follow else None})
                if not follow:
                    break
                nxt = follow['arguments']
                if (follow['reruns_current_index'] is not True or nxt['top_k'] > 50
                        or (nxt['top_k'] <= arguments['top_k']
                            and nxt['max_tokens'] <= arguments['max_tokens'])):
                    raise ValueError('Invalid continuation progress')
                arguments = nxt
            if ([s['requested'] for s in steps] != [5, 24, 48, 50]
                    or steps[-1]['next'] is not None or steps[-1]['delivered'] != 50):
                raise ValueError(f'Installed continuation mismatch: {steps}')
            print(json.dumps({'installed_continuation': 'passed', 'steps': steps,
                              'fixture_hashes': {p.name: digest(p.read_bytes())
                                                 for p in sorted(root.glob('*.py'))}}))
        finally:
            await gateway.close()


def download_published(version, directory):
    # Fixed PyPI hosts; no mutable index setting or arbitrary URL input.
    with urllib.request.urlopen(f'https://pypi.org/pypi/attocode-code-intel/{version}/json',
                                timeout=30) as response:
        body = response.read(MAX_ARTIFACT + 1)
    if len(body) > MAX_ARTIFACT:
        raise ValueError('PyPI metadata too large')
    metadata = json.loads(body)
    if metadata['info']['version'] != version:
        raise ValueError('PyPI version mismatch')
    records = metadata['urls']
    if len(records) != 2:
        raise ValueError('Expected one wheel and one sdist')
    files = []
    for record in records:
        name = record['filename']
        if (Path(name).name != name or not safe_name(name)
                or not record['url'].startswith('https://files.pythonhosted.org/')
                or record['size'] > MAX_ARTIFACT):
            raise ValueError('Unsafe PyPI artifact')
        with urllib.request.urlopen(record['url'], timeout=30) as response:
            body = response.read(MAX_ARTIFACT + 1)
        if len(body) != record['size'] or digest(body) != record['digests']['sha256']:
            raise ValueError('PyPI artifact size/hash mismatch')
        path = directory / name
        path.write_bytes(body)
        files.append(path)
    wheels = [p for p in files if p.suffix == '.whl']
    sdists = [p for p in files if p.name.endswith('.tar.gz')]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError('Expected one wheel and one sdist')
    return wheels[0], sdists[0]


def isolated_environment(root, allow_downloads):
    sys.path.insert(0, str(REPO))
    from eval.quality.runner import environment

    env = environment(root)
    for name in list(env):
        if name.startswith(('UV_', 'PIP_', 'PYTHON', 'ATTOCODE_', 'CLAUDE_', 'CODEX_')):
            env.pop(name)
    env.update(HOME=str(root / 'work/home'), XDG_CONFIG_HOME=str(root / 'work/config'),
               UV_CACHE_DIR=str(root / 'cache/uv'), UV_NO_CONFIG='1', UV_PYTHON_DOWNLOADS='never',
               UV_DEFAULT_INDEX='https://pypi.org/simple', UV_HTTP_TIMEOUT='30', UV_HTTP_RETRIES='1',
               PYTHONDONTWRITEBYTECODE='1', ATTOCODE_LOCAL_ONLY='1', ATTOCODE_INTEL_PRECISION='off',
               ATTOCODE_INTEL_RANKING_PROVIDER='off', ATTOCODE_INTEL_RANKING_ALLOW_REMOTE='0',
               ATTOCODE_NL_EMBEDDING_MODE='none', ATTOCODE_EMBEDDING_MODEL='')
    if not allow_downloads:
        env['UV_OFFLINE'] = '1'
    Path(env['HOME']).mkdir(parents=True)
    return env


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument('mode', choices=['candidate', 'published'])
    result.add_argument('--version', required=True)
    result.add_argument('--baseline-version', required=True)
    result.add_argument('--source', type=Path, required=True, help='Repository root to compare')
    result.add_argument('--wheel', type=Path)
    result.add_argument('--sdist', type=Path)
    result.add_argument('--baseline-wheel', type=Path)
    result.add_argument('--wheelhouse', type=Path)
    result.add_argument('--allow-downloads', action='store_true')
    result.add_argument('--report', type=Path, required=True, help='New JSON path; sibling logs are preserved')
    result.add_argument('--seconds', type=float, default=600)
    result.add_argument('--max-bytes', type=int, default=2 * 1024**3)
    result.add_argument('--max-rss', type=int, default=2 * 1024**3)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    report_path = args.report.resolve()
    if report_path.exists():
        print('Refusing to overwrite an existing verification report', file=sys.stderr)
        return 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'mode': args.mode, 'version': args.version, 'baseline_version': args.baseline_version,
              'status': 'failed', 'checks': [], 'cleanup_verified': True,
              'allow_downloads': args.allow_downloads, 'operator_hashes': {}, 'fixture_hashes': {}}
    temporary = None
    logs = None
    saved_logs = report_path.with_suffix('.logs')
    started = time.monotonic()
    try:
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}(?:(?:a|b|rc)[0-9]+)?', args.version):
            raise ValueError('Unsupported release version')
        if (not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', args.baseline_version)
                or tuple(map(int, args.baseline_version.split('.'))) >= tuple(
                    map(int, re.match(r'\d+\.\d+\.\d+', args.version)[0].split('.')))):
            raise ValueError('A distinct previous --baseline-version is required')
        report['baseline_kind'] = 'previous_version_upgrade'
        if min(args.seconds, args.max_bytes, args.max_rss) <= 0:
            raise ValueError('Resource limits must be positive')
        if args.mode == 'published' and not args.allow_downloads:
            raise ValueError('Published PyPI verification requires --allow-downloads')
        if args.mode == 'published' and (args.wheel or args.sdist):
            raise ValueError('Published mode obtains actual PyPI artifacts; do not supply --wheel/--sdist')
        if not args.allow_downloads and (not args.wheelhouse or not args.baseline_wheel):
            raise ValueError('Offline verification requires --wheelhouse and --baseline-wheel')
        if args.wheelhouse and not args.wheelhouse.resolve().is_dir():
            raise ValueError('Missing wheelhouse directory')
        source = args.source.resolve()
        report['source'] = source_identity(source, args.mode, args.version)
        report['source_sha256_before'] = source_digest(source)
        for p in [Path(__file__), SCRIPTS / 'check_wheel.py', SCRIPTS / 'check_upgrade.py',
                  REPO / 'eval/quality/runner.py']:
            report['operator_hashes'][str(p.relative_to(REPO))] = digest(p.read_bytes())
        sys.path.insert(0, str(REPO))
        from eval.quality.runner import managed_root, supervise

        temporary = Path(tempfile.mkdtemp(prefix='attocode-release-')).resolve()
        root = managed_root(temporary)
        if saved_logs.exists():
            raise ValueError('Refusing to overwrite existing verification logs')
        logs = root / 'runs'
        env = isolated_environment(root, args.allow_downloads)
        wheel = args.wheel.resolve() if args.wheel else None
        sdist = args.sdist.resolve() if args.sdist else None
        uv = shutil.which('uv')
        if not uv:
            raise ValueError('uv is required for isolated dependency installs')
        deadline = started + args.seconds
        wall_deadline = time.time() + max(0, args.seconds - (time.monotonic() - started))

        def check(name, command):
            row = supervise([str(p) for p in command], cwd=root / 'work', env=env, root=root,
                            log=logs / (name + '.log'), deadline=deadline, wall_deadline=wall_deadline,
                            max_bytes=args.max_bytes, max_rss=args.max_rss)
            report['checks'].append({'name': name, **row})
            if row['status'] != 'passed':
                report['status'] = row['status']
                raise ValueError(f'Check {name}: {row["status"]} ({row.get("reason", row.get("exit_code"))})')
            if name.endswith(('-identity', '-continuation')):
                report['checks'][-1]['evidence'] = json.loads(
                    (logs / (name + '.log')).read_text().splitlines()[-1])

        # Copy operators into owned storage; workers never import the checkout.
        operator = root / 'work/check_release.py'
        operator.write_bytes(Path(__file__).read_bytes())
        for name in ['check_wheel.py', 'check_upgrade.py']:
            shutil.copyfile(SCRIPTS / name, root / 'work' / name)
        if args.mode == 'published':
            downloads = root / 'work/downloads'
            downloads.mkdir()
            check('download-pypi', [sys.executable, operator, '_download', args.version,
                                    downloads, '--allow-downloads'])
            wheel = next(downloads.glob('*.whl'))
            sdist = next(downloads.glob('*.tar.gz'))
            shutil.copyfile(wheel, logs / wheel.name)
            shutil.copyfile(sdist, logs / sdist.name)
        elif not wheel:
            raise ValueError('Candidate verification requires --wheel')
        report['artifacts'] = verify_artifacts(source, wheel, args.version, sdist)
        if args.baseline_wheel:
            baseline = str(args.baseline_wheel.resolve())
            wheel_identity(Path(baseline), args.baseline_version)
            report['baseline_wheel_sha256'] = digest(Path(baseline).read_bytes())
        else:
            baseline = f'attocode-code-intel=={args.baseline_version}'
        manifest = root / 'work/identity.json'
        manifest.write_text(json.dumps(report['artifacts']))
        install_options = ['--index-url', 'https://pypi.org/simple'] if args.allow_downloads else ['--no-index']
        if args.wheelhouse:
            install_options += ['--find-links', str(args.wheelhouse.resolve())]
        project = root / 'work/project with spaces'
        clean_project = root / 'work/clean project'
        clean_project.mkdir()
        (clean_project / 'helper.py').write_text('def installed_helper(): return 1\n')
        report['fixture_hashes'] = {
            'clean-helper': digest((clean_project / 'helper.py').read_bytes()),
            'installed-fixture-operator': digest(operator.read_bytes())}
        for kind in ['clean', 'upgrade']:
            venv = root / 'work' / kind
            python = venv / 'bin/python'
            command = venv / 'bin/attocode-code-intel'
            check(kind + '-venv', [uv, 'venv', venv, '--python', sys.executable])
            def install(name, target, python=python):
                check(name, [uv, 'pip', 'install', '--reinstall-package', 'attocode-code-intel',
                             '--python', python, *install_options, target])
            if kind == 'upgrade':
                install('baseline-install', baseline)
                check('baseline-version', [python, operator, '_version', args.baseline_version])
                check('upgrade-prepare', [python, root / 'work/check_upgrade.py', 'prepare', project])
            install(kind + '-install', str(wheel))
            check(kind + '-identity', [python, operator, '_identity', manifest])
            check(kind + '-wheel', [python, root / 'work/check_wheel.py'])
            check(kind + '-continuation', [python, operator, '_continuation'])
            if kind == 'upgrade':
                check('upgrade-verify', [python, root / 'work/check_upgrade.py', 'verify', project])
            else:
                check('clean-init', [command, 'init', '--client', 'codex', '--project', clean_project])
                check('clean-doctor', [python, operator, '_doctor', command, clean_project, 'codex'])
                config = Path(env['HOME']) / '.claude.json'
                config.write_text(json.dumps({'projects': {str(clean_project): {'mcpServers': {
                    'attocode-code-intel': {'command': str(command), 'args': [
                        '--project', str(clean_project), '--profile', 'daily']}}}}}))
                (clean_project / '.mcp.json').write_text(json.dumps({'mcpServers': {
                    'attocode-code-intel': {'command': str(root / 'missing-command')}}}))
                check('clean-doctor-claude-local', [python, operator, '_doctor', command,
                                                    clean_project, 'claude', config])
        equal_identity(verify_artifacts(source, wheel, args.version, sdist)['python_hashes'],
                       report['artifacts']['python_hashes'], 'Source during verification')
        if source_identity(source, args.mode, args.version) != report['source']:
            raise ValueError('Source revision changed during verification')
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if 'source_sha256_before' in report:
            try:
                report['source_sha256_after'] = source_digest(source)
                report['source_changed'] = report['source_sha256_before'] != report['source_sha256_after']
                if report['source_changed']:
                    report['status'] = 'incomplete'
            except Exception as exc:
                report.update(status='incomplete', source_changed=True,
                              source_check_error=f'{type(exc).__name__}: {exc}')
        if temporary:
            if logs and logs.exists():
                try:
                    shutil.copytree(logs, saved_logs)
                except OSError as exc:
                    report.update(status='failed', log_preservation_error=str(exc))
            try:
                shutil.rmtree(temporary)
            except OSError as exc:
                report.update(status='failed', cleanup_error=str(exc))
            report['cleanup_verified'] = not temporary.exists()
        report['cleanup_verified'] = report['cleanup_verified'] and all(
            row.get('cleanup_verified', True) for row in report['checks'])
        report['seconds'] = round(time.monotonic() - started, 3)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': report['status'], 'report': str(report_path)}))
    return 0 if report['status'] == 'passed' else 1


def worker(argv):
    if argv[0] == '_download':
        if len(argv) != 4 or argv[3] != '--allow-downloads':
            raise ValueError('PyPI download worker requires --allow-downloads')
        download_published(argv[1], Path(argv[2]))
    elif argv[0] == '_identity':
        installed_identity(argv[1])
    elif argv[0] == '_continuation':
        asyncio.run(installed_continuation())
    elif argv[0] == '_version':
        actual = importlib.metadata.version('attocode-code-intel')
        if actual != argv[1]:
            raise ValueError(f'Installed baseline version {actual} != {argv[1]}')
        print(json.dumps({'baseline_version': actual}))
    elif argv[0] == '_doctor':
        completed = subprocess.run([argv[1], 'doctor', '--client', argv[3], '--project', argv[2]],
                                   check=True, capture_output=True, text=True, timeout=60)
        result = json.loads(completed.stdout)
        if result['status'] != 'ok' or (len(argv) > 4 and result['config'] != argv[4]):
            raise ValueError(f'Installed doctor failed: {result}')
        print(json.dumps(result))
    else:
        raise ValueError('Unknown verification worker')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].startswith('_'):
        worker(sys.argv[1:])
    else:
        raise SystemExit(main())
