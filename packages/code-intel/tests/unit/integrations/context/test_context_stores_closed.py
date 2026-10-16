"""Tests for GraphStore and VectorStore after connection close."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attocode_intel._internal.integrations.context.vector_store import VectorEntry, VectorStore

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# GraphStore — closed connection
# =============================================================================




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
