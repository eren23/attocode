"""Regression: the kw_index (BM25) store definition must target the real
`kw_docs` table, not the non-existent `documents` — otherwise cache_status_all
and verify_all_caches falsely report the BM25 index empty/broken.
"""

from __future__ import annotations

import os
import sqlite3


def test_kw_index_rows_counted_via_store_def(tmp_path):
    from attocode.code_intel.tools.maintenance_tools import _store_row_count
    from attocode.code_intel.tools.pin_tools import _STORE_DEFS

    idx = tmp_path / ".attocode" / "index"
    idx.mkdir(parents=True)
    db = idx / "kw_index.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE kw_docs (id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO kw_docs (id) VALUES (?)", [("a",), ("b",), ("c",)])
    conn.commit()
    conn.close()

    kw_def = next(d for d in _STORE_DEFS if d["name"] == "kw_index")
    path = os.path.join(str(tmp_path), ".attocode", kw_def["path_fragment"])
    # Uses the ACTUAL store-def table tuple — fails while it says ("documents",).
    assert _store_row_count(path, kw_def["tables"]) == 3
