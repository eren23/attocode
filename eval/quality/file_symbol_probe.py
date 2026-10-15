"""Bounded repeated-name lookup probe against an exact Git baseline (no corpora/models)."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
)
from attocode_intel.test_ranking import rank_symbol_tests

SOURCE = 'packages/code-intel/src/attocode_intel/_internal/integrations/context/ast_service.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = subprocess.check_output(['git', 'rev-parse', args.baseline + '^{commit}'], text=True).strip()
    raw = subprocess.check_output(['git', 'show', f'{baseline}:{SOURCE}'], text=True)
    cls = next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'ASTService')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'get_file_symbols')
    namespace = {'SymbolLocation': SymbolLocation}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<baseline-get-file-symbols>', 'exec'), namespace)
    previous = namespace['get_file_symbols']
    results = []
    with tempfile.TemporaryDirectory(prefix='attocode-file-symbol-') as tmp:
        for count in (160, 640):
            service = ASTService(tmp)
            service._initialized = True
            service._index = CrossRefIndex()
            paths = [f'tests/test_{i}.py' for i in range(count)]
            for path in paths:
                for n in range(32):
                    service._index.add_definition(SymbolLocation(f'check{n}', f'check{n}', 'function', path, n + 1, n + 1))
            timings = {'baseline': [], 'candidate': []}
            returned = {}
            expected = None
            ranking = {}
            rank_times = {}
            try:
                for repetition in range(4):
                    arms = [('baseline', previous), ('candidate', ASTService.get_file_symbols)]
                    for arm, fn in arms[::1 if repetition % 2 == 0 else -1]:
                        started = time.perf_counter()
                        pages = [fn(service, path) for path in paths]
                        timings[arm].append(time.perf_counter() - started)
                        returned[arm] = sum(map(len, pages))
                        normalized = [[(loc.file_path, loc.qualified_name, loc.start_line) for loc in page
                                       if loc.file_path == path] for path, page in zip(paths, pages, strict=True)]
                        digest = hashlib.sha256(json.dumps(normalized).encode()).hexdigest()
                        expected = expected or digest
                        assert digest == expected
                        del pages
                for arm, fn in [('baseline', previous), ('candidate', ASTService.get_file_symbols)]:
                    service.get_file_symbols = lambda path, fn=fn, service=service: fn(service, path)
                    started = time.perf_counter()
                    rows = rank_symbol_tests(service, {}, [paths[0]], 'check4', None, {}, linked_reference_files=[])
                    rank_times[arm] = time.perf_counter() - started
                    ranking[arm] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
                assert ranking['baseline'] == ranking['candidate']
                grouped = service._index._file_definitions
                # Shallow container overhead only; SymbolLocation objects are shared.
                extra_bytes = sys.getsizeof(grouped) + sum(
                    sys.getsizeof(groups) + sum(sys.getsizeof(v) for v in groups.values())
                    for groups in grouped.values())
                results.append({'files': count, 'symbols_per_file': 32, 'lookup_seconds': timings,
                                'median_lookup_seconds': {k: statistics.median(v) for k, v in timings.items()},
                                'returned_locations': returned, 'local_evidence_sha256': expected,
                                'test_ranking_seconds': rank_times, 'test_ranking_sha256': ranking['candidate'],
                                'added_container_bytes': extra_bytes})
            finally:
                service._store.close()
    result = {'baseline_commit': baseline, 'baseline_source_sha256': hashlib.sha256(raw.encode()).hexdigest(),
              'candidate_source_sha256': hashlib.sha256(Path(SOURCE).read_bytes()).hexdigest(),
              'candidate_index_sha256': hashlib.sha256(Path(SOURCE).with_name('cross_references.py').read_bytes()).hexdigest(),
              'cases': results, 'cleanup_verified': not Path(tmp).exists(),
              'scope': 'Generated repeated-name lookup and test-ranking components; no Cockroach wall-time claim.'}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
