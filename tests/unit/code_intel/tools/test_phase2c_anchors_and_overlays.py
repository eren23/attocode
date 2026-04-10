"""Phase 2c tests: anchor retrofit + orphan_scan v2 + named overlays.

Exercises:

- ``MemoryStore.add(anchor_blob_oid=...)`` stores the anchor + ``list_all`` returns it
- ``ADRStore.add(anchor_blob_oids=...)`` stores the JSON + ``list_all`` / ``get`` return it
- Phase 2c migration on a pre-anchor store works in place (ALTER TABLE path)
- ``record_learning`` MCP tool auto-computes anchor from scope
- ``record_adr`` MCP tool auto-computes anchors from related_files
- ``orphan_scan`` v2 finds blob-unreachable learnings inside a git repo
- ``orphan_scan`` v2 falls back to scope-path check for anchor-less rows
- Overlay round-trip: create, list, activate, delete

All tests use a temp project dir + the same monkeypatch fixture pattern
established in ``test_maintenance_tools_phase2.py``.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Shared fixture — real git repo with populated stores
# ---------------------------------------------------------------------------


_HAS_GIT = shutil.which("git") is not None


def _git(*args: str, cwd: str) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    subprocess.check_call(
        ["git", *args], cwd=cwd, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def git_project(tmp_path, monkeypatch):
    """A temp git repo with a populated .attocode/ directory.

    - 2 committed files (src/a.py, src/b.py)
    - 1 learning referencing src/a.py
    - 1 learning referencing a deleted file (for orphan detection)
    - 1 ADR referencing src/a.py + src/b.py
    - Monkeypatch makes every _get_project_dir() return this temp dir
    """
    if not _HAS_GIT:
        pytest.skip("git not available")

    project = tmp_path / "proj"
    project.mkdir()

    # Git repo with two committed files.
    _git("init", "--initial-branch=main", cwd=str(project))
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("def a():\n    return 1\n")
    (project / "src" / "b.py").write_text("def b():\n    return 2\n")
    _git("add", ".", cwd=str(project))
    _git("commit", "-m", "initial", cwd=str(project))

    # .attocode/ skeleton.
    attocode = project / ".attocode"
    (attocode / "index").mkdir(parents=True)
    (attocode / "vectors").mkdir()
    (attocode / "cache").mkdir()
    (attocode / "frecency").mkdir()
    (attocode / "query_history").mkdir()

    # Minimal symbols.db so overlay_create has something to snapshot.
    from attocode.integrations.context.index_store import IndexStore, StoredFile
    sym = IndexStore(db_path=str(attocode / "index" / "symbols.db"))
    try:
        sym.save_file(StoredFile(
            path="src/a.py", mtime=1700000000.0, size=100, language="python",
            line_count=10, content_hash="h_a",
        ))
    finally:
        sym.close()

    # Minimal vectors.db.
    from attocode.integrations.context.vector_store import VectorEntry, VectorStore
    vs = VectorStore(
        db_path=str(attocode / "vectors" / "embeddings.db"),
        dimension=4,
        model_name="test",
        strict_dimension=True,
    )
    try:
        vs.upsert(VectorEntry(
            id="e1", file_path="src/a.py", chunk_type="file", name="a",
            text="hello", vector=[0.1, 0.2, 0.3, 0.4],
        ))
    finally:
        vs.close()

    # Memory store with 2 learnings.
    from attocode.integrations.context.memory_store import MemoryStore
    mem = MemoryStore(str(project))
    try:
        mem.add(
            type="pattern",
            description="use deps injection here",
            details="",
            scope="src/a.py",
            confidence=0.8,
            anchor_blob_oid="",  # no anchor yet — Phase 2c auto-compute path
        )
        mem.add(
            type="gotcha",
            description="watch for removed module",
            details="",
            scope="src/deleted_path.py",
            confidence=0.5,
        )
    finally:
        mem.close()

    # ADR store with 1 ADR.
    from attocode.code_intel.tools.adr_tools import ADRStore
    adr = ADRStore(project_dir=str(project))
    try:
        adr.add(
            title="Use sqlite",
            context="want local portable storage",
            decision="adopt sqlite",
            related_files=["src/a.py", "src/b.py"],
            tags=["storage"],
        )
    finally:
        adr.close()

    # --- Monkeypatch project dir across every tool module ---
    project_dir_str = str(project)
    fake = lambda: project_dir_str  # noqa: E731

    import attocode.code_intel._shared as shared
    monkeypatch.setattr(shared, "_get_project_dir", fake)

    import attocode.code_intel.tools.maintenance_tools as mt
    monkeypatch.setattr(mt, "_get_project_dir", fake)

    import attocode.code_intel.tools.snapshot_tools as st
    monkeypatch.setattr(st, "_get_project_dir", fake)

    import attocode.code_intel.tools.pin_tools as pt
    monkeypatch.setattr(pt, "_get_project_dir", fake)
    monkeypatch.setattr(pt, "_pin_store", None, raising=False)

    import attocode.code_intel.tools.overlay_tools as ot
    monkeypatch.setattr(ot, "_get_project_dir", fake)

    import attocode.code_intel.tools.learning_tools as lt
    monkeypatch.setattr(lt, "_get_project_dir", fake, raising=False)

    import attocode.code_intel.tools.adr_tools as at
    monkeypatch.setattr(at, "_get_project_dir", fake, raising=False)
    monkeypatch.setattr(at, "_adr_store", None, raising=False)

    # MemoryStore singleton lives on server._memory_store.
    import attocode.code_intel.server as _srv
    monkeypatch.setattr(_srv, "_memory_store", None, raising=False)

    # Defensive: tools that go through @pin_stamped use
    # _get_project_dir to compute the pin footer. If the maintenance
    # test ended without patching them, they'd still point at the
    # caller's CWD. Patch them all here for safety.
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
        monkeypatch.setattr(mod, "_get_project_dir", fake, raising=False)

    return project


# ---------------------------------------------------------------------------
# Anchor retrofit on MemoryStore
# ---------------------------------------------------------------------------


class TestMemoryStoreAnchors:
    def test_add_with_anchor_persists(self, git_project):
        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(git_project))
        try:
            lid = mem.add(
                type="pattern",
                description="explicit anchored learning",
                scope="src/a.py",
                anchor_blob_oid="git:abc123",
            )
            assert lid is not None

            # list_all should surface the anchor.
            rows = mem.list_all(status="active")
            anchored = [r for r in rows if r.get("id") == lid]
            assert len(anchored) == 1
            assert anchored[0]["anchor_blob_oid"] == "git:abc123"
        finally:
            mem.close()

    def test_add_without_anchor_defaults_empty(self, git_project):
        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(git_project))
        try:
            lid = mem.add(
                type="pattern",
                description="plain learning",
                scope="src/z.py",
            )
            rows = mem.list_all(status="active")
            hit = next(r for r in rows if r["id"] == lid)
            assert hit["anchor_blob_oid"] == ""
        finally:
            mem.close()

    def test_migration_from_pre_anchor_store(self, tmp_path):
        """A pre-2c database without the anchor column is upgraded in place."""
        project = tmp_path / "legacy"
        (project / ".attocode" / "cache").mkdir(parents=True)
        db_path = project / ".attocode" / "cache" / "memory.db"

        # Create the pre-2c schema by hand (no anchor_blob_oid column).
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript("""
                CREATE TABLE learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    apply_count INTEGER NOT NULL DEFAULT 0,
                    help_count INTEGER NOT NULL DEFAULT 0,
                    unhelpful_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
            """)
            conn.execute(
                "INSERT INTO learnings (type, description, created_at, updated_at) "
                "VALUES ('pattern', 'old learning', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
        finally:
            conn.close()

        # Open via MemoryStore — migration should add the column.
        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(project))
        try:
            rows = mem.list_all(status="active")
            assert len(rows) == 1
            assert rows[0]["anchor_blob_oid"] == ""

            # Column is now actually present.
            cols = {
                r[1] for r in
                sqlite3.connect(str(db_path)).execute(
                    "PRAGMA table_info(learnings)"
                ).fetchall()
            }
            assert "anchor_blob_oid" in cols
        finally:
            mem.close()

    def test_anchor_survives_roundtrip_through_list_all(self, git_project):
        """Write with anchor, round-trip via list_all, assert preserved."""
        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(git_project))
        try:
            lid = mem.add(
                type="convention",
                description="anchored roundtrip",
                scope="src/a.py",
                anchor_blob_oid="git:roundtrip",
            )
            # Reopen the store to force a fresh read from disk (no in-memory state).
            mem.close()
            mem = MemoryStore(str(git_project))
            rows = mem.list_all(status="active")
            hit = next(r for r in rows if r["id"] == lid)
            assert hit["anchor_blob_oid"] == "git:roundtrip"
        finally:
            mem.close()


# ---------------------------------------------------------------------------
# Anchor retrofit on ADRStore
# ---------------------------------------------------------------------------


class TestADRStoreAnchors:
    def test_add_with_anchors_persists(self, git_project):
        from attocode.code_intel.tools.adr_tools import ADRStore
        adr = ADRStore(project_dir=str(git_project))
        try:
            num = adr.add(
                title="Anchored decision",
                context="x",
                decision="y",
                related_files=["src/a.py"],
                anchor_blob_oids=["git:one", "git:two"],
            )
            rows = adr.list_all()
            hit = next(r for r in rows if r["number"] == num)
            assert hit["anchor_blob_oids"] == ["git:one", "git:two"]

            # get() returns the same.
            detail = adr.get(num)
            assert detail is not None
            assert detail["anchor_blob_oids"] == ["git:one", "git:two"]
        finally:
            adr.close()

    def test_add_without_anchors_defaults_empty(self, git_project):
        from attocode.code_intel.tools.adr_tools import ADRStore
        adr = ADRStore(project_dir=str(git_project))
        try:
            num = adr.add(title="Plain", context="x", decision="y")
            detail = adr.get(num)
            assert detail is not None
            assert detail["anchor_blob_oids"] == []
        finally:
            adr.close()

    def test_migration_from_pre_anchor_store(self, tmp_path):
        project = tmp_path / "legacy-adr"
        (project / ".attocode").mkdir(parents=True)
        db_path = project / ".attocode" / "adrs.db"

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript("""
                CREATE TABLE adrs (
                    number INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    context TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL DEFAULT '',
                    consequences TEXT NOT NULL DEFAULT '',
                    related_files TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    author TEXT NOT NULL DEFAULT '',
                    superseded_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (superseded_by) REFERENCES adrs(number)
                );
            """)
            conn.execute(
                "INSERT INTO adrs (title, context, decision, created_at, updated_at) "
                "VALUES ('old', '', '', '2026-01-01', '2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        from attocode.code_intel.tools.adr_tools import ADRStore
        adr = ADRStore(project_dir=str(project))
        try:
            rows = adr.list_all()
            assert len(rows) == 1
            assert rows[0]["anchor_blob_oids"] == []

            cols = {
                r[1] for r in
                sqlite3.connect(str(db_path)).execute(
                    "PRAGMA table_info(adrs)"
                ).fetchall()
            }
            assert "anchor_blob_oids" in cols
        finally:
            adr.close()


# ---------------------------------------------------------------------------
# record_learning / record_adr MCP tool auto-anchor
# ---------------------------------------------------------------------------


class TestRecordLearningAutoAnchor:
    def test_auto_computes_anchor_from_scope_file(self, git_project):
        from attocode.code_intel.tools.learning_tools import record_learning
        result = record_learning(
            type="pattern",
            description="auto-anchored learning",
            scope="src/a.py",
        )
        assert "anchor=" in result
        assert "git:" in result

        # Verify it landed in the store.
        import attocode.code_intel.server as _srv
        _srv._memory_store = None  # force refresh
        from attocode.code_intel.tools.learning_tools import _get_memory_store
        mem = _get_memory_store()
        rows = mem.list_all(status="active")
        hit = next(
            r for r in rows if r["description"] == "auto-anchored learning"
        )
        assert hit["anchor_blob_oid"].startswith("git:")

    def test_no_anchor_when_scope_is_a_directory(self, git_project):
        from attocode.code_intel.tools.learning_tools import record_learning
        result = record_learning(
            type="convention",
            description="directory-scoped learning",
            scope="src/",
        )
        assert "anchor=" not in result


class TestRecordAdrAutoAnchor:
    def test_auto_computes_anchors_from_related_files(self, git_project):
        from attocode.code_intel.tools.adr_tools import _get_adr_store, record_adr
        result = record_adr(
            title="Auto-anchored ADR",
            context="x",
            decision="y",
            related_files=["src/a.py", "src/b.py"],
        )
        assert "2 anchor(s)" in result

        store = _get_adr_store()
        rows = store.list_all()
        hit = next(r for r in rows if r["title"] == "Auto-anchored ADR")
        assert len(hit["anchor_blob_oids"]) == 2
        assert all(a.startswith("git:") for a in hit["anchor_blob_oids"])


# ---------------------------------------------------------------------------
# orphan_scan v2 — git reachability
# ---------------------------------------------------------------------------


class TestOrphanScanV2:
    def test_detects_unreachable_anchor_learning(self, git_project):
        """A learning anchored to a fake blob_oid should be flagged."""
        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(git_project))
        try:
            mem.add(
                type="pattern",
                description="points to a blob that never existed",
                scope="src/a.py",
                anchor_blob_oid="git:" + "0" * 40,  # zero hash = not in git
            )
        finally:
            mem.close()

        # Reset singleton so orphan_scan sees the new row.
        import attocode.code_intel.server as _srv
        _srv._memory_store = None

        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        result = orphan_scan(auto_archive=False)
        assert "blob_unreachable" in result
        assert "points to a blob" in result

    def test_anchored_reachable_learning_is_not_orphaned(self, git_project):
        """A learning with a real git blob should NOT be flagged."""
        # Compute the real git OID for src/a.py.
        from attocode.integrations.context.blob_oid import compute_blob_oid
        real_oid = compute_blob_oid("src/a.py", str(git_project))

        from attocode.integrations.context.memory_store import MemoryStore
        mem = MemoryStore(str(git_project))
        try:
            mem.add(
                type="pattern",
                description="real-anchored learning",
                scope="src/a.py",
                anchor_blob_oid=real_oid,
            )
        finally:
            mem.close()

        import attocode.code_intel.server as _srv
        _srv._memory_store = None

        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        result = orphan_scan(auto_archive=False)
        # The fixture has a second learning at src/deleted_path.py that
        # IS orphaned via the scope-fallback path, so the output is
        # non-empty — but the real-anchored one should not appear.
        assert "real-anchored learning" not in result

    def test_scope_fallback_for_anchor_less_learning(self, git_project):
        """Pre-2c rows without an anchor fall back to path-exists check."""
        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        result = orphan_scan(auto_archive=False)
        # The fixture seeded one learning at scope=src/deleted_path.py
        # without an anchor — it should be caught by the scope fallback.
        assert "scope_missing" in result
        assert "src/deleted_path.py" in result

    def test_auto_archive_soft_deletes_not_hard(self, git_project):
        """Codex fix B2: auto_archive=True must flip status to
        'archived', not hard-delete the row. The archived row must
        still be present via list_all(status='archived')."""
        import sqlite3

        from attocode.code_intel.tools.maintenance_tools import orphan_scan
        from attocode.integrations.context.memory_store import MemoryStore

        # Sanity: the fixture seeded a gotcha at src/deleted_path.py
        # without an anchor. Count the active rows first.
        db_path = git_project / ".attocode" / "cache" / "memory.db"
        conn = sqlite3.connect(str(db_path))
        try:
            active_before = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE status='active'"
            ).fetchone()[0]
            archived_before = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE status='archived'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert active_before >= 1
        assert archived_before == 0

        # Archive orphans.
        result = orphan_scan(auto_archive=True)
        assert "auto-archived" in result

        # Row still present, but status is now 'archived'.
        conn = sqlite3.connect(str(db_path))
        try:
            active_after = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE status='active'"
            ).fetchone()[0]
            archived_after = conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE status='archived'"
            ).fetchone()[0]
            # The orphan(s) moved from active → archived. Total rows
            # should be unchanged.
            total_after = conn.execute(
                "SELECT COUNT(*) FROM learnings"
            ).fetchone()[0]
        finally:
            conn.close()

        # At least one orphan was archived (the fixture's
        # src/deleted_path.py learning).
        assert archived_after >= 1
        assert active_after == active_before - archived_after
        # Total unchanged — nothing was hard-deleted.
        assert total_after == active_before + archived_before

        # The archived row is listed via list_all(status='archived').
        mem = MemoryStore(str(git_project))
        try:
            archived = mem.list_all(status="archived")
        finally:
            mem.close()
        assert any(
            r.get("scope") == "src/deleted_path.py" for r in archived
        )

    def test_auto_archive_false_does_not_touch_rows(self, git_project):
        """Codex B2 regression guard: auto_archive=False is unchanged."""
        import sqlite3

        from attocode.code_intel.tools.maintenance_tools import orphan_scan

        db_path = git_project / ".attocode" / "cache" / "memory.db"
        conn = sqlite3.connect(str(db_path))
        try:
            before = conn.execute(
                "SELECT id, status FROM learnings ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        orphan_scan(auto_archive=False)

        conn = sqlite3.connect(str(db_path))
        try:
            after = conn.execute(
                "SELECT id, status FROM learnings ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        assert before == after


# ---------------------------------------------------------------------------
# Named overlays
# ---------------------------------------------------------------------------


class TestOverlayTools:
    def test_create_list_activate_delete_roundtrip(self, git_project):
        from attocode.code_intel.tools.overlay_tools import (
            overlay_activate,
            overlay_create,
            overlay_delete,
            overlay_list,
            overlay_status,
        )

        # Create.
        result = overlay_create("main", description="baseline")
        assert "captured" in result

        # List.
        listing = overlay_list()
        assert "main" in listing

        # Status before activation — no active marker yet.
        status = overlay_status()
        assert "no overlay activated yet" in status

        # Create a second overlay from the same state.
        overlay_create("variant-a")

        # Activate first (dry run).
        dry = overlay_activate("main", confirm=False)
        assert "DRY RUN" in dry

        # Apply.
        applied = overlay_activate("main", confirm=True)
        assert "activated 'main'" in applied

        # Status now reports the active overlay.
        assert "active='main'" in overlay_status()

        # Delete the variant with confirm.
        d = overlay_delete("variant-a", confirm=False)
        assert "DRY RUN" in d
        d = overlay_delete("variant-a", confirm=True)
        assert "removed" in d

    def test_create_rejects_duplicate_name(self, git_project):
        from attocode.code_intel.tools.overlay_tools import overlay_create
        overlay_create("test")
        second = overlay_create("test")
        assert "already exists" in second

    def test_create_rejects_invalid_name(self, git_project):
        from attocode.code_intel.tools.overlay_tools import overlay_create
        for bad in ("", "..", "_hidden", "has/slash", "has space"):
            result = overlay_create(bad)
            assert "invalid" in result.lower()

    def test_activate_preserves_state_when_save_current_as_set(self, git_project):
        """Overlay A → mutate → activate-save-as-B → activate A → verify."""
        import sqlite3

        from attocode.code_intel.tools.maintenance_tools import clear_symbols
        from attocode.code_intel.tools.overlay_tools import (
            overlay_activate,
            overlay_create,
        )
        db = git_project / ".attocode" / "index" / "symbols.db"

        # Capture baseline.
        overlay_create("baseline")

        # Mutate current state.
        clear_symbols(confirm=True)
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM files"
            ).fetchone()[0] == 0
        finally:
            conn.close()

        # Activate baseline, saving the mutated state as "mutated".
        result = overlay_activate("baseline", save_current_as="mutated", confirm=True)
        assert "activated 'baseline'" in result
        assert "mutated" in result

        # Baseline state is now live — files count back to 1.
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM files"
            ).fetchone()[0] == 1
        finally:
            conn.close()

        # And we can swing back to the mutated state via the save we made.
        overlay_activate("mutated", confirm=True)
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM files"
            ).fetchone()[0] == 0
        finally:
            conn.close()
