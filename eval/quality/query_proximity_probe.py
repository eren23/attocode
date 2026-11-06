"""Data-only eligibility; never query, rerank, parse or execute fixture code."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
from zipfile import ZipFile


def local_counts(body, concepts):
    from attocode_intel.focused_evidence import terms

    lines = [terms(line) & concepts for line in body.splitlines()]
    total = set().union(*lines) if lines else set()
    local = max((len(set().union(*lines[i:i + 3])) for i in range(len(lines))), default=0)
    return {'total': len(total), 'local': local}


def body_text(raw, hit):
    text = io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8', errors='replace', newline=None).read()
    lines = text.splitlines()
    first, last = hit['start'], hit['end']
    assert 1 <= first <= last <= len(lines) and last - first < 32
    shown, chars = [], 0
    for line in lines[first - 1:last]:
        remaining = 2400 - chars
        assert remaining > 0
        shown.append(line[:remaining])
        chars += min(len(line), remaining) + 1
    body = '\n'.join(shown)
    full = f"{hit['file']}:{first}-{last}\n{body}"
    assert hashlib.sha256(full.encode()).hexdigest() == hit['text_sha256']
    return body


def owner(hit):
    return '|'.join((hit['file'], hit['kind'], hit['name']))


def eligible_pair(target, competitor):
    return (target['local'] == target['total'] >= 2
            and competitor['total'] >= target['total']
            and competitor['local'] < target['local']
            and competitor['score'] >= target['score'])


def gate(rows):
    winners = [r for r in rows if r['eligible']]
    return len(winners) >= 2 and len({r['pack'] for r in winners}) >= 2


def controls():
    assert local_counts('alpha\n\nbeta', {'alpha', 'beta'}) == {'total': 2, 'local': 2}
    assert local_counts('alpha\n\n\nbeta', {'alpha', 'beta'}) == {'total': 2, 'local': 1}
    assert local_counts('', {'alpha'}) == {'total': 0, 'local': 0}
    target = {'local': 2, 'total': 2, 'score': .1}
    assert eligible_pair(target, {'local': 1, 'total': 2, 'score': .2})
    assert not eligible_pair(target, {'local': 2, 'total': 2, 'score': .2})
    assert not eligible_pair(target, {'local': 1, 'total': 2, 'score': .01})
    assert not gate([{'eligible': True, 'pack': 'one'}, {'eligible': True, 'pack': 'one'}])
    assert gate([{'eligible': True, 'pack': 'one'}, {'eligible': True, 'pack': 'two'}])
    raw = b'alpha\r\nbeta\r\n'
    hit = {'file': 'a.py', 'start': 1, 'end': 2,
           'text_sha256': hashlib.sha256(b'a.py:1-2\nalpha\nbeta').hexdigest()}
    assert body_text(raw, hit) == 'alpha\nbeta'
    try:
        body_text(raw, {**hit, 'text_sha256': '0' * 64})
    except AssertionError:
        pass
    else:
        raise AssertionError('body identity damage was accepted')
    return 10


def run(root):
    from attocode_intel.query_ranking import query_concepts

    from eval.quality.experiment_evidence import assert_engine
    from eval.quality.runner import REPO, write_json

    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    design = json.loads((REPO / 'eval/quality/experiments/query-proximity.json').read_text())['science']
    assert design['local_lines'] == 3 and design['gate'] == {'minimum_cases': 2, 'minimum_repositories': 2}
    control_count = controls()
    archive = Path(os.environ['QUERY_PROXIMITY_INPUT_ZIP'])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == design['input_zip_sha256']
    qinput = design['questions_input']
    url = f"https://raw.githubusercontent.com/eren23/attocode/{qinput['head']}/{qinput['path']}"
    with urlopen(url, timeout=25) as response:
        raw = response.read(1024 * 1024 + 1)
    assert len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == qinput['sha256']
    manifest = json.loads(raw)
    questions, groups = {}, {}
    for group in manifest['repositories']:
        groups[group['pack']] = {k: group[k] for k in ('repo', 'commit')}
        for question in group['questions']:
            if question['split'] != 'development':
                continue  # Never access reserved query/answer fields.
            assert question['id'] not in questions
            questions[question['id']] = question
    del manifest
    assert len(questions) == 24
    cases, fixtures, tasks = [], {}, {}
    with ZipFile(archive) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        assert sum(i.file_size for i in z.infolist()) < 64 * 2**20
        names = [n for n in z.namelist() if Path(n).name == 'diagnostic.json']
        assert len(names) == 1
        base = Path(names[0]).parent

        def record(folder, ref):
            assert ref['path'] == 'blobs/' + ref['sha256'] + '.json'
            raw = z.read(str(folder / ref['path']))
            assert len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
            return json.loads(raw)

        outer = json.loads(z.read(str(base / 'report.json')))
        assert outer['status'] == 'complete' and outer['cleanup_verified'] and outer['owned_scratch_removed']
        assert outer['identity']['commit'] == qinput['head']
        diagnostic = json.loads(z.read(names[0]))
        assert diagnostic['status'] == 'complete' and len(diagnostic['packs']) == 6
        for pack in diagnostic['packs']:
            name = pack['pack']
            folder = base / name / 'fixture'
            events = [json.loads(line) for line in z.read(str(folder / 'events.jsonl')).splitlines()]
            assert len(events) == 1 and events[0]['request']['event'] == 'fixture_pinned'
            pinned = events[0]['request']
            assert all(pinned[k] == groups[name][k] for k in ('repo', 'commit'))
            fixture = fixtures[name] = record(folder, events[0]['response'])
            for case in pack['cases']:
                q = questions[case['id']]
                trace = record(base / name / 'journal', case['trace_ref'])
                assert trace['request']['query'] == q['query']
                assert case['owner_score_replay'] is True
                stages = [s for s in trace['generation_diagnostic'] if s['stage'] == 'body']
                assert len(stages) == 1
                hits = stages[0]['results']
                for path in {h['file'] for h in hits} | {a['file'] for a in q['answers']}:
                    assert path in fixture and fixture[path]['kind'] == 'file'
                    assert not Path(path).is_absolute() and '..' not in Path(path).parts
                    tasks[name, path] = fixture[path]
                cases.append((name, case, q, hits))
    assert len(cases) == len({c[1]['id'] for c in cases}) == 24
    assert {c[1]['id'] for c in cases} == set(questions)
    assert len(tasks) <= design['limits']['max_source_files']
    assert sum(r['bytes'] for r in tasks.values()) <= design['limits']['max_source_bytes']

    (root / 'evidence/sources').mkdir()

    def fetch(item):
        (pack, path), expected = item
        group = groups[pack]
        url = 'https://raw.githubusercontent.com/' + group['repo'] + '/' + group['commit'] + '/' + quote(path, safe='/')
        with urlopen(url, timeout=25) as response:
            raw = response.read(1_000_001)
        assert len(raw) == expected['bytes'] <= 1_000_000
        assert hashlib.sha256(raw).hexdigest() == expected['sha256']
        write_json(root / 'evidence/sources' / (hashlib.sha256((pack + '\0' + path).encode()).hexdigest() + '.json'),
                   {'pack': pack, 'path': path, 'url': url, 'bytes': len(raw), 'sha256': expected['sha256'],
                    'body_base64': base64.b64encode(raw).decode()})
        return (pack, path), raw

    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(fetch, tasks.items()))
    rows, hashes = [], 0
    for pack, case, question, hits in cases:
        concepts = set(query_concepts(question['query']))
        for answer in question['answers']:
            text = sources[pack, answer['file']].decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
            lines = text.splitlines(keepends=True)
            for proof in answer['proofs']:
                assert answer['definition_start'] <= proof['line'] <= answer['definition_end']
                assert proof['quote'] in ''.join(lines[proof['line'] - 1:proof['line'] - 1 + len(proof['quote'].splitlines())])
        targets, competitors = [], []
        selected, bound = set(case['selected_owners']), set(case['generated_owners'])
        for hit in hits:
            body = body_text(sources[pack, hit['file']], hit)
            hashes += 1
            identity = owner(hit)
            values = {**local_counts(body, concepts), 'owner': identity, 'start': hit['start'],
                      'end': hit['end'], 'score': case['credits'][identity]['score']}
            valid = any(hit['file'] == a['file'] and a['definition_start'] <= hit['start']
                        <= hit['end'] <= a['definition_end']
                        and any(hit['start'] <= p['line'] <= hit['end'] for p in a['proofs'])
                        for a in question['answers'])
            if identity in bound and identity not in selected and valid:
                targets.append(values)
            if identity in selected and identity not in bound:
                competitors.append(values)
        pairs = [{'target': t, 'competitor': c} for t in targets for c in competitors if eligible_pair(t, c)]
        row = {'id': case['id'], 'pack': pack, 'eligible': not case['primary']['answer'] and bool(pairs),
               'pairs': pairs, 'target_windows': targets, 'selected_competitor_windows': competitors}
        rows.append(row)
    result = {'status': 'complete', 'eligible': gate(rows), 'eligible_ids': [r['id'] for r in rows if r['eligible']],
              'decision': 'eligible_for_fixed_candidate' if gate(rows) else 'unsupported_hypothesis',
              'rows': rows, 'source_files': len(sources), 'body_hashes_verified': hashes,
              'controls_passed': control_count, 'queries_issued': 0, 'holdout_issued': 0,
              'scope': design['scope'], 'origins': assert_engine(REPO / 'packages/code-intel/src/attocode_intel')}
    write_json(root / 'evidence/query-proximity.json', result)
