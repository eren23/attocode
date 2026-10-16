"""Repeated public navigation across edits, renames, deletion and branch recovery."""
import subprocess

import pytest
from attocode_intel.gateway import OperationGateway

SOURCES = {
    'py': ('def helper(): return 1\ndef other(): return 2\n', 'def caller(): return {callee}()\n'),
    'js': ('export function helper() {{ return 1 }}\nexport function other() {{ return 2 }}\n',
           'export function caller() {{ return {callee}() }}\n'),
    'ts': ('export function helper() {{ return 1 }}\nexport function other() {{ return 2 }}\n',
           'export function caller() {{ return {callee}() }}\n'),
    'go': ('package fixture\nfunc helper() int {{ return 1 }}\nfunc other() int {{ return 2 }}\n',
           'func caller() int {{ return {callee}() }}\n'),
    'rs': ('fn helper() -> i32 {{ 1 }}\nfn other() -> i32 {{ 2 }}\n',
           'fn caller() -> i32 {{ {callee}() }}\n'),
}


@pytest.mark.parametrize('extension', SOURCES)
async def test_repeated_edit_branch_and_restart_navigation(tmp_path, monkeypatch, extension):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    head, call = SOURCES[extension]
    original, moved = f'engine.{extension}', f'moved.{extension}'
    def content(callee):
        return head.format() + call.format(callee=callee)
    def git(*args):
        subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Quality Fixture',
                        '-c', 'user.email=fixture@example.invalid', *args], check=True,
                       capture_output=True, text=True)
    (tmp_path / original).write_text(content('helper'))
    git('init', '-q', '-b', 'base')
    git('add', original)
    git('commit', '-qm', 'baseline fixture')
    git('switch', '-qc', 'alternate')
    (tmp_path / original).write_text(content('other'))
    git('commit', '-qam', 'alternate caller')
    git('switch', '-q', 'base')
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    async def check(path, callee):
        for name in ('helper', 'other'):
            response = await gateway.execute('cross_references', {'symbol_name':name})
            assert not response.isError
            data = response.structuredContent['data']
            refs = data['references']
            assert [(r['file_path'], r['line']) for r in refs] == (
                [(path, len(content(callee).splitlines()))] if callee == name else [])
            assert response.structuredContent['metadata']['analysis']['absence_proven'] is False
        if path:
            impact = await gateway.execute('impact_analysis', {'changed_files':[path]})
            assert not impact.isError
            assert impact.structuredContent['metadata']['analysis']['absence_proven'] is False
    try:
        for _ in range(3):
            await check(original, 'helper')
            (tmp_path / original).write_text(content('other'))
            await check(original, 'other')
            (tmp_path / original).rename(tmp_path / moved)
            await check(moved, 'other')
            (tmp_path / moved).unlink()
            await check(None, None)
            git('restore', original)
            await check(original, 'helper')
            git('switch', '-q', 'alternate')
            await check(original, 'other')
            await gateway.close()
            gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
            await check(original, 'other')
            git('switch', '-q', 'base')
            await check(original, 'helper')
    finally:
        await gateway.close()
