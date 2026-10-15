"""File navigation must not expand same-named definitions across the workspace."""
from dataclasses import replace

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
)
from attocode_intel.service import CodeIntelService


@pytest.mark.parametrize(('suffix', 'source'), [
    ('py', 'def shared(): return 1\n'),
    ('go', 'package sample\nfunc Shared() int { return 1 }\n'),
    ('ts', 'export function shared() { return 1; }\n'),
])
def test_file_symbols_are_local_before_and_after_edit_and_restart(tmp_path, suffix, source):
    names = [f'{name}.{suffix}' for name in ('one', 'two')]
    for name in names:
        (tmp_path / name).write_text(source)
    for restart in range(2):
        ast = ASTService(str(tmp_path))
        try:
            ast.initialize_skeleton(indexing_depth='eager')
            svc = CodeIntelService(str(tmp_path))
            svc._ast_service = ast
            for name in names:
                rows = svc.symbols_data(name)
                assert rows and {r['file_path'] for r in rows} == {name}
                assert ast.get_file_symbols(str(tmp_path / name)) == ast.get_file_symbols(name)
            if not restart:
                old = tmp_path / names[0]
                old.unlink()
                ast.notify_file_changed(str(old))
                assert not ast.get_file_symbols(names[0])
                names[0] = f'renamed.{suffix}'
                new = tmp_path / names[0]
                new.write_text(source.replace('return 1', 'return 2'))
                ast.notify_file_changed(str(new))
                assert {r.file_path for r in ast.get_file_symbols(names[0])} == {names[0]}
        finally:
            ast.stop_hydration()
            ast._store.close()


def test_file_lookup_preserves_overloads_and_lsp_replacement():
    index = CrossRefIndex()
    one = SymbolLocation('shared', 'shared', 'function', 'one.py', 1, 2)
    overload = replace(one, start_line=4, end_line=5)
    other = replace(one, file_path='two.py')
    for loc in (one, overload, other):
        index.add_definition(loc)
    assert index.get_file_definitions('one.py') == [one, overload]
    index.merge_lsp_results('one.py', [replace(one, end_line=3)], [])
    rows = index.get_file_definitions('one.py')
    assert rows == [replace(one, end_line=3, source='lsp'), overload]
    rows.clear()  # A caller cannot mutate the index by changing its returned list.
    index.remove_file('one.py')
    assert not index.get_file_definitions('one.py')
    assert index.get_file_definitions('two.py') == [other]


def test_file_lookup_does_not_scan_workspace_name_collisions():
    index = CrossRefIndex()
    for n in range(500):
        index.add_definition(SymbolLocation('init', 'init', 'function', f'{n}.go', 1, 2))
    class NoScan(dict):
        def get(self, *args):
            raise AssertionError('file lookup scanned the global name index')
    index.definitions = NoScan(index.definitions)
    rows = index.get_file_definitions('12.go')
    assert len(rows) == 1 and rows[0].file_path == '12.go'
    symbols, refs = index._file_evidence_locked('12.go', [])
    assert len(symbols) == 1 and symbols[0]['name'] == 'init' and not refs


def test_constructor_and_persisted_load_rebuild_file_lookup(tmp_path):
    from attocode_intel._internal.integrations.context.index_store import IndexStore, StoredFile
    one = SymbolLocation('shared', 'shared', 'function', 'one.py', 1, 2)
    two = replace(one, file_path='two.py')
    index = CrossRefIndex(definitions={'shared': [one, two]})
    assert index.get_file_definitions('one.py') == [one]
    store = IndexStore(str(tmp_path / 'index.db'))
    try:
        store.save_files_batch([StoredFile(path, 1, 1, 'python', 1, 'hash') for path in ('one.py', 'two.py')])
        index.set_store(store)
        index.persist_files({'one.py', 'two.py'})
        reopened = CrossRefIndex()
        reopened.set_store(store)
        assert reopened.load_from_store() == 2
        assert reopened.get_file_definitions('one.py') == [one]
        assert reopened.get_file_definitions('two.py') == [two]
    finally:
        store.close()
