"""Frozen restart comparison, guarded by a baseline-only self-consistency pair."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath

from eval.quality.experiment_evidence import Journal, assert_engine, read_source
from eval.quality.fixture_identity import source_manifest
from eval.quality.runner import REPO, write_json

ORDER = [('baseline', 0), ('candidate', 0), ('candidate', 1),
         ('baseline', 1), ('baseline', 2), ('candidate', 2)]
DESIGN = REPO / 'eval/quality/experiments/restart.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def navigation_requests(spec):
    selection = {'symbol_name': spec['symbol'], 'file_path': spec['file'], 'line': spec['definition_line']}
    return [
        ('definition', 'search_symbols', {'name': spec['symbol']}),
        ('source', 'inspect_symbol', selection),
        ('caller_syntax', 'cross_references', selection),
        ('dependencies', 'dependencies', {'path': spec['file']}),
        ('tests', 'suggest_tests', {'files': [spec['file']]}),
        ('scoped_search', 'semantic_search', {'query': spec['symbol'], 'file_filter': spec['file'], 'top_k': 5}),
        *[(q['id'], 'semantic_search', {'query': q['query'], 'top_k': 24}) for q in spec.get('queries', [])],
    ]


def canonical(operation, data):
    # CallToolResult metadata is already outside data. Only this nested index
    # object is readiness metadata; keep all other fields and every list order.
    if operation == 'semantic_search' and isinstance(data.get('ranking'), dict):
        return {**data, 'ranking': {k: v for k, v in data['ranking'].items() if k != 'index'}}
    return data


def validate_operation(workspace, spec, label, operation, data):
    if label == 'definition':
        require(any(r['file_path'] == spec['file'] and r['start_line'] == spec['definition_line']
                    and r['name'] == spec['symbol'] for r in data), 'selected definition missing')
    elif label == 'source':
        require(data['status'] == 'found' and data['definition']['file_path'] == spec['file']
                and data['definition']['start_line'] == spec['definition_line'], 'selected source missing')
        excerpt = data['source']
        require(spec['anchor'] in excerpt['text'], 'selected source anchor missing')
        # inspect_symbol uses replacement UTF-8, splitlines, then joins with LF.
        lines = read_source(workspace / spec['file'], errors='replace', newlines='universal').splitlines()
        start, end = excerpt['start_line'], excerpt['end_line']
        require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines)
                and excerpt['text'] == '\n'.join(lines[start - 1:end]), 'source coordinates/text mismatch')
    elif operation == 'semantic_search':
        require(bool(data.get('results')), 'semantic search has no results')
        if label == 'scoped_search':
            require(all(r['file_path'] == spec['file'] for r in data['results']), 'scope changed')


async def navigate(workspace, spec, evidence, journal):
    from attocode_intel.gateway import OperationGateway

    gateway = OperationGateway(str(workspace), 'daily', watch=False)
    report = {'status': 'incomplete', 'operations': [], 'pid': os.getpid()}
    hashes = {}
    started = time.monotonic()
    try:
        for label, operation, arguments in navigation_requests(spec):
            before, warming = time.monotonic(), 0
            while True:
                response = await gateway.execute(operation, arguments)
                ref = journal.response({'event': 'operation', 'label': label, 'operation': operation,
                                        'arguments': arguments}, response.model_dump(mode='json'))
                require(not response.isError, 'gateway operation failed: ' + label)
                data = response.structuredContent['data']
                if (operation != 'semantic_search' or
                        data.get('ranking', {}).get('index', {}).get('status') != 'warming'):
                    break
                warming += 1
                await asyncio.sleep(.1)
            validate_operation(workspace, spec, label, operation, data)
            hashes[label] = digest(canonical(operation, data))
            report['operations'].append({'label': label, 'operation': operation, 'arguments': arguments,
                'response_ref': ref, 'canonical_sha256': hashes[label],
                'seconds': time.monotonic() - before, 'warming_responses': warming})
            write_json(evidence / 'phase.json', report)
        report['status'] = 'complete'
    except BaseException as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)[:2000]}
        raise
    finally:
        try:
            await gateway.close()
        except BaseException as error:
            report.update(status='incomplete', close_failure=type(error).__name__)
            journal.response({'event': 'gateway_close'}, {'status': 'failed', 'type': type(error).__name__})
            raise
        else:
            journal.response({'event': 'gateway_close'}, {'status': 'complete'})
        finally:
            report.update(seconds=time.monotonic() - started, evidence_sha256=digest(hashes))
            write_json(evidence / 'phase.json', report)
    return report


def admit_phase(evidence, workspace, spec, summary, *, engine=None):
    from mcp.types import CallToolResult

    require(summary['status'] == 'complete', 'phase incomplete')
    journal = evidence / 'journal'
    completed, hashes, closed, runtime = [], {}, False, {}
    expected = navigation_requests(spec)
    for event in map(json.loads, (journal / 'events.jsonl').read_text().splitlines()):
        ref = event['response']
        require(isinstance(ref['sha256'], str) and len(ref['sha256']) == 64
                and all(c in '0123456789abcdef' for c in ref['sha256']) and type(ref['bytes']) is int,
                'invalid raw reference identity')
        require(str(PurePosixPath(ref['path'])) == f'blobs/{ref["sha256"]}.json', 'unsafe response reference')
        raw = (journal / ref['path']).read_bytes()
        require(len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256'], 'response bytes changed')
        request, value = event['request'], json.loads(raw)
        if request['event'] == 'operation':
            require(len(completed) < len(expected), 'extra operation capture')
            label, operation, arguments = expected[len(completed)]
            require(request == {'event': 'operation', 'label': label, 'operation': operation, 'arguments': arguments},
                    'raw operation binding/order mismatch')
            response = CallToolResult.model_validate(value)
            require(not response.isError, 'raw operation failed')
            data = response.structuredContent['data']
            if (operation == 'semantic_search' and
                    data.get('ranking', {}).get('index', {}).get('status') == 'warming'):
                continue
            validate_operation(workspace, spec, label, operation, data)
            row = summary['operations'][len(completed)]
            sha = digest(canonical(operation, data))
            require(all(row[k] == v for k, v in {'label': label, 'operation': operation,
                    'arguments': arguments, 'response_ref': ref, 'canonical_sha256': sha}.items()), 'phase summary/raw mismatch')
            hashes[label] = sha
            completed.append(label)
        elif request['event'] == 'gateway_close':
            require(value['status'] == 'complete' and not closed, 'unverified gateway shutdown')
            closed = True
        elif request['event'] in {'origin_start', 'origin_end', 'source_before', 'source_after', 'grammar_navigation'}:
            require(request['event'] not in runtime, 'duplicate runtime identity')
            runtime[request['event']] = value
    require(closed and len(completed) == len(expected) == len(summary['operations'])
            and summary['evidence_sha256'] == digest(hashes), 'missing or changed canonical phase evidence')
    if engine is not None:
        require(set(runtime) == {'origin_start', 'origin_end', 'source_before', 'source_after', 'grammar_navigation'},
                'missing child runtime identity')
        for key in ('origin_start', 'origin_end'):
            require(runtime[key].get('attocode_intel') == '__init__.py', 'wrong package origin')
            for module, relative in runtime[key].items():
                path = PurePosixPath(relative)
                require(module.startswith('attocode_intel') and not path.is_absolute() and '..' not in path.parts
                        and (engine / path).is_file(), 'child module outside selected engine')
        manifest = source_manifest(workspace)
        expected_source = {'sha256': digest(manifest), 'entries': len(manifest)}
        require(runtime['source_before'] == runtime['source_after'] == expected_source
                and summary['source_sha256'] == expected_source['sha256'], 'runtime source identity mismatch')
        require(runtime['grammar_navigation'] == summary['grammar_navigation']
                and runtime['grammar_navigation']['go_direct']
                and runtime['grammar_navigation']['loaded'], 'runtime grammar/navigation identity mismatch')
    return digest(hashes)


def decide(rows, expected):
    try:
        require([(r['arm'], r['number']) for r in rows] == ORDER, 'missing/reordered trials')
        for row in rows:
            require(set(row['phases']) == {'cold', 'restart'}, 'missing phase')
            for phase in row['phases'].values():
                require(phase['evidence_sha256'] == expected, 'canonical evidence differs')
                require(type(phase['seconds']) in (int, float) and math.isfinite(phase['seconds'])
                        and phase['seconds'] > 0, 'invalid elapsed phase time')
        medians = {arm: {phase: statistics.median(r['phases'][phase]['seconds'] for r in rows if r['arm'] == arm)
                   for phase in ('cold', 'restart')} for arm in ('baseline', 'candidate')}
        ratios = {p: medians['candidate'][p] / medians['baseline'][p] for p in ('cold', 'restart')}
        return {'status': 'complete', 'decision': 'retain' if ratios['restart'] <= .75 and ratios['cold'] <= 1.05 else 'reject',
                'medians_seconds': medians, 'ratios': ratios, 'all_twelve_canonical_hashes_equal': True}
    except (KeyError, ValueError, TypeError) as error:
        return {'status': 'incomplete', 'decision': None, 'error': str(error)[:2000]}


def engine_files(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def archive_engine(commit, destination):
    prefix = 'packages/code-intel/src/'
    exists = subprocess.run(['git', 'cat-file', '-e', commit + '^{commit}'], capture_output=True).returncode == 0
    if not exists:
        subprocess.run(['git', 'fetch', '--depth', '1', 'origin', commit], check=True)
    raw = subprocess.check_output(['git', 'archive', commit, prefix + 'attocode_intel'])
    require(len(raw) < 16 * 2**20, 'engine archive exceeds bound')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.isdir():
                continue
            require(member.isfile() and member.name.startswith(prefix + 'attocode_intel/'), 'invalid engine archive member')
            relative = PurePosixPath(member.name.removeprefix(prefix))
            require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe engine archive path')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    return destination / 'attocode_intel'


def native_identity():
    from attocode_intel._internal.integrations.context.ast_snapshot import (
        navigation_identity,
        parser_identity,
    )

    files = {}
    for name, module in list(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if name.startswith('tree_sitter') and path:
            p = Path(path)
            if p.is_file() and p.suffix in {'.py', '.so', '.pyd', '.dylib', '.dll'}:
                files[name] = {'filename': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    return {'navigation': navigation_identity(), 'go_direct': parser_identity('go'), 'loaded': files}


def phase(workspace, spec_path, evidence):
    journal = Journal(evidence / 'journal', 4 * 2**20)
    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    spec = json.loads(spec_path.read_bytes())
    report = None
    try:
        journal.response({'event': 'origin_start'}, assert_engine(selected))
        before = source_manifest(workspace)
        journal.response({'event': 'source_before'}, {'sha256': digest(before), 'entries': len(before)})
        report = asyncio.run(navigate(workspace, spec, evidence, journal))
        identity = native_identity()
        journal.response({'event': 'grammar_navigation'}, identity)
        require(identity['go_direct'] and any(n.startswith('tree_sitter_go') for n in identity['loaded']), 'direct Go grammar not proven')
        after = source_manifest(workspace)
        journal.response({'event': 'source_after'}, {'sha256': digest(after), 'entries': len(after)})
        require(after == before, 'phase source changed')
        journal.response({'event': 'origin_end'}, assert_engine(selected))
        report.update(grammar_navigation=identity, source_sha256=digest(before))
        write_json(evidence / 'phase.json', report)
    except BaseException as error:
        journal.response({'event': 'phase_failure'}, {'type': type(error).__name__, 'message': str(error)[:2000]})
        report = report or (json.loads((evidence / 'phase.json').read_bytes()) if (evidence / 'phase.json').exists() else {})
        report.update(status='incomplete', worker_error={'type': type(error).__name__, 'message': str(error)[:2000]})
        write_json(evidence / 'phase.json', report)
        raise


def run(root):
    import yaml

    from eval.quality.corpus import PACK, materialize

    design = json.loads(DESIGN.read_bytes())
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
        spec['definition_line'] = 255
        spec_path = evidence / 'spec.json'
        write_json(spec_path, spec)
        fixture, receipt = work / 'fixture', {}
        tree = materialize(spec, fixture, root / 'cache/restart-source', receipt=receipt)
        require(source_manifest(fixture) == receipt and len(receipt) == 9758, 'fixture inventory mismatch')
        require(hashlib.sha256((fixture / spec['file']).read_bytes()).hexdigest() == spec['source_sha256'], 'fixture label mismatch')
        fixture_ref = journal.response({'event': 'pinned_fixture'}, receipt)
        write_json(evidence / 'freeze.json', {'baseline': baseline, 'head': head, 'engines': identities,
                    'fixture_ref': fixture_ref, 'tree': tree, 'design_sha256': hashlib.sha256(DESIGN.read_bytes()).hexdigest(), 'order': ORDER})
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
                    phase_started = time.monotonic()
                    with (dest / 'process.log').open('xb') as log:
                        result = subprocess.run(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
                    row['phases'][name] = {'exit_code': result.returncode, 'status': 'incomplete'}
                    write_json(evidence / (label + '.json'), row)
                    require(result.returncode == 0, 'restart phase failed: ' + label + '-' + name)
                    captured = json.loads((dest / 'phase.json').read_bytes())
                    observed = admit_phase(dest, workspace, spec, captured, engine=engine)
                    require(captured['pid'] not in pids and captured['source_sha256'] == digest(receipt), 'phase PID/source identity mismatch')
                    pids.add(captured['pid'])
                    require(source_manifest(workspace) == receipt and engine_files(engine) == identities[arm], 'phase inputs changed')
                    expected = observed if expected is None else expected
                    require(observed == expected, 'canonical evidence differs; stop before next phase')
                    require(captured['grammar_navigation']['go_direct'], 'missing native identity')
                    row['phases'][name].update(status='complete', seconds=time.monotonic() - phase_started,
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    phase(args.workspace, args.spec, args.evidence)
