"""Temporary source-bound baseline census. Never changes production ranking."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

BASELINE = '0984c60f11259d8f7c09295104deeb3cbcfd6892'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(root: Path) -> None:
    from eval.quality.corpus import PACK, materialize
    from eval.quality.experiment_evidence import Journal
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.runner import REPO, GIB, supervise, write_json
    import yaml

    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('runtime only in GitHub Actions')
    if os.environ.get('FIRST_PAGE_PHASE') != 'diagnostic':
        raise ValueError('phase requires prior qualified evidence; no scored candidate authorized yet')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if os.environ.get('FIRST_PAGE_EXPECTED_HEAD') != commit:
        raise ValueError('dispatch head is not frozen')
    subprocess.run(['git', 'diff', '--exit-code', BASELINE, 'HEAD', '--',
                    'packages/code-intel/src', 'packages/code-intel/pyproject.toml', 'uv.lock'], check=True)
    manifest_path = REPO / 'eval/quality/first_page_ranking_questions.json'
    design = json.loads((REPO / 'eval/quality/experiments/first-page-ranking.json').read_text())
    if sha(manifest_path) != design['questions_sha256']:
        raise ValueError('questions changed after qualification')
    manifest = json.loads(manifest_path.read_text())
    specs = {s['id']: s for s in yaml.safe_load(PACK.read_text())['repositories']}
    report = {'status': 'incomplete', 'decision': None, 'baseline': BASELINE,
              'operator_commit': commit, 'questions_sha256': sha(manifest_path), 'packs': []}
    write_json(root / 'evidence/diagnostic.json', report)
    groups = manifest['repositories']
    if len(groups) != 6 or len({g['pack'] for g in groups}) != 6:
        raise ValueError('six frozen packs required')
    deadline = time.monotonic() + 850
    for group in groups:
        spec = specs[group['pack']]
        if group['commit'] != spec['commit'] or group['repo'] != spec['repo']:
            raise ValueError('immutable pack identity mismatch')
        source = root / 'work/source'
        source.mkdir()
        receipt = {}
        tree = materialize(spec, source, root / 'cache', receipt=receipt)
        if source_manifest(source) != receipt:
            raise ValueError('materialized source differs from pinned Git blobs')
        folder = root / 'evidence' / group['pack']
        folder.mkdir()
        fixture_journal = Journal(folder / 'fixture', 64 * 2**20)
        fixture_journal.response({'event': 'fixture_pinned', 'repo': spec['repo'],
                                  'commit': spec['commit'], 'tree': tree}, receipt)
        row = supervise([sys.executable, '-m', 'eval.quality.first_page_ranking_trial',
                         '--worker', str(root), group['pack']], cwd=REPO, env=os.environ.copy(), root=root,
                        log=folder / 'worker.log', deadline=deadline, max_bytes=2*GIB, max_rss=2*GIB,
                        evidence_root=root / 'evidence', max_evidence_bytes=63*2**20)
        if row['status'] != 'passed' or not row['cleanup_verified'] or row['log_truncated']:
            raise ValueError('incomplete diagnostic worker: ' + json.dumps(row))
        summary = json.loads((folder / 'worker.json').read_text())
        if summary['status'] != 'complete' or not summary['source_unchanged']:
            raise ValueError('worker admission failed')
        report['packs'].append({'pack': group['pack'], 'tree': tree,
                                'worker': row, 'cases': summary['cases']})
        write_json(root / 'evidence/diagnostic.json', report)
        shutil.rmtree(source)
    cases = [c for p in report['packs'] for c in p['cases']]
    if len(cases) != 24 or len({c['id'] for c in cases}) != 24:
        raise ValueError('incomplete diagnostic inventory')
    eligible = [c for c in cases if c['eligible']]
    qualifies = len(eligible) >= 2 and len({c['pack'] for c in eligible}) >= 2
    # Eligibility is provisional until the outer controller admits final cleanup,
    # immutable inputs and aggregate deadline. Only its report may authorize work.
    report.update(status='complete', eligibility=qualifies, decision=None,
                  eligible_ids=[c['id'] for c in eligible])
    write_json(root / 'evidence/diagnostic.json', report)


async def worker(root, pack):
    from attocode_intel.gateway import OperationGateway
    from eval.quality.corpus import ready_search
    from eval.quality.corpus_capture import RecordedGateway, digest, journal_events
    from eval.quality.experiment_evidence import Journal, assert_engine
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.first_page_ranking_decision import page_metrics, owner_credit
    from eval.quality.mcp_search import decode, engine_identity, observe
    from eval.quality.runner import REPO, write_json

    manifest = json.loads((REPO / 'eval/quality/first_page_ranking_questions.json').read_text())
    group = next(g for g in manifest['repositories'] if g['pack'] == pack)
    questions = [q for q in group['questions'] if q['split'] == 'development']
    if len(questions) != 4:
        raise ValueError('four development questions per pack required')
    source, folder = root / 'work/source', root / 'evidence' / pack
    before = source_manifest(source)
    for q in questions:
        for a in q['answers']:
            path = (source / a['file']).resolve()
            if not path.is_relative_to(source.resolve()) or sha(path) != a['source_sha256']:
                raise ValueError('question source hash or boundary mismatch')
            lines = path.read_text().splitlines()
            if any(p['quote'] not in lines[p['line']-1] for p in a['proofs']):
                raise ValueError('question source proof mismatch')
    journal = Journal(folder / 'journal', 64 * 2**20)
    engine_root = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    initial_engine = engine_identity()
    journal.response({'event': 'engine_before'}, {'origins': assert_engine(engine_root),
                                                'sha256': initial_engine})
    journal.response({'event': 'source_before'}, before)
    report = {'status': 'incomplete', 'cases': [], 'pack': pack}
    write_json(folder / 'worker.json', report)
    peer = OperationGateway(str(source), profile='daily', watch=False)
    class TimedPeer:
        seconds = 0.
        async def execute_mcp(self, tool, arguments):
            started = time.perf_counter()
            result = await peer.execute_mcp(tool, arguments)
            self.seconds = time.perf_counter() - started
            return result
        async def close(self):
            await peer.close()
    timed = TimedPeer()
    gateway = RecordedGateway(timed, source, journal)
    primary = {}
    try:
        response, warmup = await ready_search(gateway, {'query': 'neutral readiness sentinel',
                                                       'top_k': 1, 'max_tokens': 2000})
        index = decode(response)['data']['ranking']['index']
        if index['status'] != 'ready' or not index['body_index_ready']:
            raise ValueError('lexical index not ready')
        report.update(warmup=warmup, initial_index=index)
        for q in questions:
            request = {'query': q['query'], 'top_k': 10, 'max_tokens': 2000,
                       'mode': 'auto', 'file_filter': ''}
            journal.response({'event': 'question_issued', 'id': q['id']}, request)
            page = decode(await gateway.execute_mcp('semantic_search', request))
            if page['data']['ranking']['index']['status'] != 'ready':
                raise ValueError('index became incomplete')
            primary[q['id']] = page
            journal.response({'event': 'primary', 'id': q['id']},
                             {'page': page, 'instrumented_seconds': timed.seconds,
                              'metrics': page_metrics(q, page['data']['results'])})
        for q in questions:
            traced = await observe(gateway, q['query'], top_k=10, budget=2000,
                                   capture_generation=True, capture_owner_fusion=True)
            if traced['response'] != primary[q['id']]:
                raise ValueError('observer changed canonical delivered envelope')
            ref = journal.response({'event': 'trace', 'id': q['id']}, traced)
            generation = traced['generation_diagnostic']
            config = generation[0]['owner_config']
            credits = owner_credit(generation, config['chunk_rrf_k'], config['body_weight'])
            heads = next((s['before'] for s in traced['owner_fusion_diagnostic']
                          if s['stage'] == 'exclusion'), [])
            observed = {}
            for h in heads:
                key = '|'.join((h['file'], h['kind'], h['name']))
                observed.setdefault(key, h['score'])
            replay = bool(credits) and set(credits) == set(observed) and all(
                credits[k]['score'] == observed[k] for k in credits)
            if (any(s['results'] for s in generation if s['stage'] in {'body', 'file_bm25'})
                    and not replay):
                raise ValueError('baseline owner-score replay mismatch')
            target_owners = set()
            for stage in generation:
                if stage['stage'] not in {'keyword', 'body'}:
                    continue
                for hit in stage['results']:
                    start, end = (hit['definition_start'] or hit['start'],
                                  hit['definition_end'] or hit['end'])
                    for a in q['answers']:
                        if (hit['file'] == a['file'] and start >= a['definition_start']
                                and end <= a['definition_end'] and start > 0
                                and any(start <= p['line'] <= end for p in a['proofs'])):
                            target_owners.add('|'.join((hit['file'], hit['kind'], hit['name'])))
            selected = {'|'.join((h['file_path'], h['chunk_type'], h['name']))
                        for h in traced['pre_hydration_diagnostic']}
            metrics = page_metrics(q, primary[q['id']]['data']['results'])
            competitors = sorted(k for k in selected if k in credits and credits[k]['keyword_votes'] > 1)
            eligible = (replay and bool(target_owners) and not (selected & target_owners)
                        and not metrics['answer'] and bool(competitors))
            row = {'id': q['id'], 'pack': pack, 'primary': metrics, 'trace_ref': ref,
                   'owner_score_replay': replay, 'generated_owners': sorted(target_owners),
                   'selected_owners': sorted(selected), 'multiple_credit_competitors': competitors,
                   'credits': credits, 'eligible': eligible, 'controls': []}
            report['cases'].append(row)
            write_json(folder / 'worker.json', report)
            for name, depth, budget, scope in [('deep', 24, 8000, ''),
                    *[('scoped', 5, 4000, f) for f in sorted({a['file'] for a in q['answers']})]]:
                control = await observe(gateway, q['query'], top_k=depth, budget=budget, file_filter=scope)
                control_ref = journal.response({'event': name, 'id': q['id'], 'scope': scope}, control)
                row['controls'].append({'page': name, 'scope': scope, 'ref': control_ref,
                                        'metrics': page_metrics(q, control['response']['data']['results'])})
            write_json(folder / 'worker.json', report)
    finally:
        await gateway.close()
        after = source_manifest(source)
        journal.response({'event': 'source_after'}, after)
        report['source_unchanged'] = before == after
        write_json(folder / 'worker.json', report)
    if before != after or engine_identity() != initial_engine:
        raise ValueError('source or selected engine changed')
    journal.response({'event': 'engine_after'}, {'origins': assert_engine(engine_root), 'sha256': initial_engine})
    journal_events(folder / 'journal')
    report.update(status='complete', source_sha256=digest(before), engine_sha256=initial_engine)
    write_json(folder / 'worker.json', report)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('only supervised GitHub Actions workers may execute')
    asyncio.run(worker(Path(sys.argv[2]), sys.argv[3]))
