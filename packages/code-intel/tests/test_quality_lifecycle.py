"""Regression checks for ownership and shutdown, including optional indexes."""
import json
import sqlite3
import threading
import time
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


def test_close_cancels_body_refresh_and_rolls_back_partial_changes(tmp_path, monkeypatch):
    source = tmp_path / "worker.py"
    source.write_text("def original(): return 1\n")
    manager = SemanticSearchManager(str(tmp_path))
    manager._sync_body_index()
    connection = manager._open_body_db()
    before = connection.execute("SELECT * FROM body_fts").fetchall()
    connection.close()
    manager._body_index_built = False
    source.write_text("def changed(): return 12345\n")
    entered = threading.Event()
    original = SemanticSearchManager._body_chunks

    def blocked_chunks(self, *args):
        entered.set()
        deadline = time.monotonic() + 2
        while not self._closed and time.monotonic() < deadline:
            time.sleep(.001)
        yield from original(*args)

    monkeypatch.setattr(SemanticSearchManager, "_body_chunks", blocked_chunks)
    worker = threading.Thread(target=manager._sync_body_index)
    manager._body_thread = worker
    worker.start()
    try:
        assert entered.wait(2)
        manager.close()
        assert not worker.is_alive() and not manager._body_index_built
        connection = manager._open_body_db()
        assert connection.execute("SELECT * FROM body_fts").fetchall() == before
        connection.close()
        manager.warm()
        assert manager._body_thread is worker and not worker.is_alive()
    finally:
        manager.close()
        worker.join(3)


def test_close_refuses_live_indexer_without_closing_shared_resources(tmp_path):
    closed = []
    manager = SemanticSearchManager(str(tmp_path))
    manager._store = SimpleNamespace(close=lambda: closed.append(True))
    worker = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: True)
    manager._body_thread = worker
    with pytest.raises(RuntimeError, match="Source-body indexer did not stop"):
        manager.close()
    assert closed == []
    worker.is_alive = lambda: False
    manager.close()
    assert closed == [True]


def test_close_cancels_keyword_build_between_files(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context import codebase_ast
    for name in ("first.py", "second.py"):
        (tmp_path / name).write_text("def example(): return 1\n")
    manager = SemanticSearchManager(str(tmp_path))
    entered = threading.Event()
    parsed = []
    original = codebase_ast.parse_file

    def blocked_parse(path):
        parsed.append(path)
        entered.set()
        deadline = time.monotonic() + 2
        while not manager._closed and time.monotonic() < deadline:
            time.sleep(.001)
        return original(path)

    monkeypatch.setattr(codebase_ast, "parse_file", blocked_parse)
    context = SimpleNamespace(_ensure_fresh=lambda: None, _files=[
        SimpleNamespace(path=str(tmp_path / name), relative_path=name, is_test=False)
        for name in ("first.py", "second.py")
    ])
    worker = threading.Thread(target=manager._build_keyword_index, args=(context,))
    manager._body_thread = worker
    worker.start()
    try:
        assert entered.wait(2)
        manager.close()
        assert len(parsed) == 1 and not worker.is_alive()
        assert not manager._kw_index_built
    finally:
        manager.close()
        worker.join(3)


def test_close_cancels_discovery_before_keyword_build(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context import codebase_ast
    for name in ("first.py", "second.py"):
        (tmp_path / name).write_text("import sibling\ndef example(): return 1\n")
    manager = SemanticSearchManager(str(tmp_path))
    entered = threading.Event()
    parsed = []
    original = codebase_ast.parse_file

    def blocked_parse(path):
        parsed.append(path)
        entered.set()
        deadline = time.monotonic() + 2
        while not manager._closed and time.monotonic() < deadline:
            time.sleep(.001)
        return original(path)

    monkeypatch.setattr(codebase_ast, "parse_file", blocked_parse)
    manager.warm()
    try:
        assert entered.wait(2)
        manager.close()
        assert len(parsed) == 1 and not manager._body_thread.is_alive()
        assert not manager._kw_index_built and not manager._body_index_built
    finally:
        manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses,is_error,expected_calls", [
    (["warming", "ready"], False, 2),
    (["ready"], False, 1),
    (["warming"], True, 1),
])
async def test_workflow_waits_only_for_explicit_warming(statuses, is_error, expected_calls):
    from mcp import types

    from eval.quality.corpus import ready_search
    calls = []
    async def execute(tool, arguments):
        status = statuses[len(calls)]
        calls.append(tool)
        return types.CallToolResult(isError=is_error, content=[types.TextContent(type="text", text=json.dumps(
            {"data": {"results": [], "ranking": {"index": {"status": status}}}}))])
    result, metrics = await ready_search(SimpleNamespace(execute_mcp=execute), {"max_tokens": 4000})
    assert len(calls) == expected_calls
    assert metrics["warming_responses"] == expected_calls - 1
    assert json.loads(result.content[0].text)["data"]["results"] == []  # A ready miss is not retried.


@pytest.mark.asyncio
async def test_workflow_warming_has_a_deadline():
    from mcp import types

    from eval.quality.corpus import ready_search
    async def execute(tool, arguments):
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(
            {"data": {"ranking": {"index": {"status": "warming"}}}}))])
    with pytest.raises(TimeoutError, match="still warming"):
        await ready_search(SimpleNamespace(execute_mcp=execute), {"max_tokens": 4000}, timeout=0)
