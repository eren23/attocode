"""Retrieval pin MCP tools — deterministic RAG for code-intel queries.

Every ranked-result tool (``semantic_search``, ``fast_search``, ``repo_map``,
etc.) is retrofitted to emit an ``index_pin`` footer on its response. A
caller can then:

  - ``pin_current``        : mint a fresh pin of the current index state.
  - ``pin_resolve``        : look up an existing pin's manifest.
  - ``pin_list``           : list all active pins.
  - ``pin_delete``         : drop a pin.
  - ``verify_pin``         : compare a pin's recorded state to the current
                             state and return a drift report.

Phase 1 delivers the pin primitive + verification flow. Phase 2 layers on
``retrieve_with_pin`` (re-run a tool against pinned state) once the stacked
overlay machinery lands.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from attocode.code_intel._shared import _get_project_dir, mcp
from attocode.code_intel.artifacts import (
    RetrievalPin,
    compute_store_hash,
)

logger = logging.getLogger(__name__)


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


def _compute_current_manifest_hashes() -> dict[str, str]:
    """Return the current per-store manifest hashes for the active project."""
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


_pin_store: PinStore | None = None


def _get_pin_store() -> PinStore:
    global _pin_store
    if _pin_store is None:
        _pin_store = PinStore(_get_project_dir())
    return _pin_store


# ---------------------------------------------------------------------------
# _stamp_pin helper — used by all ranked-result tools
# ---------------------------------------------------------------------------


def pin_stamped(fn):  # type: ignore[no-untyped-def]
    """Decorator: append an ``index_pin`` footer to a tool's string return.

    Apply *below* ``@mcp.tool()`` so the registered function is the
    wrapped one::

        @mcp.tool()
        @pin_stamped
        def semantic_search(...) -> str:
            ...

    Non-string returns pass through unchanged — defensive against tools
    that might return structured data in the future.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = fn(*args, **kwargs)
        if isinstance(result, str):
            return _stamp_pin(result)
        return result

    return wrapper


def _stamp_pin(result_text: str, *, persist: bool = False, ttl_seconds: int = 0) -> str:
    """Append an ``index_pin`` footer to a tool response.

    Cheap path: compute the current manifest hashes, derive a content-addressed
    pin id (``pin_<hex12>`` of the manifest hash), append a single line to the
    response text. Does NOT persist the pin unless ``persist=True`` — that's
    a separate opt-in step via ``pin_current``.

    Idempotent: calling twice with no intervening writes produces the same
    pin id.
    """
    try:
        hashes = _compute_current_manifest_hashes()
    except Exception as exc:  # noqa: BLE001 — never let pin failure hide a result
        logger.debug("pin: hash computation failed: %s", exc)
        return result_text

    pin = RetrievalPin.create(manifest_hashes=hashes, ttl_seconds=ttl_seconds)
    # Use a deterministic id derived from the manifest_hash so repeat calls
    # on an unchanged state yield the same pin_id — enabling cheap "did the
    # state change?" checks without persisting anything.
    deterministic_id = f"pin_{pin.manifest_hash[:20]}"

    if persist:
        pin_to_save = RetrievalPin(
            pin_id=deterministic_id,
            schema_version=pin.schema_version,
            manifest_hashes=pin.manifest_hashes,
            manifest_hash=pin.manifest_hash,
            overlay_id=pin.overlay_id,
            branch_id=pin.branch_id,
            created_at=pin.created_at,
            expires_at=pin.expires_at,
        )
        try:
            _get_pin_store().save(pin_to_save)
        except sqlite3.Error as exc:
            logger.debug("pin: persist failed: %s", exc)

    footer = (
        f"\n\n---\nindex_pin: {deterministic_id}\n"
        f"manifest_hash: {pin.manifest_hash[:16]}…"
    )
    if result_text.endswith("\n"):
        return result_text + footer.lstrip("\n")
    return result_text + footer


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pin_current(ttl_seconds: int = 86400) -> str:
    """Mint a retrieval pin capturing the current code-intel state.

    A pin is a content-addressed snapshot of every local store's manifest
    hash (symbols, embeddings, learnings, ADRs, trigrams, etc.). Later you
    can call ``verify_pin(pin_id)`` to check whether the state has drifted
    since the pin was minted.

    Args:
        ttl_seconds: Pin expires after this many seconds. 0 = never expires.
                     Default 86400 (24h).

    Returns:
        The pin_id + a summary of hashed stores.
    """
    hashes = _compute_current_manifest_hashes()
    pin = RetrievalPin.create(manifest_hashes=hashes, ttl_seconds=ttl_seconds)
    _get_pin_store().save(pin)
    lines = [f"Pinned: {pin.pin_id}", f"manifest_hash: {pin.manifest_hash}"]
    if pin.expires_at > 0:
        import time
        remaining = int(pin.expires_at - time.time())
        lines.append(f"expires_in: {remaining}s")
    else:
        lines.append("expires_in: never")
    lines.append("stores:")
    for name, h in sorted(hashes.items()):
        short = h[:16] + "…" if len(h) > 20 else h
        lines.append(f"  - {name}: {short}")
    return "\n".join(lines)


@mcp.tool()
def pin_resolve(pin_id: str) -> str:
    """Look up a previously-minted retrieval pin by id."""
    pin = _get_pin_store().get(pin_id)
    if pin is None:
        return f"No pin with id {pin_id!r}"
    lines = [
        f"pin_id: {pin.pin_id}",
        f"manifest_hash: {pin.manifest_hash}",
        f"created_at: {pin.created_at}",
        f"expires_at: {pin.expires_at if pin.expires_at > 0 else 'never'}",
        f"expired: {pin.is_expired()}",
        "stores:",
    ]
    for name, h in sorted(pin.manifest_hashes.items()):
        lines.append(f"  - {name}: {h}")
    return "\n".join(lines)


@mcp.tool()
def pin_list() -> str:
    """List all retrieval pins, most recent first."""
    store = _get_pin_store()
    store.gc_expired()
    pins = store.list_all()
    if not pins:
        return "No pins."
    lines = [f"{len(pins)} pin(s):"]
    for pin in pins:
        status = "expired" if pin.is_expired() else "active"
        lines.append(
            f"  - {pin.pin_id}  ({status})  manifest={pin.manifest_hash[:12]}…"
        )
    return "\n".join(lines)


@mcp.tool()
def pin_delete(pin_id: str) -> str:
    """Delete a retrieval pin by id."""
    deleted = _get_pin_store().delete(pin_id)
    return f"Deleted pin {pin_id}" if deleted else f"No pin with id {pin_id!r}"


@mcp.tool()
def verify_pin(pin_id: str) -> str:
    """Check whether the code-intel state has drifted since a pin was minted.

    Returns a drift report: for each store, whether its hash matches the
    pinned value. If there is no drift, a query re-run against the current
    state is guaranteed to produce the same ranked results as when the pin
    was minted (assuming the tool is deterministic for a fixed index state —
    which is the whole point of these pins).
    """
    pin = _get_pin_store().get(pin_id)
    if pin is None:
        return f"No pin with id {pin_id!r}"
    if pin.is_expired():
        return f"Pin {pin_id} has expired."

    current = _compute_current_manifest_hashes()
    drift = pin.drift_from(current)
    if not drift:
        return f"Pin {pin_id}: no drift. State is identical to the pinned snapshot."

    lines = [f"Pin {pin_id}: DRIFT in {len(drift)} store(s):"]
    for name, (pinned_hash, current_hash) in sorted(drift.items()):
        lines.append(
            f"  - {name}: pinned={pinned_hash[:16]}… current={current_hash[:16]}…"
        )
    return "\n".join(lines)
