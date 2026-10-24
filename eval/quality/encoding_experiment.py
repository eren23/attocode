"""One prospective unprofiled bounded-JSON cold/restart comparison."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time

from eval.quality.experiment_evidence import Journal
from eval.quality.fixture_identity import source_manifest
from eval.quality.restart_experiment import (
    ORDER,
    admit_phase,
    archive_engine,
    digest,
    engine_files,
    require,
)
from eval.quality.runner import REPO, stop_group, write_json


def decide(rows, expected):
    try:
        require([(r['arm'], r['number']) for r in rows] == ORDER, 'missing/reordered trials')
        for row in rows:
            require(row['status'] == 'complete' and set(row['phases']) == {'cold', 'restart'}, 'incomplete pair')
            for phase in row['phases'].values():
                require(phase['status'] == 'complete' and phase['evidence_sha256'] == expected, 'phase evidence differs')
                value = phase['process_seconds']
                require(type(value) in (int, float) and math.isfinite(value) and value > 0, 'invalid process clock')
        medians = {arm: {kind: statistics.median(r['phases'][kind]['process_seconds']
                    for r in rows if r['arm'] == arm) for kind in ('cold', 'restart')}
                    for arm in ('baseline', 'candidate')}
        ratios = {k: medians['candidate'][k] / medians['baseline'][k] for k in ('cold', 'restart')}
        rounds = {arm: {r['number']: r['phases']['restart']['process_seconds'] for r in rows if r['arm'] == arm}
                  for arm in ('baseline', 'candidate')}
        faster = all(rounds['candidate'][n] < rounds['baseline'][n] for n in range(3))
        return {'status': 'complete', 'decision': 'retain' if ratios['restart'] <= .90 and ratios['cold'] <= 1.05 and faster else 'reject',
                'medians_seconds': medians, 'ratios': ratios, 'every_restart_round_faster': faster,
                'all_twelve_canonical_hashes_equal': True}
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'incomplete', 'decision': None, 'error': str(error)[:2000]}


def run_process(command, evidence, timeout, row, persist, *, env=None):
    spawned, process = time.monotonic_ns(), None
    row.update(parent_spawn_ns=spawned, worker_pid=None, status='incomplete', timed_out=False)
    persist()
    failed = False
    try:
        with (evidence / 'process.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=REPO, env=env if env is not None else dict(os.environ),
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            row['worker_pid'] = process.pid
            persist()
            return process.wait(timeout=timeout)
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
                       parent_exit_ns=exited, parent_wall_seconds=(exited-spawned)/1e9)
            persist()


def run(root):
    import yaml

    from eval.quality.corpus import PACK, materialize

    design = json.loads((REPO / 'eval/quality/experiments/encoding.json').read_bytes())
    public = (REPO / design['public_design']).read_bytes()
    require(hashlib.sha256(public).hexdigest() == design['public_design_sha256']
            and json.loads(public) == {k: v for k, v in design.items()
                                      if k not in ('public_design', 'public_design_sha256')},
            'public and executed encoding designs differ')
    require(design['gates'] == {'restart_median_ratio_max': .90, 'cold_median_ratio_max': 1.05,
                               'every_restart_round_faster': True}, 'encoding gate changed')
    baseline = design['baseline_commit']
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    evidence, work = root / 'evidence/restart', root / 'work/restart'
    evidence.mkdir()
    work.mkdir(parents=True)
    journal = Journal(evidence / 'journal', 8 * 2**20)
    report = {'status': 'incomplete', 'decision': None, 'trials': []}
    started = time.monotonic()
    try:
        engines = {arm: archive_engine(commit, work / 'engines' / arm) for arm, commit in [('baseline', baseline), ('candidate', head)]}
        identities = {arm: engine_files(path) for arm, path in engines.items()}
        changed = sorted(p for p in identities['baseline'].keys() | identities['candidate'].keys()
                         if identities['baseline'].get(p) != identities['candidate'].get(p))
        require(changed == design['candidate_files'], 'candidate differs from frozen product scope')
        require({p: identities['candidate'][p] for p in changed} == design['candidate_file_sha256'],
                'archived candidate bytes changed')
        spec = next(p for p in yaml.safe_load(PACK.read_text())['repositories'] if p['id'] == 'cockroach')
        require(spec['commit'] == design['fixture']['commit'] and spec['include'] == design['fixture']['include'], 'fixture specification changed')
        spec.update(definition_line=255, readiness_poll_seconds=1.0)
        spec_path = evidence / 'spec.json'
        write_json(spec_path, spec)
        fixture, receipt = work / 'fixture', {}
        tree = materialize(spec, fixture, root / 'cache/restart-source', receipt=receipt)
        require(source_manifest(fixture) == receipt and len(receipt) == 9758, 'fixture inventory mismatch')
        require(hashlib.sha256((fixture / spec['file']).read_bytes()).hexdigest() == spec['source_sha256'], 'fixture label mismatch')
        fixture_ref = journal.response({'event': 'pinned_fixture'}, receipt)
        write_json(evidence / 'freeze.json', {'baseline': baseline, 'head': head, 'engines': identities,
                    'fixture_ref': fixture_ref, 'tree': tree, 'design_sha256': hashlib.sha256((REPO / 'eval/quality/experiments/encoding.json').read_bytes()).hexdigest(), 'order': ORDER, 'gates': design['gates']})
        expected, pids = None, set()

        def pair(arm, label):
            nonlocal expected
            workspace = work / label
            require(not workspace.exists(), 'workspace already exists')
            shutil.copytree(fixture, workspace, symlinks=True)
            row = {'arm': arm, 'label': label, 'status': 'incomplete', 'phases': {}}
            try:
                for name in ('cold', 'restart'):
                    dest = evidence / (label + '-' + name)
                    dest.mkdir()
                    engine = engines[arm]
                    require(engine_files(engine) == identities[arm] and source_manifest(workspace) == receipt, 'phase input changed')
                    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(engine.parent), str(REPO)]),
                               ATTOCODE_EXPERIMENT_ENGINE=str(engine))
                    command = [sys.executable, '-m', 'eval.quality.restart_experiment', '--workspace', str(workspace),
                               '--spec', str(spec_path), '--evidence', str(dest)]
                    process_row = {'status': 'incomplete'}
                    row['phases'][name] = process_row
                    code = run_process(command, dest, design['phase_seconds'][name], process_row,
                        lambda: write_json(evidence / (label + '.json'), row), env=env)
                    require(code == 0, 'restart phase failed: ' + label + '-' + name)
                    require(process_row['parent_wall_seconds'] < design['phase_seconds'][name],
                            'phase process/cleanup ceiling exceeded')
                    captured = json.loads((dest / 'phase.json').read_bytes())
                    process_row['admission_start_ns'] = time.monotonic_ns()
                    observed = admit_phase(dest, workspace, spec, captured, engine=engine)
                    process_row['admission_end_ns'] = time.monotonic_ns()
                    ready_ref = captured['readiness']['response_ref']
                    ready = json.loads((dest / 'journal' / ready_ref['path']).read_bytes())['structuredContent']['capabilities']['coverage']
                    require(ready['total_files'] == ready['parsed_files'] == ready['reference_indexed_files'] == 4980, 'incomplete pinned navigation coverage')
                    require(captured['pid'] == process_row['worker_pid'], 'worker PID differs from launched process')
                    require(captured['pid'] not in pids and captured['source_sha256'] == digest(receipt), 'phase PID/source identity mismatch')
                    pids.add(captured['pid'])
                    require(source_manifest(workspace) == receipt and engine_files(engine) == identities[arm], 'phase inputs changed')
                    process_row['post_validation_end_ns'] = time.monotonic_ns()
                    expected = observed if expected is None else expected
                    require(observed == expected, 'canonical evidence differs; stop before next phase')
                    require(captured['grammar_navigation']['go_direct'], 'missing native identity')
                    row['phases'][name].update(status='complete', process_seconds=process_row['parent_wall_seconds'],
                        evidence_sha256=observed, pid=captured['pid'], phase_report=dest.name + '/phase.json')
                    write_json(evidence / (label + '.json'), row)
                row['status'] = 'complete'
                return row
            finally:
                shutil.rmtree(workspace)
                row['workspace_removed'] = not workspace.exists()
                write_json(evidence / (label + '.json'), row)

        # This pair must finish before ANY candidate phase and has no performance verdict.
        report['self_consistency'] = pair('baseline', 'baseline-self-consistency')
        write_json(evidence / 'decision.json', report)
        for arm, number in ORDER:
            row = pair(arm, f'{arm}-{number}')
            row['number'] = number
            report['trials'].append(row)
            write_json(evidence / 'decision.json', report)
        report.update(decide(report['trials'], expected))
        require(report['status'] == 'complete', 'incomplete restart comparison')
        require(source_manifest(fixture) == receipt, 'fixture changed')
    except BaseException as error:
        report.update(status='incomplete', decision=None, error={'type': type(error).__name__, 'message': str(error)[:2000]})
        raise
    finally:
        report['seconds'] = time.monotonic() - started
        write_json(evidence / 'decision.json', report)
