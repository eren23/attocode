"""Lexical SQL batching preserves cache contents, replacement order and rollback."""
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _KeywordDoc,
)


def docs(count):
    return [_KeywordDoc(f'id:{i}', f"file_{i}%'.py", 'function', f'Helper{i}',
                        'preview K', i % 2 == 0, i % 3 == 0, {'needle': i + 1}, i + 1)
            for i in range(count)]


def cache_rows(manager):
    conn = manager._open_kw_cache_db()
    try:
        return [conn.execute(f'SELECT rowid,* FROM {table} ORDER BY rowid').fetchall()
                for table in ('kw_files', 'kw_docs')]
    finally:
        conn.close()


def test_keyword_batches_preserve_duplicate_order_fields_and_loaded_documents(tmp_path, monkeypatch):
    manager = SemanticSearchManager(str(tmp_path))
    documents = docs(133)
    documents += [replace(documents[i], name='Replacement', term_freqs={'changed': 2})
                  for i in (0, 63, 64)]
    mtimes = {d.file_path: float(i) for i, d in enumerate(documents)}
    original = SemanticSearchManager._open_kw_cache_db
    statements = []
    def opened(self):
        conn = original(self)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(SemanticSearchManager, '_open_kw_cache_db', opened)
    try:
        manager._save_kw_cache(documents, mtimes)
        assert sum(s.startswith('INSERT INTO kw_files ') for s in statements) == 3
        assert sum(s.startswith('INSERT OR REPLACE INTO kw_docs ') for s in statements) == 3
        with original(manager) as conn, sqlite3.connect(':memory:') as reference:
            for table in ('kw_files', 'kw_docs'):
                reference.execute(conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0])
            # Preceding row-at-a-time semantics, including repeated IDs across groups.
            for path, mtime in mtimes.items():
                reference.execute('INSERT INTO kw_files VALUES (?,?)', (path, mtime))
            for d in documents:
                reference.execute('INSERT OR REPLACE INTO kw_docs VALUES (?,?,?,?,?,?,?,?,?)',
                                  (d.id,d.file_path,d.chunk_type,d.name,d.text,int(d.is_config),int(d.is_test),
                                   json.dumps(d.term_freqs),d.doc_len))
            expected = [reference.execute(f'SELECT rowid,* FROM {t} ORDER BY rowid').fetchall()
                        for t in ('kw_files', 'kw_docs')]
        conn.close()
        reference.close()
        assert cache_rows(manager) == expected
        loaded, stale = manager._load_kw_cache({p: (str(tmp_path / p), m) for p, m in mtimes.items()})
        assert not stale and {d.id: d for d in loaded} == {d.id: d for d in documents}
    finally:
        manager.close()


@pytest.mark.parametrize('failure', ['sql', 'encoding', 'cancel'])
def test_keyword_second_group_failure_or_close_keeps_prior_atomic_cache(tmp_path, monkeypatch, failure):
    manager = SemanticSearchManager(str(tmp_path))
    old = docs(1)
    manager._save_kw_cache(old, {old[0].file_path: 1})
    before = cache_rows(manager)
    original = SemanticSearchManager._open_kw_cache_db
    inserts = []
    class Connection:
        def __init__(self, conn):
            self.conn = conn
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def execute(self, sql, parameters=()):
            if sql.startswith('INSERT OR REPLACE INTO kw_docs '):
                inserts.append(len(parameters) // 9)
                assert len(parameters) <= 576
                if failure == 'sql' and len(inserts) == 2:
                    raise sqlite3.OperationalError('second group failure')
                if failure == 'cancel' and len(inserts) == 1:
                    manager._closed = True
            return self.conn.execute(sql, parameters)
    monkeypatch.setattr(SemanticSearchManager, '_open_kw_cache_db', lambda self: Connection(original(self)))
    documents = docs(133)
    if failure == 'encoding':
        documents[100].term_freqs = {'bad': object()}
    try:
        manager._save_kw_cache(documents, {d.file_path: 2 for d in documents})
        manager._closed = False
        monkeypatch.setattr(SemanticSearchManager, '_open_kw_cache_db', original)
        assert cache_rows(manager) == before
        assert inserts[0] == 64
        manager._save_kw_cache(docs(133), {d.file_path: 2 for d in docs(133)})
        assert len(cache_rows(manager)[1]) == 133
    finally:
        manager.close()


def test_body_delete_groups_preserve_unchanged_rows_and_rollback_mid_delete(tmp_path, monkeypatch):
    paths = [tmp_path / f'f{i:03}.py' for i in range(133)] + [tmp_path / 'unchanged.py']
    for path in paths:
        path.write_text('def helper(): return "OldNeedle"\n')
    def context():
        return SimpleNamespace(_ensure_fresh=lambda: None, _files=[SimpleNamespace(
            path=str(p), relative_path=p.name) for p in paths if p.exists()])
    manager = SemanticSearchManager(str(tmp_path))
    original = SemanticSearchManager._open_body_db
    def snapshot():
        conn = original(manager)
        try:
            return [conn.execute(f'SELECT rowid,* FROM {t} ORDER BY rowid').fetchall()
                    for t in ('body_fts', 'body_file_fts', 'body_files')]
        finally:
            conn.close()
    try:
        manager._sync_body_index(context())
        assert manager._body_index_built
        before = snapshot()
        for i, path in enumerate(paths[:-1]):
            if i < 12:
                path.unlink()
            else:
                path.write_text('def helper(): return "FreshNeedle"\n')
        deletes = []
        fail = [True]
        class Connection:
            def __init__(self, conn):
                self.conn = conn
            def __getattr__(self, name):
                return getattr(self.conn, name)
            def execute(self, sql, parameters=()):
                if sql.startswith('DELETE FROM body_'):
                    deletes.append((sql, len(parameters)))
                    assert 1 <= len(parameters) <= 64
                    if fail[0] and len(deletes) == 4:
                        raise sqlite3.OperationalError('second delete group failure')
                return self.conn.execute(sql, parameters)
        monkeypatch.setattr(SemanticSearchManager, '_open_body_db', lambda self: Connection(original(self)))
        manager._body_index_built = False
        manager._sync_body_index(context())
        assert not manager._body_index_built and snapshot() == before
        fail[0] = False
        deletes.clear()
        manager._sync_body_index(context())
        assert manager._body_index_built and len(deletes) == 9
        assert [count for _, count in deletes] == [64]*6 + [5]*3
        after = snapshot()
        for old, new in zip(before, after, strict=True):
            assert [r for r in old if r[1] == 'unchanged.py'] == [r for r in new if r[1] == 'unchanged.py']
        conn = original(manager)
        try:
            assert conn.execute("SELECT DISTINCT file_path FROM body_fts WHERE body_fts MATCH 'old'").fetchall() == [('unchanged.py',)]
            assert conn.execute('SELECT count(*) FROM body_files').fetchone()[0] == 122
        finally:
            conn.close()
    finally:
        manager.close()
