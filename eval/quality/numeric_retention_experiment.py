"""Paired numeric-admission diagnostic with isolated, attested engine processes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.corpus_capture import RecordedGateway, digest
from eval.quality.experiment_evidence import Journal, assert_engine
from eval.quality.fixture_identity import source_manifest
from eval.quality.mcp_search import decode, engine_identity, evidence_hits, observe
from eval.quality.numeric_query_experiment import materialize_bound
from eval.quality.restart_experiment import archive_engine, engine_files
from eval.quality.runner import REPO, write_json

BASELINE = 'd1399be0684835e8b704eac440e5a2ebfbaf617f'
ROLES = {'primary': (10, 2000), 'deep': (24, 8000), 'scoped': (5, 4000)}
SENTINEL = 'numeric_retention_readiness_control_20261110'
INPUTS = REPO / 'eval/quality/numeric_retention'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare_engines(work, patch):
    engines = {arm: archive_engine(BASELINE, work/'engines'/arm)
               for arm in ('baseline', 'candidate')}
    before = engine_files(engines['baseline'])
    require(engine_files(engines['candidate']) == before, 'archive engines differ before patch')
    relative = Path(patch['path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe patch path')
    target = engines['candidate']/relative
    raw = target.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == patch['before_sha256'], 'patch baseline hash mismatch')
    old, new = patch['before'].encode(), patch['after'].encode()
    require(raw.count(old) == 1, 'patch anchor not unique')
    changed = raw.replace(old, new)
    require(hashlib.sha256(changed).hexdigest() == patch['after_sha256'], 'patch treatment hash mismatch')
    target.write_bytes(changed)
    after = engine_files(engines['candidate'])
    require(sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
            == [relative.as_posix()], 'undeclared treatment files')
    return engines


def trial_order(repositories):
    require(len(repositories) == 2 and len(set(repositories)) == 2, 'expected two distinct repositories')
    pairs = [(repositories[0], 'baseline'), (repositories[0], 'candidate'),
             (repositories[1], 'candidate'), (repositories[1], 'baseline')]
    return [{'phase': phase, 'repo_id': repo, 'arm': arm,
             'id': f'{phase}-{repo}-{arm}'}
            for phase in ('primary', 'diagnostic') for repo, arm in pairs]


def child_environment(engine):
    return dict(os.environ, PYTHONPATH=os.pathsep.join([str(engine.parent), str(REPO)]),
                ATTOCODE_EXPERIMENT_ENGINE=str(engine), PYTHONDONTWRITEBYTECODE='1')


def qualify_candidate(root, engine):
    dest = root/'evidence/causal-green'
    dest.mkdir(parents=True)
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=packages/code-intel/tests',
               'packages/code-intel/tests/test_numeric_retention_causal.py', '-q',
               '--junitxml='+str(dest/'pytest.xml'), '--basetemp='+str(root/'work/causal-pytest'),
               '-o', 'cache_dir='+str(root/'work/causal-pytest-cache'),
               '-o', 'pythonpath='+str(engine.parent)]
    before = engine_files(engine)
    with (dest/'pytest.log').open('xb') as stream:
        process = subprocess.run(command, cwd=REPO, env=child_environment(engine),
                                 stdout=stream, stderr=subprocess.STDOUT, check=False)
    require(process.returncode == 0, 'candidate causal assertions failed')
    require(engine_files(engine) == before, 'causal engine changed')
    xml = ET.fromstring((dest/'pytest.xml').read_bytes())
    cases = list(xml.iter('testcase'))
    require(len(cases) == 8 and all(c.find(k) is None for c in cases
                                  for k in ('failure', 'error', 'skipped')), 'causal GREEN inventory mismatch')
    report = {'status': 'complete', 'cases': 8, 'exit_code': 0, 'command': command,
              'engine_files': before}
    write_json(dest/'proof.json', report)
    return report


async def collect_worker(gateway, cases, phase, journal, report, checkpoint):
    require(phase in {'primary', 'diagnostic'}, 'unknown worker phase')
    roles = ['primary'] if phase == 'primary' else ['deep', 'scoped']
    for case in cases:
        for role in roles:
            top_k, budget = ROLES[role]
            scope = case['evidence'][0]['file'] if role == 'scoped' else ''
            arguments = {'query': case['query'], 'top_k': top_k, 'max_tokens': budget,
                         'file_filter': scope, 'mode': 'auto'}
            ref = journal.response({'event': 'consume_request', 'id': case['id'], 'role': role,
                                    'arm': report['arm'], 'repo_id': report['repo_id']}, arguments)
            report['issued'].append({'id': case['id'], 'role': role, 'ref': ref})
            checkpoint()
            page = await observe(gateway, case['query'], top_k=top_k, budget=budget,
                                 file_filter=scope, capture_generation=True)
            page['hits'] = evidence_hits(page['response']['data']['results'], case['evidence'])
            report['pages'].append({'id': case['id'], 'role': role, **page})
            checkpoint()


async def worker_async(workspace, job, evidence):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus import ready_search

    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    require(engine_files(selected) == job['engine_files'], 'selected engine differs from frozen arm')
    before, original_engine = source_manifest(workspace), engine_identity()
    require(digest(before) == job['source_sha256'], 'worker source binding mismatch')
    journal = Journal(evidence/'journal', 6*2**20)
    report = {'status': 'incomplete', 'pid': os.getpid(), 'arm': job['arm'],
              'phase': job['phase'], 'repo_id': job['repo_id'], 'issued': [], 'pages': [],
              'engine_sha256': original_engine, 'source_sha256': digest(before)}
    def checkpoint():
        write_json(evidence/'worker.json', report)
    checkpoint()
    journal.response({'event': 'engine_before'}, {'origins': assert_engine(selected), 'sha256': original_engine})
    journal.response({'event': 'source_before'}, before)
    gateway = RecordedGateway(OperationGateway(str(workspace), 'daily', watch=False), workspace, journal)
    try:
        raw, warmup = await ready_search(gateway, {'query': SENTINEL, 'top_k': 1, 'max_tokens': 2000}, timeout=180)
        index = decode(raw)['data']['ranking']['index']
        require(index['status'] == 'ready' and index['body_index_ready'], 'worker index not ready')
        report.update(warmup=warmup, index=index)
        await collect_worker(gateway, job['cases'], job['phase'], journal, report, checkpoint)
    finally:
        try:
            await gateway.close()
        finally:
            after = source_manifest(workspace)
            journal.response({'event': 'source_after'}, after)
            after_engine = engine_identity()
            journal.response({'event': 'engine_after'}, {'origins': assert_engine(selected), 'sha256': after_engine})
            report['source_unchanged'] = before == after
            report['engine_unchanged'] = original_engine == after_engine and engine_files(selected) == job['engine_files']
            checkpoint()
            require(report['source_unchanged'] and report['engine_unchanged'], 'worker inputs changed')
    report['status'] = 'complete'
    checkpoint()


def execute_workunits(root, manifest, engines, fixtures, inventories, report):
    identities = {arm: engine_files(engine) for arm, engine in engines.items()}
    pids = set()
    for unit in trial_order([r['id'] for r in manifest['repositories']]):
        arm, repo = unit['arm'], unit['repo_id']
        workspace, engine = fixtures[repo, arm], engines[arm]
        dest = root/'evidence/workers'/unit['id']
        dest.mkdir(parents=True)
        require(source_manifest(workspace) == inventories[repo], 'source changed before worker')
        require(engine_files(engine) == identities[arm], 'engine changed before worker')
        spec = {**unit, 'cases': [c for c in manifest['cases'] if c['repo_id'] == repo],
                'source_sha256': digest(inventories[repo]), 'engine_files': identities[arm]}
        job_path = dest/'job.json'
        write_json(job_path, spec)
        row = {**unit, 'status': 'incomplete'}
        report['workers'].append(row)
        write_json(root/'evidence/trial.json', report)
        command = [sys.executable, '-m', 'eval.quality.numeric_retention_experiment',
                   '--worker', '--workspace', str(workspace), '--job', str(job_path), '--evidence', str(dest)]
        with (dest/'process.log').open('xb') as log:
            process = subprocess.run(command, cwd=REPO, env=child_environment(engine),
                                     stdout=log, stderr=subprocess.STDOUT, check=False)
        row['exit_code'] = process.returncode
        write_json(root/'evidence/trial.json', report)
        require(process.returncode == 0, 'numeric worker failed: '+unit['id'])
        child = json.loads((dest/'worker.json').read_bytes())
        require(child['status'] == 'complete' and child['pid'] not in pids, 'incomplete or reused worker')
        pids.add(child['pid'])
        expected = 2 if unit['phase'] == 'primary' else 4
        require(len(child['issued']) == len(child['pages']) == expected, 'worker request cardinality mismatch')
        require(child['source_unchanged'] and child['engine_unchanged'], 'worker source or engine changed')
        require(source_manifest(workspace) == inventories[repo] and engine_files(engine) == identities[arm],
                'worker changed frozen inputs')
        row.update(status='complete', pid=child['pid'], issued=child['issued'])
        write_json(root/'evidence/trial.json', report)


def run(root):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'runtime only in GitHub Actions')
    root = Path(root)
    patch = json.loads((INPUTS/'patch.json').read_bytes())
    manifest = json.loads((INPUTS/'development-questions.json').read_bytes())
    protocol = json.loads((INPUTS/'protocol.json').read_bytes())
    issue = os.environ.get('ATTOCODE_NUMERIC_ISSUE_DEVELOPMENT', 'false')
    require(issue in {'true', 'false'}, 'invalid scientific dispatch flag')
    require(manifest['engine_commit'] == BASELINE and len(manifest['cases']) == 4
            and len(manifest['repositories']) == 2, 'development input mismatch')
    require(protocol['scientific_calls'] == 24 and protocol['roles'] == {
        role: {'top_k': values[0], 'max_tokens': values[1]} for role, values in ROLES.items()}, 'protocol mismatch')
    report = {'status': 'incomplete', 'decision': None, 'scientific_allowed': issue == 'true',
              'baseline_commit': BASELINE, 'workers': [], 'repositories': [],
              'inputs': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(INPUTS.glob('*.json'))}}
    write_json(root/'evidence/trial.json', report)
    engines = prepare_engines(root/'work', patch)
    identities = {arm: engine_files(engine) for arm, engine in engines.items()}
    write_json(root/'evidence/engines.json', {'baseline_commit': BASELINE, 'patch': patch, 'files': identities})
    for arm, engine in engines.items():
        with tarfile.open(root/('evidence/engine-'+arm+'.tar'), 'w') as archive:
            for path in sorted(identities[arm]):
                archive.add(engine/path, arcname=path, recursive=False)
    qualify_candidate(root, engines['candidate'])
    if issue == 'false':
        report.update(status='complete', scientific_requests=0)
        write_json(root/'evidence/trial.json', report)
        return
    from eval.quality import corpus
    original = corpus.HISTORY, corpus.CLONES
    corpus.HISTORY, corpus.CLONES = root/'cache/history', root/'cache/unavailable-clones'
    journal = Journal(root/'evidence/sources-journal', 8*2**20)
    fixtures, inventories = {}, {}
    try:
        for spec in manifest['repositories']:
            repo = spec['id']
            require(repo and all(c.isalnum() or c in '-_' for c in repo), 'unsafe repository identifier')
            master = root/'work/masters'/repo
            master.mkdir(parents=True)
            tree, pinned, git_ref = materialize_bound(spec, master, root/'cache/sources', journal)
            inventory = source_manifest(master)
            require(inventory == pinned, 'master source does not match pinned Git')
            for case in [c for c in manifest['cases'] if c['repo_id'] == repo]:
                for witness in case['evidence']:
                    raw = (master/witness['file']).read_bytes()
                    require(hashlib.sha256(raw).hexdigest() == witness['source_sha256']
                            and raw.decode().splitlines()[witness['line']-1] == witness['quote'], 'source label changed')
            with tarfile.open(root/('evidence/source-'+repo+'.tar'), 'w') as archive:
                for path in sorted(inventory):
                    archive.add(master/path, arcname=path, recursive=False)
            journal.response({'event': 'source_pinned', 'repo_id': repo}, inventory)
            inventories[repo] = inventory
            report['repositories'].append({**spec, 'tree': tree, 'git_provenance_ref': git_ref,
                                           'source_sha256': digest(inventory)})
            for arm in engines:
                dest = root/'work/fixtures'/(repo+'-'+arm)
                shutil.copytree(master, dest, symlinks=True)
                fixtures[repo, arm] = dest
        execute_workunits(root, manifest, engines, fixtures, inventories, report)
        require(len(report['workers']) == 8 and sum(len(w['issued']) for w in report['workers']) == 24,
                'paired trial cardinality mismatch')
        report.update(status='complete', scientific_requests=24)
    finally:
        corpus.HISTORY, corpus.CLONES = original
        report['source_unchanged'] = all(source_manifest(path) == inventories[repo]
                                       for (repo, _arm), path in fixtures.items())
        report['engines_unchanged'] = all(engine_files(engine) == identities[arm] for arm, engine in engines.items())
        write_json(root/'evidence/trial.json', report)
        require(report['source_unchanged'] and report['engines_unchanged'], 'trial inputs changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    for name in ('workspace', 'job', 'evidence'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'runtime only in GitHub Actions')
    asyncio.run(worker_async(args.workspace, json.loads(args.job.read_bytes()), args.evidence))


if __name__ == '__main__':
    main()
