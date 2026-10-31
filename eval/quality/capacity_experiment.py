"""Bounded current-source capacity observations with explicit discovery limits."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

from eval.quality.corpus_capture import RecordedGateway
from eval.quality.experiment_evidence import Journal, assert_engine
from eval.quality.runner import REPO, supervise, write_json
from eval.quality.scale_evidence import admit_coverage, admit_identities, admit_parsers, require
from eval.quality.scale_workload import Requests, indexed_snapshot, sqlite_integrity

DESIGN = REPO / 'eval/quality/experiments/capacity.json'


class CapacityGateway(RecordedGateway):
    async def execute(self, tool, arguments):
        # Uncompacted hydration status carries coverage, not rendered source.
        return await self.peer.execute(tool, arguments)



def source_bytes(number):
    prefix = f'from module_{number - 1:06d} import operation_{number - 1:06d}\n' if number else ''
    body = f'    return operation_{number - 1:06d}(value) + {number}\n' if number else '    return value\n'
    return (prefix + f'def operation_{number:06d}(value: int) -> int:\n' + body).encode()


def generate(tree, size):
    tree.mkdir()
    rows = {}
    digest = hashlib.sha256()
    for number in range(size):
        name = f'module_{number:06d}.py'
        raw = source_bytes(number)
        (tree / name).write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        rows[name] = {'sha256': sha, 'bytes': len(raw)}
        digest.update(name.encode() + b'\0' + bytes.fromhex(sha))
    return {'generator': 'zero-padded-python-import-chain-v1', 'source_files': size,
            'source_sha256': digest.hexdigest(), 'files': rows}


def databases(tree):
    paths = sorted(set(tree.rglob('*.db')) | set(tree.rglob('*.sqlite')) | set(tree.rglob('*.sqlite3')))
    return {p.relative_to(tree).as_posix(): {'bytes': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}


async def candidate_snapshot(gateway):
    key = next(iter(gateway._workers))

    def snapshot():
        manager = gateway._stores[key]['service']._get_semantic_search()
        conn = manager._open_body_db()
        require(conn is not None, 'candidate database absent')
        try:
            return {'diagnostics': manager.candidate_diagnostics(),
                    'keyword_paths': sorted(row[0] for row in conn.execute('SELECT file_path FROM kw_files')),
                    'body_paths': sorted(row[0] for row in conn.execute('SELECT file_path FROM body_files'))}
        finally:
            conn.close()

    return await asyncio.get_running_loop().run_in_executor(gateway._workers[key], snapshot)


async def phase(spec, output):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus_capture import validate_sources

    output.mkdir()
    tree = Path(spec['tree'])
    started = time.monotonic()
    until = started + spec['seconds']
    selected = min(spec['size'], 50000)
    expected = [f'module_{number:06d}.py' for number in range(selected)]
    engine = REPO / 'packages/code-intel/src/attocode_intel'
    result = {'complete': False, 'closed': False, 'pid': os.getpid(), 'phase': spec['phase'],
              'size': spec['size'], 'expected_selected_files': selected, 'origin_start': assert_engine(engine),
              'databases_before': databases(tree)}
    require(bool(result['databases_before']) == (spec['phase'] == 'restart'), 'cold/restart database provenance differs')
    gateway = OperationGateway(str(tree), 'daily', watch=False)
    recorded = CapacityGateway(gateway, tree, Journal(output / 'sources', 16 * 2**20))
    requests = Requests(recorded, output)
    try:
        await requests.call('bootstrap', {'task_hint': 'operation_000000', 'max_tokens': 2500})
        result['bootstrap_seconds'] = time.monotonic() - started
        while True:
            page = await requests.call('hydration_status', {}, compact=False)
            coverage = page['metadata']['coverage']
            if coverage.get('phase') == 'ready':
                observed = await indexed_snapshot(gateway)
                write_json(output / 'index-identities.json', {'expected': expected, **observed,
                           'coverage': coverage, 'analysis': page['metadata']['analysis']})
                admit_coverage(coverage, selected)
                admit_identities(expected, observed['parsed'], observed['referenced'])
                admit_parsers(page['metadata']['analysis'], observed['grammars'], selected)
                require(observed['degraded_count'] == 0, 'native failures in small synthetic Python sources')
                break
            require(time.monotonic() < until, 'native/reference readiness deadline')
            await asyncio.sleep(1)
        result['hydration_seconds'] = time.monotonic() - started
        last = selected - 1
        file = f'module_{last:06d}.py'
        symbol = f'operation_{last:06d}'
        page = await requests.call('inspect_symbol', {'symbol_name': symbol, 'file_path': file,
                                   'line': 2, 'max_tokens': 2500})
        require(page['data'].get('status') == 'found', 'included boundary symbol absent')
        require(page['data']['definition']['file_path'] == file, 'included boundary symbol path differs')
        require(bool(validate_sources('inspect_symbol', page, tree, [])), 'included symbol source absent')
        page = await requests.call('dependencies', {'path': file, 'max_tokens': 2500})
        require(f'module_{last - 1:06d}.py' in json.dumps(page['data']), 'included boundary import absent')
        for number in (0, last):
            while True:
                page = await requests.call('semantic_search', {'query': f'operation_{number:06d}',
                        'file_filter': f'module_{number:06d}.py', 'top_k': 3, 'max_tokens': 2500})
                state = page.get('data', {}).get('ranking', {}).get('index', {})
                if state.get('status') != 'warming':
                    rows = page.get('data', {}).get('results', [])
                    require(bool(rows) and all(r['file_path'] == f'module_{number:06d}.py' for r in rows),
                            'included boundary scoped search missing or escaped')
                    # RecordedGateway already admitted the actual producer policies and source spans.
                    break
                require(time.monotonic() < until, 'search readiness deadline')
                await asyncio.sleep(1)
        result['search_ready_seconds'] = time.monotonic() - started
        snapshot = await candidate_snapshot(gateway)
        write_json(output / 'candidate-identities.json', snapshot)
        require(snapshot['keyword_paths'] == snapshot['body_paths'] == expected, 'candidate exact path sets differ')
        diagnostic = snapshot['diagnostics']
        require(diagnostic['status'] == 'ready' and diagnostic['body_index_coverage'] == 1.0,
                'candidate readiness/selected coverage incomplete')
        require(diagnostic['discovery_max_files'] == 100000, 'configured request cap changed')
        require(diagnostic['discovery_selected_files'] == diagnostic['discovery_discovered_files'] == selected,
                'discovery selected count differs')
        require(diagnostic['discovery_truncated'] == (spec['size'] >= 50000), 'safety-boundary disclosure differs')
        result['outside_search'] = []
        if spec['size'] > selected:
            for number in sorted({selected, spec['size'] - 1}):
                page = await requests.call('semantic_search', {'query': f'operation_{number:06d}',
                        'file_filter': f'module_{number:06d}.py', 'top_k': 3, 'max_tokens': 2500})
                require(page.get('data', {}).get('ranking', {}).get('index', {}).get('status') == 'ready',
                        'outside-boundary search not ready')
                require(page.get('data', {}).get('results') == [], 'outside-boundary result differs from frozen policy')
                result['outside_search'].append({'file': f'module_{number:06d}.py', 'results': 0})
        result.update(complete=True, outcome='passed' if spec['size'] < 50000 else 'limited',
                      source_total=spec['size'], omitted_files=spec['size'] - selected,
                      discovery_truncated=diagnostic['discovery_truncated'])
    except BaseException as error:
        result['error'] = {'type': type(error).__name__, 'message': str(error)[:4000]}
        raise
    finally:
        try:
            await recorded.close()
            result['closed'] = True
            result['sqlite_integrity'] = sqlite_integrity(tree)
            result['databases_after'] = databases(tree)
        except BaseException:
            result.update(complete=False, closed=False)
            raise
        finally:
            result.update(seconds=time.monotonic() - started, requests=requests.metrics,
                          origin_end=assert_engine(engine))
            write_json(output / 'result.json', result)
    return result


def run(root):
    frozen = json.loads(DESIGN.read_bytes())
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'capacity runner target differs')
    require(os.environ.get('ATTOCODE_INTEL_MAX_FILES', '100000') == '100000', 'request cap overridden')
    os.environ['ATTOCODE_INTEL_MAX_FILES'] = '100000'
    os.environ['ATTOCODE_INTEL_RANKING_PROVIDER'] = 'off'
    write_json(root / 'evidence/capacity-environment.json', {
        'platform': platform.platform(), 'cpu': Path('/proc/cpuinfo').read_text(),
        'memory': Path('/proc/meminfo').read_text(), 'cgroup': Path('/proc/self/cgroup').read_text(),
        'engine_origin': assert_engine(REPO / 'packages/code-intel/src/attocode_intel')})
    result = {'complete': False, 'cases': [], 'unissued': list(frozen['sizes']),
              'scope': frozen['scope'], 'model_calls': 0}
    try:
        for size in frozen['sizes']:
            started = time.monotonic()
            output = root / 'evidence' / f'capacity-{size}'
            output.mkdir()
            tree = root / 'work' / f'capacity-{size}'
            manifest = generate(tree, size)
            write_json(output / 'source.json', manifest)
            case = {'size': size, 'complete': False, 'phases': []}
            result['cases'].append(case)
            result['unissued'].remove(size)
            write_json(root / 'evidence/capacity-result.json', result)
            for phase_name in ('cold', 'restart'):
                folder = output / phase_name
                folder.mkdir()
                seconds = int(frozen['per_case_seconds'][str(size)] - (time.monotonic() - started))
                require(seconds > 20, 'case deadline leaves phase unissued')
                spec = {'tree': str(tree), 'size': size, 'phase': phase_name, 'seconds': seconds}
                spec_path = output / (phase_name + '-spec.json')
                write_json(spec_path, spec)
                row = supervise([sys.executable, '-m', 'eval.quality.capacity_experiment',
                                 '--phase', str(spec_path), '--output', str(folder / 'data')],
                        cwd=REPO, env=os.environ.copy(), root=root, log=folder / 'process.log',
                        deadline=time.monotonic() + seconds, max_bytes=frozen['limits']['disk_bytes'],
                        max_rss=frozen['limits']['rss_bytes'], evidence_root=root / 'evidence',
                        max_evidence_bytes=255 * 2**20)
                case['phases'].append({'phase': phase_name, 'supervision': row})
                write_json(root / 'evidence/capacity-result.json', result)
                require(row['status'] == 'passed' and row['exit_code'] == 0 and row['cleanup_verified']
                        and not row['log_truncated'], 'capacity phase incomplete; preserve original attempt')
                observed = json.loads((folder / 'data/result.json').read_bytes())
                require(observed['complete'] and observed['closed'], 'phase did not close completely')
                case['phases'][-1].update(pid=observed['pid'], outcome=observed['outcome'])
            require(case['phases'][0]['pid'] != case['phases'][1]['pid'], 'persisted restart reused PID')
            case.update(complete=True, outcome='passed' if size < 50000 else 'limited',
                        seconds=time.monotonic() - started)
            write_json(root / 'evidence/capacity-result.json', result)
        result['complete'] = True
    finally:
        write_json(root / 'evidence/capacity-result.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(phase(json.loads(args.phase.read_bytes()), args.output))
