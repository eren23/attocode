"""Bounded generated body-work probe: no downloads, models or cloud resources.

This isolates document generation, using empty known spans (no AST parsing), not
an end-to-end repository benchmark. Compare identical terms/windows by digest.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import platform
import subprocess
import tempfile
import time
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from attocode_intel._internal.integrations.context import index_probe as probe
from attocode_intel._internal.integrations.context import semantic_search as search

BASELINE = "3d7c41ca628e8dfd2f62cf7eff9c4ae3aadbbdc2"
SOURCE = "packages/code-intel/src/attocode_intel/_internal/integrations/context/semantic_search.py"


def baseline_body():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:{SOURCE}"], timeout=10)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "SemanticSearchManager")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_body_document")
    method.decorator_list = []
    scope = dict(vars(search))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<frozen body>", "exec"), scope)
    return scope[method.name], hashlib.sha256(source).hexdigest()


def fixture(root, unique=False):
    paths = []
    for i in range(8):
        path = root / f'generated{i}.go'
        path.write_text('package example\n' + ''.join(
            f'// block {n if unique else n // 32}\nvalue_{n if unique else n % 64} = otherHTTPValue + processRow(value_{n if unique else n % 64})\n'
            for n in range(2048)
        ))
        paths.append(path)
    return paths


def run():
    observations = []
    legacy, baseline_hash = baseline_body()
    source_bytes = {}
    with tempfile.TemporaryDirectory(prefix='attocode-body-cost-') as tmp:
        for workload in ('repeated', 'unique'):
            root = Path(tmp) / workload
            root.mkdir()
            paths = fixture(root, unique=workload == 'unique')
            source_bytes[workload] = sum(p.stat().st_size for p in paths)
            assert source_bytes[workload] < 2 * 2**20
            modes = ['baseline_off', 'off', 'all_calls', 'default']
            for rotation in range(4):
                for mode in modes[rotation:] + modes[:rotation]:
                    collector = None if mode in ('baseline_off', 'off') else probe.IndexProbe()
                    wrapping = (patch.object(search, 'instrument', lambda phase, fn:
                                partial(probe.measured_call, phase, fn))
                                if mode == 'all_calls' else nullcontext())
                    method = legacy if mode == 'baseline_off' else search.SemanticSearchManager._body_document
                    outputs = []
                    with wrapping, probe.activate(collector):
                        wall, cpu = time.monotonic(), time.thread_time()
                        for p in paths:
                            outputs.append(method(
                                p.name, str(p), SimpleNamespace(take=lambda *_: ([], [])),
                                include_file_terms=True,
                            ))
                        elapsed, used = time.monotonic()-wall, time.thread_time()-cpu
                    digest = hashlib.sha256(json.dumps(outputs, ensure_ascii=False).encode()).hexdigest()
                    observations.append({'workload': workload, 'mode': mode, 'rotation': rotation,
                                         'wall_seconds': elapsed, 'thread_cpu_seconds': used,
                                         'output_sha256': digest,
                                         'windows': sum(len(o[0]) for o in outputs),
                                         'profile': collector.snapshot() if collector else None})
            assert len({o['output_sha256'] for o in observations if o['workload'] == workload}) == 1
    return {'scope': 'Generated document generation, empty known spans; no parsing, SQL or cold-start claim',
            'baseline_commit': BASELINE, 'baseline_source_sha256': baseline_hash,
            'candidate_source_sha256': hashlib.sha256(Path(inspect.getfile(search)).read_bytes()).hexdigest(),
            'profiler_sha256': hashlib.sha256(Path(inspect.getfile(probe)).read_bytes()).hexdigest(),
            'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'python': platform.python_version(), 'platform': platform.platform(),
            'source_bytes': source_bytes, 'observations': observations,
            'cleanup_verified': not Path(tmp).exists()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), indent=2)+'\n')
