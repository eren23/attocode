"""Frozen preview trial; incomplete evidence never earns a quality verdict."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from eval.quality.experiment_evidence import Journal, assert_engine, encode, read_source
from eval.quality.runner import REPO, write_json

DESIGN = REPO / 'packages/code-intel/evals/designs/2026-10-23-preview-windows.json'


def decide(reports, design):
    try:
        return _decide(reports, design)
    except (KeyError, TypeError, ValueError) as error:
        return {'status': 'incomplete', 'decision': None,
                'error': {'type': type(error).__name__, 'message': str(error)[:2000]}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


async def request_page(gateway, tracker, journal, arguments):
    from attocode_intel.output import response_tokens

    from eval.quality.preview_sources import source_spans
    started = time.perf_counter()
    with tracker.capture():
        response = await gateway.execute_mcp('semantic_search', arguments)
    milliseconds = (time.perf_counter() - started) * 1000
    ref = journal.response({'event': 'mcp_response', 'tool': 'semantic_search', 'arguments': arguments},
                           response.model_dump(mode='json'))
    # Everything above is durable before even malformed JSON is inspected.
    if response.isError or response_tokens(response) > arguments['max_tokens']:
        raise ValueError('MCP search error or output budget violation')
    decoded = json.loads(response.content[0].text)
    data = decoded['data']
    require(isinstance(data['results'], list), 'missing delivered result list')
    index = data['ranking']['index']
    ready = index['status'] == 'ready' and index.get('warmup_stage') == 'ready'
    spans = source_spans(decoded, tracker.root, tracker.policies(decoded)) if ready else None
    return decoded, ref, milliseconds, spans


def requests(question, design):
    config = design['requests']
    return [(depth, budget, '') for depth in config['depths'] for budget in config['budgets']] + [
        (config['scoped_depth'], config['scoped_budget'], question['file'])]


def _decide(reports, design):
    packs = {p['id']: p for p in design['packs']}
    require(len(reports) == len(packs) and {r['pack'] for r in reports} == set(packs), 'pack capture mismatch')
    pairs, timing = {}, {'baseline': [], 'candidate': []}
    for report in reports:
        require(report['status'] == 'complete', 'pack incomplete')
        pack = packs[report['pack']]
        questions = {q['id']: q for q in pack['questions']}
        expected = [(n, arm, q['id'], depth, budget, scope)
                    for n, arms in enumerate(design['rounds']) for arm in arms
                    for q in pack['questions'] for depth, budget, scope in requests(q, design)]
        actual = []
        for row in report['pages']:
            q, args = questions[row['question']], row['arguments']
            require(args['query'] == q['query'] and row['kind'] == q['kind'] and row['split'] == q['split'],
                    'question/request capture mismatch')
            require(type(args['top_k']) is int and type(args['max_tokens']) is int and type(row['round']) is int,
                    'noninteger request/round')
            key = (row['round'], row['arm'], row['question'], args['top_k'], args['max_tokens'], args['file_filter'])
            actual.append(key)
            require(all(type(row['judgment'][k]) is bool for k in ('file', 'visible'))
                    and (not row['judgment']['visible'] or row['judgment']['file']), 'invalid source judgments')
            require(isinstance(row['identity'], list) and re.fullmatch('[0-9a-f]{64}', row['data_sha256']),
                    'invalid delivered capture identity')
            ms = row['milliseconds']
            require(type(ms) in (int, float) and math.isfinite(ms) and ms >= 0, 'invalid measured latency')
            if not args['file_filter']:
                timing[row['arm']].append(ms)
            pair = (report['pack'], row['round'], row['question'], args['top_k'], args['max_tokens'], args['file_filter'])
            by_arm = pairs.setdefault(pair, {})
            require(row['arm'] not in by_arm, 'duplicate paired capture')
            by_arm[row['arm']] = row
        require(actual == expected, 'missing, extra, reordered or misbound captures')
    require(all(set(p) == {'baseline', 'candidate'} for p in pairs.values()), 'unpaired capture')
    losses, identities, controls, gains = [], [], [], {}
    for key, arms in pairs.items():
        old, new = arms['baseline'], arms['candidate']
        for metric in ('file', 'visible'):
            if old['judgment'][metric] and not new['judgment'][metric]:
                losses.append({'key': key, 'metric': metric})
        if old['identity'] != new['identity']:
            identities.append(key)
        if new['kind'] in {'exact', 'unrelated'} and old['data_sha256'] != new['data_sha256']:
            controls.append(key)
        if (new['kind'] == 'behavior' and new['arguments']['top_k'] == 5
                and not new['arguments']['file_filter']
                and new['judgment']['visible'] and not old['judgment']['visible']):
            gains.setdefault((new['round'], new['split']), set()).add((key[0], new['question']))
    gain_gate = all(len(gains.get((r, split), set())) >= 2
                    and len({p for p, _q in gains.get((r, split), set())}) >= 2
                    for r in range(len(design['rounds'])) for split in ('development', 'validation'))
    require(all(timing.values()), 'missing warm measurements')
    p95 = {arm: sorted(values)[math.ceil(.95 * len(values)) - 1] for arm, values in timing.items()}
    latency_gate = p95['candidate'] <= max(100, 1.5 * p95['baseline'])
    passed = gain_gate and latency_gate and not losses and not identities and not controls
    return {'status': 'complete', 'decision': 'retain' if passed else 'reject',
            'gain_gate': gain_gate, 'latency_gate': latency_gate,
            'losses': losses, 'identity_changes': identities, 'control_changes': controls,
            'gains_by_round_and_split': {f'{r}:{s}': sorted(gains.get((r, s), set()))
                for r in range(len(design['rounds'])) for s in ('development', 'validation')},
            'warm_p95_ms': p95, 'pairs': len(pairs),
            'qualification': 'Source-bound non-exhaustive excerpt judgments; no ranking or agent-completion gain.'}


def page_identity(page):
    return [{key: row.get(key) for key in ('file_path', 'name', 'chunk_type', 'score', 'line', 'end_line')}
            for row in page['data']['results']]


def verify_labels(workspace, spec):
    hashes = {path: hashlib.sha256((workspace / path).read_bytes()).hexdigest()
              for path in spec['source_sha256']}
    require(hashes == spec['source_sha256'], 'pinned label source identity mismatch')
    for question in spec['questions']:
        lines = read_source(workspace / question['file'], errors='replace', newlines='universal').splitlines()
        require(all(type(a['line']) is int and 1 <= a['line'] <= len(lines)
                    and lines[a['line'] - 1] == a['quote'] for a in question['anchors']), 'label anchor changed')
    return hashes


def judgment(page, spans, question, workspace, sources):
    found, visible = False, False
    for hit, evidence in zip(page['data']['results'], spans, strict=True):
        if hit['file_path'] != question['file']:
            continue
        found = True
        if not question['anchors'] or evidence['kind'] != 'source':
            continue
        policy = evidence['policy']
        key = question['file'], policy['errors'], policy['newlines']
        if key not in sources:
            content = read_source(workspace / key[0], errors=key[1], newlines=key[2])
            lines = content.splitlines(keepends=True)
            offsets = [0]
            for line in lines:
                offsets.append(offsets[-1] + len(line))
            sources[key] = offsets
        offsets = sources[key]
        anchors = [(offsets[a['line'] - 1], len(a['quote'])) for a in question['anchors']]
        if any(all(begin <= position and position + size <= end for position, size in anchors)
               for begin, end in evidence['spans']):
            visible = True
    return {'file': found, 'visible': visible}


async def observe(spec, workspace, evidence, journal, design):
    from attocode_intel import output, search_evidence
    from attocode_intel.gateway import OperationGateway

    from eval.quality.preview_sources import SourceTracker
    from eval.quality.preview_windows import window_preview

    report = {'status': 'incomplete', 'decision': None, 'pack': spec['id'], 'pages': []}
    started = time.monotonic()
    before = verify_labels(workspace, spec)
    journal.response({'event': 'label_sources'}, before)
    gateway = OperationGateway(str(workspace), 'daily', watch=False)
    tracker = SourceTracker(workspace, journal)
    baseline, label_cache = search_evidence.snippet_window, {}
    warmup_count = 0
    try:
        warm_started = time.monotonic()
        while True:
            _page, _ref, _ms, spans = await request_page(gateway, tracker, journal, {
                'query': spec['questions'][0]['query'], 'top_k': 5, 'max_tokens': 2000, 'file_filter': ''})
            warmup_count += 1
            if spans is not None:
                break
            await asyncio.sleep(.1)
        report['warmup'] = {'responses': warmup_count, 'seconds': time.monotonic() - warm_started}
        for round_number, arms in enumerate(design['rounds']):
            for arm in arms:
                function = baseline if arm == 'baseline' else window_preview
                with patch.object(search_evidence, 'snippet_window', function), patch.object(output, 'snippet_window', function):
                    for question in spec['questions']:
                        for depth, budget, scope in requests(question, design):
                            arguments = {'query': question['query'], 'top_k': depth,
                                         'max_tokens': budget, 'file_filter': scope}
                            page, ref, milliseconds, spans = await request_page(gateway, tracker, journal, arguments)
                            require(spans is not None, 'index became unready during scored capture')
                            row = {'round': round_number, 'arm': arm, 'question': question['id'],
                                   'split': question['split'], 'kind': question['kind'], 'arguments': arguments,
                                   'response_ref': ref, 'milliseconds': milliseconds,
                                   'identity': page_identity(page), 'data_sha256': hashlib.sha256(encode(page['data'])).hexdigest(),
                                   'judgment': judgment(page, spans, question, workspace, label_cache)}
                            # Only compact derived records here; the response already exists once.
                            journal.response({'event': 'validated_page'}, row)
                            report['pages'].append(row)
                            write_json(evidence / 'pages.json', report)
    finally:
        try:
            await gateway.close()
        except BaseException as error:
            journal.response({'event': 'gateway_close'}, {'status': 'failed', 'type': type(error).__name__, 'message': str(error)[:2000]})
            raise
        journal.response({'event': 'gateway_close'}, {'status': 'complete'})
        report['seconds'] = time.monotonic() - started
        write_json(evidence / 'pages.json', report)
    require(verify_labels(workspace, spec) == before, 'label source changed during trial')
    report.update(status='complete', source=before)
    write_json(evidence / 'pages.json', report)
    return report


def worker(pack, workspace, evidence):
    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    journal = Journal(evidence / 'journal', 30 * 2**20)
    try:
        journal.response({'event': 'origin_start'}, assert_engine(selected))
        from eval.quality.corpus import materialize
        assert_engine(selected)
        design = json.loads(DESIGN.read_bytes())
        spec = next(p for p in design['packs'] if p['id'] == pack)
        tree = materialize(spec, workspace, workspace.parent / (pack + '-cache'))
        journal.response({'event': 'fixture'}, {'commit': spec['commit'], 'tree': tree,
                         'repo': spec['repo'], 'include': spec['include']})
        asyncio.run(observe(spec, workspace, evidence, journal, design))
        journal.response({'event': 'origin_end'}, assert_engine(selected))
    except BaseException as error:
        journal.response({'event': 'worker_failure'}, {'type': type(error).__name__, 'message': str(error)[:2000]})
        raise


def run(root):
    frozen = json.loads((REPO / 'eval/quality/experiments/preview.json').read_bytes())
    raw_design = DESIGN.read_bytes()
    require(hashlib.sha256(raw_design).hexdigest() == frozen['design_sha256'], 'frozen design identity mismatch')
    design = json.loads(raw_design)
    evidence, work = root / 'evidence/preview', root / 'work/preview'
    evidence.mkdir()
    work.mkdir(parents=True)
    report = {'status': 'incomplete', 'decision': None, 'workers': []}
    started, observations = time.monotonic(), []
    try:
        for spec in design['packs']:
            destination = evidence / spec['id']
            destination.mkdir()
            workspace = work / spec['id']
            command = [sys.executable, '-m', 'eval.quality.preview_experiment', '--worker', spec['id'],
                       '--workspace', str(workspace), '--evidence', str(destination)]
            row = {'pack': spec['id'], 'command': command, 'status': 'incomplete'}
            report['workers'].append(row)
            write_json(evidence / 'decision.json', report)
            with (destination / 'process.log').open('xb') as stream:
                result = subprocess.run(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT, check=False)
            row['exit_code'] = result.returncode
            require(result.returncode == 0, 'preview worker failed: ' + spec['id'])
            observation = json.loads((destination / 'pages.json').read_bytes())
            require(observation['status'] == 'complete', 'preview worker incomplete')
            row['status'] = 'complete'
            observations.append(observation)
        report.update(decide(observations, design))
        require(report['status'] == 'complete', 'incomplete paired preview evidence')
    except BaseException as error:
        report.update(status='incomplete', decision=None, error={
            'type': type(error).__name__, 'message': str(error)[:2000]})
        raise
    finally:
        report['seconds'] = time.monotonic() - started
        write_json(evidence / 'decision.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    worker(args.worker, args.workspace, args.evidence)
