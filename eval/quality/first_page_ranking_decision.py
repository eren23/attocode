"""Strict prospective decisions from admitted data; no product imports or execution."""
import math


def admit_diagnostic(outer, diagnostic):
    supervision = outer.get('supervision', {})
    seconds = outer.get('seconds')
    valid = (outer.get('status') == 'complete' and outer.get('cleanup_verified') is True
             and outer.get('owned_scratch_removed') is True
             and type(seconds) in (int, float) and math.isfinite(seconds)
             and 0 <= seconds < outer['limits']['seconds']
             and supervision.get('status') == 'passed' and supervision.get('exit_code') == 0
             and supervision.get('cleanup_verified') is True and supervision.get('log_truncated') is False
             and diagnostic.get('status') == 'complete' and type(diagnostic.get('eligibility')) is bool)
    if not valid:
        return None
    return 'eligible_for_fixed_candidate' if diagnostic['eligibility'] else 'unsupported_hypothesis'


def _proof_visible(row, proof):
    start, end = row.get('snippet_start_line'), row.get('snippet_end_line')
    if type(start) is not int or type(end) is not int or not isinstance(row.get('snippet'), str):
        return False
    lines = row['snippet'].splitlines()
    offset = proof['line'] - start
    return (start <= proof['line'] <= end and 0 <= offset < len(lines)
            and proof['quote'] in lines[offset])


def page_metrics(question, results):
    files, visible, answered, ranks = set(), set(), False, []
    for i, answer in enumerate(question['answers']):
        matched = [r for r in results if r['file_path'] == answer['file']]
        if matched:
            files.add(answer['file'])
            ranks.append(next(n+1 for n, r in enumerate(results) if r['file_path'] == answer['file']))
        proofs = set()
        for j, proof in enumerate(answer['proofs']):
            if any(_proof_visible(r, proof) for r in matched):
                proofs.add(j)
                visible.add(f'{i}:{j}')
        answered |= bool(answer['proofs']) and len(proofs) == len(answer['proofs'])
    return {'answer': answered, 'files': sorted(files), 'visible': sorted(visible),
            'first_rank': min(ranks, default=None)}


def owner_credit(generation, chunk_rrf_k, body_weight):
    owners = {}
    for stage in generation:
        if stage['stage'] not in {'keyword', 'body'}:
            continue
        seen_chunks, seen_owners = set(), set()
        weight = 1. if stage['stage'] == 'keyword' else body_weight
        for rank, row in enumerate(stage['results'], 1):
            owner = '|'.join((row['file'], row['kind'], row['name']))
            key = (owner, row['start'] or row['definition_start'], row['end'] or row['definition_end'])
            if key in seen_chunks or (stage['stage'] == 'body' and owner in seen_owners):
                continue
            seen_chunks.add(key)
            seen_owners.add(owner)
            entry = owners.setdefault(owner, {'keyword_votes': 0, 'body_votes': 0, 'score': 0.})
            entry[stage['stage'] + '_votes'] += 1
            entry['score'] += weight / (chunk_rrf_k + rank)
    for entry in owners.values():
        entry['score'] = round(entry['score'], 6)
    return owners


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
