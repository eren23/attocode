"""Frozen runner-only Cockroach restart comparison; no target code execution."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from eval.quality import runner
from eval.quality.experiment_budget import BudgetGuard

BASE = 'eb3b21d6925d27c1addfe106cbc23b828e2bf4cc'
PREFIX = 'packages/code-intel/src/'
ORDER = [('baseline', 0), ('candidate', 0), ('candidate', 1),
         ('baseline', 1), ('baseline', 2), ('candidate', 2)]
LIMITS = {'total_seconds': 1560, 'trial_seconds': 180, 'scored_seconds': 1200,
          'prepare_seconds': 180, 'correctness_seconds': 180,
          'rss_bytes': 2 * 2**30, 'disk_bytes': 2 * 2**30, 'evidence_bytes': 32 * 2**20}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def engine(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def archive_engine(commit, root):
    raw = subprocess.check_output(['git', 'archive', commit, PREFIX + 'attocode_intel'], timeout=60)
    assert len(raw) < 16 * 2**20
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if not member.isfile():
                continue
            assert member.name.startswith(PREFIX + 'attocode_intel/')
            relative = Path(member.name.removeprefix(PREFIX))
            assert '..' not in relative.parts and not relative.is_absolute()
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    return engine(root)


def fixture_manifest(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raw = os.fsencode(os.readlink(path))
            assert path.resolve().is_relative_to(root.resolve())
            kind = 'symlink'
        elif path.is_file():
            raw, kind = path.read_bytes(), 'file'
        else:
            continue
        rows.append({'path': path.relative_to(root).as_posix(), 'kind': kind,
                     'size': len(raw), 'sha256': digest(raw)})
    return rows


def prepare(args):
    from eval.quality import corpus

    spec = next(p for p in yaml.safe_load(corpus.PACK.read_text())['repositories'] if p['id'] == 'cockroach')
    assert spec['commit'] == '53aadff3cedde4d810c72b69ddd96e6a735d93e7'
    assert spec['include'] == ['pkg/server', 'pkg/cli', 'pkg/sql', 'pkg/kv']
    fixture = args.root / 'fixture'
    fixture.mkdir()
    tree = corpus.materialize(spec, fixture, args.root / 'cache' / 'source')
    rows = fixture_manifest(fixture)
    regular = [r for r in rows if r['kind'] == 'file']
    assert len(rows) == 9758 and len(regular) == 9748
    assert sum(r['size'] for r in rows) == 133715342
    target = fixture / spec['file']
    assert digest(target.read_bytes()) == spec['source_sha256']
    assert target.read_text().splitlines()[254].startswith(spec['anchor'])
    spec['definition_line'] = 255
    runner.write_json(args.out, {'spec': spec, 'source_tree': tree, 'files': rows,
                     'fixture_sha256': digest(json.dumps(rows, sort_keys=True).encode())})


def run_tests(args):
    sys.path.insert(0, str(args.engine))
    import attocode_intel
    import pytest

    assert Path(attocode_intel.__file__).resolve().is_relative_to(args.engine.resolve())
    tests = ['packages/code-intel/tests/test_snapshot_fingerprints.py']
    if args.mode == 'baseline-tests':
        tests[0] += '::test_identical_reparse_reuses_navigation_without_repair'
    else:
        tests += ['packages/code-intel/tests/' + p for p in (
            'test_ast_snapshot.py', 'test_parse_recovery.py', 'test_edit_restart.py', 'test_experiment_budget.py',
            'test_restart_evidence.py')]
    code = pytest.main(['-c', 'packages/code-intel/pyproject.toml', '--confcutdir=packages/code-intel/tests',
                       '-o', 'pythonpath=', *tests, '-q', '-p', 'eval.quality.no_agent', '--junitxml=' + str(args.out)])
    assert all(Path(module.__file__).resolve().is_relative_to(args.engine.resolve())
               for name, module in sys.modules.items() if name.startswith('attocode_intel') and getattr(module, '__file__', None))
    raise SystemExit(code)


def supervised(command, root, env, log, deadline):
    return runner.supervise(command, cwd=runner.REPO, env=env, root=root, log=log, deadline=deadline,
                            max_bytes=LIMITS['disk_bytes'], max_rss=LIMITS['rss_bytes'])


def decision(rows):
    times = {arm: {phase: [row['record'][phase]['seconds'] for row in rows if row['arm'] == arm]
                   for phase in ('cold', 'restart')} for arm in ('baseline', 'candidate')}
    medians = {arm: {phase: statistics.median(values) for phase, values in phases.items()}
               for arm, phases in times.items()}
    ratios = {phase: medians['candidate'][phase] / medians['baseline'][phase] for phase in ('cold', 'restart')}
    identical = len({row['record'][phase]['evidence_sha256'] for row in rows for phase in ('cold', 'restart')}) == 1
    assert identical, 'Canonical navigation/search evidence differs; no performance verdict'
    return {'decision': 'retain' if ratios['restart'] <= .75 and ratios['cold'] <= 1.05 else 'reject',
            'phase_seconds': times, 'medians_seconds': medians, 'ratios': ratios,
            'all_twelve_evidence_identical': identical,
            'scope': 'Matched runner observations with warm OS caches; no ranking/relevance or general host-performance claim.'}


def controller(args):
    assert not args.out.exists()
    args.out.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix='cockroach-restart-', dir=os.environ['RUNNER_TEMP']))
    runner.managed_root(scratch)
    env = dict(runner.environment(scratch), QUALITY_ALLOW_DOWNLOADS='1')
    env['PYTHONPATH'] = str(runner.REPO)
    started, rows = time.monotonic(), []
    deadline = started + LIMITS['total_seconds']
    guard = BudgetGuard([scratch, args.out], args.out, LIMITS, deadline)
    paths = [runner.REPO / p for p in (
        'eval/quality/restart_trial.py', 'eval/quality/restart_worker.py', 'eval/quality/experiment_budget.py',
        'eval/quality/corpus.py', 'eval/quality/runner.py', 'eval/quality/sources.py', 'eval/quality/workflows.yaml',
        'eval/matrix/run.py', 'packages/code-intel/tests/test_snapshot_fingerprints.py',
        'packages/code-intel/tests/test_ast_snapshot.py', 'packages/code-intel/tests/test_parse_recovery.py',
        'packages/code-intel/tests/test_edit_restart.py', 'packages/code-intel/tests/test_experiment_budget.py',
        'packages/code-intel/tests/test_restart_evidence.py',
        'uv.lock', 'packages/code-intel/pyproject.toml')]
    identity = runner.fingerprint(paths)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
    before, error, result = {}, None, {'status': 'incomplete', 'trials': rows}
    try:
        guard.start()
        for arm, commit in [('baseline', BASE), ('candidate', head)]:
            before[arm] = archive_engine(commit, scratch / arm)
        changed = {p for p in before['baseline'].keys() | before['candidate'].keys()
                   if before['baseline'].get(p) != before['candidate'].get(p)}
        assert changed == {'attocode_intel/_internal/integrations/context/ast_snapshot.py',
                           'attocode_intel/_internal/integrations/context/ast_service.py'}
        runner.write_json(args.out / 'freeze.json', {'baseline': BASE, 'head': head, 'engines': before,
             'operator_identity': identity, 'order': ORDER, 'limits': LIMITS,
             'gate': {'restart_median_ratio_max': .75, 'cold_median_ratio_max': 1.05},
             'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT']})
        correctness_deadline = min(deadline, time.monotonic() + LIMITS['correctness_seconds'])
        tests = []
        for arm in ('baseline', 'candidate'):
            guard.check()
            xml = args.out / (arm + '-tests.xml')
            runtime = supervised([sys.executable, '-m', 'eval.quality.restart_trial', '--mode', arm + '-tests',
                '--engine', str(scratch / arm), '--out', str(xml)], scratch, env,
                args.out / (arm + '-tests.log'), correctness_deadline)
            test_row = {'arm': arm, 'runtime': runtime, 'cases': None, 'failures': None}
            tests.append(test_row)
            runner.write_json(args.out / 'correctness.json', tests)
            cases = ET.parse(xml).findall('.//testcase')
            assert cases and not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
            failures = [c for c in cases if c.find('failure') is not None]
            assert runtime['cleanup_verified'] and 'reason' not in runtime
            if arm == 'baseline':
                assert len(cases) == len(failures) == 1 and runtime['exit_code'] == 1
                assert 'identical healthy reparse unnecessarily repaired navigation' in failures[0].find('failure').attrib['message']
            else:
                assert runtime['status'] == 'passed' and not failures
                assert sum(c.attrib['classname'].endswith('test_snapshot_fingerprints') for c in cases) == 8
                assert sum(c.attrib['classname'].endswith('test_experiment_budget') for c in cases) == 3
                assert sum(c.attrib['classname'].endswith('test_restart_evidence') for c in cases) == 2
            test_row.update(cases=len(cases), failures=len(failures))
            runner.write_json(args.out / 'correctness.json', tests)
        assert time.monotonic() < correctness_deadline, 'Correctness admission deadline'
        guard.check()
        manifest = args.out / 'fixture.json'
        preparation_deadline = min(deadline, time.monotonic() + LIMITS['prepare_seconds'])
        runtime = supervised([sys.executable, '-m', 'eval.quality.restart_trial', '--mode', 'prepare',
            '--root', str(scratch), '--out', str(manifest)], scratch, env, args.out / 'prepare.log',
            preparation_deadline)
        runner.write_json(args.out / 'preparation.json', runtime)
        assert runtime['status'] == 'passed' and runtime['cleanup_verified'], runtime
        guard.check()
        fixture = json.loads(manifest.read_text())
        assert fixture_manifest(scratch / 'fixture') == fixture['files']
        assert time.monotonic() < preparation_deadline, 'Preparation admission deadline'
        scored_deadline = min(deadline, time.monotonic() + LIMITS['scored_seconds'])
        expected_evidence = None
        for arm, number in ORDER:
            guard.check()
            assert engine(scratch / arm) == before[arm]
            label = f'{arm}-{number}'
            report = args.out / (label + '.json')
            runtime = supervised([sys.executable, '-m', 'eval.quality.restart_worker', '--engine', str(scratch / arm),
                '--fixture', str(scratch / 'fixture'), '--workspace', str(scratch / 'work' / label),
                '--manifest', str(manifest), '--output', str(report), '--seconds', str(LIMITS['trial_seconds'])],
                scratch, env, args.out / (label + '.log'), min(scored_deadline, time.monotonic() + LIMITS['trial_seconds']))
            row = {'arm': arm, 'number': number, 'runtime': runtime}
            rows.append(row)
            runner.write_json(args.out / 'trials.json', rows)
            assert runtime['status'] == 'passed' and runtime['cleanup_verified'], runtime
            record = json.loads(report.read_text())
            assert record['status'] == 'passed' and record['workspace_removed']
            assert record['cold']['pid'] != record['restart']['pid']
            for phase in ('cold', 'restart'):
                observed = record[phase]['evidence_sha256']
                expected_evidence = observed if expected_evidence is None else expected_evidence
                assert observed == expected_evidence, 'Evidence differs; stop before next trial'
            row['record'] = record
            runner.write_json(args.out / 'trials.json', rows)
            assert fixture_manifest(scratch / 'fixture') == fixture['files']
            assert engine(scratch / arm) == before[arm]
            guard.check()
        assert time.monotonic() < scored_deadline, 'Scored comparison admission deadline'
        result = decision(rows)
        result.update(status='observed', correctness=tests, trials=rows)
    except BaseException as exc:
        error = exc
        result.update(status='incomplete', error_type=type(exc).__name__, error=str(exc), trials=rows)
    finally:
        shutil.rmtree(scratch)
        guard.close()
        result.update(seconds=time.monotonic() - started, cleanup_verified=not scratch.exists(),
            aggregate_sampled_peaks=guard.peaks, budget_violation=guard.violation,
            operator_identity=identity, identities_unchanged=runner.fingerprint(paths) == identity)
        if guard.violation or not result['identities_unchanged'] or time.monotonic() >= deadline:
            result['status'] = 'incomplete'
        if result['status'] != 'observed':
            result['decision'] = None
        runner.write_json(args.out / 'decision.json', result)
        if time.monotonic() >= deadline or runner.disk_bytes(args.out) >= LIMITS['evidence_bytes']:
            result.update(status='incomplete', decision=None, budget_violation=guard.violation or 'finalization_budget')
            runner.write_json(args.out / 'decision.json', result)
        print(json.dumps({'status': result['status'], 'decision': result.get('decision'),
                          'seconds': result['seconds'], 'error': result.get('error')}), flush=True)
    if error:
        raise error
    if result['status'] != 'observed':
        raise RuntimeError('Incomplete comparison; no performance verdict')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['prepare', 'baseline-tests', 'candidate-tests'])
    parser.add_argument('--root', type=Path)
    parser.add_argument('--engine', type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Runtime validation runs only on GitHub Actions; no local fallback.')
    if args.mode == 'prepare':
        prepare(args)
    elif args.mode:
        run_tests(args)
    else:
        controller(args)


if __name__ == '__main__':
    main()
