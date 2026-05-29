"""Regression: opening a pre-v3 IndexStore DB must migrate (drop+rebuild)
without crashing.

A v2 ``refs`` table lacks ``caller_qualified_name``. The v3 ``_create_tables``
builds ``CREATE INDEX ix_refs_caller ON refs(caller_qualified_name)``, which
raises ``OperationalError`` on the stale table — and because that ran *before*
the schema-version check, the store could never open to perform the migration.
This blocks local mode entirely on any existing v2 ``.attocode/index/symbols.db``.
"""

from __future__ import annotations

import sqlite3


def _seed_v2_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata (key, value) VALUES ('schema_version', '2');
        CREATE TABLE files (
            path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL,
            language TEXT NOT NULL DEFAULT '', line_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL,
            name TEXT NOT NULL, qualified_name TEXT NOT NULL, kind TEXT NOT NULL,
            line INTEGER NOT NULL DEFAULT 0, end_line INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'tree-sitter'
        );
        -- v2 refs: NO caller_qualified_name column
        CREATE TABLE refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL,
            symbol_name TEXT NOT NULL, ref_kind TEXT NOT NULL DEFAULT 'call',
            line INTEGER NOT NULL DEFAULT 0, col INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'tree-sitter'
        );
        CREATE TABLE dependencies (
            source_path TEXT NOT NULL, target_path TEXT NOT NULL,
            PRIMARY KEY (source_path, target_path)
        );
        INSERT INTO files (path, mtime, size) VALUES ('a.py', 1.0, 10);
        """
    )
    conn.commit()
    conn.close()


def test_indexstore_opens_and_migrates_stale_v2_schema(tmp_path):
    from attocode.integrations.context.index_store import SCHEMA_VERSION, IndexStore

    db = tmp_path / "symbols.db"
    _seed_v2_db(str(db))

    # Must NOT raise OperationalError("no such column: caller_qualified_name").
    store = IndexStore(db_path=str(db))

    assert store.get_meta("schema_version") == SCHEMA_VERSION
    cols = [r[1] for r in store._get_conn().execute("PRAGMA table_info(refs)").fetchall()]
    assert "caller_qualified_name" in cols
