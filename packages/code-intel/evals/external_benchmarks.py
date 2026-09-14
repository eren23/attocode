"""Local runtime and public-input boundary for externally prepared benchmarks."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def shell(argv, **kwargs):
    if argv and argv[0] == 'git':
        argv = ['git', '-c', 'core.hooksPath=/dev/null', *argv[1:]]
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=kwargs.pop('timeout', 120), **kwargs).stdout


def public_task(task):
    # Never pass the source dictionary to a template or client.
    return {k: task[k] for k in ('id', 'kind', 'repo', 'prompt', 'workdir', 'timeout')}


def prompt_for(task, root):
    task = public_task(task)
    answer = root / '.benchmark' / 'answer.txt'
    # Upstream prompts also create this directory in their shell examples.
    question = task['prompt'].replace('/logs/agent', str(answer.parent))
    question = question.replace(task['workdir'], str(root))
    return (f"Local benchmark environment: your source workspace is {root}. "
            "Native reads and edits operate on this workspace. Run repository programs, builds and tests "
            "inside the prepared Linux environment with `python3 .benchmark/run.py -- <command> <args...>`; "
            "for shell syntax use `python3 .benchmark/run.py -- bash -c '...'`. "
            "The helper uses the same source files; container paths in its output map to this workspace. "
            "Do not inspect other host directories, Docker resources, benchmark data, reference answers, "
            "or online solutions. Do not delegate. The .benchmark helper is harness infrastructure; do not edit it. "
            "Use your available tools naturally.\n\n" + question)


def validate_pack(pack, directory):
    tasks = pack['tasks']
    if len(tasks) != 4 or sorted(t['kind'] for t in tasks) != ['feature', 'feature', 'qa', 'qa']:
        raise ValueError('External pilot requires two QA and two feature tasks')
    if len({t['id'] for t in tasks}) != 4 or len({t['repo'] for t in tasks}) != 4:
        raise ValueError('Tasks and repositories must be distinct')
    for task in tasks:
        if Path(task['id']).name != task['id'] or task['id'] in {'.', '..'}:
            raise ValueError('Invalid task identity')
        if task['timeout'] != (1200 if task['kind'] == 'qa' else 3600):
            raise ValueError('Unexpected task time limit')
        if not task['image'].startswith('sha256:'):
            raise ValueError('Prepared image must be pinned by content ID')
        if not (directory / 'sources' / task['id']).is_dir():
            raise ValueError('Missing source snapshot')
        control = task['preparation']
        if not control.get('passed'):
            raise ValueError('Task preparation failed')
        required = ('rubric_verified', 'runtime_verified') if task['kind'] == 'qa' else (
            'reference_passed', 'starting_feature_failed', 'existing_behavior_passed')
        if not all(control.get(key) is True for key in required):
            raise ValueError('Missing independent preparation controls')


def copy_source(source, target):
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns('.git', '.attocode', '__pycache__', '*.pyc'))


def start_runtime(task, root, name):
    root = root.resolve()
    workdir = task['workdir']
    # No grading data, host credentials, Docker socket or private study directory is mounted.
    shell(['docker', 'run', '-d', '--name', name, '--platform', task.get('platform', 'linux/amd64'),
           *(['--shm-size', str(task['shm_size'])] if task.get('shm_size') else []),
           '--network', 'none', '--mount', f'type=bind,source={root},target={workdir}',
           '--workdir', workdir, '--entrypoint', 'sleep', task['image'], 'infinity'])
    helper = root / '.benchmark'
    helper.mkdir(exist_ok=True)
    # Login shells can replace the image's PATH and hide its pinned language toolchain.
    argv = ['docker', 'exec', '-w', workdir, name, 'bash', '-c']
    prelude = task.get('runtime_prelude', '')
    # Serialize arguments as Python data, never interpolate them into a shell command.
    code = ('import shlex, subprocess, sys\n'
            'args = sys.argv[1:]\n'
            "if args[:1] == ['--']: args = args[1:]\n"
            "if not args: raise SystemExit('Supply a command')\n"
            f'prefix = {prelude!r}\n'
            f'raise SystemExit(subprocess.call({argv!r} + [prefix + shlex.join(args)]))\n')
    (helper / 'run.py').write_text(code)
    return name


def stop_runtime(name):
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=60)


def initialize_git(root):
    shell(['git', 'init', '-q', str(root)])
    # Preserve repository identity/settings in the snapshot, not personal Git config.
    for key, value in [('user.name', 'Benchmark'), ('user.email', 'benchmark@localhost'), ('commit.gpgsign', 'false')]:
        shell(['git', '-C', str(root), 'config', key, value])
    shell(['git', '-C', str(root), 'add', '-A'], timeout=300)
    shell(['git', '-C', str(root), 'commit', '-qm', 'Prepared task workspace'], timeout=300)


def submitted_patch(root):
    # Include new implementation files; ignore only adapter/runtime artifacts.
    excluded = ['.benchmark', '.attocode', '.codex', '.mcp.json', 'CLAUDE.md', 'AGENTS.md']
    paths = ['.', *[':(exclude)' + p for p in excluded]]
    shell(['git', '-C', str(root), 'add', '-A', '--', *paths], timeout=300)
    patch = shell(['git', '-C', str(root), 'diff', '--cached', '--binary', 'HEAD', '--', *paths], timeout=300)
    changed = shell(['git', '-C', str(root), 'diff', '--cached', '--name-only', 'HEAD', '--', *paths]).splitlines()
    for name in changed:
        path = root / name
        if path.is_symlink():
            raise ValueError('Submitted symlink requires review; do not apply it to the verifier')
    return patch, changed


def evaluate_feature(study, task, patch_path, destination):
    pack = json.loads((study / 'private' / 'pack.json').read_text())
    worker = study / 'private' / 'feature_worker.py'
    destination.mkdir(parents=True, exist_ok=False)
    argv = [pack['feature_python'], str(worker), 'evaluate',
            str(study / 'private' / 'feature-data' / (task['id'] + '.json')),
            str(patch_path), str(destination)]
    with (destination / 'worker.log').open('w') as log:
        result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT,
                                timeout=1800, env={**os.environ, 'PYTHONPATH': pack['feature_checkout']})
    output = destination / 'acceptance.json'
    if result.returncode or not output.exists():
        return {'passed': False, 'status': 'evaluation_error', 'exit_code': result.returncode}
    return json.loads(output.read_text())
