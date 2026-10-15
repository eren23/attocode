"""Trace lexical candidate stages on at most two small, pinned, local source packs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager

from eval.quality import sources
from eval.quality.corpus import PACK, materialize


class TracedSearch(SemanticSearchManager):
    def search_candidates(self, *args, **kwargs):
        return super().search_candidates(*args, **kwargs, trace=self.trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--questions', type=Path, help='Frozen source-bound questions on the same pinned packs')
    args = parser.parse_args()
    if not 1 <= len(set(args.pack)) <= 2:
        parser.error('Choose one or two packs')
    os.environ['QUALITY_ALLOW_DOWNLOADS'] = '0'
    sources.MAX_PACK_BYTES = 64 * 1024**2
    specs = {s['id']: s for s in yaml.safe_load(PACK.read_text())['repositories']}
    if not set(args.pack) <= set(specs):
        parser.error('Unknown pack')
    if args.questions:
        for item in json.loads(args.questions.read_text())['repositories']:
            if item['pack'] not in specs or item['commit'] != specs[item['pack']]['commit']:
                parser.error('Question revision does not match pinned pack')
            specs[item['pack']]['queries'] = item['queries']
    reports = []
    for name in dict.fromkeys(args.pack):
        spec = specs[name]
        with tempfile.TemporaryDirectory(prefix='attocode-retrieval-replay-') as tmp:
            root, cache = Path(tmp) / 'source', Path(tmp) / 'cache'
            root.mkdir()
            cache.mkdir()
            tree = materialize(spec, root, cache)
            mgr = TracedSearch(root_dir=str(root))
            trace = {}
            mgr.trace = trace
            observations = []
            try:
                mgr.search('warmup', top_k=24)
                if not mgr.wait_for_body_index(timeout=90):
                    raise TimeoutError('Candidate indexes did not become ready')
                for q in spec['queries']:
                    for label in q['evidence']:
                        path = (root / label['file']).resolve()
                        if not path.is_relative_to(root.resolve()):
                            raise ValueError('Query label escapes source pack')
                        text = path.read_text()
                        if hashlib.sha256(text.encode()).hexdigest() != label['source_sha256'] or label['quote'] not in text:
                            raise ValueError('Pinned query label changed')
                    labels = {label['file'] for label in q['evidence']}
                    for depth in (24, 96):
                        trace.clear()
                        started = time.perf_counter()
                        hits = mgr.search(q['query'], top_k=depth)
                        elapsed = time.perf_counter() - started
                        paths = list(dict.fromkeys(hit.file_path for hit in hits))
                        def ranks(paths, labels=labels):
                            return {p: i + 1 for i, p in enumerate(paths) if p in labels}
                        observations.append({'id': q['id'], 'query': q['query'], 'depth': depth,
                                             'labeled_files': sorted(labels), 'stage_ranks': {k: ranks(v) for k, v in trace.items()},
                                             'stage_counts': {k: len(v) for k, v in trace.items()},
                                             'returned_labeled_ranks': ranks(paths), 'ranked_files': paths,
                                             'seconds': elapsed})
                reports.append({'pack': name, 'commit': spec['commit'], 'tree': tree,
                                'diagnostics': mgr.candidate_diagnostics(), 'queries': observations})
            finally:
                mgr.close()
        reports[-1]['cleanup_verified'] = not Path(tmp).exists()
    result = {'scope': 'Local lexical replay; depth 96 reruns candidate generation, not a stable cursor. '
                       'Development labels unchanged. No models, downloads, or agent runs.',
              'pack_sha256': hashlib.sha256(PACK.read_bytes()).hexdigest(),
              'questions_sha256': hashlib.sha256(args.questions.read_bytes()).hexdigest() if args.questions else None,
              'repositories': reports}
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
