"""Persisted repair must build one final index with legacy-equivalent navigation."""
import json
import logging
import re
import sqlite3
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service, index_repair
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_context import build_dependency_graph
from attocode_intel._internal.integrations.context.cross_references import CrossRefIndex, SymbolRef
from attocode_intel._internal.integrations.context.index_store import (
    AST_SNAPSHOT_KEY,
    SNAPSHOT_KEY,
    IndexStore,
)

logger = logging.getLogger(__name__)
parse_file = ast_service.parse_file


def close(service):
    service.stop_hydration()
    service._store.close()


def seed(root):
    root.mkdir(exist_ok=True)
    for name, text in {
        'a.py': 'def target(): return 1\n\ndef helper(): return 2\n',
        'b.py': 'from a import target\n\ndef caller(): return target() + added()\n',
        'c.py': 'from a import helper\n\ndef idle(): return helper()\n',
        'd.py': 'def tail(): return 3\n',
    }.items():
        (root / name).write_text(text)
    service = ASTService(str(root))
    assert service.initialize_skeleton(indexing_depth='eager').phase == 'ready'
    return service


def omit_summary(service, path='a.py'):
    data = json.loads(service._store.get_meta(AST_SNAPSHOT_KEY))
    assert path in data['files']
    del data['files'][path]
    service._store.set_meta(AST_SNAPSHOT_KEY, json.dumps(data))


def database(store):
    conn = store._get_conn()
    return {name: conn.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
            for name in ('files', 'symbols', 'refs', 'dependencies')}


def capture(service):
    index = service._index
    return {
        'asts': {p: asdict(ast) for p, ast in service._ast_cache.items()},
        'definitions': {p: [asdict(v) for v in values] for p, values in index.definitions.items()},
        'references': {p: [asdict(v) for v in values] for p, values in index.references.items()},
        'definition_order': list(index.definitions), 'reference_order': list(index.references),
        'file_symbols': deepcopy(index.file_symbols), 'file_definitions': deepcopy(index._file_definitions),
        'names': index.known_symbol_names(), 'call_edges': deepcopy(index.call_edges),
        'callers_of': deepcopy(index.callers_of), 'dependencies': deepcopy(index.file_dependencies),
        'dependents': deepcopy(index.file_dependents), 'database': database(service._store),
        'stats': service._store.stats(), 'repair': dict(service._last_snapshot_repair),
        'snapshot': service._store.get_meta(SNAPSHOT_KEY),
        'summaries': service._store.get_meta(AST_SNAPSHOT_KEY),
    }


def backup(source, destination):
    before, after = sqlite3.connect(str(source)), sqlite3.connect(str(destination))
    try:
        before.backup(after)
    finally:
        before.close()
        after.close()


def test_persisted_repair_constructs_only_the_final_index(tmp_path):
    root = tmp_path / 'repo'
    first = seed(root)
    expected = {p: asdict(ast) for p, ast in first._ast_cache.items()}
    omit_summary(first)
    close(first)
    second = ASTService(str(root))
    loaded, indexes = [], set()
    original_load, original_add = IndexStore.load_symbols, CrossRefIndex.add_definition

    def load(store, *args, **kwargs):
        loaded.append(id(store))
        return original_load(store, *args, **kwargs)

    def add(index, location):
        indexes.add(id(index))
        return original_add(index, location)

    try:
        with patch.object(IndexStore, 'load_symbols', load), patch.object(CrossRefIndex, 'add_definition', add):
            assert second.initialize_skeleton().phase == 'ready'
        assert {p: asdict(ast) for p, ast in second._ast_cache.items()} == expected
        assert not loaded, 'persisted repair still constructs the complete old index'
        assert len(indexes) == 1, 'persisted repair constructed more than one definition index'
    finally:
        close(second)


def test_repair_loader_matches_full_legacy_inputs_and_preserves_rows(tmp_path):
    service = seed(tmp_path / 'repo')
    try:
        conn = service._store._get_conn()
        with conn:
            for name, line, source in [('zeta', 30, 'tree-sitter'), ('alpha', 31, 'lsp'),
                                       ('zeta', 30, 'tree-sitter'), ('alpha', 32, 'tree-sitter')]:
                conn.execute('INSERT INTO refs(file_path,symbol_name,ref_kind,line,col,source,syntax_name,caller_qualified_name,definition_key) VALUES(?,?,?,?,?,?,?,?,?)',
                    ('c.py', name, 'call', line, 7, source, 'alias.é', 'idle', '["a.py",1,"target"]'))
        before = database(service._store)
        old = CrossRefIndex()
        old.set_store(service._store)
        old.load_from_store()
        names, references = service._store.load_repair_state()
        assert names == set(old.definitions)
        assert list(references) == list(old.references) and references == old.references
        assert len(references['zeta']) == 2 and references['zeta'][0] == references['zeta'][1]
        assert references['alpha'][0].source == 'lsp' and references['alpha'][0].definition_key == '["a.py",1,"target"]'
        assert database(service._store) == before
    finally:
        close(service)


def test_empty_repair_loader_returns_empty_inputs_without_writes(tmp_path):
    store = IndexStore(str(tmp_path / 'empty.db'))
    try:
        before = database(store)
        assert store.load_repair_state() == (set(), {})
        assert database(store) == before
    finally:
        store.close()


@pytest.mark.parametrize('change', ['partial', 'rename', 'added', 'deleted', 'lsp', 'duplicates', 'empty_name'])
def test_persisted_repair_matches_frozen_restore_and_repair(tmp_path, change):
    root = tmp_path / 'repo'
    first = seed(root)
    conn = first._store._get_conn()
    if change in ('lsp', 'duplicates'):
        with conn:
            for source in (['lsp'] if change == 'lsp' else ['tree-sitter', 'tree-sitter']):
                conn.execute('INSERT INTO refs(file_path,symbol_name,ref_kind,line,col,source,syntax_name,caller_qualified_name,definition_key) VALUES(?,?,?,?,?,?,?,?,?)',
                    ('c.py', 'target', 'call', 33, 9, source, 'alias.target', 'idle', '["a.py",1,"target"]'))
        assert first._save_snapshot()
    if change == 'empty_name':
        with conn:
            conn.execute('INSERT INTO symbols(file_path,name,qualified_name,kind,line,end_line,source) VALUES(?,?,?,?,?,?,?)',
                         ('d.py', 'empty', '', 'function', 50, 51, 'tree-sitter'))
        assert first._save_snapshot()
    omit_summary(first)
    db = Path(first._store.db_path)
    close(first)
    if change == 'rename':
        (root / 'a.py').write_text('def replacement(): return 1\n\ndef helper(): return 2\n')
    elif change == 'added':
        with (root / 'a.py').open('a') as stream:
            stream.write('\ndef added(): return 4\n')
    elif change == 'deleted':
        (root / 'a.py').unlink()
    frozen = tmp_path / 'before.sqlite'
    backup(db, frozen)
    legacy = ASTService(str(root))
    try:
        with patch.object(ASTService, '_restore_snapshot', legacy_restore), patch.object(index_repair, 'repair_index', legacy_repair):
            assert legacy.initialize_skeleton().phase == 'ready'
        expected = capture(legacy)
    finally:
        close(legacy)
    backup(frozen, db)
    candidate = ASTService(str(root))
    try:
        assert candidate.initialize_skeleton().phase == 'ready'
        assert capture(candidate) == expected
        if change == 'added':
            assert any(ref.file_path == 'b.py' for ref in candidate._index.references['added'])
        if change == 'lsp':
            assert not any(ref.source == 'lsp' for refs in candidate._index.references.values() for ref in refs)
    finally:
        close(candidate)


def test_complete_restart_still_uses_full_load_without_repair(tmp_path):
    root = tmp_path / 'repo'
    first = seed(root)
    close(first)
    second = ASTService(str(root))
    original, calls = IndexStore.load_symbols, []

    def loaded(store, *args, **kwargs):
        calls.append(id(store))
        return original(store, *args, **kwargs)

    try:
        with patch.object(IndexStore, 'load_repair_state', side_effect=AssertionError('unexpected repair load')), patch.object(IndexStore, 'load_symbols', loaded):
            assert second.initialize_skeleton().phase == 'ready'
        assert calls == [id(second._store)]
    finally:
        close(second)


def test_live_repair_keeps_unpersisted_lsp_invalidation(tmp_path):
    service = seed(tmp_path / 'repo')
    service._index.add_reference(SymbolRef('ghost', 'call', 'd.py', 1, source='lsp', caller_qualified_name='tail'))
    try:
        with patch.object(IndexStore, 'load_repair_state', side_effect=AssertionError('live repair reloaded disk')):
            assert service.repair_changed_files()
        assert service._last_snapshot_repair['reindexed_reference_files'] == 1
        assert not service._index.references.get('ghost')
    finally:
        close(service)


def test_failed_snapshot_save_does_not_publish_replacement(tmp_path):
    service = seed(tmp_path / 'repo')
    original, asts = service._index, dict(service._ast_cache)
    try:
        with patch.object(ASTService, '_save_snapshot', return_value=False), pytest.raises(ValueError, match='before index repair completed'):
            index_repair.repair_index(service, asts, service._snapshot_start, {'a.py'}, persisted=True)
        assert service._index is original and service._ast_cache == asts
        assert service._store.get_meta(SNAPSHOT_KEY) == ''
    finally:
        close(service)


def test_sql_read_failure_falls_back_to_full_initialization(tmp_path):
    root = tmp_path / 'repo'
    first = seed(root)
    expected = {p: asdict(ast) for p, ast in first._ast_cache.items()}
    omit_summary(first)
    close(first)
    second = ASTService(str(root))
    try:
        with (patch.object(IndexStore, 'load_repair_state', side_effect=sqlite3.DatabaseError('read failed')),
              patch.object(second, '_index_references', wraps=second._index_references) as extracted):
            state = second.initialize_skeleton()
        assert extracted.call_count == state.parsed_files == state.reference_indexed_files == len(expected)
        assert second.hydration_snapshot()['phase'] == 'ready'
        assert {p: asdict(ast) for p, ast in second._ast_cache.items()} == expected
    finally:
        close(second)


# Frozen baseline6143d0d algorithms, test-only semantic oracle; imports made absolute.


def legacy_restore(self, files, parseable, state, *, summaries=None, snapshot=None) -> bool:
        """Restore a completed index and repair offline edits when necessary.

        Bounded summaries reuse unchanged ASTs with exact source/parser identity;
        missing or invalid entries are reparsed. References remain persisted. Older caches
        without the completion record are rebuilt once.
        """
        raw = self._store.get_meta(SNAPSHOT_KEY)
        if not raw:
            return False
        try:
            saved = json.loads(raw)
            if saved["counts"] != self._store.stats():
                return False
            from attocode_intel._internal.integrations.context.ast_snapshot import (
                navigation_identity,
                restore_summaries,
            )

            if summaries is None or snapshot != raw:
                summaries = restore_summaries(self._store, raw, parseable)
            else:
                eligible = {fi.relative_path for fi in parseable}
                summaries = {path: ast for path, ast in summaries.items() if path in eligible}
            cached = summaries if summaries is not None else {}
            reparsed = set()
            for fi in parseable:
                if fi.relative_path not in cached:
                    cached[fi.relative_path] = parse_file(fi.path)
                    reparsed.add(fi.relative_path)
            if self._snapshot_identity() != self._snapshot_start:
                return False
            self._index.load_from_store()
            verified_navigation = saved.get('navigation_identity') == navigation_identity()
            # A missing summary can follow a transient grammar failure or a
            # parser upgrade. Unchanged source does not prove that the freshly
            # parsed definitions/references match the persisted index.
            if (reparsed or not verified_navigation or saved["identity"] != self._snapshot_start
                    or saved["discovered"] != sorted(fi.relative_path for fi in files)
                    or saved["parsed"] != sorted(cached)):
                from attocode_intel._internal.integrations.context.index_repair import (
                    changed_paths,
                    repair_index,
                )

                changed = changed_paths(saved["identity"], self._snapshot_start)
                changed |= set(saved["parsed"]) ^ cached.keys()
                changed |= reparsed
                if not verified_navigation:
                    changed |= cached.keys()
                self._last_snapshot_repair = repair_index(self, cached, self._snapshot_start, changed)
                return True
            from attocode_intel._internal.integrations.context.codebase_context import (
                DependencyGraph,
            )

            graph = DependencyGraph(unresolved=saved["unresolved"])
            for source, targets in self._index.file_dependencies.items():
                for target in targets:
                    graph.add_edge(source, target)
            if summaries is None:
                from attocode_intel._internal.integrations.context.ast_snapshot import (
                    encode_summaries,
                )

                # Retain a completion summary even for an empty parseable set.
                # Nonempty cache misses were reconciled by repair_index above.
                self._store.set_meta(AST_SNAPSHOT_KEY, encode_summaries(cached, raw))
            self._context_mgr._dep_graph = graph
            self._ast_cache = cached
            self._reference_indexed_files = set(cached)
            state.parsed_files = len(cached)
            state.reference_indexed_files = len(cached)
            state.dep_graph_files = len(graph.forward)
            state.phase = "ready"
            return True
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            logger.debug("Cannot restore structural snapshot", exc_info=True)
            self._index = CrossRefIndex()
            self._index.set_store(self._store)
            self._ast_cache.clear()
            self._reference_indexed_files.clear()
            state.parsed_files = state.reference_indexed_files = 0
            state.phase = "skeleton"
            return False


def legacy_repair(service, asts: dict, identity: dict, changed: set[str]) -> dict:
    """Keep unaffected references; rebuild graph resolution from current ASTs.

    A definition added or removed can affect calls in unchanged source files.
    Shortlist those files using changed symbol names before extracting their
    references again. All definitions exist before any reference extraction.
    """
    asts = dict(asts)
    old = service._index
    new = CrossRefIndex()
    for path, ast in asts.items():
        service._index_definitions(path, ast, index=new)

    names = {name.rsplit(".", 1)[-1] for name in old.definitions.keys() ^ new.definitions.keys()}
    affected = changed & asts.keys()
    # Precision is tied to a complete workspace generation, including target edits.
    affected |= {ref.file_path for refs in old.references.values() for ref in refs
                 if ref.source == "lsp" and ref.file_path in asts}
    if names:
        # Broad refactors fall back to complete reference extraction. Small
        # edits scan text once without parsing every call site again.
        pattern = re.compile("|".join(re.escape(name) for name in sorted(names))) if len(names) <= 128 else None
        for path in asts.keys() - affected:
            if pattern is None or pattern.search(
                (Path(service.root_dir) / path).read_text(encoding="utf-8", errors="replace")
            ):
                affected.add(path)

    for refs in old.references.values():
        for ref in refs:
            if ref.file_path in asts and ref.file_path not in affected:
                new.add_reference(ref)
    for path in sorted(affected):
        # Reference extraction updates diagnostics. Keep those changes private
        # as well as navigation until the replacement generation is accepted.
        asts[path] = replace(asts[path], parse_failures=list(asts[path].parse_failures))
        service._index_references(path, asts[path], index=new)

    graph = build_dependency_graph(service._context_mgr._files, service.root_dir, ast_cache=asts)
    for source, targets in graph.forward.items():
        for target in targets:
            new.add_file_dependency(source, target)
    if service._snapshot_identity() != identity:
        raise ValueError("Workspace changed during index repair; retry")

    # Invalidate before the first write: a crash cannot bless a partial update.
    store = service._store
    store.set_meta(SNAPSHOT_KEY, "")
    removed = {row.path for row in store.get_all_files()} - asts.keys()
    for path in sorted(removed):
        store.remove_file(path)
    store.save_files_batch([
        service._build_stored_file(path, asts[path], identity["files"][path][0] / 1e9)
        for path in sorted(affected)
    ])
    new.set_store(store)
    new.persist_files(affected)

    if not service._save_snapshot(asts=asts, index=new, identity=identity, graph=graph):
        raise ValueError("Workspace changed before index repair completed; retry")

    service._index = new
    service._ast_cache = asts
    service._reference_indexed_files = set(asts)
    service._context_mgr._dep_graph = graph
    service._context_mgr._ast_cache = dict(asts)
    service._context_mgr._repo_map = None
    service._snapshot_start = identity
    state = service._hydration_state
    state.total_files = state.parsed_files = state.reference_indexed_files = len(asts)
    state.dep_graph_files = len(graph.forward)
    state.phase = "ready"
    store.record_scan_time()
    return {
        "changed_files": len(changed),
        "removed_files": len(removed),
        "reindexed_reference_files": len(affected),
        "reused_reference_files": len(asts) - len(affected),
    }
