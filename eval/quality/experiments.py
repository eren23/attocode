"""Manual-only, source-bound experiment dispatch with preserved partial evidence.

Setup belongs to CI; the payload/controller, descendants, scratch, logs and
evidence share one fixed budget. No experiment is a normal CI prerequisite.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from eval.quality.experiment_evidence import assert_engine
from eval.quality.runner import GIB, REPO, environment, managed_root, supervise, write_json

SECONDS = {'preflight': 600, 'native': 1200, 'preview': 600, 'restart': 1800, 'broad': 1200, 'coverage': 600}
OPERATORS = {
    'native': 'eval.quality.native_experiment',
    'preview': 'eval.quality.preview_experiment',
    'restart': 'eval.quality.restart_experiment',
    'coverage': 'eval.quality.coverage_experiment',
}
ENGINE = REPO / 'packages/code-intel/src/attocode_intel'
TESTS = ['test_experiment_evidence.py', 'test_quality_runner.py', 'test_quality_evidence.py',
         'test_image_budget.py', 'test_native_experiment.py', 'test_preview_windows.py', 'test_preview_sources.py', 'test_preview_experiment.py', 'test_preview_admission.py', 'test_restart_experiment.py', 'test_corpus_capture.py', 'test_parse_recovery.py', 'test_experiment_readiness.py', 'test_fixture_source_alias.py', 'test_ast_snapshot.py', 'test_discovery_reuse.py', 'test_index_reuse.py', 'test_cold_index_cost.py', 'test_recovery_readiness.py', 'test_snippet_budget.py', 'test_experiment_dispatch.py', 'test_native_capture.py', 'test_source_exclusions.py', 'test_optional_grammar_admission.py']


def identity(design):
    """Require committed design/operators/engine; never equate a dirty tree to HEAD."""
    roots = ['eval', 'packages/code-intel', 'pyproject.toml',
             'uv.lock', '.github/workflows/intelligence-experiments.yml', str(design.relative_to(REPO))]
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', *roots], cwd=REPO,
                   check=True, stdout=subprocess.DEVNULL)
    unknown = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard',
                                       '--', *roots], cwd=REPO)
    if unknown.strip():
        raise ValueError('uncommitted experiment inputs')
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--', *roots], cwd=REPO).decode().split('\0')
    files = {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in sorted(set(paths)) if p}
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
            'design_sha256': hashlib.sha256(design.read_bytes()).hexdigest(), 'files': files,
            'python': sys.version, 'platform': platform.platform(),
            'github_run_id': os.environ.get('GITHUB_RUN_ID'),
            'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}


def load_operator(name):
    """Qualify a declared synchronous run(root) without executing its body.

    Maintained preflight checks every registration before future manual launches.
    Runtime qualification stays inside the supervised controller and follows its
    selected-engine guard, rather than importing operators in an unbounded parent.
    """
    if name in {'preflight', 'broad'}:
        return None
    module_name = OPERATORS.get(name)
    if module_name is None:
        raise ValueError(f'undeclared experiment operator: {name}')
    try:
        expected = (REPO / Path(*module_name.split('.'))).with_suffix('.py').resolve()
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            raise ModuleNotFoundError(module_name)
        if spec.origin is None or Path(spec.origin).resolve() != expected:
            raise ValueError('operator module is outside its declared source')
        module = importlib.import_module(module_name)
        if Path(module.__file__).resolve() != expected:
            raise ValueError('imported operator source differs from registration')
        operator = getattr(module, 'run', None)
        if not callable(operator) or any(
            check(target)
            for target in (operator, operator.__call__)
            for check in (inspect.iscoroutinefunction, inspect.isgeneratorfunction, inspect.isasyncgenfunction)
        ):
            raise ValueError('operator must provide synchronous non-generator run(root)')
        inspect.signature(operator).bind(Path('.'))
        return operator
    except Exception as error:
        raise ValueError(f'invalid experiment operator {name} ({module_name}): {error}') from error


def payload(name, root):
    """Every controller checks its selected engine before importing an operator."""
    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    origins = assert_engine(selected)
    write_json(root / 'evidence/controller-origin.json', {'pid': os.getpid(), 'origins': origins})
    operator = load_operator(name)
    if name == 'preflight':
        command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
                   '--confcutdir=packages/code-intel/tests', '-q',
                   '--basetemp=' + str(root / 'work/pytest'), '-o', 'cache_dir=' + str(root / 'work/cache'),
                   '--junitxml=' + str(root / 'evidence/preflight.xml'),
                   '-p', 'eval.quality.experiment_origin',
                   *['packages/code-intel/tests/' + test for test in TESTS]]
        subprocess.run(command, cwd=REPO, check=True)
    elif name == 'broad':
        import tomllib

        import yaml
        frozen = json.loads((REPO / 'eval/quality/experiments/broad.json').read_bytes())
        pack_path = REPO / frozen['workflow_manifest']
        specs = yaml.safe_load(pack_path.read_text())['repositories']
        version = tomllib.loads((REPO / 'packages/code-intel/pyproject.toml').read_text())['project']['version']
        if (version != frozen['version'] or hashlib.sha256(pack_path.read_bytes()).hexdigest() != frozen['workflow_manifest_sha256']
                or len(specs) != frozen['expected_packs'] or sum(len(s['queries']) for s in specs) != frozen['expected_questions']):
            raise ValueError('broad version/fixture identity mismatch')
        target = frozen['runtime_target']
        actual = {'sys_platform': sys.platform, 'machine': platform.machine(), 'platform': platform.platform()}
        if any(actual[key] != target[key] for key in ('sys_platform', 'machine')):
            raise ValueError('broad runtime target mismatch')
        write_json(root / 'evidence/runtime-platform.json', {'target': target, 'actual': actual})
        acquired = Path(os.environ['QUALITY_GRAMMAR_CACHE'])
        managed = root / 'cache/grammars'
        shutil.copytree(acquired, managed)
        os.environ['QUALITY_GRAMMAR_CACHE'] = str(managed)
        os.environ['ATTOCODE_CORPUS_EVIDENCE'] = str(root / 'evidence/broad')
        subprocess.run([sys.executable, '-m', 'eval.quality.corpus', '--output',
                        str(root / 'evidence/workflows.json')], cwd=REPO, check=True)
        result = json.loads((root / 'evidence/workflows.json').read_text())
        if not result.get('complete') or not result.get('passed'):
            raise ValueError('incomplete broad compatibility')
    else:
        # Each scored design and operator is introduced/reviewed before dispatch.
        operator(root)
    write_json(root / 'evidence/controller-complete.json', {
        'complete': True, 'origins': assert_engine(selected)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', choices=SECONDS)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--payload', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.payload:
        payload(args.experiment, root)
        return 0
    if root.exists():
        raise ValueError('experiment requires a new attempt directory')
    root = managed_root(root)
    (root / 'evidence').mkdir()
    report = {'experiment': args.experiment, 'status': 'incomplete', 'decision': None,
              'limits': {'seconds': SECONDS[args.experiment], 'disk_bytes': 2 * GIB,
                         'rss_bytes': 2 * GIB, 'evidence_bytes': 64 * 2**20}}
    design = REPO / 'eval/quality/experiments' / (args.experiment + '.json')
    before = None
    started = time.monotonic()
    try:
        before = identity(design)
        frozen = json.loads(design.read_text())
        if frozen['experiment'] != args.experiment or frozen['limits'] != report['limits']:
            raise ValueError('design limit/selection mismatch')
        report['identity'] = before
        report['parent_origins'] = assert_engine(ENGINE)
        write_json(root / 'evidence/report.json', report)
        env = environment(root)
        env.update(ATTOCODE_EXPERIMENT_ENGINE=str(ENGINE),
                   ATTOCODE_EXPERIMENT_EVIDENCE=str(root / 'evidence'),
                   PYTHONPATH=os.pathsep.join([str(ENGINE.parent), str(REPO)]))
        row = supervise([sys.executable, '-m', 'eval.quality.experiments', args.experiment,
                         '--root', str(root), '--payload'], cwd=REPO, env=env, root=root,
                        log=root / 'evidence/payload.log', deadline=started + SECONDS[args.experiment],
                        max_bytes=2 * GIB, max_rss=2 * GIB, include_controller=True,
                        evidence_root=root / 'evidence', max_evidence_bytes=63 * 2**20)
        report['supervision'] = row
        report['cleanup_verified'] = row.get('cleanup_verified') is True
        complete = root / 'evidence/controller-complete.json'
        if (row['status'] == 'passed' and not row['log_truncated'] and complete.is_file()
                and json.loads(complete.read_text()).get('complete') is True):
            report['status'] = 'complete'
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
    finally:
        # Retain evidence/logs even when operators/assertions/cleanup fail.
        try:
            if before is None or identity(design) != before:
                report.update(status='incomplete', reason='inputs_changed_or_unbound')
        except Exception as exc:
            report.update(status='incomplete', reason='identity_recheck_failed',
                          identity_error=type(exc).__name__)
        for name in ('work', 'cache'):
            try:
                shutil.rmtree(root / name)
            except OSError as exc:
                report.update(status='incomplete', cleanup_error=type(exc).__name__)
        report['seconds'] = time.monotonic() - started
        report['owned_scratch_removed'] = all(not (root / name).exists() for name in ('work', 'cache'))
        if report['seconds'] >= SECONDS[args.experiment]:
            report.update(status='incomplete', reason='complete_deadline')
        # Quality decisions are separate operator evidence; incomplete never earns one.
        write_json(root / 'evidence/report.json', report)
    print(json.dumps({k: report[k] for k in ('experiment', 'status', 'decision', 'seconds')}))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
