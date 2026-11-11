"""One fixed, dependency-free native Rust observation; no artificial delays."""
import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway


def _files(version):
    files = {
        'Cargo.toml': '[package]\nname="gateway-witness"\nversion="0.1.0"\nedition="2021"\n',
        'src/first.rs': 'pub fn helper() -> i32 { 1 }\n' + '\n' * version,
        'src/second.rs': 'pub fn helper() -> i32 { 2 }\n',
    }
    modules = ''.join(f'pub mod part_{i:03};\n' for i in range(128))
    files['src/lib.rs'] = ('pub mod first;\npub mod second;\n' + modules +
                           ('pub fn caller() -> i32 { first::helper() }\n' if version == 0 else
                            '\npub fn caller() -> i32 { second::helper() }\n'))
    for i in range(128):
        files[f'src/part_{i:03}.rs'] = ''.join(
            f'pub fn value_{j:03}(x: i32) -> i32 {{ x + {i + j + version} }}\n'
            for j in range(64))
    return files


async def test_real_rust_gateway_reload_observation(tmp_path, monkeypatch, record_property):
    if 'rust' not in os.environ.get('QUALITY_REAL_LSP_LANGUAGES', '').split(','):
        pytest.skip('Worker-only pinned Rust witness; no local acquisition')
    from attocode_intel._internal.errors import ToolError
    from attocode_intel._internal.integrations.lsp.client import BUILTIN_SERVERS
    from attocode_intel.precision import PrecisionSession
    from eval.quality.lsp_trace import LSPTrace

    assert shutil.which(BUILTIN_SERVERS['rust'].command)
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
    output = Path(os.environ['QUALITY_LSP_TRACE_DIR'])
    trace = LSPTrace(output / 'lsp-gateway-rust.jsonl', tmp_path.as_uri())
    precision_times = []
    original = PrecisionSession.enrich

    async def timed(self, *args, **kwargs):
        started = time.monotonic()
        try:
            return await original(self, *args, **kwargs)
        finally:
            precision_times.append(time.monotonic() - started)

    monkeypatch.setattr(PrecisionSession, 'enrich', timed)

    def write_sources(version):
        files = _files(version)
        hashes = {}
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            retained = output / 'rust-gateway-source' / str(version) / name
            retained.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, retained)
        trace.record('fixture_sources', version=version, hashes=hashes)
        return files

    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    process = None
    with trace.capture(monkeypatch):
        try:
            trace.stage('fixture_sources_original')
            write_sources(0)
            trace.stage('prepare_static_index')
            response = await gateway.execute('symbols', {'path': 'src/first.rs'})
            assert not response.isError
            stores = next(iter(gateway._stores.values()))
            manager = stores['service']._get_lsp_manager()
            worker = next(iter(gateway._workers.values()))

            async def inspect(path, stage):
                trace.stage(stage)
                started = time.monotonic()
                response = await gateway.execute_mcp('inspect_symbol', {
                    'symbol_name': 'helper', 'file_path': path, 'line': 1, 'max_tokens': 8000})
                assert not response.isError
                result = json.loads(response.content[0].text)
                trace.record('inspection', path=path, elapsed=time.monotonic() - started,
                             precision_elapsed=precision_times[-1], response=result,
                             raw_text=response.content[0].text)
                # This is the precision budget, excluding static refresh/formatting.
                assert precision_times[-1] < 5.8
                return result, precision_times[-1]

            async def warm(target, expected_line):
                nonlocal process
                async with asyncio.timeout(45):
                    if 'rust' not in manager.get_active_servers():
                        await manager.start_server('rust', tmp_path.as_uri(), timeout=5)
                    process = manager._clients['rust']._process
                    for name in ('src/first.rs', 'src/second.rs', 'src/lib.rs'):
                        path = tmp_path / name
                        if str(path) not in stores['precision'].documents:
                            manager.notify_file_opened(str(path), path.read_text())
                            stores['precision'].documents[str(path)] = 1
                    callback = manager.on_result_callback
                    manager.on_result_callback = None
                    try:
                        while True:
                            try:
                                refs = await manager.get_references(
                                    str(tmp_path / target), 0, 7, include_declaration=False)
                            except ToolError as error:
                                if str(error).lower() != 'content modified':
                                    raise
                                refs = None
                            if any(ref.uri == (tmp_path / 'src/lib.rs').as_uri() and
                                   ref.range.start.line == expected_line - 1 for ref in refs or []):
                                break
                            await asyncio.sleep(.1)
                    finally:
                        manager.on_result_callback = callback

            async def explicit_warm(target, expected_line, stage):
                trace.stage(stage)

                def run():
                    return stores['async_runner'].run(warm(target, expected_line))

                await asyncio.get_running_loop().run_in_executor(worker, run)
                await asyncio.sleep(1.05)  # Fixture separation from real retry cooldown.

            cold, cold_time = await inspect('src/first.rs', 'cold_public_gateway')
            assert cold['metadata']['precision'] in {'partial', 'verified'}
            await explicit_warm('src/first.rs', 131, 'explicit_fixture_warmup_original')
            before, _ = await inspect('src/first.rs', 'public_baseline_after_fixture_warmup')
            assert any(ref['file_path'] == 'src/lib.rs' and ref['line'] == 131 and ref['source'] == 'lsp'
                       for ref in before['data']['references'])
            write_sources(1)
            after, reload_time = await inspect('src/second.rs', 'first_public_gateway_after_edit')
            precision = after['metadata']['precision']
            assert precision in {'partial', 'verified'}
            record_property('qualified_input', 'true')
            record_property('fixture_modules', 128)
            record_property('fixture_functions_per_module', 64)
            record_property('cold_precision_elapsed', cold_time)
            record_property('reload_precision_elapsed', reload_time)
            record_property('reload_precision', json.dumps(precision))
            await explicit_warm('src/second.rs', 132, 'explicit_fixture_warmup_changed')
            recovered, _ = await inspect('src/second.rs', 'later_public_gateway_retry')
            assert recovered['metadata']['precision'] == 'verified'
            assert any(ref['file_path'] == 'src/lib.rs' and ref['line'] == 132 and ref['source'] == 'lsp'
                       for ref in recovered['data']['references'])
            old, _ = await inspect('src/first.rs', 'old_definition_after_retarget')
            assert not any(ref['file_path'] == 'src/lib.rs' for ref in old['data']['references'])
            assert manager._clients['rust']._process is process
        except BaseException as error:
            trace.failed(error)
            raise
        finally:
            trace.stage('shutdown')
            await gateway.close()
    assert process is not None and process.returncode is not None
    record_property('owned_process_exit_code', process.returncode)
