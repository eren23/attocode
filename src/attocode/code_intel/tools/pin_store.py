"""MCP-free pin storage + manifest hashing helpers.

Everything in this module is importable without touching the MCP
runtime. It exists so that the HTTP API providers (``api/providers/``)
can mint and persist retrieval pins without transitively importing
``attocode.code_intel._shared``, which would call ``sys.exit(1)`` in
environments where the ``mcp`` package isn't installed.

``tools/pin_tools.py`` re-exports everything here and layers the MCP
``@mcp.tool()`` decorators + the ``_stamp_pin`` footer on top.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from attocode.code_intel.artifacts import (
    RetrievalPin,
    compute_store_hash,
)

logger = logging.getLogger(__name__)


def _get_project_dir() -> str:
    """Dynamic dispatch to ``project_dir._get_project_dir``.

    Looks up the function on every call so monkeypatches in
    ``project_dir`` are observed by pin_store without needing to
    also patch this module directly. Prevents the "stale binding
    across test fixtures" class of pollution that a ``from
    project_dir import`` binding would otherwise introduce.

    We use the neutral ``project_dir`` module rather than
    ``_shared`` so HTTP providers can import this without dragging
    in the MCP runtime (which ``_shared`` ``sys.exit(1)`` s on if
    the ``mcp`` package is missing).
    """
    from attocode.code_intel import project_dir
    return project_dir._get_project_dir()


# ---------------------------------------------------------------------------
# Per-store hash computation
# ---------------------------------------------------------------------------

# Declarative table for stdio stores — each entry is enough to compute the
# store's cheap manifest hash. ``schema_version_source`` is either a literal
# default or a ``("table", "where_key")`` tuple used to query a metadata row.
#
# We keep the shape simple on purpose: row_count + max(updated_at) + schema
# version + file presence is enough to change on any mutation while staying
# stable under no-op reads.
_STORE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbols",
        "path_fragment": os.path.join("index", "symbols.db"),
        "tables": ("symbols", "files", "refs", "dependencies"),
        "timestamp_table": "files",
        "timestamp_col": "mtime",
        "schema_meta": ("metadata", "schema_version"),
        "default_schema_version": "1",
    },
    {
        "name": "embeddings",
        "path_fragment": os.path.join("vectors", "embeddings.db"),
        "tables": ("vectors", "file_metadata"),
        "timestamp_table": "file_metadata",
        "timestamp_col": "last_indexed_at",
        "schema_meta": ("store_metadata", "schema_version"),
        "default_schema_version": "1",
    },
    {
        "name": "kw_index",
        "path_fragment": os.path.join("index", "kw_index.db"),
        "tables": ("documents",),
        "timestamp_table": None,
        "timestamp_col": None,
        "schema_meta": None,
        "default_schema_version": "1",
    },
    {
        "name": "learnings",
        "path_fragment": os.path.join("cache", "memory.db"),
        "tables": ("learnings",),
        "timestamp_table": "learnings",
        "timestamp_col": "updated_at",
        "schema_meta": None,
        "default_schema_version": "1",
    },
    {
        "name": "adrs",
        "path_fragment": "adrs.db",
        "tables": ("adrs",),
        "timestamp_table": "adrs",
        "timestamp_col": "updated_at",
        "schema_meta": None,
        "default_schema_version": "1",
    },
    {
        "name": "frecency",
        "path_fragment": os.path.join("frecency", "frecency.db"),
        "tables": ("frecency_accesses",),
        "timestamp_table": "frecency_accesses",
        "timestamp_col": "updated_at",
        "schema_meta": ("meta", "schema_version"),
        "default_schema_version": "1",
    },
    {
        "name": "query_history",
        "path_fragment": os.path.join("query_history", "query_history.db"),
        "tables": ("query_selections",),
        "timestamp_table": "query_selections",
        "timestamp_col": "last_selected",
        "schema_meta": ("meta", "schema_version"),
        "default_schema_version": "1",
    },
)


def _hash_for_store(project_dir: str, defn: dict[str, Any]) -> str:
    """Compute the manifest hash for one stdio store.

    Returns the string ``"absent"`` if the store's DB file doesn't exist —
    that way "absent" vs "empty" vs "populated" all produce distinct hashes
    and a drift check catches any of those transitions.
    """
    db_path = os.path.join(project_dir, ".attocode", defn["path_fragment"])
    if not os.path.exists(db_path):
        return "absent"

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.debug("pin: could not open %s (%s)", db_path, exc)
        return "unreadable"

    try:
        # Row count: sum across all declared tables (so dropping one and
        # adding another still changes the hash).
        total_rows = 0
        existing_tables: list[str] = []
        for tbl in defn["tables"]:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            except sqlite3.OperationalError:
                continue
            total_rows += int(row[0]) if row else 0
            existing_tables.append(tbl)

        max_updated_at: float | None = None
        tt = defn["timestamp_table"]
        tc = defn["timestamp_col"]
        if tt and tc and tt in existing_tables:
            try:
                row = conn.execute(f"SELECT MAX({tc}) FROM {tt}").fetchone()
                if row and row[0] is not None:
                    max_updated_at = float(row[0])
            except (sqlite3.OperationalError, ValueError, TypeError):
                pass

        schema_version = defn["default_schema_version"]
        sm = defn["schema_meta"]
        if sm is not None:
            meta_table, meta_key = sm
            try:
                row = conn.execute(
                    f"SELECT value FROM {meta_table} WHERE key = ?",
                    (meta_key,),
                ).fetchone()
                if row:
                    schema_version = str(row[0])
            except sqlite3.OperationalError:
                pass

        return compute_store_hash(
            schema_version=schema_version,
            row_count=total_rows,
            max_updated_at=max_updated_at,
            extra={"tables": sorted(existing_tables)},
        )
    finally:
        conn.close()


def _hash_for_trigrams(project_dir: str) -> str:
    """Trigram index is binary files, not a DB — hash on presence + mtime + size."""
    base = os.path.join(project_dir, ".attocode", "index")
    parts: list[tuple[str, float, int]] = []
    for name in ("trigrams.lookup", "trigrams.postings", "trigrams.db"):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            continue
        st = os.stat(path)
        parts.append((name, st.st_mtime, st.st_size))
    if not parts:
        return "absent"
    return compute_store_hash(
        schema_version="trigram_v1",
        row_count=len(parts),
        max_updated_at=max(p[1] for p in parts),
        extra={"files": [[p[0], p[2]] for p in parts]},
    )


def _compute_current_manifest_hashes(project_dir: str | None = None) -> dict[str, str]:
    """Return the current per-store manifest hashes for a project.

    ``project_dir`` is optional: if omitted, falls back to the active
    project via ``_get_project_dir()`` — useful for pin_tools callers
    that don't carry an explicit project context. Callers with a
    bound service (e.g. ``LocalSearchProvider``) MUST pass the
    service's ``project_dir`` so the resulting pin is minted against
    the correct repo's on-disk stores.
    """
    if project_dir is None:
        project_dir = _get_project_dir()
    hashes: dict[str, str] = {}
    for defn in _STORE_DEFS:
        hashes[defn["name"]] = _hash_for_store(project_dir, defn)
    hashes["trigrams"] = _hash_for_trigrams(project_dir)
    return hashes


# ---------------------------------------------------------------------------
# PinStore — persistent pin storage (small SQLite DB)
# ---------------------------------------------------------------------------


class PinStore:
    """SQLite-backed pin registry at ``.attocode/cache/pins.db``."""

    def __init__(self, project_dir: str) -> None:
        db_dir = os.path.join(project_dir, ".attocode", "cache")
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, "pins.db")
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pins (
                pin_id            TEXT PRIMARY KEY,
                created_at        REAL NOT NULL,
                expires_at        REAL NOT NULL DEFAULT 0,
                overlay_id        TEXT,
                branch_id         TEXT,
                manifest_hash     TEXT NOT NULL,
                manifest_json     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_pins_expires ON pins(expires_at);
            """
        )
        self._conn.commit()

    def save(self, pin: RetrievalPin) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO pins
               (pin_id, created_at, expires_at, overlay_id, branch_id,
                manifest_hash, manifest_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                pin.pin_id, pin.created_at, pin.expires_at,
                pin.overlay_id, pin.branch_id, pin.manifest_hash,
                json.dumps(pin.manifest_hashes, sort_keys=True),
            ),
        )
        self._conn.commit()

    def get(self, pin_id: str) -> RetrievalPin | None:
        import json
        row = self._conn.execute(
            """SELECT pin_id, created_at, expires_at, overlay_id, branch_id,
                      manifest_hash, manifest_json FROM pins WHERE pin_id = ?""",
            (pin_id,),
        ).fetchone()
        if row is None:
            return None
        return RetrievalPin(
            pin_id=row[0],
            schema_version=1,
            manifest_hashes=json.loads(row[6]),
            manifest_hash=row[5],
            overlay_id=row[3],
            branch_id=row[4],
            created_at=row[1],
            expires_at=row[2],
        )

    def list_all(self) -> list[RetrievalPin]:
        import json
        rows = self._conn.execute(
            """SELECT pin_id, created_at, expires_at, overlay_id, branch_id,
                      manifest_hash, manifest_json FROM pins
               ORDER BY created_at DESC"""
        ).fetchall()
        return [
            RetrievalPin(
                pin_id=r[0],
                schema_version=1,
                manifest_hashes=json.loads(r[6]),
                manifest_hash=r[5],
                overlay_id=r[3],
                branch_id=r[4],
                created_at=r[1],
                expires_at=r[2],
            )
            for r in rows
        ]

    def delete(self, pin_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM pins WHERE pin_id = ?", (pin_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def gc_expired(self) -> int:
        import time
        cur = self._conn.execute(
            "DELETE FROM pins WHERE expires_at > 0 AND expires_at < ?",
            (time.time(),),
        )
        self._conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Per-project PinStore cache
# ---------------------------------------------------------------------------
#
# Dict-keyed by absolute project_dir so a single interpreter serving
# multiple projects (e.g. an HTTP API with ``register_project``)
# maintains one PinStore per repo — not a "current project" singleton
# that silently points at whatever the env var happens to say.
#
# ``_pin_store`` / ``_pin_store_project`` remain as legacy aliases so
# existing test fixtures that reset them see a usable (empty) state,
# but the primary cache is ``_pin_stores``.

_pin_stores: dict[str, PinStore] = {}

_pin_store: PinStore | None = None
_pin_store_project: str = ""


def _get_pin_store(project_dir: str | None = None) -> PinStore:
    """Return the PinStore for a project, caching per project_dir.

    ``project_dir`` is optional: if omitted, falls back to the active
    project via ``_get_project_dir()``. Pass the bound service's
    ``project_dir`` explicitly from HTTP providers so an API serving
    multiple projects doesn't route pin writes to the wrong repo's
    ``.attocode/cache/pins.db``.

    Legacy behavior: if the caller sets ``_pin_store = None`` via
    monkeypatch, a fresh store is created for the current project.
    """
    global _pin_store, _pin_store_project
    if project_dir is None:
        project_dir = _get_project_dir()
    current = os.path.abspath(project_dir)

    # Legacy compat: if a test reset ``_pin_store``, honor that by
    # re-creating on next access.
    if _pin_store is None and current == _pin_store_project:
        _pin_store_project = ""

    cached = _pin_stores.get(current)
    if cached is None:
        cached = PinStore(current)
        _pin_stores[current] = cached
        # Keep the legacy singleton in sync with whatever the most
        # recent call was so ``_pin_store`` / ``_pin_store_project``
        # attribute reads still reflect something sensible.
        _pin_store = cached
        _pin_store_project = current
    return cached


def compute_and_persist_pin(
    project_dir: str | None = None, *, ttl_seconds: int = 0,
) -> RetrievalPin:
    """MCP-free helper used by HTTP providers.

    Computes the per-store manifest hashes for ``project_dir``,
    derives a deterministic pin id (``pin_<hex20>`` of the manifest
    hash), persists it via :class:`PinStore`, and returns the stored
    :class:`RetrievalPin`. Round-trippable with ``pin_resolve`` and
    ``verify_pin`` on the stdio side because both read from the same
    ``.attocode/cache/pins.db``.

    ``project_dir`` is optional; if omitted it falls back to
    auto-discovery via ``_get_project_dir()``. Callers with a bound
    ``CodeIntelService`` (e.g. ``LocalSearchProvider``) MUST pass
    ``svc.project_dir`` to avoid writing pins for project A into
    project B's ``pins.db`` when one interpreter serves both.

    Failures in hashing or persistence surface as exceptions so callers
    can decide whether to swallow or log. This function MUST NOT catch
    ``SystemExit`` or ``BaseException`` — those indicate the process
    should exit.
    """
    if project_dir is None:
        project_dir = _get_project_dir()
    abs_dir = os.path.abspath(project_dir)
    hashes = _compute_current_manifest_hashes(abs_dir)
    raw = RetrievalPin.create(manifest_hashes=hashes, ttl_seconds=ttl_seconds)
    deterministic_id = f"pin_{raw.manifest_hash[:20]}"
    pin = RetrievalPin(
        pin_id=deterministic_id,
        schema_version=raw.schema_version,
        manifest_hashes=raw.manifest_hashes,
        manifest_hash=raw.manifest_hash,
        overlay_id=raw.overlay_id,
        branch_id=raw.branch_id,
        created_at=raw.created_at,
        expires_at=raw.expires_at,
    )
    _get_pin_store(abs_dir).save(pin)
    return pin
