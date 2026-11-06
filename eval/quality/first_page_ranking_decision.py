"""Strict prospective decisions from admitted data; no product imports or execution."""
import math


def evaluate_split(observations: list[dict], frozen_design: dict) -> dict:
    result = {'complete': False, 'decision': None, 'checks': {}, 'losses': []}
    questions = frozen_design['questions']
    if len(questions) != 24:
        return {**result, 'reason': 'question inventory'}
    expected = {(q, role, n, page) for q in questions for role in ('baseline', 'candidate')
                for n in range(3) for page in ('default', 'deep', 'scoped')}
    rows = {}
    for row in observations:
        try:
            key = row['id'], row['role'], row['round'], row['page']
            valid = (key in expected and key not in rows and type(row['round']) is int
                     and row['query'] == questions[row['id']]['query']
                     and row['pack'] == questions[row['id']]['pack']
                     and row['engine'] == frozen_design['engines'][row['role']]
                     and row['source_sha256'] == frozen_design['source_sha256']
                     and row['complete'] is True and type(row['answer']) is bool
                     and type(row['seconds']) in (float, int) and math.isfinite(row['seconds'])
                     and row['seconds'] >= 0
                     and (row['first_rank'] is None or (type(row['first_rank']) is int
                          and 1 <= row['first_rank'] <= {'default': 10, 'deep': 24, 'scoped': 5}[row['page']]))
                     and all(isinstance(row[k], list) and all(isinstance(x, str) for x in row[k])
                             and len(set(row[k])) == len(row[k]) for k in ('files', 'visible')))
        except (KeyError, TypeError):
            valid = False
        if not valid:
            return {**result, 'reason': 'invalid/duplicate row'}
        rows[key] = row
    if set(rows) != expected:
        return {**result, 'reason': 'missing rows'}
    gains, losses, latency, mrr = [], [], [], []
    for n in range(3):
        winners = set()
        times = {'baseline': [], 'candidate': []}
        reciprocal = {'baseline': 0., 'candidate': 0.}
        for q in questions:
            for page in ('default', 'deep', 'scoped'):
                b, c = (rows[q, role, n, page] for role in ('baseline', 'candidate'))
                lost_files = sorted(set(b['files']) - set(c['files']))
                lost_proofs = sorted(set(b['visible']) - set(c['visible']))
                if (b['answer'] and not c['answer']) or lost_files or lost_proofs:
                    losses.append({'id': q, 'round': n, 'page': page,
                                   'answer': b['answer'] and not c['answer'],
                                   'files': lost_files, 'visible': lost_proofs})
                if page != 'default':
                    continue
                if not b['answer'] and c['answer']:
                    winners.add(q)
                for role, r in (('baseline', b), ('candidate', c)):
                    times[role].append(r['seconds'])
                    reciprocal[role] += 1 / r['first_rank'] if r['first_rank'] else 0
        gains.append(winners)
        p95 = {role: sorted(values)[math.ceil(.95 * len(values)) - 1] for role, values in times.items()}
        latency.append(p95['candidate'] <= max(.250, p95['baseline'] * 1.25)
                       and max(times['candidate']) <= 2.)
        mrr.append(reciprocal['candidate'] >= reciprocal['baseline'])
    stable = set.intersection(*gains)
    checks = {'three_stable_gains': len(stable) >= 3,
              'two_repositories': len({questions[q]['pack'] for q in stable}) >= 2,
              'zero_individual_losses': not losses, 'latency': all(latency), 'mrr': all(mrr)}
    return {'complete': True, 'decision': 'promote' if all(checks.values()) else 'reject',
            'stable_gains': sorted(stable), 'checks': checks, 'losses': losses}
