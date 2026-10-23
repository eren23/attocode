"""One bounded, diagnostic-only profile of the existing pinned Cockroach pack."""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import itertools
import json
import os
import pstats
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import yaml

from eval.quality.corpus import PACK, materialize
from eval.quality.corpus_capture import admit_worker
from eval.quality.experiment_evidence import Journal
from eval.quality.fixture_identity import source_manifest
from eval.quality.runner import REPO, stop_group, write_json


def profile_summary(path):
    stats = pstats.Stats(str(path))
    rows = [{'file': key[0], 'line': key[1], 'function': key[2], 'primitive_calls': value[0],
             'calls': value[1], 'self_seconds': value[2], 'cumulative_seconds': value[3]}
            for key, value in stats.stats.items()]
    return {'total_calls': stats.total_calls, 'total_seconds': stats.total_tt,
            'by_self': sorted(rows, key=lambda r: r['self_seconds'], reverse=True)[:100],
            'by_cumulative': sorted(rows, key=lambda r: r['cumulative_seconds'], reverse=True)[:100]}


def worker_entry(evidence, arguments):
    from attocode_intel import gateway as gateway_module

    sequence = itertools.count()
    class ProfiledExecutor(gateway_module.ThreadPoolExecutor):
        def submit(self, function, *args, **kwargs):
            number = next(sequence)
            name = getattr(function, '__qualname__', str(function))
            if args and callable(args[0]):
                name = getattr(args[0], '__qualname__', name)
                if len(args) > 2 and isinstance(args[2], str):
                    name += ':' + args[2]
            def observed():
                profiler = cProfile.Profile()
                try:
                    return profiler.runcall(function, *args, **kwargs)
                finally:
                    path = evidence / f'workspace-{number:04d}.prof'
                    profiler.dump_stats(str(path))
                    write_json(path.with_suffix('.json'), {'operation': name, 'sequence': number,
                        'diagnostic_only': True, **profile_summary(path)})
            return super().submit(observed)
    profiler = cProfile.Profile()
    sys.argv = ['corpus', *arguments]
    try:
        with patch.object(gateway_module, 'ThreadPoolExecutor', ProfiledExecutor):
            profiler.runcall(runpy.run_module, 'eval.quality.corpus', run_name='__main__')
    finally:
        path = evidence / 'worker.prof'
        profiler.dump_stats(str(path))
        write_json(evidence / 'profile.json', {'diagnostic_only': True,
            'limitations': 'cProfile changes timings. Main and actual workspace executor operations are profiled separately; other index threads/native internals are not independently sampled. No speed or full compatibility verdict.',
            **profile_summary(path)})


def run(root):
    design = json.loads((Path(__file__).with_name('experiments') / 'broad-cost.json').read_bytes())
    if not design['diagnostic_only'] or hashlib.sha256(PACK.read_bytes()).hexdigest() != design['workflow_manifest_sha256']:
        raise ValueError('diagnostic source design changed')
    spec = next(s for s in yaml.safe_load(PACK.read_text())['repositories'] if s['id'] == design['pack'])
    evidence = root / 'evidence/cost'
    evidence.mkdir()
    fixture = root / 'work/fixture'
    fixture.mkdir()
    cache = root / 'cache/grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), cache)
    os.environ['QUALITY_GRAMMAR_CACHE'] = str(cache)
    os.environ['ATTOCODE_CORPUS_EVIDENCE'] = str(evidence)
    row = {'id': spec['id'], 'diagnostic_only': True, 'complete': False, 'decision': None}
    started = time.monotonic()
    try:
        receipt = {}
        row['tree'] = materialize(spec, fixture, root / 'cache/blobs', receipt=receipt)
        journal = Journal(evidence / spec['id'] / 'fixture', 8 * 2**20)
        row['fixture_ref'] = journal.response({'event': 'fixture_pinned', 'repo': spec['repo'],
            'commit': spec['commit'], 'tree': row['tree']}, receipt)
        if source_manifest(fixture) != receipt:
            raise ValueError('diagnostic fixture identity differs from pinned blobs')
        row['setup_seconds'] = time.monotonic() - started
        write_json(evidence / 'spec.json', spec)
        write_json(evidence / 'diagnostic.json', row)
        command = [sys.executable, '-m', 'eval.quality.broad_cost_experiment', '--profile-worker', str(evidence),
            '--worker', str(fixture), '--spec', str(evidence / 'spec.json'),
            '--output', str(evidence / 'worker.json')]
        process = subprocess.Popen(command, cwd=REPO, start_new_session=True)
        try:
            code = process.wait(timeout=design['worker_seconds'])
        finally:
            stop_group(process)
        if code:
            raise ValueError('diagnostic worker failed')
        row.update(json.loads((evidence / 'worker.json').read_bytes()))
        row['admission'] = admit_worker(fixture, spec, evidence / spec['id'], row,
            Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE']))
        row['complete'] = True
    finally:
        row['seconds'] = time.monotonic() - started
        write_json(evidence / 'diagnostic.json', row)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile-worker', type=Path, required=True)
    options, remaining = parser.parse_known_args()
    worker_entry(options.profile_worker, remaining)
