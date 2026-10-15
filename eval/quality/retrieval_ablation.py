"""Bounded expansion comparisons and offline fusion over retained candidate lists.

Run through quality.runner.supervise/environment. Source packs are local-only,
at most two per invocation and 64 MiB each. No models or repository execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel._internal.integrations.context.semantic_search import (
    _CONSTRUCT_HINTS,
    SemanticSearchManager,
    _expand_query,
    _tokenize,
)
from attocode_intel.query_ranking import demote_tests

from eval.quality import sources
from eval.quality.corpus import PACK, materialize
from eval.quality.runner import REPO, fingerprint


def token_expansion(query):
    tokens = set(_tokenize(query))
    additions = []
    for concept, hints in _CONSTRUCT_HINTS.items():
        if concept in tokens:
            additions.extend(h for h in hints if h not in tokens and h not in additions)
    return query + (' ' + ' '.join(additions) if additions else '')


def file_fusion(trace, query):
    """Fixed weighted file RRF, using only the retained keyword/body candidates."""
    scores = {}
    for weight, stage in ((1., 'keyword'), (1.15, 'body')):
        for rank, path in enumerate(trace[stage]):
            scores[path] = scores.get(path, 0.) + weight / (60 + rank + 1)
    # Apply the existing test-intent policy without inventing a new one.
    from types import SimpleNamespace
    paths = sorted(scores, key=lambda p: (-scores[p], p))
    return [r.file_path for r in demote_tests(query, [SimpleNamespace(file_path=p) for p in paths])]


def metrics(paths, labels):
    ranks = [i + 1 for i, path in enumerate(paths) if path in labels]
    return {'first_rank': min(ranks, default=None), 'hit5': any(r <= 5 for r in ranks),
            'hit24': any(r <= 24 for r in ranks),
            'labeled_recall5': len(set(paths[:5]) & labels) / len(labels)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--arms', nargs='+', default=['expanded', 'tokens', 'literal'],
                        choices=['expanded', 'tokens', 'literal'])
    args = parser.parse_args()
    raw = args.questions.read_bytes()
    questions = json.loads(raw)
    repos = questions['repositories']
    if not 1 <= len(repos) <= 2 or len({r['pack'] for r in repos}) != len(repos):
        parser.error('Select one or two distinct packs')
    if sum(len(r['queries']) for r in repos) > 24:
        parser.error('At most 24 questions')
    os.environ['QUALITY_ALLOW_DOWNLOADS'] = '0'
    sources.MAX_PACK_BYTES = 64 * 1024**2
    specs = {s['id']: s for s in yaml.safe_load(PACK.read_text())['repositories']}
    rows, packs = [], []
    for repo in repos:
        spec = specs[repo['pack']]
        if spec['commit'] != repo['commit']:
            raise ValueError('Question revision mismatch')
        with tempfile.TemporaryDirectory(prefix='attocode-ablation-') as tmp:
            root, cache = Path(tmp) / 'source', Path(tmp) / 'cache'
            root.mkdir()
            cache.mkdir()
            tree = materialize(spec, root, cache)
            mgr = SemanticSearchManager(root_dir=str(root))
            try:
                mgr.search_candidates('warmup')
                if not mgr.wait_for_body_index(timeout=90):
                    raise TimeoutError('Index warmup incomplete')
                for q in repo['queries']:
                    for label in q['evidence']:
                        path = (root / label['file']).resolve()
                        if not path.is_relative_to(root.resolve()):
                            raise ValueError('Label escapes pack')
                        content = path.read_text()
                        if (hashlib.sha256(content.encode()).hexdigest() != label['source_sha256']
                                or label['quote'] not in content):
                            raise ValueError('Label source mismatch')
                    labels = {e['file'] for e in q['evidence']}
                    row = {'id': q['id'], 'query': q['query'], 'labels': sorted(labels), 'arms': {}}
                    for arm in args.arms:
                        query = {'expanded': _expand_query, 'tokens': token_expansion,
                                 'literal': lambda q: q}[arm](q['query'])
                        trace = {}
                        start = time.perf_counter()
                        hits = mgr.search_candidates(query, top_k=24, trace=trace)
                        elapsed = time.perf_counter() - start
                        paths = list(dict.fromkeys(r.file_path for r in hits))
                        fused = file_fusion(trace, query)
                        row['arms'][arm] = {'query': query, 'seconds': elapsed, 'files': paths,
                                            'metrics': metrics(paths, labels), 'stages': trace,
                                            'file_rrf_files': fused, 'file_rrf_metrics': metrics(fused, labels)}
                    rows.append(row)
                packs.append({'pack': spec['id'], 'commit': spec['commit'], 'tree': tree,
                              'index': mgr.candidate_diagnostics()})
            finally:
                mgr.close()
        packs[-1]['cleanup_verified'] = not Path(tmp).exists()
    result = {'questions_sha256': hashlib.sha256(raw).hexdigest(), 'packs': packs, 'queries': rows,
              'source_sha256': fingerprint([REPO / 'packages/code-intel/src', Path(__file__)]),
              'scope': 'Unchanged indexes per pack. Expansion changes retrieval; file fusion uses only retained lists. '
                       'Non-exhaustive file judgments, no model or agent runs.'}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for arm in args.arms:
        for key in ('metrics', 'file_rrf_metrics'):
            print(arm, key, {k: sum(r['arms'][arm][key][k] for r in rows) for k in ('hit5', 'hit24')})


if __name__ == '__main__':
    main()
