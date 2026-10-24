"""One unchanged-engine cold/reference/restart diagnostic without profiling."""
# ruff: noqa: E402 -- record module entry before importing observer machinery.
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
    from eval.quality.stage_clocks import StageClocks, WorkspaceStages, hook_targets

    evidence.mkdir(exist_ok=True)
    clocks = StageClocks(evidence / 'clocks')
    timeline = {'entry_ns': ENTRY_NS, 'observer_ready_ns': time.monotonic_ns(), 'status': 'incomplete'}

    def point(label):
        timeline[label] = time.monotonic_ns()
        write_json(evidence / 'timeline.json', timeline)

    def imports():
        from attocode_intel import gateway

        from eval.quality import restart_experiment
        return restart_experiment, gateway, hook_targets()

    point('imports_start_ns')
    trial, gateway, targets = clocks.call('main.imports', imports)
    point('imports_end_ns')
    original_source, original_native = trial.source_manifest, trial.native_identity
    original_navigate, original_ready = trial.navigate, trial.wait_ready
    sequence = iter(('source-before', 'source-after'))

    def source(root):
        label = next(sequence)
        point(label + '_start_ns')
        result = clocks.call('main.' + label, original_source, root)
        point(label + '_end_ns')
        return result

    def native():
        point('native_start_ns')
        result = clocks.call('main.native', original_native)
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

    failed = False
    try:
        if sys.getprofile() is not None:
            raise ValueError('profiler active before stage observation')
        point('phase_start_ns')
        with (WorkspaceStages(clocks, targets=targets), patch.object(trial, 'source_manifest', source),
              patch.object(trial, 'native_identity', native), patch.object(trial, 'navigate', navigate),
              patch.object(trial, 'wait_ready', readiness)):
            point('observer_installed_ns')
            trial.phase(workspace, spec_path, evidence)
        point('phase_end_ns')
        timeline['remaining_threads'] = [{'name': t.name, 'ident': t.ident, 'native_id': t.native_id}
                                         for t in threading.enumerate()]
        timeline['status'] = 'complete'
    except BaseException as error:
        failed = True
        timeline.update(status='incomplete', error_type=type(error).__name__)
        raise
    finally:
        try:
            clocks.close()
        except BaseException as error:
            timeline.update(status='incomplete', observer_error=type(error).__name__)
            if not failed:
                raise
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
    """Persist attempted phase boundaries even if launch, timeout or cleanup raises."""
    from eval.quality.runner import REPO, stop_group

    spawned, process = time.monotonic_ns(), None
    row.update(parent_spawn_ns=spawned, worker_pid=None, status='incomplete', timed_out=False)
    persist()
    failed = False
    try:
        with (evidence / 'process.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=REPO, env=dict(os.environ), stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            row['worker_pid'] = process.pid
            persist()
            code = process.wait(timeout=timeout)
        return code
    except BaseException as error:
        failed = True
        row.update(error_type=type(error).__name__, timed_out=isinstance(error, subprocess.TimeoutExpired))
        raise
    finally:
        try:
            if process is not None:
                stop_group(process)
        except BaseException as cleanup:
            row['cleanup_error'] = type(cleanup).__name__
            if not failed:
                raise
        finally:
            exited = time.monotonic_ns()
            row.update(exit_code=process.poll() if process is not None else None,
                       parent_exit_ns=exited, parent_wall_seconds=(exited - spawned) / 1e9)
            persist()


def run(root):
    import yaml

    from eval.quality.corpus import PACK, materialize
    from eval.quality.experiment_evidence import Journal
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.restart_experiment import admit_phase, digest, engine_files, require
    from eval.quality.runner import REPO, write_json
    from eval.quality.stage_clocks import admit_records

    design_path = REPO / 'eval/quality/experiments/stages.json'
    design = json.loads(design_path.read_bytes())
    engine = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    require(design['diagnostic_only'] and digest(engine_files(engine)) == design['engine_files_sha256'], 'frozen engine differs')
    require(hashlib.sha256(PACK.read_bytes()).hexdigest() == design['workflow_manifest_sha256'], 'fixture manifest changed')
    spec = next(s for s in yaml.safe_load(PACK.read_bytes())['repositories'] if s['id'] == 'cockroach')
    require(spec['commit'] == design['fixture_commit'] and spec['include'] == design['fixture_include'], 'fixture changed')
    spec.update(definition_line=255, readiness_poll_seconds=1.0)
    evidence, workspace = root / 'evidence/stages', root / 'work/fixture'
    evidence.mkdir()
    workspace.mkdir()
    journal = Journal(evidence / 'journal', 8 * 2**20)
    report = {'status': 'incomplete', 'decision': None, 'diagnostic_only': True, 'phases': {}}
    started, expected, pids, previous_end = time.monotonic(), None, set(), 0
    try:
        receipt = {}
        tree = materialize(spec, workspace, root / 'cache/source', receipt=receipt)
        require(source_manifest(workspace) == receipt and len(receipt) == 9758, 'fixture inventory differs')
        require(hashlib.sha256((workspace / spec['file']).read_bytes()).hexdigest() == spec['source_sha256'], 'selected source changed')
        spec_path = evidence / 'spec.json'
        write_json(spec_path, spec)
        fixture_ref = journal.response({'event': 'pinned_fixture', 'commit': spec['commit'], 'tree': tree}, receipt)
        write_json(evidence / 'freeze.json', {'engine_files': engine_files(engine), 'engine_commit': design['engine_commit'],
                   'fixture_ref': fixture_ref, 'tree': tree, 'design_sha256': hashlib.sha256(design_path.read_bytes()).hexdigest()})
        for name in ('cold', 'reference', 'restart'):
            dest = evidence / name
            dest.mkdir()
            validation_start = time.monotonic_ns()
            require(source_manifest(workspace) == receipt and digest(engine_files(engine)) == design['engine_files_sha256'], 'phase input changed')
            if name != 'cold':
                write_json(evidence / ('cache-before-' + name + '.json'), cache_inventory(workspace))
            module = 'eval.quality.restart_experiment' if name == 'reference' else 'eval.quality.stages_experiment'
            command = [sys.executable, '-m', module, '--workspace', str(workspace), '--spec', str(spec_path), '--evidence', str(dest)]
            row = {'pre_spawn_validation_start_ns': validation_start, 'instrumented': name != 'reference'}
            report['phases'][name] = row
            code = run_process(command, dest, design['phase_seconds'][name], row,
                               lambda: write_json(evidence / 'diagnostic.json', report))
            require(previous_end <= row['parent_spawn_ns'], 'phase chronology differs')
            require(code == 0 and row['parent_wall_seconds'] < design['phase_seconds'][name], 'phase failed or exceeded process/cleanup ceiling')
            captured = json.loads((dest / 'phase.json').read_bytes())
            row['admission_start_ns'] = time.monotonic_ns()
            observed = admit_phase(dest, workspace, spec, captured, engine=engine)
            row['admission_end_ns'] = time.monotonic_ns()
            require(captured['pid'] == row['worker_pid'] and captured['pid'] not in pids
                    and captured['source_sha256'] == digest(receipt), 'launched PID/source differs')
            pids.add(captured['pid'])
            expected = observed if expected is None else expected
            require(expected == observed, 'canonical operation data differs')
            ready_ref = captured['readiness']['response_ref']
            coverage = json.loads((dest / 'journal' / ready_ref['path']).read_bytes())['structuredContent']['capabilities']['coverage']
            require(coverage['total_files'] == coverage['parsed_files'] == coverage['reference_indexed_files'] == 4980, 'full readiness differs')
            if name != 'reference':
                timeline = json.loads((dest / 'timeline.json').read_bytes())
                require(timeline['status'] == 'complete'
                        and row['parent_spawn_ns'] < timeline['entry_ns'] < timeline['worker_finish_ns'] < row['parent_exit_ns'], 'incomplete worker timeline')
                manifest = json.loads((dest / 'clocks/manifest.json').read_bytes())
                spans = admit_records(dest / 'clocks', manifest)
                require(manifest['max_records'] == design['stage_limits']['records']
                        and manifest['max_bytes'] == design['stage_limits']['bytes'] and spans, 'observer scope/bounds differ')
                roots = [r['label'] for r in spans if r['label'].startswith('executor:')]
                require(all(any(target in label for label in roots) for target in ('_execute_sync', '_warm_search', '_close_stores')), 'actual executor coverage incomplete')
                labels = {r['label'] for r in spans}
                required = design['required_stages'][name]
                require(set(required) <= labels, 'frozen stage coverage incomplete: ' + str(set(required) - labels))
                row['stage_records'] = len(spans)
            if name != 'cold':
                write_json(evidence / ('cache-after-' + name + '.json'), cache_inventory(workspace))
            require(source_manifest(workspace) == receipt and digest(engine_files(engine)) == design['engine_files_sha256'], 'phase inputs changed')
            row.update(status='complete', pid=captured['pid'], evidence_sha256=observed,
                       inner_seconds=captured['seconds'], readiness_seconds=captured['readiness']['seconds'])
            row['post_validation_end_ns'] = previous_end = time.monotonic_ns()
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
