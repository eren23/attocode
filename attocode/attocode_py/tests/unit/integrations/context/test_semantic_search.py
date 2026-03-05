"""Tests for semantic search manager queue-based reindexing."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.context.semantic_search import SemanticSearchManager


class TestQueueReindex:
    def test_queue_reindex_deduplicates_same_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = False
        mgr._store = object()

        # Keep the test deterministic: do not spawn real worker threads.
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)

        file_path = tmp_path / "src" / "mod.py"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("x = 1\n", encoding="utf-8")

        mgr.queue_reindex(str(file_path))
        mgr.queue_reindex(str(file_path))

        assert mgr._reindex_queue.qsize() == 1
        rel = file_path.relative_to(tmp_path).as_posix()
        assert rel in mgr._reindex_pending

    def test_queue_reindex_allows_requeue_after_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = False
        mgr._store = object()
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)

        file_path = tmp_path / "a.py"
        file_path.write_text("print('ok')\n", encoding="utf-8")

        mgr.queue_reindex(str(file_path))
        assert mgr._reindex_queue.qsize() == 1

        # Simulate worker completing the queued item.
        queued = mgr._reindex_queue.get_nowait()
        with mgr._reindex_lock:
            mgr._reindex_pending.discard(queued)
        mgr._reindex_queue.task_done()

        mgr.queue_reindex(str(file_path))
        assert mgr._reindex_queue.qsize() == 1

    def test_queue_reindex_noop_when_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = True
        mgr._store = None
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)

        mgr.queue_reindex(str(tmp_path / "x.py"))
        assert mgr._reindex_queue.qsize() == 0
