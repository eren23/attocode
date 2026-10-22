"""Measure disposable CI images, compare identities, enforce reviewed size growth."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKS = {'health', 'dashboard', 'mcp_auth', 'navigation', 'cli', 'writable_state'}


def positive_size(value):
    if type(value) is not int or value <= 0:
        raise ValueError('invalid image size')
    return value


def check_growth(size, baseline):
    size = positive_size(size)
    previous = positive_size(baseline.get('image_size_bytes'))
    if (baseline.get('schema_version') != 1 or baseline.get('allowed_growth_percent') != 5
            or not isinstance(baseline.get('review'), str) or len(baseline['review'].strip()) < 20
            or not isinstance(baseline.get('source_commit'), str)
            or not re.fullmatch('[0-9a-f]{40}', baseline['source_commit'])):
        raise ValueError('invalid reviewed image baseline')
    if size * 100 > previous * 105:
        raise ValueError(f'image_growth: {size} exceeds reviewed {previous} +5%')


def check_comparison(baseline, candidate):
    for row in (baseline, candidate):
        positive_size(row.get('size_bytes'))
        checks = row.get('runtime_checks', {})
        if not all(checks.get(name) is True for name in CHECKS):
            raise ValueError('runtime checks incomplete or failed')
        identity = row.get('identity', {})
        if not all(identity.get(key) for key in ('dependencies', 'runtime_layers', 'static_sha256')):
            raise ValueError('image identity incomplete')
    if baseline['identity'] != candidate['identity']:
        raise ValueError('image identity mismatch')
    if candidate['size_bytes'] >= baseline['size_bytes']:
        raise ValueError('candidate not_smaller than baseline')


PROBE = r'''
import hashlib, importlib.metadata, json, pathlib, subprocess, sys
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024): h.update(block)
    return h.hexdigest()
deps=[]
for dist in importlib.metadata.distributions():
    files=[]
    for item in sorted(dist.files or [], key=str):
        if str(item).endswith('.pyc') or item.name in {'RECORD','direct_url.json','INSTALLER','REQUESTED'}: continue
        path=pathlib.Path(dist.locate_file(item))
        if path.is_file(): files.append([str(item),digest(path)])
    deps.append([dist.metadata['Name'].lower().replace('_','-'),dist.version,files])
static=pathlib.Path('/app/static')
h=hashlib.sha256()
for path in sorted(static.rglob('*')):
    if path.is_file(): h.update(str(path.relative_to(static)).encode()+b'\0'+path.read_bytes())
print(json.dumps({'python':sys.version,'dependencies':sorted(deps),
 'static_sha256':h.hexdigest(),
 'os_packages':subprocess.check_output(['dpkg-query','-W','-f=${Package}=${Version}\n'],text=True).splitlines(),
 'npm':json.loads(subprocess.check_output(['npm','list','--global','--depth=0','--json'],text=True))}))
'''


class Measurement:
    def __init__(self, directory):
        self.directory = directory
        self.deadline = time.monotonic() + 12 * 60
        self.commands = []

    def command(self, name, arguments, *, limit=180):
        path = self.directory / (name + '.log')
        timeout = min(limit, self.deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('image measurement deadline')
        row = {'name': name, 'arguments': arguments, 'log': path.name}
        self.commands.append(row)
        try:
            with path.open('xb') as stream:
                result = subprocess.run(arguments, cwd=REPO, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=timeout)
            row['exit_code'] = result.returncode
        finally:
            if path.exists():
                raw = path.read_bytes()
                row.update(log_sha256=hashlib.sha256(raw).hexdigest(), log_bytes=len(raw))
        if row['log_bytes'] > 8 * 2**20:
            raise ValueError('image evidence log exceeds 8MiB')
        if row['exit_code']:
            raise ValueError('image command failed: ' + name)
        return raw.decode()

    def inspect(self, image):
        return json.loads(self.command(image + '-inspect', ['docker', 'image', 'inspect', image]))[0]

    def build(self, image, dockerfile, *, target=None):
        command = ['docker', 'build', '--progress=plain', '-t', image, '-f', str(dockerfile)]
        if target:
            command.extend(['--target', target])
        raw = self.command(image + '-build', [*command, '.'], limit=600)
        # BuildKit reports rounded units; keep that qualification in the report.
        context_ids = set(re.findall(r'(#\d+) \[internal\] load build context', raw))
        rows = []
        for tag, value, unit in re.findall(r'(#\d+) transferring context: ([\d.]+)([kMGT]?B)', raw):
            if tag in context_ids:
                rows.append({'display': value + unit, 'approximate_bytes': int(float(value) * {
                    'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4}[unit])})
        return rows

    def measure(self, image, runtime_layers, context, *, historical=False):
        info = self.inspect(image)
        if info['RootFS']['Layers'][:len(runtime_layers)] != runtime_layers:
            raise ValueError('runtime base layer identity mismatch')
        history = self.command(image + '-history', ['docker', 'image', 'history', '--no-trunc',
                               '--human=false', '--format', '{{json .}}', image])
        layers = [{'size_bytes': int(row['Size']), 'created_by': row['CreatedBy'], 'id': row['ID']}
                  for row in map(json.loads, history.splitlines())]
        identity = json.loads(self.command(image + '-identity', ['docker', 'run', '--rm',
                              '--entrypoint', 'python', image, '-c', PROBE]))
        # Keep full inventories once in the flushed log, with compact file
        # fingerprints, installed versions and file counts in the report.
        identity['dependencies'] = [[name, version, len(files), hashlib.sha256(
            json.dumps(files, separators=(',', ':')).encode()).hexdigest()]
            for name, version, files in identity['dependencies']]
        identity['runtime_layers'] = runtime_layers
        identity['config'] = {key: info['Config'].get(key) for key in (
            'Env', 'Cmd', 'Entrypoint', 'WorkingDir', 'User', 'ExposedPorts')}
        raw = self.command(image + '-smoke', [sys.executable, 'packages/code-intel/scripts/smoke_image.py',
                           image, *(['--allow-build-tree'] if historical else [])], limit=300)
        smoke = json.loads(raw.splitlines()[-1])
        return {'image': image, 'id': info['Id'], 'size_bytes': info['Size'], 'layers': layers,
                'context_transfer_reported': context, 'identity': identity,
                'inventory_evidence': image + '-identity.log',
                'runtime_checks': {key: smoke.get(key) == 'ok' for key in CHECKS},
                'build_source': smoke['build_source']}


def write_report(path, report):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-ref', help='Exact historical Dockerfile/ignore commit')
    parser.add_argument('--baseline', type=Path, default=REPO / 'docker/code-intel/image-budget.json')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    directory = args.report.parent / 'image-measurement'
    directory.mkdir(exist_ok=False)
    measurement = Measurement(directory)
    started = time.monotonic()
    report = {'status': 'incomplete', 'decision': None, 'commands': measurement.commands}
    write_report(args.report, report)
    try:
        def git(*arguments):
            return subprocess.check_output(['git', *arguments], cwd=REPO).decode().strip()
        report['source_commit'] = git('rev-parse', 'HEAD')
        report['inputs'] = {'package_tree': git('rev-parse', 'HEAD:packages/code-intel'),
                            'frontend_tree': git('rev-parse', 'HEAD:frontend')}
        for name in ('Dockerfile', 'Dockerfile.dockerignore'):
            report['inputs'][name] = hashlib.sha256((REPO / 'docker/code-intel' / name).read_bytes()).hexdigest()
        report['operator_hashes'] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in (
            'eval/quality/image_budget.py', 'packages/code-intel/scripts/smoke_image.py')}
        write_report(args.report, report)
        baseline_context = None
        if args.compare_ref:
            if not re.fullmatch('[0-9a-f]{40}', args.compare_ref):
                raise ValueError('comparison needs an exact historical commit')
            recipe = directory / 'Dockerfile.baseline'
            for relative, target in [('Dockerfile', recipe), ('Dockerfile.dockerignore', Path(str(recipe) + '.dockerignore'))]:
                target.write_bytes(subprocess.check_output(['git', 'show', args.compare_ref + ':docker/code-intel/' + relative], cwd=REPO))
            report['baseline_recipe_commit'] = args.compare_ref
            baseline_context = measurement.build('intelligence-baseline', recipe)
        candidate_context = measurement.build('intelligence-test', REPO / 'docker/code-intel/Dockerfile')
        measurement.build('intelligence-runtime-base', REPO / 'docker/code-intel/Dockerfile', target='runtime-base')
        runtime_layers = measurement.inspect('intelligence-runtime-base')['RootFS']['Layers']
        if args.compare_ref:
            report['baseline'] = measurement.measure('intelligence-baseline', runtime_layers, baseline_context, historical=True)
            write_report(args.report, report)
        report['candidate'] = measurement.measure('intelligence-test', runtime_layers, candidate_context)
        write_report(args.report, report)  # Keep actual measurements before adoption assertions.
        if args.compare_ref:
            check_comparison(report['baseline'], report['candidate'])
            report['decision'] = 'adopt'
            report['saved_bytes'] = report['baseline']['size_bytes'] - report['candidate']['size_bytes']
        else:
            frozen = json.loads(args.baseline.read_bytes())
            report['reviewed_baseline'] = frozen
            check_growth(report['candidate']['size_bytes'], frozen)
            report['decision'] = 'within_reviewed_budget'
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
        raise
    finally:
        report['seconds'] = time.monotonic() - started
        write_report(args.report, report)
    print(json.dumps({key: report.get(key) for key in ('status', 'decision', 'saved_bytes', 'seconds')}))


if __name__ == '__main__':
    main()
