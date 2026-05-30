"""semantic_search_status surfaces an embedding-model mismatch."""
from __future__ import annotations

from unittest.mock import MagicMock

import attocode.code_intel.tools.search_tools as st


def test_status_reports_model_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_get_remote_service", lambda: None)

    mgr = MagicMock()
    mgr.provider_name = "local:nomic-embed-text-v1.5"
    mgr.is_available = True
    mgr.is_index_ready.return_value = True
    prog = MagicMock()
    prog.status = "idle"
    prog.coverage = 1.0
    prog.indexed_files = 1
    prog.total_files = 1
    prog.failed_files = 0
    prog.degraded_reason = ""
    prog.last_error = ""
    prog.elapsed_seconds = 0.0
    mgr.get_index_progress.return_value = prog
    store = MagicMock()
    store.model_name = "local:bge-base-en-v1.5"
    mgr._store = store
    monkeypatch.setattr(st, "_get_semantic_search", lambda: mgr)

    out = st.semantic_search_status()
    assert "mismatch" in out.lower() or "reindex" in out.lower()
