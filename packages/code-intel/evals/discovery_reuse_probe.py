"""Bounded two-consumer discovery comparison, not a cold-start performance gate."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import platform
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from attocode_intel._internal.integrations.context import codebase_context as context
from attocode_intel._internal.integrations.context import discovery_snapshot

BASELINE = '3d7c41ca628e8dfd2f62cf7eff9c4ae3aadbbdc2'
SOURCE = 'packages/code-intel/src/attocode_intel/_internal/integrations/context/codebase_context.py'


def run():
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{SOURCE}'], timeout=10)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'CodebaseContextManager')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'discover_files')
    scope = dict(vars(context))
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<frozen discovery>', 'exec'), scope)
    legacy = scope['discover_files']
    observations = []
    with tempfile.TemporaryDirectory(prefix='attocode-discovery-cost-') as tmp:
        root = Path(tmp)
        for i in range(640):
            (root / f'f{i}.py').write_text(f'def helper_{i}():\n    return "meaningfulValue"\n' * 4)
        source_bytes = sum(p.stat().st_size for p in root.iterdir())
        assert source_bytes < 2**20
        for order in [('baseline', 'reuse'), ('reuse', 'baseline'), ('baseline', 'reuse')]:
            for mode in order:
                donor = context.CodebaseContextManager(tmp, max_files=100000)
                consumer = context.CodebaseContextManager(tmp)
                wall, cpu = time.monotonic(), time.thread_time()
                (legacy(donor) if mode == 'baseline' else donor.discover_files())
                donor_seconds = time.monotonic() - wall
                if mode == 'baseline':
                    legacy(consumer)
                else:
                    assert consumer.reuse_discovery(donor._discovery_snapshot)
                seconds, used = time.monotonic()-wall, time.thread_time()-cpu
                files = [{k:v for k,v in asdict(f).items() if k != 'path'} for f in consumer._files]
                observations.append({'mode':mode,'wall_seconds':seconds,'thread_cpu_seconds':used,
                                     'donor_seconds':donor_seconds,'consumer_seconds':seconds-donor_seconds,
                                     'files':len(files),'inventory_sha256':hashlib.sha256(json.dumps(files).encode()).hexdigest()})
        assert len({o['inventory_sha256'] for o in observations}) == 1
    return {'scope':'Generated 640-file two-consumer inventory work; no cloud or cold-gate claim',
            'baseline_commit':BASELINE,'baseline_source_sha256':hashlib.sha256(source).hexdigest(),
            'candidate_source_sha256':hashlib.sha256(Path(inspect.getfile(context)).read_bytes()).hexdigest(),
            'snapshot_source_sha256':hashlib.sha256(Path(inspect.getfile(discovery_snapshot)).read_bytes()).hexdigest(),
            'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'python':platform.python_version(),'platform':platform.platform(),
            'source_bytes':source_bytes,'observations':observations,'cleanup_verified':not root.exists()}


if __name__ == '__main__':
    print(json.dumps(run(),indent=2))
