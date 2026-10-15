"""Generated Go cold+restart comparison with exact AST/index parity and cleanup."""
from __future__ import annotations

import ast
import hashlib
import json
import platform
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from attocode_intel._internal.integrations.context import ast_service, ast_snapshot
from attocode_intel._internal.integrations.context.index_store import AST_SNAPSHOT_KEY

BASELINE = 'b3501b9d7ae016572d77ceae1289026d23719694'
SOURCE = 'packages/code-intel/src/attocode_intel/_internal/integrations/context/ast_service.py'


def run():
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{SOURCE}'], timeout=10)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'ASTService')
    methods, scopes = {}, []
    for name in ('_save_snapshot', '_restore_snapshot'):
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        scope = dict(vars(ast_service))
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<frozen restart>', 'exec'), scope)
        methods[name] = scope[name]
        scopes.append(scope)
    original = {name: getattr(ast_service.ASTService, name) for name in methods}
    observations = []
    with tempfile.TemporaryDirectory(prefix='attocode-restart-probe-') as tmp:
        root = Path(tmp)
        workloads = ['short_body', 'long_body']
        source_sizes = {}
        for number, (workload, mode) in enumerate((w, m) for w in workloads
                for m in ['baseline', 'candidate', 'candidate', 'baseline']):
            for scope in scopes:
                scope['parse_file'] = ast_service.parse_file
            project = root / str(number)
            project.mkdir()
            for i in range(160):
                (project / f'file{i:04d}.go').write_text('package example\n' + ''.join(
                    f'// Helper{i}_{j} returns an adjusted value.\nfunc Helper{i}_{j}(value int) int {{\n'
                    + '    if value < 0 { return 0 }\n' * (1 if workload == 'short_body' else 12)
                    + '    return value + 1\n}\n' for j in range(32)))
            source_sizes[workload] = sum(p.stat().st_size for p in project.iterdir())
            assert source_sizes[workload] < 8 * 2**20
            with patch.multiple(ast_service.ASTService, **(methods if mode == 'baseline' else original)):
                first = ast_service.ASTService(str(project))
                start = time.monotonic()
                try:
                    first.initialize_skeleton(indexing_depth='eager')
                    cold = time.monotonic() - start
                    payload_bytes = len((first._store.get_meta(AST_SNAPSHOT_KEY) or '').encode())
                finally:
                    first.stop_hydration()
                    first._store.close()
                second = ast_service.ASTService(str(project))
                try:
                    with patch.object(ast_service, 'parse_file', wraps=ast_service.parse_file) as parse:
                        for scope in scopes:
                            scope['parse_file'] = parse
                        wall, cpu = time.monotonic(), time.thread_time()
                        state = second.initialize_skeleton()
                        restart, thread_cpu = time.monotonic()-wall, time.thread_time()-cpu
                        calls = parse.call_count
                    assert state.phase == 'ready' and state.parsed_files == 160
                    assert calls == (160 if mode == 'baseline' else 0)
                    summaries = {key: {**asdict(value), 'path': key} for key, value in second._ast_cache.items()}
                    evidence = {'asts': summaries, 'definitions': {
                        key: [asdict(v) for v in value] for key, value in second._index.definitions.items()},
                        'stats': second._store.stats(), 'dependencies': {
                            key: sorted(value) for key, value in second._index.file_dependencies.items()}}
                    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
                    observations.append({'mode': mode, 'workload': workload, 'cold_seconds': cold, 'restart_seconds': restart,
                                         'cold_plus_restart_seconds': cold+restart, 'restart_thread_cpu_seconds': thread_cpu,
                                         'restart_parse_calls': calls, 'cache_payload_bytes': payload_bytes,
                                         'evidence_sha256': digest})
                finally:
                    second.stop_hydration()
                    second._store.close()
        for workload in workloads:
            assert len({row['evidence_sha256'] for row in observations if row['workload'] == workload}) == 1
        disk_bytes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        assert disk_bytes < 100 * 2**20
    return {'scope': 'Generated 160-file/5120-function Go cold+restart; no Cockroach or cloud speed claim',
            'baseline_commit': BASELINE, 'baseline_source_sha256': hashlib.sha256(source).hexdigest(),
            'candidate_source_sha256': hashlib.sha256(Path(ast_service.__file__).read_bytes()).hexdigest(),
            'cache_source_sha256': hashlib.sha256(Path(ast_snapshot.__file__).read_bytes()).hexdigest(),
            'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'python': platform.python_version(), 'platform': platform.platform(),
            'source_bytes': source_sizes, 'final_owned_disk_bytes': disk_bytes,
            'observations': observations, 'cleanup_verified': not root.exists()}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
