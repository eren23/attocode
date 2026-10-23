"""Frozen preview trial; incomplete evidence never earns a quality verdict."""
from __future__ import annotations

import math
import re


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
    raise NotImplementedError('malformed MCP response must be retained before validation')


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
