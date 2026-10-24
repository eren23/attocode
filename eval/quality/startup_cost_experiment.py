"""One cold priming phase and fresh profiled restart of unchanged0.1.17."""
# ruff: noqa: E402 -- record module entry before importing the diagnostic machinery.
from __future__ import annotations

import time

ENTRY_NS = time.monotonic_ns()

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from unittest.mock import patch


def worker(workspace, spec_path, evidence):
    from eval.quality.runner import write_json
    from eval.quality.startup_profile import WorkspaceProfiles, profile_call

    evidence.mkdir(exist_ok=True)
    profiles = evidence / 'profiles'
    timeline = {'entry_ns': ENTRY_NS, 'observer_ready_ns': time.monotonic_ns(), 'status': 'incomplete'}

    def point(label):
        timeline[label] = time.monotonic_ns()
        write_json(evidence / 'timeline.json', timeline)

    def imports():
        from attocode_intel import gateway

        from eval.quality import restart_experiment
        return restart_experiment, gateway

    point('imports_start_ns')
    trial, gateway = profile_call(profiles / 'main-imports.prof', 'main:imports', imports)
    point('imports_end_ns')
    original_source, original_native = trial.source_manifest, trial.native_identity
    original_navigate, original_ready = trial.navigate, trial.wait_ready
    sequence = iter(('source-before', 'source-after'))
    threads = []
    original_start = threading.Thread.start

    def start(thread, *args, **kwargs):
        target = getattr(thread, '_target', None)
        threads.append({'name': thread.name, 'target': getattr(target, '__qualname__', ''),
                        'started_ns': time.monotonic_ns()})
        return original_start(thread, *args, **kwargs)

    def source(root):
        label = next(sequence)
        point(label + '_start_ns')
        result = profile_call(profiles / ('main-' + label + '.prof'), 'main:' + label, original_source, root)
        point(label + '_end_ns')
        return result

    def native():
        point('native_start_ns')
        result = profile_call(profiles / 'main-native.prof', 'main:native', original_native)
        point('native_end_ns')
        return result

    async def readiness(*args, **kwargs):
        point('readiness_start_ns')
        value = await original_ready(*args, **kwargs)
        point('readiness_end_ns')
        return value

    async def navigate(*args, **kwargs):
        point('navigate_start_ns')
        try:
            return await original_navigate(*args, **kwargs)
        finally:
            point('navigate_end_ns')

    try:
        point('phase_start_ns')
        with (WorkspaceProfiles(profiles), patch.object(trial, 'source_manifest', source),
              patch.object(trial, 'native_identity', native), patch.object(trial, 'navigate', navigate),
              patch.object(trial, 'wait_ready', readiness), patch.object(threading.Thread, 'start', start)):
            trial.phase(workspace, spec_path, evidence)
        point('phase_end_ns')
        if any('_run_hydration' in row['target'] for row in threads):
            raise ValueError('restart unexpectedly required unprofiled background AST hydration')
        timeline.update(status='complete', started_threads=threads,
                        loaded_threads=[{'name': t.name, 'ident': t.ident} for t in threading.enumerate()])
    finally:
        point('worker_finish_ns')


def cache_inventory(workspace):
    """Read source-bound compact metadata after shutdown; never keep/mutate the cache DB."""
    path = workspace / '.attocode/index/symbols.db'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        values = dict(conn.execute('SELECT key,value FROM metadata WHERE key IN (?,?)',
            ('structural_snapshot_v4', 'structural_ast_summaries_v1')))
    snapshot_raw, summaries_raw = values['structural_snapshot_v4'], values['structural_ast_summaries_v1']
    snapshot, summaries = json.loads(snapshot_raw), json.loads(summaries_raw)
    missing = sorted(set(snapshot['parsed']) - summaries['files'].keys())
    return {'metadata_observation_only': True, 'raw_cache_retained': False,
            'snapshot_sha256': hashlib.sha256(snapshot_raw.encode()).hexdigest(),
            'summary_sha256': hashlib.sha256(summaries_raw.encode()).hexdigest(),
            'snapshot_bytes': len(snapshot_raw.encode()), 'summary_bytes': len(summaries_raw.encode()),
            'summary_snapshot_sha256': summaries['snapshot'], 'parsers': summaries['parsers'],
            'discovered_files': len(snapshot['discovered']), 'parsed_files': len(snapshot['parsed']),
            'cached_files': len(summaries['files']), 'missing_files': missing,
            'missing_extensions': dict(Counter(Path(p).suffix for p in missing)),
            'cached_languages': dict(Counter(v['language'] for v in summaries['files'].values())),
            'saved_counts': snapshot['counts']}


def run_process(command, evidence, timeout, row, persist):
    """Existing launch behavior extracted unchanged for real timeout/launch controls."""
    from eval.quality.runner import REPO, stop_group

    spawned, process = time.monotonic_ns(), None
    with (evidence / 'process.log').open('xb') as log:
        try:
            process = subprocess.Popen(command, cwd=REPO, env=dict(os.environ), stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            code = process.wait(timeout=timeout)
        finally:
            if process is not None:
                stop_group(process)
    exited = time.monotonic_ns()
    row.update(exit_code=code, parent_spawn_ns=spawned, parent_exit_ns=exited,
               parent_wall_seconds=(exited - spawned) / 1e9, status='incomplete')
    persist()
    return code


def run(root):
    import yaml

    from eval.quality.corpus import PACK, materialize
    from eval.quality.experiment_evidence import Journal
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.restart_experiment import admit_phase, digest, engine_files, require
    from eval.quality.runner import REPO, write_json

    design_path = REPO / 'eval/quality/experiments/startup-cost.json'
    design = json.loads(design_path.read_bytes())
    engine = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    require(design['diagnostic_only'] and digest(engine_files(engine)) == design['engine_files_sha256'],
            'diagnostic engine differs from frozen0.1.17')
    require(hashlib.sha256(PACK.read_bytes()).hexdigest() == design['workflow_manifest_sha256'], 'fixture manifest changed')
    spec = next(s for s in yaml.safe_load(PACK.read_bytes())['repositories'] if s['id'] == 'cockroach')
    require(spec['commit'] == design['fixture_commit'] and spec['include'] == design['fixture_include'], 'fixture changed')
    spec.update(definition_line=255, readiness_poll_seconds=1.0)
    evidence, workspace = root / 'evidence/startup', root / 'work/fixture'
    evidence.mkdir()
    workspace.mkdir()
    journal = Journal(evidence / 'journal', 8 * 2**20)
    report = {'status': 'incomplete', 'decision': None, 'diagnostic_only': True, 'phases': {}}
    started = time.monotonic()
    expected, pids = None, set()
    try:
        receipt = {}
        tree = materialize(spec, workspace, root / 'cache/source', receipt=receipt)
        require(source_manifest(workspace) == receipt and len(receipt) == 9758, 'pinned fixture identity mismatch')
        require(hashlib.sha256((workspace / spec['file']).read_bytes()).hexdigest() == spec['source_sha256'], 'selected source changed')
        spec_path = evidence / 'spec.json'
        write_json(spec_path, spec)
        fixture_ref = journal.response({'event': 'pinned_fixture', 'commit': spec['commit'], 'tree': tree}, receipt)
        write_json(evidence / 'freeze.json', {'engine_files': engine_files(engine), 'engine_commit': design['engine_commit'],
                   'fixture_ref': fixture_ref, 'tree': tree, 'design_sha256': hashlib.sha256(design_path.read_bytes()).hexdigest()})
        for name in ('cold', 'restart'):
            dest = evidence / name
            dest.mkdir()
            validation_start = time.monotonic_ns()
            require(source_manifest(workspace) == receipt and digest(engine_files(engine)) == design['engine_files_sha256'], 'phase input changed')
            if name == 'restart':
                before_cache = cache_inventory(workspace)
                write_json(evidence / 'cache-before-restart.json', before_cache)
                module = 'eval.quality.startup_cost_experiment'
            else:
                module = 'eval.quality.restart_experiment'
            command = [sys.executable, '-m', module, '--workspace', str(workspace), '--spec', str(spec_path), '--evidence', str(dest)]
            row = {'pre_spawn_validation_start_ns': validation_start}
            report['phases'][name] = row
            code = run_process(command, dest, design['phase_seconds'][name], row,
                               lambda: write_json(evidence / 'diagnostic.json', report))
            spawned, exited = row['parent_spawn_ns'], row['parent_exit_ns']
            row['pre_spawn_validation_seconds'] = (spawned - validation_start) / 1e9
            require(code == 0, 'diagnostic phase failed: ' + name)
            captured = json.loads((dest / 'phase.json').read_bytes())
            row['admission_start_ns'] = time.monotonic_ns()
            observed = admit_phase(dest, workspace, spec, captured, engine=engine)
            row['admission_end_ns'] = time.monotonic_ns()
            require(captured['pid'] not in pids and captured['source_sha256'] == digest(receipt), 'worker PID/source mismatch')
            pids.add(captured['pid'])
            expected = observed if expected is None else expected
            require(expected == observed, 'cold/restart operation data differs')
            ready_ref = captured['readiness']['response_ref']
            ready = json.loads((dest / 'journal' / ready_ref['path']).read_bytes())
            coverage = ready['structuredContent']['capabilities']['coverage']
            require(coverage['total_files'] == coverage['parsed_files'] == coverage['reference_indexed_files'] == 4980,
                    'diagnostic did not reach frozen full navigation coverage')
            row.update(status='complete', pid=captured['pid'], evidence_sha256=observed,
                       inner_seconds=captured['seconds'], readiness_seconds=captured['readiness']['seconds'])
            if name == 'restart':
                timeline = json.loads((dest / 'timeline.json').read_bytes())
                require(timeline['status'] == 'complete' and spawned < timeline['entry_ns'] < timeline['worker_finish_ns'] < exited,
                        'missing or non-monotonic worker timeline')
                paths = sorted((dest / 'profiles').glob('task-*.json'))
                tasks = [json.loads(p.read_bytes()) for p in paths]
                require(tasks and all(t['status'] == 'passed' for t in tasks), 'missing or failed executor profiles')
                names = {t['task'].split(':')[0].split('.')[-1] for t in tasks}
                require({'_execute_sync', '_warm_search', '_close_stores'} <= names, 'executor coverage incomplete')
                write_json(evidence / 'cache-after-restart.json', cache_inventory(workspace))
            require(source_manifest(workspace) == receipt and digest(engine_files(engine)) == design['engine_files_sha256'], 'phase inputs changed')
            row['post_validation_end_ns'] = time.monotonic_ns()
            row['harness_after_process_exit_seconds'] = (row['post_validation_end_ns'] - exited) / 1e9
            write_json(evidence / 'diagnostic.json', report)
        report.update(status='complete', all_canonical_data_equal=True)
    finally:
        report['seconds'] = time.monotonic() - started
        write_json(evidence / 'diagnostic.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    options = parser.parse_args()
    worker(options.workspace, options.spec, options.evidence)
