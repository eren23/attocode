"""Audit saved workflow pages without reindexing, downloading, or changing labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def audit(report: dict) -> dict:
    rows = []
    seen = set()
    missing = []
    for repo in report['repositories']:
        observed = set()
        for query in repo.get('retrieval', []):
            key = query['id']
            if key in seen:
                raise ValueError(f'Duplicate question: {key}')
            seen.add(key)
            observed.add(key)
            files = query['ranked_files']
            if len(files) != len(set(files)):
                raise ValueError(f'Expected unique ranked files: {key}')
            labels = set(query['labeled_files'])
            ranks = [i + 1 for i, path in enumerate(files) if path in labels]
            rank = min(ranks, default=None)
            if (rank != query['first_labeled_rank']
                    or bool(rank and rank <= 5) != query['hit_at_5']
                    or bool(rank and rank <= 24) != query['hit_at_24']):
                raise ValueError(f'Inconsistent saved rank: {key}')
            metadata = query.get('metadata', {})
            ranking = metadata.get('ranking', {})
            index = ranking.get('index', {})
            incomplete = (metadata.get('truncated', False)
                          or index.get('status') != 'ready')
            category = ('incomplete' if incomplete else 'labeled_top5' if rank and rank <= 5
                        else 'labeled_6_to_24' if rank and rank <= 24 else 'page_miss_unresolved')
            rows.append({'pack': repo['id'], 'id': key, 'query': query['query'],
                         'category': category, 'first_labeled_rank': rank,
                         'labeled_files': sorted(labels), 'ranked_files': files,
                         'returned_candidate_count': ranking.get('candidate_pool_count'),
                         'body_coverage': index.get('body_index_coverage'),
                         'seconds': query['seconds']})
        missing.extend(sorted(set(repo.get('expected_questions', [])) - observed))
    counts = Counter(row['category'] for row in rows)
    return {'schema_version': 1, 'observed_questions': len(rows), 'missing_questions': missing,
            'categories': dict(sorted(counts.items())), 'queries': rows,
            'scope': ('Original non-exhaustive labels retained. Page absence does not prove candidate-pool '
                      'or index absence. Labels may omit relevant returned files. No ranking/agent benefit claim.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    result = audit(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'queries'}, indent=2))


if __name__ == '__main__':
    main()
