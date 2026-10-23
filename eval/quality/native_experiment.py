"""CI-only native diagnostics; observe existing limits without changing them."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from eval.quality.experiment_evidence import Journal, assert_engine, read_source, validate_excerpt
from eval.quality.runner import REPO, write_json

DESIGN = Path(__file__).with_name('experiments') / 'native.json'


class ParserObserver:
    """Forward parser state, retaining the actual outcome before bounded fallback."""
    def __init__(self, parser, record, language):
        object.__setattr__(self, '_parser', parser)
        object.__setattr__(self, '_record', record)
        object.__setattr__(self, '_language', language)

    def __getattr__(self, name):
        return getattr(self._parser, name)

    def __setattr__(self, name, value):
        setattr(self._parser, name, value)
        if name == 'timeout_micros':
            self._record({'event': 'native'}, {'stage': 'timeout_set', 'value': value,
                         'parser_id': id(self._parser), 'thread_id': threading.get_ident()})

    def parse(self, source, *args, **kwargs):
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        row = {'stage': 'parse', 'language': self._language, 'parser_id': id(self._parser),
               'thread_id': threading.get_ident(), 'thread_name': threading.current_thread().name,
               'source_sha256': hashlib.sha256(source).hexdigest(), 'bytes': len(source),
               'limit_micros': self._parser.timeout_micros, 'error': None}
        try:
            tree = self._parser.parse(source, *args, **kwargs)
        except BaseException as error:
            row.update(outcome=type(error).__name__, error={
                'type': type(error).__name__, 'message': str(error)[:2000]})
            raise
        else:
            row['outcome'] = 'no_tree' if tree is None else 'tree'
            return tree
        finally:
            row.update(wall_ns=time.perf_counter_ns() - wall,
                       thread_cpu_ns=time.thread_time_ns() - cpu)
            self._record({'event': 'native'}, row)

    def reset(self):
        self._parser.reset()
        self._record({'event': 'native'}, {'stage': 'reset', 'parser_id': id(self._parser),
                     'thread_id': threading.get_ident()})


def grammar_identity(cache):
    import tree_sitter_language_pack as pack
    pack.configure(cache_dir=str(cache))
    if 'ocaml' not in pack.downloaded_languages():
        raise ValueError('CI optional OCaml grammar was not acquired')
    files = {p.relative_to(cache).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(cache.rglob('*')) if p.is_file()}
    if not files:
        raise ValueError('empty optional grammar identity')
    return {'cache_files': files, 'distributions': distribution_identity(
        ('tree-sitter', 'tree-sitter-language-pack'))}


def distribution_identity(names):
    distributions = {}
    for name in names:
        dist = importlib.metadata.distribution(name)
        rows = [[str(item), hashlib.sha256(Path(dist.locate_file(item)).read_bytes()).hexdigest()]
                for item in sorted(dist.files or [], key=str)
                if str(item).endswith(('.py', '.so', '.dll', '.pyd', '.dylib'))
                and Path(dist.locate_file(item)).is_file()]
        distributions[name] = {'version': dist.version, 'files': rows}
    return distributions


async def observe_ocaml(mode, workspace, spec, record):
    source = workspace / spec['file']
    raw = source.read_bytes()
    record({'event': 'source'}, {'sha256': hashlib.sha256(raw).hexdigest(),
           'path': spec['file'], 'bytes': len(raw), 'decode': spec['decode']})
    if hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise ValueError('pinned OCaml source mismatch')
    content = read_source(source, **spec['decode'])
    canonical = hashlib.sha256(content.encode()).hexdigest()
    from attocode_intel._internal.integrations.context import ts_parser
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file
    original, proxies, native_rows = ts_parser._get_parser, {}, []

    def retain(request, row):
        ref = record(request, row)
        if row.get('stage') == 'parse':
            native_rows.append(row)
        return ref

    def get_parser(language):
        parser = original(language)
        if parser is None:
            retain({'event': 'parser_lookup'}, {'language': language, 'available': False})
            return None
        key = id(parser)
        if key not in proxies:
            proxies[key] = ParserObserver(parser, retain, language)
        return proxies[key]

    with patch.object(ts_parser, '_get_parser', get_parser):
        if mode == 'direct':
            result = parse_file(spec['file'], content)
            observed = {'parsing_tier': result.parsing_tier, 'symbol_count': result.symbol_count,
                        'content_sha256': result.content_sha256,
                        'failures': [asdict(f) for f in result.parse_failures],
                        'selected': [asdict(f) for f in result.functions if f.name == spec['symbol']]}
            record({'event': 'direct_result'}, observed)
            found = any(f['start_line'] == spec['line'] for f in observed['selected'])
        else:
            from attocode_intel.gateway import OperationGateway
            gateway = OperationGateway(str(workspace), spec['profile'], watch=spec['watch'])
            try:
                arguments = {'symbol_name': spec['symbol'], 'file_path': spec['file'], 'line': spec['line']}
                recovery = spec.get('recovery_control')
                if recovery:
                    if (recovery['injected_timeout_micros'] != 1
                            or recovery['cooldown_wait_seconds'] != 1.1):
                        raise ValueError('unfrozen recovery control')
                    with patch.object(ts_parser, 'PARSE_TIMEOUT_MICROS', 1):
                        initial = await gateway.execute('inspect_symbol', arguments)
                    record({'event': 'forced_failure_response', 'tool': 'inspect_symbol', 'arguments': arguments,
                            'injected_timeout_micros': 1}, initial.model_dump(mode='json'))
                    initial_data = initial.structuredContent['data'] if not initial.isError else {}
                    parse_state = initial_data.get('parse_state', {})
                    if (initial.isError or initial_data.get('status') != 'not_found'
                            or parse_state.get('recovery_attempted') is not True or not parse_state.get('failures')):
                        raise ValueError('forced native failure did not produce the expected partial lookup')
                    if ts_parser.PARSE_TIMEOUT_MICROS != 100000:
                        raise ValueError('normal parser limit was not restored')
                    record({'event': 'normal_timeout_restored'}, {
                        'limit_micros': ts_parser.PARSE_TIMEOUT_MICROS,
                        'cooldown_wait_seconds': recovery['cooldown_wait_seconds']})
                    await asyncio.sleep(recovery['cooldown_wait_seconds'])
                response = await gateway.execute('inspect_symbol', arguments)
                record({'event': 'gateway_response', 'tool': 'inspect_symbol', 'arguments': arguments},
                       response.model_dump(mode='json'))
                if response.isError:
                    raise ValueError('OCaml selected gateway returned an error')
                data = response.structuredContent['data']
                found = data['status'] == 'found'
                if found:
                    definition = data['definition']
                    if (definition['file_path'] != spec['file'] or definition['start_line'] != spec['line']
                            or definition['name'] != spec['symbol']):
                        raise ValueError('OCaml selected definition identity mismatch')
                    excerpt = data.get('source')
                    if recovery and (not excerpt or not excerpt.get('text')
                                     or excerpt.get('start_line') != spec['line']):
                        raise ValueError('recovered selected source is missing')
                    if excerpt and excerpt.get('text'):
                        validate_excerpt(content, excerpt['text'], excerpt['start_line'], excerpt['end_line'])
            finally:
                try:
                    await gateway.close()
                except BaseException as error:
                    record({'event': 'gateway_close'}, {'status': 'failed', 'type': type(error).__name__,
                           'message': str(error)[:2000]})
                    raise
                record({'event': 'gateway_close'}, {'status': 'complete'})
    selected = [r for r in native_rows if r['source_sha256'] == canonical]
    limits = {1, 100000} if spec.get('recovery_control') else {100000}
    if not selected or any(r['limit_micros'] not in limits for r in native_rows):
        raise ValueError('missing native observation or changed parser limit')
    return {'mode': mode, 'found': found, 'native_outcomes': [r['outcome'] for r in selected],
            'native_calls': len(native_rows), 'source_sha256': spec['sha256'],
            'decoded_source_sha256': canonical}


def worker(mode, workspace, evidence):
    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    journal = Journal(evidence / 'journal', 8 * 2**20)
    lock = threading.RLock()
    def record(request, value):
        with lock:
            return journal.response(request, value)
    outcome = {'status': 'incomplete', 'decision': None, 'mode': mode, 'pid': os.getpid()}
    started = time.monotonic()
    try:
        record({'event': 'origin_start'}, assert_engine(selected))
        if (workspace / '.attocode').exists():
            raise ValueError('OCaml workspace already has an index')
        record({'event': 'fresh_workspace'}, {'files': [p.relative_to(workspace).as_posix()
               for p in sorted(workspace.rglob('*')) if p.is_file()]})
        record({'event': 'grammar_identity'}, grammar_identity(Path(os.environ['QUALITY_GRAMMAR_CACHE'])))
        spec = json.loads(DESIGN.read_bytes())['ocaml']
        result = asyncio.run(observe_ocaml(mode, workspace, spec, record))
        record({'event': 'origin_end'}, assert_engine(selected))
        outcome.update(status='complete', observation=result)
    except BaseException as error:
        record({'event': 'worker_failure'}, {'type': type(error).__name__, 'message': str(error)[:2000]})
        raise
    finally:
        outcome['seconds'] = time.monotonic() - started
        write_json(evidence / 'result.json', outcome)


def admit_rust(trial):
    from eval.quality.lsp_admission import expected_sources, verify_diagnostic
    verdict = {'status': 'incomplete', 'decision': None}
    try:
        verdict['capture'] = verify_diagnostic((trial / 'lsp-diagnostic-rust.jsonl').read_bytes(), expected_sources())
        raw = (trial / 'rust.xml').read_bytes()
        if len(raw) > 2**20 or b'<!DOCTYPE' in raw.upper():
            raise ValueError('unsafe Rust JUnit')
        tree = ET.fromstring(raw)
        cases = list(tree.iter('testcase'))
        if (len(cases) != 1 or cases[0].get('name') != 'test_real_server_warmed_selected_definition_and_edit[rust]'
                or not cases[0].get('classname', '').endswith('test_real_language_server')
                or any(list(tree.iter(kind)) for kind in ('failure', 'error', 'skipped'))):
            raise ValueError('Rust fixture did not pass its required case')
        origins = json.loads((trial / 'pytest-origin.json').read_bytes())
        if origins['exitstatus'] != 0 or origins['origins'].get('attocode_intel') != '__init__.py':
            raise ValueError('Rust origin outcome incomplete')
        selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE']).resolve()
        for name, relative in origins['origins'].items():
            path = (selected / relative).resolve()
            if not name.startswith('attocode_intel') or not path.is_relative_to(selected) or not path.is_file():
                raise ValueError('Rust origin outside selected engine')
        identity = json.loads((trial / 'rust-native-identity.json').read_bytes())
        if (identity['exitstatus'] != 0 or identity['distributions'] !=
                distribution_identity(('tree-sitter', 'tree-sitter-rust'))):
            raise ValueError('Rust installed native identity changed')
        files = {path: sha for d in identity['distributions'].values() for path, sha in d['files']}
        loaded = identity['loaded']
        if not loaded or not any(name.startswith('tree_sitter_rust') for name in loaded):
            raise ValueError('Rust native module was not observed in worker')
        for name, row in loaded.items():
            if (not (name == 'tree_sitter' or name.startswith('tree_sitter.')
                     or name == 'tree_sitter_rust' or name.startswith('tree_sitter_rust.'))
                    or files.get(row['path']) != row['sha256']):
                raise ValueError('Rust loaded module identity mismatch')
        verdict['status'] = 'complete'
    except Exception as error:
        verdict['error'] = {'type': type(error).__name__, 'message': str(error)[:2000]}
        raise ValueError('Rust evidence admission failed: ' + str(error)) from error
    finally:
        write_json(trial / 'admission.json', verdict)
    return verdict


def run_rust_trials(frozen, evidence, work, command):
    for number in range(1, frozen['rust']['processes'] + 1):
        name = f'rust-{number}'
        env = {**os.environ, 'QUALITY_REQUIRE_REAL_LSP': '1', 'QUALITY_REAL_LSP_LANGUAGES': 'rust',
               'QUALITY_LSP_TRACE_DIR': str(evidence / name), 'ATTOCODE_EXPERIMENT_EVIDENCE': str(evidence / name),
               'RA_LOG': 'rust_analyzer=info', 'CARGO_NET_OFFLINE': 'true'}
        trial, row = command(name, [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
                '--confcutdir=packages/code-intel/tests', '-q', '--basetemp=' + str(work / name),
                '-o', 'cache_dir=' + str(work / (name + '-cache')),
                '-p', 'eval.quality.experiment_origin', '-p', 'eval.quality.native_origin',
                '--junitxml=' + str(evidence / name / 'rust.xml'),
                frozen['rust']['test']], env)
        row['admission'] = admit_rust(trial)
        row['status'] = 'complete'


def run(root):
    frozen = json.loads(DESIGN.read_bytes())
    if frozen.get('recovery_pair'):
        from eval.quality.native_recovery_probe import run as run_recovery_probe
        return run_recovery_probe(root, frozen)
    evidence, work = root / 'evidence/native', root / 'work/native'
    evidence.mkdir()
    work.mkdir(parents=True)
    report = {'status': 'incomplete', 'decision': None, 'trials': [], 'historical_cause': 'open'}
    started = time.monotonic()

    def command(name, arguments, env):
        trial = evidence / name
        trial.mkdir()
        row = {'name': name, 'arguments': arguments, 'status': 'incomplete'}
        report['trials'].append(row)
        write_json(evidence / 'summary.json', report)
        with (trial / 'process.log').open('xb') as stream:
            result = subprocess.run(arguments, cwd=REPO, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, check=False)
        row['exit_code'] = result.returncode
        write_json(evidence / 'summary.json', report)
        if result.returncode:
            raise ValueError('native trial failed: ' + name)
        return trial, row

    try:
        environment = Journal(evidence / 'environment', 2**20)
        for arguments in (['rustc', '--version', '--verbose'], ['rust-analyzer', '--version'],
                          ['rustup', 'which', 'rust-analyzer']):
            result = subprocess.run(arguments, capture_output=True, check=False)
            environment.response({'arguments': arguments}, {'exit_code': result.returncode,
                'stdout': result.stdout.decode(errors='replace'), 'stderr': result.stderr.decode(errors='replace')})
            if result.returncode:
                raise ValueError('native tool identity failed')
            if arguments[0] == 'rustup':
                binary = Path(result.stdout.decode().strip())
                environment.response({'event': 'rust_analyzer_binary'}, {
                    'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()})
        from eval.quality.corpus import materialize
        assert_engine(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
        spec = frozen['ocaml']
        fixture = work / 'source'
        tree = materialize({'id': 'native-ocaml', 'repo': spec['repo'], 'commit': spec['commit'],
                            'include': [spec['file']]}, fixture, work / 'source-cache')
        write_json(evidence / 'fixture.json', {'repo': spec['repo'], 'commit': spec['commit'], 'tree': tree,
                   'file': spec['file'], 'sha256': hashlib.sha256((fixture / spec['file']).read_bytes()).hexdigest()})
        for mode in ('direct', 'gateway'):
            for number in range(1, spec[mode + '_processes'] + 1):
                name = f'ocaml-{mode}-{number}'
                workspace = work / name
                (workspace / spec['file']).parent.mkdir(parents=True)
                shutil.copy2(fixture / spec['file'], workspace / spec['file'])
                trial, row = command(name, [sys.executable, '-m', 'eval.quality.native_experiment',
                       '--worker', mode, '--workspace', str(workspace), '--evidence', str(evidence / name)], os.environ.copy())
                result = json.loads((trial / 'result.json').read_bytes())
                if result['status'] != 'complete':
                    raise ValueError('incomplete OCaml worker')
                row.update(result=result, status='complete')
        run_rust_trials(frozen, evidence, work, command)
        report.update(status='complete', conclusion='Observed 12 fresh OCaml and 6 fresh Rust processes; '
                      'historical causes remain open. No parser or precision limit was changed.')
    finally:
        report['seconds'] = time.monotonic() - started
        write_json(evidence / 'summary.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=['direct', 'gateway'], required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    worker(args.worker, args.workspace, args.evidence)
