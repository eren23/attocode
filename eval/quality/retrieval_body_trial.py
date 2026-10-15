"""One predeclared file-body candidate on consumed, retained development pools."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from attocode_intel.query_ranking import demote_tests

from eval.quality.retrieval_ablation import metrics


def body_file_fusion(trace, query):
    scores = {}
    for weight, stage in ((1., 'keyword'), (2., 'body')):
        for rank, path in enumerate(dict.fromkeys(trace[stage]), 1):
            scores[path] = scores.get(path, 0.) + weight / (60 + rank)
    paths = sorted(scores, key=lambda p: (-scores[p], p))
    return [r.file_path for r in demote_tests(query, [SimpleNamespace(file_path=p) for p in paths])][:24]


def evaluate(source):
    from eval.quality.retrieval_cycle import summary

    rows = [r for split in ('development', 'validation') for batch in source['reports'][split]
            for r in batch['queries']]
    if len(rows) != 48 or len({r['id'] for r in rows}) != 48:
        raise ValueError('Requires all 48 distinct consumed questions')
    results, gains, losses, losses24 = [], [], [], []
    for row in rows:
        baseline = row['arms']['expanded']
        paths = body_file_fusion(baseline['stages'], row['query'])
        score = metrics(paths, set(row['labels']))
        result = {k: row[k] for k in ('id', 'pack', 'query', 'labels')}
        # Offline fusion does not measure end-to-end candidate latency.
        result['arms'] = {'expanded': baseline, 'body_file': {'files': paths, 'metrics': score, 'seconds': 0}}
        results.append(result)
        b = baseline['metrics']
        if score['hit5'] and not b['hit5']:
            gains.append(row)
        if b['hit5'] and not score['hit5']:
            losses.append(row['id'])
        if b['hit24'] and not score['hit24']:
            losses24.append(row['id'])
    before, after = summary(results, 'expanded'), summary(results, 'body_file')
    after.pop('p95_seconds')
    before.pop('p95_seconds')
    checks = {'net_hit5_at_least_four': after['hit5'] - before['hit5'] >= 4,
              'gains_in_two_repos': len({r['pack'] for r in gains}) >= 2,
              'at_most_two_hit5_losses': len(losses) <= 2,
              'no_individual_hit24_loss': not losses24,
              'recall5_not_decreased': after['mean_labeled_recall5'] >= before['mean_labeled_recall5']}
    return {'passed': all(checks.values()), 'checks': checks, 'baseline': before, 'candidate': after,
            'hit5_gains': [r['id'] for r in gains], 'hit5_losses': losses, 'hit24_losses': losses24,
            'queries': [{k: v for k, v in r.items() if k != 'arms'} | {
                'baseline_files': r['arms']['expanded']['files'], 'candidate_files': r['arms']['body_file']['files'],
                'baseline_metrics': r['arms']['expanded']['metrics'], 'candidate_metrics': r['arms']['body_file']['metrics']}
                for r in results],
            'scope': 'Consumed development questions, frozen retained pools. No latency or fresh validation claim.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    raw = args.source.read_bytes()
    result = evaluate(json.loads(raw))
    result.update(source_sha256=hashlib.sha256(raw).hexdigest(),
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'queries'}, indent=2))


if __name__ == '__main__':
    main()
