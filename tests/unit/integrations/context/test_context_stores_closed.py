"""Tests for GraphStore and VectorStore after connection close."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from attocode.integrations.context.graph_store import CachedFileInfo, GraphStore
from attocode.integrations.context.vector_store import VectorEntry, VectorStore

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# GraphStore — closed connection
# =============================================================================


class TestGraphStoreClosedConnection:
    """All public methods raise RuntimeError after close()."""

    def test_get_cached_files_after_close(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        with pytest.raises(RuntimeError, match="GraphStore connection is closed"):
            store.get_cached_files()

    def test_upsert_file_after_close(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        info = CachedFileInfo(
            relative_path="a.py",
            content_hash="abc",
            language="python",
            line_count=10,
            importance=0.5,
            mtime=0.0,
        )
        with pytest.raises(RuntimeError, match="GraphStore connection is closed"):
            store.upsert_file(info)

    def test_get_forward_deps_after_close(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        with pytest.raises(RuntimeError, match="GraphStore connection is closed"):
            store.get_forward_deps()

    def test_file_count_after_close(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        with pytest.raises(RuntimeError, match="GraphStore connection is closed"):
            _ = store.file_count

    def test_get_meta_after_close(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        with pytest.raises(RuntimeError, match="GraphStore connection is closed"):
            store.get_meta("version")

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        store = GraphStore(str(tmp_path))
        store.close()
        store.close()  # should not raise


# =============================================================================
# VectorStore — closed connection
# =============================================================================


class TestVectorStoreClosedConnection:
    """All public methods raise RuntimeError after close()."""

    def test_upsert_after_close(self, tmp_path: Path) -> None:
        store = VectorStore(db_path=str(tmp_path / "v.db"), dimension=4)
        store.close()
        entry = VectorEntry(
            id="e1",
            file_path="a.py",
            chunk_type="file",
            name="a",
            text="hello",
            vector=[0.1, 0.2, 0.3, 0.4],
        )
        with pytest.raises(RuntimeError, match="VectorStore connection is closed"):
            store.upsert(entry)

    def test_search_after_close(self, tmp_path: Path) -> None:
        store = VectorStore(db_path=str(tmp_path / "v.db"), dimension=4)
        store.close()
        with pytest.raises(RuntimeError, match="VectorStore connection is closed"):
            store.search([0.0, 0.0, 0.0, 0.0])

    def test_count_after_close(self, tmp_path: Path) -> None:
        store = VectorStore(db_path=str(tmp_path / "v.db"), dimension=4)
        store.close()
        with pytest.raises(RuntimeError, match="VectorStore connection is closed"):
            store.count()

    def test_delete_by_file_after_close(self, tmp_path: Path) -> None:
        store = VectorStore(db_path=str(tmp_path / "v.db"), dimension=4)
        store.close()
        with pytest.raises(RuntimeError, match="VectorStore connection is closed"):
            store.delete_by_file("a.py")

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        store = VectorStore(db_path=str(tmp_path / "v.db"), dimension=4)
        store.close()
        store.close()  # should not raise
