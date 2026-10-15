"""Generated Go navigation profile, confined to disposable source and indexes."""
from __future__ import annotations

import argparse
import asyncio
import cProfile
import hashlib
import json
import pstats
import tempfile
import time
from pathlib import Path

from attocode_intel.gateway import OperationGateway

from eval.quality.corpus import ready_search


class ProfileGateway(OperationGateway):
    def __init__(self, root, records):
        super().__init__(str(root), 'daily', watch=False)
        self.records = records

    def _execute_sync(self, context, name, args, compact=False, timings=None):
        profiler = cProfile.Profile()
        start = time.perf_counter()
        try:
            return profiler.runcall(super()._execute_sync, context, name, args, compact, timings)
        finally:
            rows = []
            for (file, line, function), (_primitive, calls, own, cumulative, _) in pstats.Stats(profiler).stats.items():
                if 'attocode_intel/' in file:
                    rows.append({'file': file.split('attocode_intel/', 1)[-1], 'line': line,
                                 'function': function, 'calls': calls, 'self_seconds': own,
                                 'cumulative_seconds': cumulative})
            self.records.append({'operation': name, 'profiled_seconds': time.perf_counter() - start,
                                 'hotspots': sorted(rows, key=lambda r: -r['cumulative_seconds'])[:30]})


async def run(root, records):
    gateway = ProfileGateway(root, records)
    selection = {'symbol_name': 'Work0', 'file_path': 'pkg0/worker.go'}
    try:
        for operation, args in [('search_symbols', {'name': 'Work0'}),
                                ('inspect_symbol', selection),
                                ('suggest_tests', {'files': ['pkg0/worker.go']})]:
            response = await gateway.execute_mcp(operation, args)
            if response.isError:
                raise ValueError(str(response.content)[:1000])
        response, _ = await ready_search(gateway, {'query': 'compute worker value', 'top_k': 5, 'max_tokens': 4000})
        if response.isError:
            raise ValueError('Search failed')
    finally:
        await gateway.close()
    reopened = ProfileGateway(root, records)
    try:
        response = await reopened.execute_mcp('inspect_symbol', selection)
        if response.isError:
            raise ValueError('Restart inspection failed')
    finally:
        await reopened.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    records = []
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix='attocode-navigation-profile-') as tmp:
        root = Path(tmp)
        for i in range(128):
            folder = root / f'pkg{i}'
            folder.mkdir()
            content = f'package pkg{i}\n\n' + ''.join(
                f'// Work{n} computes a worker value.\nfunc Work{n}(value int) int {{ return value + {n} }}\n'
                for n in range(32))
            test = f'package pkg{i}\nfunc TestWorker() {{ Work0(1) }}\n'
            for name, data in [('worker.go', content), ('worker_test.go', test)]:
                (folder / name).write_text(data)
                digest.update(f'pkg{i}/{name}\0{data}'.encode())
        asyncio.run(run(root, records))
    args.output.write_text(json.dumps({'source_sha256': digest.hexdigest(), 'source_files': 256,
                                       'operations': records, 'cleanup_verified': not Path(tmp).exists(),
                                       'scope': 'Instrumented foreground request costs; concurrent background '
                                                'warmup is not profiled. Synthetic, not Cockroach timing.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
