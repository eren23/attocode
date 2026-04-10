"""Unit tests for the Phase 2a maintenance + snapshot tool surface.

Covers the clear_*, export/import, gc, orphan_scan, and snapshot_* tools.
Each test runs in an isolated temp ``.attocode/`` directory by monkeypatching
``_get_project_dir`` and the lazy memory/adr/pin store singletons.
"""

from __future__ import annotations

import json
import struct

import pytest

# ---------------------------------------------------------------------------
# Shared fixture: fake project with a populated .attocode/ tree
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_project(tmp_path, monkeypatch):
    """A temp directory set up as a project root with real populated stores.

    Monkey-patches every ``_get_*`` singleton + ``_get_project_dir`` so
    the Phase 2a tools read/write into this directory rather than the
    user's real ~/.cache.
    """
    project = tmp_path / "proj"
    project.mkdir()
    attocode = project / ".attocode"
    (attocode / "index").mkdir(parents=True)
    (attocode / "vectors").mkdir()
    (attocode / "cache").mkdir()
    (attocode / "frecency").mkdir()
    (attocode / "query_history").mkdir()

    # --- Minimal symbols.db ---
    from attocode.integrations.context.index_store import IndexStore, StoredFile
    sym_store = IndexStore(db_path=str(attocode / "index" / "symbols.db"))
    try:
        sym_store.save_file(StoredFile(
            path="src/a.py", mtime=1700000000.0, size=100, language="python",
            line_count=10, content_hash="hash_a",
        ))
        sym_store.save_symbols("src/a.py", [
            {
                "name": "foo",
                "qualified_name": "a.foo",
                "kind": "function",
                "line": 1,
                "end_line": 5,
                "source": "tree-sitter",
            },
        ])
    finally:
        sym_store.close()

    # --- Minimal embeddings.db ---
    from attocode.integrations.context.vector_store import VectorEntry, VectorStore
    vec_store = VectorStore(
        db_path=str(attocode / "vectors" / "embeddings.db"),
        dimension=4,
        model_name="test-model",
        model_version="v1",
        strict_dimension=True,
    )
    try:
        vec_store.upsert(VectorEntry(
            id="e1", file_path="src/a.py", chunk_type="file",
            name="a", text="hello", vector=[0.1, 0.2, 0.3, 0.4],
        ))
    finally:
        vec_store.close()

    # --- Minimal kw_index.db + trigram files (dummy content) ---
    (attocode / "index" / "kw_index.db").write_bytes(b"dummy kw index\x00")
    (attocode / "index" / "trigrams.lookup").write_bytes(b"TRI3" + struct.pack("I", 0) * 3)
    (attocode / "index" / "trigrams.postings").write_bytes(b"\x00" * 16)
    # trigrams.db is a sqlite database file
    import sqlite3 as _sq
    _c = _sq.connect(str(attocode / "index" / "trigrams.db"))
    _c.execute("CREATE TABLE trigram_files (file_id INTEGER PRIMARY KEY, path TEXT)")
    _c.commit()
    _c.close()

    # --- Memory store with 2 active + 1 archived learnings ---
    from attocode.integrations.context.memory_store import MemoryStore
    mem = MemoryStore(str(project))
    try:
        mem.add(
            type="pattern",
            description="use dependency injection",
            details="prefer ctor params",
            scope="src/a.py",
            confidence=0.8,
        )
        mem.add(
            type="gotcha",
            description="watch for deleted-file refs",
            details="in src/deleted_path.py",
            scope="src/deleted_path.py",
            confidence=0.6,
        )
    finally:
        mem.close()

    # --- ADR store with 2 ADRs ---
    from attocode.code_intel.tools.adr_tools import ADRStore
    adr = ADRStore(project_dir=str(project))
    try:
        adr.add(
            title="Use sqlite for local state",
            context="Want portable single-file storage",
            decision="Adopt sqlite with WAL",
            consequences="Some concurrency limits",
            related_files=["src/a.py"],
            tags=["storage"],
        )
        adr.add(
            title="Track ADRs with missing paths",
            context="ADRs may reference deleted files",
            decision="Flag in orphan_scan",
            consequences="Maintenance overhead",
            related_files=["src/deleted_path.py"],
            tags=["process"],
        )
    finally:
        adr.close()

    # --- Patch _get_project_dir in every tool module that imported it
    #     (the tool modules do `from _shared import _get_project_dir` so
    #     patching the source module is insufficient) and clear lazy
    #     singleton caches so they rebuild against this temp project. ---
    project_dir_str = str(project)

    def _fake_project_dir() -> str:
        return project_dir_str

    import attocode.code_intel._shared as shared
    monkeypatch.setattr(shared, "_get_project_dir", _fake_project_dir)

    import attocode.code_intel.tools.maintenance_tools as mt
    monkeypatch.setattr(mt, "_get_project_dir", _fake_project_dir)

    import attocode.code_intel.tools.snapshot_tools as st
    monkeypatch.setattr(st, "_get_project_dir", _fake_project_dir)

    import attocode.code_intel.tools.pin_tools as pt
    monkeypatch.setattr(pt, "_get_project_dir", _fake_project_dir)
    monkeypatch.setattr(pt, "_pin_store", None, raising=False)

    import attocode.code_intel.tools.learning_tools as lt
    monkeypatch.setattr(lt, "_get_project_dir", _fake_project_dir, raising=False)
    # _get_memory_store caches the singleton on server._memory_store
    # (cross-module) so reset *that* location, not the learning_tools
    # module attribute.
    import attocode.code_intel.server as _srv
    monkeypatch.setattr(_srv, "_memory_store", None, raising=False)

    import attocode.code_intel.tools.adr_tools as at
    monkeypatch.setattr(at, "_get_project_dir", _fake_project_dir, raising=False)
    monkeypatch.setattr(at, "_adr_store", None, raising=False)

    # Also patch search_tools + frecency_tools / query_history_tools /
    # navigation_tools / cross_mode_tools / analysis_tools so the
    # @pin_stamped decorator in those modules resolves ``_get_project_dir``
    # to the test's temp project when a tool invocation goes through
    # them. Without these, a ranked-result tool called during a
    # maintenance test would reach out to the caller's CWD and produce
    # flaky results.
    for mod_name in (
        "attocode.code_intel.tools.search_tools",
        "attocode.code_intel.tools.frecency_tools",
        "attocode.code_intel.tools.query_history_tools",
        "attocode.code_intel.tools.navigation_tools",
        "attocode.code_intel.tools.cross_mode_tools",
        "attocode.code_intel.tools.analysis_tools",
    ):
        import importlib
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "_get_project_dir", _fake_project_dir, raising=False)

    return project


# ---------------------------------------------------------------------------
# clear_* tools
# ---------------------------------------------------------------------------


class TestClearTools:
    def test_clear_symbols_dry_run_preserves_data(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_symbols
        result = clear_symbols(confirm=False)
        assert "DRY RUN" in result
        # Data still present
        db = fake_project / ".attocode" / "index" / "symbols.db"
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            assert n == 1
        finally:
            conn.close()

    def test_clear_symbols_apply(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_symbols
        result = clear_symbols(confirm=True)
        assert "cleared" in result
        import sqlite3
        db = fake_project / ".attocode" / "index" / "symbols.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
        finally:
            conn.close()

    def test_clear_embeddings_dry_run_preserves(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_embeddings
        result = clear_embeddings(confirm=False)
        assert "DRY RUN" in result
        import sqlite3
        db = fake_project / ".attocode" / "vectors" / "embeddings.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 1
        finally:
            conn.close()

    def test_clear_embeddings_apply_preserves_dim(self, fake_project):
        """Non-destructive clear: vectors gone, stored dimension preserved."""
        from attocode.code_intel.tools.maintenance_tools import clear_embeddings
        clear_embeddings(confirm=True)
        import sqlite3
        db = fake_project / ".attocode" / "vectors" / "embeddings.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0
            # store_metadata still has dimension = 4
            row = conn.execute(
                "SELECT value FROM store_metadata WHERE key = 'dimension'"
            ).fetchone()
            assert row is not None
            assert row[0] == "4"
        finally:
            conn.close()

    def test_clear_trigrams_apply(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_trigrams
        clear_trigrams(confirm=True)
        for name in ("trigrams.lookup", "trigrams.postings", "trigrams.db"):
            assert not (fake_project / ".attocode" / "index" / name).exists()

    def test_clear_kw_index_apply(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_kw_index
        clear_kw_index(confirm=True)
        assert not (fake_project / ".attocode" / "index" / "kw_index.db").exists()

    def test_clear_learnings_dry_run(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_learnings
        # No archived learnings in the fixture; dry-run with default filter
        # should report zero.
        result = clear_learnings(confirm=False, status_filter="archived")
        assert "DRY RUN" in result
        assert "0 learning" in result

    def test_clear_learnings_all(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_learnings
        clear_learnings(confirm=True, status_filter="")
        import sqlite3
        db = fake_project / ".attocode" / "cache" / "memory.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 0
        finally:
            conn.close()

    def test_clear_adrs_all(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_adrs
        clear_adrs(confirm=True, status_filter="")
        import sqlite3
        db = fake_project / ".attocode" / "adrs.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM adrs").fetchone()[0] == 0
        finally:
            conn.close()

    def test_clear_all_dry_run(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_all
        result = clear_all(confirm=False)
        assert "DRY RUN" in result
        assert "symbols" in result
        assert "embeddings" in result

    def test_clear_all_apply_respects_except(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import clear_all
        result = clear_all(confirm=True, except_stores="symbols,trigrams")
        # symbols should have been skipped
        assert "SKIPPED" in result
        # Non-skipped stores should have been cleared — kw_index file gone.
        assert not (fake_project / ".attocode" / "index" / "kw_index.db").exists()
        # Symbols preserved.
        import sqlite3
        db = fake_project / ".attocode" / "index" / "symbols.db"
        assert db.exists()
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_learnings_roundtrip(self, fake_project, tmp_path):
        from attocode.code_intel.tools.maintenance_tools import (
            clear_learnings,
            export_learnings,
            import_learnings,
        )
        export_path = tmp_path / "learnings.jsonl"
        result = export_learnings(str(export_path), fmt="jsonl")
        assert "wrote 2" in result
        # Wipe and re-import.
        clear_learnings(confirm=True, status_filter="")
        # Sanity: DB is empty.
        import sqlite3
        db = fake_project / ".attocode" / "cache" / "memory.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 0
        finally:
            conn.close()
        # Import.
        result = import_learnings(str(export_path))
        assert "imported 2" in result
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 2
        finally:
            conn.close()

    def test_export_learnings_missing_format(self, fake_project, tmp_path):
        from attocode.code_intel.tools.maintenance_tools import export_learnings
        result = export_learnings(str(tmp_path / "x.xml"), fmt="xml")
        assert "unsupported" in result

    def test_adrs_markdown_roundtrip(self, fake_project, tmp_path):
        from attocode.code_intel.tools.maintenance_tools import (
            clear_adrs,
            export_adrs_markdown,
            import_adrs_markdown,
        )
        dest = tmp_path / "adrs"
        result = export_adrs_markdown(str(dest))
        assert "wrote 2" in result
        md_files = sorted(dest.iterdir())
        assert len(md_files) == 2
        # Files follow 0001-... naming.
        assert md_files[0].name.startswith("0001-")
        assert md_files[0].name.endswith(".md")

        # Re-import.
        clear_adrs(confirm=True, status_filter="")
        result = import_adrs_markdown(str(dest))
        assert "imported 2" in result
        import sqlite3
        db = fake_project / ".attocode" / "adrs.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM adrs").fetchone()[0] == 2
            # Titles survived (new numbering is assigned by the DB on insert).
            titles = {r[0] for r in conn.execute("SELECT title FROM adrs")}
            assert "Use sqlite for local state" in titles
            assert "Track ADRs with missing paths" in titles
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Orphan scan
# ---------------------------------------------------------------------------


class TestOrphanScan:
    def test_detects_missing_scope_and_related_files(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        # Create src/a.py so non-orphaned entries are truly present.
        (fake_project / "src").mkdir(exist_ok=True)
        (fake_project / "src" / "a.py").write_text("def foo(): pass\n")

        result = orphan_scan(auto_archive=False)
        # The "src/deleted_path.py" scope+related file is missing.
        assert "orphan" in result.lower()
        assert "src/deleted_path.py" in result

    def test_no_orphans(self, fake_project):
        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        # Create every referenced file so no orphans.
        (fake_project / "src").mkdir(exist_ok=True)
        (fake_project / "src" / "a.py").write_text("x\n")
        (fake_project / "src" / "deleted_path.py").write_text("x\n")
        result = orphan_scan(auto_archive=False)
        assert "no orphaned" in result.lower()


# ---------------------------------------------------------------------------
# GC
# ---------------------------------------------------------------------------


class TestGC:
    def test_gc_preview_on_empty_cas(self, fake_project, monkeypatch, tmp_path):
        # Use a tmp CAS dir so we don't touch the user's ~/.cache.
        monkeypatch.setenv("ATTOCODE_CAS_DIR", str(tmp_path / "cas"))
        from attocode.code_intel.tools.maintenance_tools import gc_preview
        result = gc_preview(min_age_days=0)
        assert "would delete: 0" in result

    def test_gc_run_dry_default(self, fake_project, monkeypatch, tmp_path):
        monkeypatch.setenv("ATTOCODE_CAS_DIR", str(tmp_path / "cas"))
        from attocode.code_intel.tools.maintenance_tools import gc_run
        result = gc_run(min_age_days=0, confirm=False)
        assert "DRY RUN" in result

    def test_gc_run_apply_deletes_orphans(self, fake_project, monkeypatch, tmp_path):
        monkeypatch.setenv("ATTOCODE_CAS_DIR", str(tmp_path / "cas"))
        from attocode.code_intel.artifacts import Provenance
        from attocode.code_intel.tools.maintenance_tools import gc_run
        from attocode.integrations.context.cas import ContentAddressedCache

        cas = ContentAddressedCache()
        cas.put(
            "sha256:" + "a" * 64,
            b"orphan_data",
            artifact_type="symbols",
            provenance=Provenance.create(
                artifact_type="symbols",
                action_hash="h",
                input_blob_oid="git:abc",
                indexer_name="tree-sitter",
                indexer_version="0.21.0",
            ),
        )
        cas.close()

        result = gc_run(min_age_days=0, confirm=True)
        assert "deleted 1 entries" in result


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_create_list_diff_delete(self, fake_project):
        from attocode.code_intel.tools.snapshot_tools import (
            snapshot_create,
            snapshot_delete,
            snapshot_diff,
            snapshot_list,
        )
        result = snapshot_create(name="phase2a_test")
        assert "components" in result

        listing = snapshot_list()
        assert "phase2a_test" in listing

        # Create a second snapshot and diff.
        snapshot_create(name="phase2a_test2")
        diff = snapshot_diff("phase2a_test", "phase2a_test2")
        # Both snapshots have identical components (same underlying stores)
        # so nothing should be in changed/added/removed.
        assert "same:" in diff

        # Delete the second — dry run first.
        d = snapshot_delete("phase2a_test2", confirm=False)
        assert "DRY RUN" in d
        d = snapshot_delete("phase2a_test2", confirm=True)
        assert "removed" in d

    def test_snapshot_restore_roundtrip(self, fake_project):
        """Mutate state, snapshot, mutate again, restore → original state."""
        from attocode.code_intel.tools.maintenance_tools import clear_symbols
        from attocode.code_intel.tools.snapshot_tools import (
            snapshot_create,
            snapshot_restore,
        )

        # Snapshot the populated state.
        snapshot_create(name="baseline")

        # Wipe symbols.
        clear_symbols(confirm=True)

        import sqlite3
        db = fake_project / ".attocode" / "index" / "symbols.db"
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        finally:
            conn.close()

        # Restore the baseline snapshot.
        result = snapshot_restore("baseline", confirm=True)
        assert "restored from" in result

        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1
        finally:
            conn.close()

    def test_snapshot_restore_dry_run(self, fake_project):
        from attocode.code_intel.tools.snapshot_tools import (
            snapshot_create,
            snapshot_restore,
        )
        snapshot_create(name="dryrun_test")
        result = snapshot_restore("dryrun_test", confirm=False)
        assert "DRY RUN" in result
        assert "components" in result

    def test_snapshot_manifest_contains_digests(self, fake_project):
        import tarfile

        from attocode.code_intel.tools.snapshot_tools import snapshot_create
        snapshot_create(name="digest_test")
        sdir = fake_project / ".attocode" / "snapshots"
        snaps = list(sdir.iterdir())
        assert len(snaps) == 1
        with tarfile.open(snaps[0], "r:gz") as tar:
            mfile = tar.extractfile("manifest.json")
            assert mfile is not None
            manifest = json.loads(mfile.read().decode("utf-8"))
        assert manifest["schema"] == "atto.snapshot.v1"
        for c in manifest["components"]:
            assert c["digest"].startswith("sha256:")
            assert len(c["digest"]) == len("sha256:") + 64
