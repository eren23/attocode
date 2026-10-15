"""Controlled cache-save overlap probe; no downloaded sources or models."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tempfile
import threading
import time
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from attocode_intel._internal.integrations.context import (
    codebase_ast,
    codebase_context,
    semantic_search,
)
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager


def run(arm, methods):
    with tempfile.TemporaryDirectory(prefix='attocode-importance-') as tmp:
        root = Path(tmp)
        for i in range(128):
            (root / f'worker{i}.go').write_text('package example\n' + ''.join(
                f'// Work{n} computes a worker value.\nfunc Work{n}(value int) int {{ return value + {n} }}\n'
                for n in range(32)))
        paused, release = threading.Event(), threading.Event()
        discoveries, parses = [], []
        discover = codebase_context.CodebaseContextManager.discover_files
        parse = codebase_ast.parse_file
        save = SemanticSearchManager._save_kw_cache
        def tracked_discovery(self, *args, **kwargs):
            discoveries.append(threading.current_thread().name)
            return discover(self, *args, **kwargs)
        def tracked_parse(*args, **kwargs):
            parses.append(threading.current_thread().name)
            return parse(*args, **kwargs)
        def paused_save(self, *args):
            paused.set()
            if not release.wait(10):
                raise TimeoutError('Foreground did not finish')
            return save(self, *args)
        mgr = SemanticSearchManager(str(root))
        start = time.perf_counter()
        try:
            with (patch.multiple(SemanticSearchManager, **methods) if methods else nullcontext(),
                  patch.object(SemanticSearchManager, '_save_kw_cache', paused_save),
                  patch.object(codebase_context.CodebaseContextManager, 'discover_files', tracked_discovery),
                  patch.object(codebase_ast, 'parse_file', tracked_parse)):
                mgr.search_candidates('compute worker')
                if not paused.wait(30):
                    raise TimeoutError('Keyword build incomplete')
                before = len(discoveries), len(parses)
                started = time.perf_counter()
                hits = mgr.search_candidates('compute worker')
                foreground_seconds = time.perf_counter() - started
                foreground_counts = {'discoveries': len(discoveries) - before[0],
                                     'parses': len(parses) - before[1]}
                foreground_hash = hashlib.sha256(json.dumps([asdict(h) for h in hits], sort_keys=True).encode()).hexdigest()
                release.set()
                if not mgr.wait_for_body_index(timeout=30):
                    raise TimeoutError('Body build incomplete')
                final = mgr.search_candidates('compute worker')
                elapsed = time.perf_counter() - start
                result = {'arm': arm, 'foreground_seconds': foreground_seconds,
                          'foreground_work': foreground_counts, 'total_seconds': elapsed,
                          'total_discoveries': len(discoveries), 'total_parses': len(parses),
                          'foreground_sha256': foreground_hash,
                          'ready_results_sha256': hashlib.sha256(json.dumps([asdict(h) for h in final], sort_keys=True).encode()).hexdigest(),
                          'importance_sha256': hashlib.sha256(json.dumps(mgr._importance_scores, sort_keys=True).encode()).hexdigest()}
        finally:
            release.set()
            mgr.close()
    result['cleanup_verified'] = not root.exists()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-source', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.baseline_source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.expected_sha256:
        raise ValueError('Frozen baseline source changed')
    names = {'_build_keyword_index', '_load_importance_scores', '_warm_candidate_indexes_impl'}
    cls = next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'SemanticSearchManager')
    selected = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(selected) != len(names):
        raise ValueError('Baseline methods missing')
    scope = dict(vars(semantic_search))
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<frozen-importance-baseline>', 'exec'), scope)
    methods = {name: scope[name] for name in names}
    rows = []
    for order in [('baseline', 'candidate'), ('candidate', 'baseline')]:
        for arm in order:
            rows.append(run(arm, methods if arm == 'baseline' else {}))
    for key in ['foreground_sha256', 'ready_results_sha256', 'importance_sha256']:
        assert len({r[key] for r in rows}) == 1, key
    result = {'baseline_source_sha256': args.expected_sha256,
              'candidate_source_sha256': hashlib.sha256(Path(semantic_search.__file__).read_bytes()).hexdigest(),
              'rows': rows, 'scope': 'Forced query/cache-save overlap on 128 generated Go files. '
                                    'Two alternating observations per arm; counters instrument both arms. '
                                    'Component evidence, not Cockroach wall time.'}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
