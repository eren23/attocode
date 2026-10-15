"""Frozen development/validation retrieval cycle; run under quality supervision."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import yaml
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _expand_query,
)
from attocode_intel.query_ranking import demote_tests

from eval.quality import sources
from eval.quality.corpus import PACK, materialize
from eval.quality.retrieval_ablation import metrics
from eval.quality.retrieval_body_trial import body_file_fusion
from eval.quality.runner import REPO, fingerprint


def identity():
    return fingerprint([REPO / 'packages/code-intel/src', REPO / 'eval/quality'])


def dual_fusion(expanded, literal, query):
    """Equal-weight file RRF over unique delivered files; deterministic ties."""
    scores = {}
    for paths in (expanded, literal):
        for rank, path in enumerate(dict.fromkeys(paths), 1):
            scores[path] = scores.get(path, 0.) + 1 / (60 + rank)
    paths = sorted(scores, key=lambda p: (-scores[p], p))
    return [r.file_path for r in demote_tests(
        query, [SimpleNamespace(file_path=p) for p in paths])][:24]


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1]


def summary(rows, arm):
    values = [r['arms'][arm] for r in rows]
    return {
        'queries': len(values),
        'hit5': sum(v['metrics']['hit5'] for v in values),
        'hit24': sum(v['metrics']['hit24'] for v in values),
        'mean_labeled_recall5': statistics.mean(v['metrics']['labeled_recall5'] for v in values),
        'mrr24': statistics.mean(1 / v['metrics']['first_rank']
                                if v['metrics']['first_rank'] else 0 for v in values),
        'p95_seconds': p95([v['seconds'] for v in values]),
    }


def choose(rows):
    baseline = summary(rows, 'expanded')
    scores = {a: summary(rows, a) for a in ('literal', 'dual')}
    eligible = [a for a, s in scores.items() if s['hit5'] >= baseline['hit5'] + 3
                and s['hit24'] >= baseline['hit24']]
    selected = max(eligible, key=lambda a: (scores[a]['mrr24'], a == 'literal'), default='none')
    return {'candidate': selected, 'baseline': baseline, 'candidates': scores}


def validation_gate(rows, candidate):
    baseline = summary(rows, 'expanded')
    if candidate == 'none':
        return {'passed': False, 'reason': 'No development candidate qualified', 'baseline': baseline}
    score = summary(rows, candidate)
    gains, losses, losses24 = [], [], []
    for r in rows:
        b, c = r['arms']['expanded']['metrics'], r['arms'][candidate]['metrics']
        if c['hit5'] and not b['hit5']:
            gains.append(r)
        if b['hit5'] and not c['hit5']:
            losses.append(r['id'])
        if b['hit24'] and not c['hit24']:
            losses24.append(r['id'])
    checks = {
        'net_hit5_at_least_three': score['hit5'] - baseline['hit5'] >= 3,
        'gains_in_two_repos': len({r['pack'] for r in gains}) >= 2,
        'at_most_one_hit5_loss': len(losses) <= 1,
        'no_individual_hit24_loss': not losses24,
        'recall5_not_decreased': score['mean_labeled_recall5'] >= baseline['mean_labeled_recall5'],
        'latency': score['p95_seconds'] <= max(1.5 * baseline['p95_seconds'], .05),
    }
    return {'passed': all(checks.values()), 'checks': checks, 'baseline': baseline,
            'candidate': score, 'hit5_gains': [r['id'] for r in gains],
            'hit5_losses': losses, 'hit24_losses': losses24}


def complete_rows(reports, questions, split):
    expected = {q['id'] for repo in questions['repositories'] for q in repo['queries'] if q['split'] == split}
    rows = [row for report in reports for row in report['queries']]
    if len(rows) != 24 or len(rows) != len({r['id'] for r in rows}) or {r['id'] for r in rows} != expected:
        raise ValueError('Incomplete or duplicate split')
    return rows


def check_choice(choice, question_hash, source_hash):
    if (choice['questions_sha256'] != question_hash or choice['source_sha256'] != source_hash
            or choice['development_queries'] != 24 or choice['candidate'] not in ('none', 'literal', 'dual')):
        raise ValueError('Choice does not match frozen inputs')


def check_body_choice(choice, question_hash, source_hash):
    if (choice['questions_sha256'] != question_hash or choice['source_sha256'] != source_hash
            or choice['candidate'] != 'body_file' or not choice['development']['passed']
            or len(choice['development']['checks']) != 5
            or not all(choice['development']['checks'].values())
            or choice['development']['baseline']['queries'] != 48):
        raise ValueError('Body-file choice does not match qualified frozen inputs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=['development', 'validation'], required=True)
    parser.add_argument('--pack', action='append', required=True)
    parser.add_argument('--choice', type=Path)
    parser.add_argument('--body-file-choice', type=Path)
    args = parser.parse_args()
    if not 1 <= len(args.pack) <= 2 or len(set(args.pack)) != len(args.pack):
        parser.error('Select one or two distinct packs')
    raw = args.questions.read_bytes()
    question_hash, source_hash = hashlib.sha256(raw).hexdigest(), identity()
    questions = json.loads(raw)
    candidate = 'both'
    if args.body_file_choice:
        if args.split != 'validation' or args.choice:
            parser.error('Body-file trial requires validation and its own choice')
        choice = json.loads(args.body_file_choice.read_bytes())
        check_body_choice(choice, question_hash, source_hash)
        candidate = 'body_file'
    elif args.split == 'validation':
        if not args.choice:
            parser.error('Validation requires a frozen development choice')
        choice = json.loads(args.choice.read_bytes())
        check_choice(choice, question_hash, source_hash)
        candidate = choice['candidate']
    os.environ['QUALITY_ALLOW_DOWNLOADS'] = '0'
    sources.MAX_PACK_BYTES = 64 * 1024**2
    specs = {s['id']: s for s in yaml.safe_load(PACK.read_text())['repositories']}
    repos = {r['pack']: r for r in questions['repositories']}
    rows, packs = [], []
    for pack in args.pack:
        repo, spec = repos[pack], specs[pack]
        if spec['commit'] != repo['commit']:
            raise ValueError('Question revision mismatch')
        selected = [q for q in repo['queries'] if q['split'] == args.split]
        if len(selected) != 4:
            raise ValueError('Expected four questions per pack and split')
        with tempfile.TemporaryDirectory(prefix='attocode-retrieval-cycle-') as tmp:
            root, cache = Path(tmp) / 'source', Path(tmp) / 'cache'
            root.mkdir()
            cache.mkdir()
            tree = materialize(spec, root, cache)
            mgr = SemanticSearchManager(root_dir=str(root))
            try:
                mgr.search_candidates('warmup')
                if not mgr.wait_for_body_index(timeout=90):
                    raise TimeoutError('Index warmup incomplete')
                coverage = {}
                conn = mgr._open_body_db()
                if conn is None:
                    raise RuntimeError('Body index unavailable')
                try:
                    for table in ('body_files', 'kw_files'):
                        coverage[table] = {r[0] for r in conn.execute(f'SELECT file_path FROM {table}')}
                finally:
                    conn.close()
                for number, q in enumerate(selected):
                    labels = {e['file'] for e in q['evidence']}
                    for label in q['evidence']:
                        path = (root / label['file']).resolve()
                        if not path.is_relative_to(root.resolve()):
                            raise ValueError('Label escapes pack')
                        content = path.read_text()
                        if (hashlib.sha256(content.encode()).hexdigest() != label['source_sha256']
                                or label['quote'] not in content):
                            raise ValueError('Label source mismatch')
                    queries = {'expanded': _expand_query(q['query'])}
                    if candidate not in ('none', 'body_file'):
                        queries['literal'] = q['query']
                    samples = {a: [] for a in queries}
                    outputs, dual_samples, body_samples = {}, [], []
                    for repeat in range(3):
                        order = list(queries)
                        if (repeat + number) % 2:
                            order.reverse()
                        times = {}
                        for arm in order:
                            trace = {}
                            start = time.perf_counter()
                            hits = mgr.search_candidates(queries[arm], top_k=24, trace=trace)
                            paths = list(dict.fromkeys(h.file_path for h in hits))
                            times[arm] = time.perf_counter() - start
                            samples[arm].append(times[arm])
                            if arm in outputs and outputs[arm]['files'] != paths:
                                raise RuntimeError('Unstable warmed result order')
                            outputs[arm] = {'files': paths, 'stages': trace, 'query': queries[arm]}
                        if candidate in ('both', 'dual'):
                            start = time.perf_counter()
                            paths = dual_fusion(outputs['expanded']['files'], outputs['literal']['files'], q['query'])
                            dual_samples.append(sum(times.values()) + time.perf_counter() - start)
                            outputs['dual'] = {'files': paths}
                        if candidate == 'body_file':
                            start = time.perf_counter()
                            paths = body_file_fusion(outputs['expanded']['stages'], q['query'])
                            body_samples.append(times['expanded'] + time.perf_counter() - start)
                            outputs['body_file'] = {'files': paths}
                    if body_samples:
                        samples['body_file'] = body_samples
                    if dual_samples:
                        samples['dual'] = dual_samples
                    arms = {}
                    for arm, output in outputs.items():
                        if candidate == 'dual' and arm == 'literal':
                            continue  # retained in dual input below; no unselected validation metric
                        arms[arm] = {**output, 'seconds': statistics.median(samples[arm]),
                                     'samples_seconds': samples[arm], 'metrics': metrics(output['files'], labels)}
                    if candidate == 'dual':
                        arms['dual']['literal_input'] = outputs['literal']
                    rows.append({'id': q['id'], 'pack': pack, 'query': q['query'], 'labels': sorted(labels),
                                 'arms': arms, 'label_index_coverage': {
                                     p: {table: p in paths for table, paths in coverage.items()} for p in sorted(labels)}})
                packs.append({'pack': pack, 'commit': spec['commit'], 'tree': tree,
                              'index': mgr.candidate_diagnostics()})
            finally:
                mgr.close()
        packs[-1]['cleanup_verified'] = not Path(tmp).exists()
    if source_hash != identity():
        raise RuntimeError('Implementation changed during run')
    result = {'questions_sha256': question_hash, 'source_sha256': source_hash,
              'split': args.split, 'candidate': candidate, 'packs': packs, 'queries': rows,
              'fixture_sha256': hashlib.sha256(PACK.read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({a: summary(rows, a) for a in rows[0]['arms']}))


if __name__ == '__main__':
    main()
