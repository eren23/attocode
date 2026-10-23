"""Compare explicit native recovery on pinned OCaml after a labeled fault."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from eval.quality.fixture_identity import source_manifest
from eval.quality.restart_experiment import archive_engine, engine_files, require
from eval.quality.runner import REPO, write_json


def run(root, frozen):
    from eval.quality.corpus import materialize
    from eval.quality.native_experiment import grammar_identity

    evidence, work = root / 'evidence/native-recovery', root / 'work/native-recovery'
    evidence.mkdir()
    work.mkdir()
    spec = frozen['ocaml']
    managed = root / 'cache/recovery-grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), managed)
    grammar = grammar_identity(managed)
    fixture, cache = work / 'fixture', root / 'cache/recovery-source'
    pinned = {}
    tree = materialize({'id': 'ocaml-recovery', 'repo': spec['repo'], 'commit': spec['commit'],
                        'include': [spec['file']]}, fixture, cache, receipt=pinned)
    require(source_manifest(fixture) == pinned and len(pinned) == 1
            and pinned[spec['file']]['sha256'] == spec['sha256'], 'OCaml pinned source differs')
    engines = {'baseline': archive_engine(frozen['recovery_pair']['baseline_commit'], work / 'baseline-engine'),
               'candidate': Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])}
    identities = {arm: engine_files(engine) for arm, engine in engines.items()}
    changed = sorted(name for name in identities['baseline'].keys() | identities['candidate'].keys()
                     if identities['baseline'].get(name) != identities['candidate'].get(name))
    require(changed == ['_internal/integrations/context/ast_service.py'], 'unexpected recovery product scope')
    report = {'status': 'incomplete', 'decision': None, 'engines': identities,
              'fixture': pinned, 'fixture_tree': tree, 'grammar': grammar, 'trials': [],
              'scope': 'Controlled native fault/recovery only; not a reproduction of the historical scheduling cause'}
    write_json(evidence / 'recovery-pair.json', report)
    for arm, engine in engines.items():
        workspace, dest = work / arm, evidence / arm
        shutil.copytree(fixture, workspace)
        dest.mkdir()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(engine.parent), str(REPO)]),
                   ATTOCODE_EXPERIMENT_ENGINE=str(engine), QUALITY_GRAMMAR_CACHE=str(managed),
                   ATTOCODE_INTEL_PRECISION='off')
        with (dest / 'process.log').open('xb') as stream:
            result = subprocess.run([sys.executable, '-m', 'eval.quality.native_experiment',
                '--worker', 'gateway', '--workspace', str(workspace), '--evidence', str(dest)],
                cwd=REPO, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=90, check=False)
        require(result.returncode == 0, 'OCaml recovery worker failed: ' + arm)
        outcome = json.loads((dest / 'result.json').read_bytes())
        require(outcome['status'] == 'complete' and outcome['observation']['found'] == (arm == 'candidate'),
                'unexpected native recovery outcome: ' + arm)
        kinds, parsings = {}, []
        for line in (dest / 'journal/events.jsonl').read_bytes().splitlines():
            event = json.loads(line)
            ref = event['response']
            require(ref['path'] == 'blobs/' + ref['sha256'] + '.json', 'unsafe recovery evidence reference')
            raw = (dest / 'journal' / ref['path']).read_bytes()
            require(len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256'],
                    'recovery raw evidence changed')
            value = json.loads(raw)
            if event['request']['event'] == 'native' and value.get('stage') == 'parse':
                parsings.append(value)
            else:
                kinds.setdefault(event['request']['event'], []).append(value)
        require(len(kinds.get('forced_failure_response', [])) == len(kinds.get('gateway_response', [])) == 1,
                'missing initial or later raw response')
        require(kinds['forced_failure_response'][0]['structuredContent']['data']['status'] == 'not_found'
                and kinds['gateway_response'][0]['structuredContent']['data']['status'] ==
                ('found' if arm == 'candidate' else 'not_found'), 'raw recovery status differs')
        require(kinds.get('normal_timeout_restored') == [{'limit_micros': 100000, 'cooldown_wait_seconds': 1.1}],
                'normal recovery limit/wait not proven')
        require(kinds.get('gateway_close') == [{'status': 'complete'}]
                and kinds.get('grammar_identity') == [grammar], 'close or loaded grammar differs')
        for name in ('origin_start', 'origin_end'):
            require(len(kinds.get(name, [])) == 1, 'missing recovery child origins')
            origins = kinds[name][0]
            require(origins.get('attocode_intel') == '__init__.py', 'recovery child package missing')
            require(all(module.startswith('attocode_intel') and relative in identities[arm]
                        for module, relative in origins.items()), 'recovery child origin outside selected engine')
        require(kinds['origin_end'][0].get('attocode_intel._internal.integrations.context.ast_service') ==
                '_internal/integrations/context/ast_service.py', 'recovery implementation not loaded')
        require(all(row['source_sha256'] == outcome['observation']['decoded_source_sha256']
                    and row['bytes'] == pinned[spec['file']]['bytes'] for row in parsings),
                'native recovery parsed different source')
        require(parsings and any(row['limit_micros'] == 1 and row['outcome'] != 'tree' for row in parsings),
                'controlled native failure was not captured')
        if arm == 'candidate':
            require(any(row['limit_micros'] == 100000 and row['outcome'] == 'tree' for row in parsings),
                    'normal-budget recovery tree missing')
        require(source_manifest(workspace) == pinned and engine_files(engine) == identities[arm],
                'recovery source/engine changed')
        report['trials'].append({'arm': arm, 'pid': outcome['pid'], 'outcome': outcome,
                                  'raw_initial_and_final_admitted': True, 'cleanup': 'owned outer supervisor'})
        write_json(evidence / 'recovery-pair.json', report)
    require(report['trials'][0]['pid'] != report['trials'][1]['pid'], 'native arms reused a process')
    report['status'] = 'complete'
    write_json(evidence / 'recovery-pair.json', report)
