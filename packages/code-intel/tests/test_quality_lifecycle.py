"""Regression checks for ownership and shutdown, including optional indexes."""
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager


def test_embedding_queue_worker_stops_before_store_close(tmp_path, monkeypatch):
    observed = []
    manager = SemanticSearchManager(str(tmp_path))
    manager._keyword_fallback = False
    manager._store = SimpleNamespace(close=lambda: observed.append("closed"))
    monkeypatch.setattr(SemanticSearchManager, "reindex_file", lambda self, path: observed.append(path))
    manager.queue_reindex(str(tmp_path / "sample.py"))
    manager.close()
    assert observed == ["sample.py", "closed"]
    assert not manager._reindex_thread.is_alive()
    manager.queue_reindex(str(tmp_path / "later.py"))
    assert manager._reindex_queue.empty()
    assert not any(t is manager._reindex_thread for t in threading.enumerate())


@pytest.mark.asyncio
async def test_local_lifecycle_releases_resources(tmp_path, monkeypatch):
    from eval.quality.probes import probe
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    monkeypatch.setenv("ATTOCODE_EMBEDDING_MODEL", "")
    result = await probe(tmp_path, cycles=3)
    assert result["passed"] and len(result["cycles"]) == 3


@pytest.mark.parametrize("error,available", [("database is locked", True), ("no such module: fts5", False)])
def test_transient_sqlite_error_does_not_disable_source_search(tmp_path, monkeypatch, error, available):
    manager = SemanticSearchManager(str(tmp_path))
    closed = []
    def fail(*args):
        raise sqlite3.OperationalError(error)
    connection = SimpleNamespace(execute=fail, close=lambda: closed.append(True))
    monkeypatch.setattr(SemanticSearchManager, "_open_kw_cache_db", lambda self: connection)
    assert manager._open_body_db() is None
    assert manager._body_index_available is available and closed == [True]


def test_schema_setup_failure_closes_sqlite_connection(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context import semantic_search
    closed = []
    def fail(*args):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(semantic_search.sqlite3, "connect", lambda *a, **kw:
                        SimpleNamespace(execute=fail, close=lambda: closed.append(True)))
    manager = SemanticSearchManager(str(tmp_path))
    assert manager._open_kw_cache_db() is None and closed == [True]
