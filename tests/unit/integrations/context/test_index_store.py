"""Tests for IndexStore — SQLite persistence for symbols, refs, and deps."""

from __future__ import annotations

import os
import tempfile

import pytest

from attocode.integrations.context.index_store import (
    IndexStore,
    StoredFile,
)


@pytest.fixture()
def store(tmp_path):
    """Create an IndexStore with a temp database."""
    db_path = str(tmp_path / "test_symbols.db")
    s = IndexStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture()
def populated_store(store):
    """Store pre-populated with sample data."""
    store.save_file(StoredFile(
        path="src/main.py", mtime=1000.0, size=500,
        language="python", line_count=50, content_hash="abc",
    ))
    store.save_file(StoredFile(
        path="src/utils.py", mtime=2000.0, size=300,
        language="python", line_count=30, content_hash="def",
    ))
    store.save_symbols("src/main.py", [
        {"name": "main", "qualified_name": "main", "kind": "function",
         "line": 1, "end_line": 10},
        {"name": "Config", "qualified_name": "Config", "kind": "class",
         "line": 12, "end_line": 30},
    ])
    store.save_symbols("src/utils.py", [
        {"name": "parse", "qualified_name": "parse", "kind": "function",
         "line": 1, "end_line": 15},
    ])
    store.save_references("src/main.py", [
        {"symbol_name": "parse", "ref_kind": "call", "line": 5, "column": 4},
    ])
    store.save_dependencies("src/main.py", {"src/utils.py"})
    return store


class TestIndexStoreBasics:
    def test_create_store(self, store):
        stats = store.stats()
        assert stats["files"] == 0
        assert stats["symbols"] == 0

    def test_schema_version_set(self, store):
        from attocode.integrations.context.index_store import SCHEMA_VERSION

        assert store.get_meta("schema_version") == SCHEMA_VERSION

    def test_metadata(self, store):
        store.set_meta("test_key", "test_value")
        assert store.get_meta("test_key") == "test_value"
        assert store.get_meta("nonexistent") is None


class TestFileOperations:
    def test_save_and_get_file(self, store):
        f = StoredFile(
            path="src/main.py", mtime=1234.5, size=100,
            language="python", line_count=10, content_hash="abc",
        )
        store.save_file(f)
        loaded = store.get_file("src/main.py")
        assert loaded is not None
        assert loaded.path == "src/main.py"
        assert loaded.mtime == 1234.5
        assert loaded.language == "python"

    def test_get_nonexistent_file(self, store):
        assert store.get_file("nonexistent.py") is None

    def test_get_all_files(self, populated_store):
        files = populated_store.get_all_files()
        assert len(files) == 2
        paths = {f.path for f in files}
        assert paths == {"src/main.py", "src/utils.py"}

    def test_save_files_batch(self, store):
        files = [
            StoredFile(path=f"file{i}.py", mtime=float(i), size=i * 10,
                       language="python", line_count=i, content_hash=str(i))
            for i in range(5)
        ]
        store.save_files_batch(files)
        assert store.stats()["files"] == 5

    def test_remove_file_cascades(self, populated_store):
        populated_store.remove_file("src/main.py")
        assert populated_store.get_file("src/main.py") is None
        # Symbols for that file should also be gone
        symbols = populated_store.load_symbols("src/main.py")
        assert len(symbols) == 0
        # References should also be gone
        refs = populated_store.load_references("src/main.py")
        assert len(refs) == 0


class TestStalenessDetection:
    def test_stale_files_new_file(self, store):
        stale = store.get_stale_files({"new_file.py": 100.0})
        assert "new_file.py" in stale

    def test_stale_files_unchanged(self, populated_store):
        stale = populated_store.get_stale_files({"src/main.py": 1000.0})
        assert "src/main.py" not in stale

    def test_stale_files_modified(self, populated_store):
        stale = populated_store.get_stale_files({"src/main.py": 2000.0})
        assert "src/main.py" in stale

    def test_deleted_files(self, populated_store):
        deleted = populated_store.get_deleted_files({"src/main.py"})
        assert "src/utils.py" in deleted
        assert "src/main.py" not in deleted


class TestSymbolOperations:
    def test_save_and_load_symbols(self, populated_store):
        symbols = populated_store.load_symbols("src/main.py")
        assert len(symbols) == 2
        names = {s.name for s in symbols}
        assert names == {"main", "Config"}

    def test_load_all_symbols(self, populated_store):
        symbols = populated_store.load_symbols()
        assert len(symbols) == 3  # 2 from main.py + 1 from utils.py

    def test_save_replaces_existing(self, populated_store):
        populated_store.save_symbols("src/main.py", [
            {"name": "new_func", "qualified_name": "new_func", "kind": "function"},
        ])
        symbols = populated_store.load_symbols("src/main.py")
        assert len(symbols) == 1
        assert symbols[0].name == "new_func"

    def test_symbol_source_field(self, store):
        store.save_file(StoredFile(
            path="test.py", mtime=0, size=0, language="python",
            line_count=0, content_hash="",
        ))
        store.save_symbols("test.py", [
            {"name": "foo", "qualified_name": "foo", "kind": "function",
             "source": "lsp"},
        ])
        symbols = store.load_symbols("test.py")
        assert symbols[0].source == "lsp"


class TestReferenceOperations:
    def test_save_and_load_refs(self, populated_store):
        refs = populated_store.load_references("src/main.py")
        assert len(refs) == 1
        assert refs[0].symbol_name == "parse"
        assert refs[0].ref_kind == "call"

    def test_load_all_refs(self, populated_store):
        refs = populated_store.load_references()
        assert len(refs) == 1


class TestDependencyOperations:
    def test_save_and_load_deps(self, populated_store):
        deps = populated_store.load_dependencies()
        assert "src/main.py" in deps
        assert "src/utils.py" in deps["src/main.py"]

    def test_save_deps_replaces(self, populated_store):
        populated_store.save_dependencies("src/main.py", {"src/new.py"})
        deps = populated_store.load_dependencies()
        assert deps["src/main.py"] == {"src/new.py"}

    def test_batch_save_deps(self, store):
        edges = [("a.py", "b.py"), ("a.py", "c.py"), ("b.py", "c.py")]
        store.save_dependencies_batch(edges)
        deps = store.load_dependencies()
        assert deps["a.py"] == {"b.py", "c.py"}
        assert deps["b.py"] == {"c.py"}


class TestBulkOperations:
    def test_clear_all(self, populated_store):
        populated_store.clear_all()
        stats = populated_store.stats()
        assert stats["files"] == 0
        assert stats["symbols"] == 0
        assert stats["references"] == 0
        assert stats["dependencies"] == 0

    def test_record_and_get_scan_time(self, store):
        assert store.get_last_scan_time() is None
        store.record_scan_time()
        scan_time = store.get_last_scan_time()
        assert scan_time is not None
        assert scan_time > 0


class TestSchemaVersioning:
    def test_schema_mismatch_clears_data(self, tmp_path):
        """When schema version changes, existing data should be cleared."""
        db_path = str(tmp_path / "version_test.db")

        # Create store with data
        store1 = IndexStore(db_path=db_path)
        store1.save_file(StoredFile(
            path="test.py", mtime=0, size=0, language="python",
            line_count=0, content_hash="",
        ))
        assert store1.stats()["files"] == 1
        store1.close()

        # Simulate schema version change by manually updating
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE metadata SET value = '0' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()

        # Reopen — should detect mismatch and clear
        store2 = IndexStore(db_path=db_path)
        assert store2.stats()["files"] == 0
        store2.close()
