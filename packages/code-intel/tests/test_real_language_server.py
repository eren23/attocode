"""An installed TypeScript server, not a protocol double, resolves and refreshes references."""
import os
import shutil
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway


async def test_real_typescript_server_selected_definition_and_edits(tmp_path, monkeypatch):
    if not shutil.which('typescript-language-server'):
        if os.environ.get('QUALITY_REQUIRE_REAL_LSP') == '1':
            pytest.fail('Required pinned TypeScript language server is missing')
        pytest.skip('TypeScript language server is not installed; no automatic installation')
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
    (tmp_path / 'tsconfig.json').write_text('{"compilerOptions":{"strict":true},"include":["*.ts"]}')
    (tmp_path / 'first.ts').write_text('export function helper() { return 1; }\n')
    (tmp_path / 'second.ts').write_text('export function helper() { return 2; }\n')
    (tmp_path / 'caller.ts').write_text("import { helper } from './first';\nhelper();\n")
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    process = None
    try:
        async def inspect(path):
            response = await gateway.execute('inspect_symbol', {'symbol_name':'helper', 'file_path':path, 'line':1})
            assert not response.isError
            return response.structuredContent
        first = await inspect('first.ts')
        assert first['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(r['file_path'] == 'caller.ts' and r['line'] == 2 and r['source'] == 'lsp'
                   for r in first['data']['references'])
        other = await inspect('second.ts')
        assert not any(r['file_path'] == 'caller.ts' for r in other['data']['references'])
        (tmp_path / 'caller.ts').write_text("import { helper } from './second';\n\nhelper();\n")
        other = await inspect('second.ts')
        assert any(r['file_path'] == 'caller.ts' and r['line'] == 3 and r['source'] == 'lsp'
                   for r in other['data']['references'])
        first = await inspect('first.ts')
        assert not any(r['file_path'] == 'caller.ts' for r in first['data']['references'])
        process = next(iter(gateway._stores.values()))['service']._lsp_manager._clients['typescript']._process
    finally:
        await gateway.close()
    assert process.returncode is not None


@pytest.mark.parametrize('language', ['python', 'go', 'rust'])
async def test_real_server_warmed_selected_definition_and_edit(tmp_path, monkeypatch, language):
    """Explicit opt-in on workers: bounded warmup is not a cold-latency claim."""
    import asyncio
    from collections import deque

    protocol = deque(maxlen=128)

    from attocode_intel._internal.errors import ToolError
    from attocode_intel._internal.integrations.lsp.client import BUILTIN_SERVERS
    if language not in os.environ.get('QUALITY_REAL_LSP_LANGUAGES', '').split(','):
        pytest.skip('Worker-only real server matrix; no local acquisition')
    command = BUILTIN_SERVERS[language].command
    assert shutil.which(command), f'Required worker server missing: {command}'
    if language == 'python':
        files = {'first.py':'def helper(): return 1\n', 'second.py':'def helper(): return 2\n',
                 'caller.py':'from first import helper\nhelper()\n',
                 'pyrightconfig.json':'{"include":["*.py"]}'}
        target, other, caller, symbol, line, column, call_line = 'first.py','second.py','caller.py','helper',1,4,2
        changed = 'from second import helper\n\nhelper()\n'
    elif language == 'go':
        files = {'go.mod':'module example.org/quality\ngo 1.25\n',
                 'first/helper.go':'package first\nfunc Helper() int { return 1 }\n',
                 'second/helper.go':'package second\nfunc Helper() int { return 2 }\n',
                 'caller.go':'package quality\nimport "example.org/quality/first"\nfunc Run() int { return first.Helper() }\n'}
        target, other, caller, symbol, line, column, call_line = 'first/helper.go','second/helper.go','caller.go','Helper',2,5,3
        changed = 'package quality\nimport "example.org/quality/second"\n\nfunc Run() int { return second.Helper() }\n'
    else:
        files = {'Cargo.toml':'[package]\nname="quality-fixture"\nversion="0.1.0"\nedition="2021"\n',
                 'src/first.rs':'pub fn helper() -> i32 { 1 }\n',
                 'src/second.rs':'pub fn helper() -> i32 { 2 }\n',
                 'src/lib.rs':'pub mod first;\npub mod second;\npub fn caller() -> i32 { first::helper() }\n'}
        target, other, caller, symbol, line, column, call_line = 'src/first.rs','src/second.rs','src/lib.rs','helper',1,7,3
        changed = 'pub mod first;\npub mod second;\n\npub fn caller() -> i32 { second::helper() }\n'
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    process = None
    from eval.quality.lsp_trace import LSPTrace

    trace_dir = os.environ.get("QUALITY_LSP_TRACE_DIR")
    trace_path = Path(trace_dir) / "lsp-diagnostic-rust.jsonl" if language == "rust" and trace_dir else None
    trace = LSPTrace(trace_path, tmp_path.as_uri())
    with trace.capture(monkeypatch):
        try:
            trace.stage("warmup")
            await gateway.execute('symbols', {'path':target})
            service = next(iter(gateway._stores.values()))['service']
            manager = service._get_lsp_manager()
            manager._timeout = 5
            stores = next(iter(gateway._stores.values()))
            worker = next(iter(gateway._workers.values()))
            async def on_workspace_loop(coroutine):
                def run():
                    runner = stores.setdefault('async_runner', asyncio.Runner())
                    return runner.run(coroutine)
                return await asyncio.get_running_loop().run_in_executor(worker, run)
            async def warm():
                nonlocal process
                async with asyncio.timeout(30):
                    await manager.start_server(language, tmp_path.as_uri())
                    client = manager._clients[language]
                    process = client._process
                    send, receive = client._send_message, client._handle_message
                    async def trace_send(message):
                        protocol.append({"direction": "out", "message": message})
                        return await send(message)
                    def trace_receive(message):
                        protocol.append({"direction": "in", "message": message})
                        return receive(message)
                    client._send_message = trace_send
                    client._handle_message = trace_receive
                    manager.on_result_callback = None
                    for name, content in files.items():
                        if manager._get_client_for_file(str(tmp_path / name)):
                            manager.notify_file_opened(str(tmp_path / name), content)
                    while True:
                        try:
                            refs = await manager.get_references(str(tmp_path / target), line - 1, column, include_declaration=False)
                        except ToolError as error:
                            if str(error).lower() != 'content modified':
                                raise
                            refs = []
                        if any(r.uri == (tmp_path / caller).as_uri() and r.range.start.line == call_line - 1 for r in refs):
                            break
                        await asyncio.sleep(.1)
            await on_workspace_loop(warm())
            monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
            async def inspect(path):
                response = await gateway.execute('inspect_symbol', {'symbol_name':symbol, 'file_path':path, 'line':line})
                trace.record("inspection", path=path, is_error=response.isError, response=response.structuredContent)
                assert not response.isError
                return response.structuredContent
            trace.stage("selected_original")
            selected = await inspect(target)
            assert selected['metadata']['analysis']['precision']['status'] == 'verified', {
                'response': selected, 'protocol': list(protocol)}
            assert any(r['file_path'] == caller and r['source'] == 'lsp' for r in selected['data']['references']), {
                'response': selected, 'protocol': list(protocol)}
            trace.stage("unused_namesake")
            wrong = await inspect(other)
            assert not any(r['file_path'] == caller for r in wrong['data']['references'])
            trace.stage("edit_delivery")
            (tmp_path / caller).write_text(changed)
            # Test real protocol edit delivery independently before testing cached
            # selected-symbol evidence. Production refresh must then evict old links.
            async def wait_for_edit():
                manager.notify_file_changed(str(tmp_path / caller), changed, 2)
                async with asyncio.timeout(15):
                    while True:
                        try:
                            refs = await manager.get_references(str(tmp_path / other), line - 1, column, include_declaration=False)
                        except ToolError as error:
                            if str(error).lower() != 'content modified':
                                raise
                            refs = []
                        if any(r.uri == (tmp_path / caller).as_uri() and r.range.start.line == call_line for r in refs):
                            break
                        await asyncio.sleep(.1)
            await on_workspace_loop(wait_for_edit())
            trace.stage("selected_after_edit")
            changed_result = await inspect(other)
            assert any(r['file_path'] == caller and r['line'] == call_line + 1 and r['source'] == 'lsp'
                       for r in changed_result['data']['references']), {
                'response': changed_result, 'protocol': list(protocol)}
            trace.stage("original_after_retarget")
            old = await inspect(target)
            assert not any(r['file_path'] == caller for r in old['data']['references'])
        except BaseException as error:
            trace.failed(error)
            raise
        finally:
            trace.stage("shutdown")
            await gateway.close()
            if trace_dir := os.environ.get("QUALITY_LSP_TRACE_DIR"):
                import json

                destination = Path(trace_dir)
                destination.mkdir(parents=True, exist_ok=True)
                (destination / f"real-server-{language}.json").write_text(
                    json.dumps(list(protocol), indent=2) + "\n")
        assert process is not None and process.returncode is not None
