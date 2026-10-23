"""Bounded same-runner comparison of metadata counters, without product calls."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import yaml

from eval.quality import runner
from eval.quality.corpus import PACK, materialize
from eval.quality.experiment_evidence import Journal
from eval.quality.fixture_identity import source_manifest
from eval.quality.runner import REPO, write_json


def oracle(root):
    """Independently account names; real directories contribute no file bytes."""
    ordinary, directory_links, names = 0, 0, 0
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in files:
            metadata = os.lstat(os.path.join(parent, name))
            ordinary += max(metadata.st_size, getattr(metadata, 'st_blocks', 0) * 512)
            names += 1
        for name in directories:
            path = Path(parent) / name
            if path.is_symlink():
                metadata = path.lstat()
                directory_links += max(metadata.st_size, getattr(metadata, 'st_blocks', 0) * 512)
                names += 1
    return {'baseline': ordinary, 'candidate': ordinary + directory_links,
            'directory_symlink_bytes': directory_links, 'entries': names}


def run(root):
    design = json.loads(Path(__file__).with_name('experiments').joinpath('disk-cost.json').read_bytes())
    if not design['diagnostic_only'] or hashlib.sha256(PACK.read_bytes()).hexdigest() != design['workflow_manifest_sha256']:
        raise ValueError('counter diagnostic design changed')
    baseline_bytes = subprocess.check_output(['git', 'show', design['baseline_commit'] + ':eval/quality/runner.py'], cwd=REPO)
    text = baseline_bytes.decode()
    function = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'disk_bytes')
    baseline_source = ast.get_source_segment(text, function) + '\n'
    if hashlib.sha256(baseline_source.encode()).hexdigest() != design['baseline_function_sha256']:
        raise ValueError('baseline counter source changed')
    namespace = {'os': os, 'Path': Path}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'pinned-baseline-counter', 'exec'), namespace)
    functions = {'baseline': namespace['disk_bytes'], 'candidate': runner.disk_bytes}
    spec = next(s for s in yaml.safe_load(PACK.read_text())['repositories'] if s['id'] == design['pack'])
    evidence = root / 'evidence/disk-cost'
    evidence.mkdir()
    journal = Journal(evidence / 'journal', 16 * 2**20)
    fixture = root / 'work/fixture'
    fixture.mkdir()
    receipt = {}
    tree = materialize(spec, fixture, root / 'cache/blobs', receipt=receipt)
    # Match the full matrix: discard acquisition blobs before observing the tree.
    shutil.rmtree(root / 'cache/blobs')
    if source_manifest(fixture) != receipt:
        raise ValueError('counter fixture differs from pinned blobs')
    fixture_ref = journal.response({'event': 'fixture_pinned', 'repo': spec['repo'],
        'commit': spec['commit'], 'tree': tree}, receipt)
    before = oracle(fixture)
    source_ref = journal.response({'event': 'counter_sources'}, {'baseline': baseline_source,
        'candidate': inspect.getsource(runner.disk_bytes), 'baseline_file_sha256': hashlib.sha256(baseline_bytes).hexdigest()})
    journal.response({'event': 'oracle_before'}, before)
    rows = []
    report = {'diagnostic_only': True, 'complete': False, 'decision': None, 'tree': tree,
        'fixture_ref': fixture_ref, 'source_ref': source_ref, 'oracle': before, 'rows': rows,
        'scope': 'Pinned source-only metadata tree; no product operations or full-matrix speed prediction'}
    try:
        for phase, order in [('warmup', ['baseline', 'candidate']),
                *[('measured', ['baseline', 'candidate'] if n % 2 == 0 else ['candidate', 'baseline'])
                  for n in range(design['rounds'])]]:
            for arm in order:
                row = {'phase': phase, 'arm': arm, 'sequence': len(rows)}
                wall, cpu = time.perf_counter(), time.process_time()
                try:
                    count = functions[arm](fixture)
                    row['bytes'] = count
                except BaseException as error:
                    row['error'] = type(error).__name__
                    raise
                finally:
                    row.update(wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu)
                    row['response_ref'] = journal.response({'event': 'counter_result', 'sequence': row['sequence']}, dict(row))
                    rows.append(row)
                    write_json(evidence / 'comparison.json', report)
                if count != before[arm]:
                    raise ValueError('counter differs from independent byte oracle')
        after = oracle(fixture)
        journal.response({'event': 'oracle_after'}, after)
        if after != before or source_manifest(fixture) != receipt:
            raise ValueError('counter fixture changed during comparison')
        medians = {arm: {metric: statistics.median(r[metric] for r in rows if r['phase'] == 'measured' and r['arm'] == arm)
            for metric in ('wall_seconds', 'cpu_seconds')} for arm in functions}
        ratios = {metric: medians['candidate'][metric] / medians['baseline'][metric]
            for metric in ('wall_seconds', 'cpu_seconds')}
        report.update(complete=True, medians=medians, ratios=ratios,
            decision='retain_counter' if ratios['cpu_seconds'] <= design['max_cpu_ratio']
                and ratios['wall_seconds'] <= design['max_wall_ratio'] else 'reject_speed_hypothesis')
    finally:
        write_json(evidence / 'comparison.json', report)
