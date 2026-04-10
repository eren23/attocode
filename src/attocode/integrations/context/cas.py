"""Content-addressable cache for code-intel derived artifacts.

A single shared store (default ``~/.cache/attocode/cas/``) holds both raw
source blobs and derived artifacts (symbol sets, embeddings, dep graphs,
stack-graph partials, etc.) keyed by content hash. Cross-project dedup: if
two projects reference the same source file or the same (file, indexer,
version, config) tuple, they share the cache entry.

Design notes:
  - On-disk layout:
      <cas_root>/
          blobs/<aa>/<bb>/<rest>          # raw file contents (opt-in)
          derived/<artifact_type>/<aa>/<bb>/<rest>
          manifest.db                       # SQLite index: fast exists / gc
  - Keys are hex digests (sha256 or git-style sha1) prefixed with algo
    (``"sha256:..."``, ``"git:..."``). The prefix is stripped before the
    two-level directory sharding.
  - Reference counting is application-level: callers ``incref()`` on write
    and ``decref()`` when a downstream store drops its reference. GC only
    removes entries whose refcount is zero *and* whose last-accessed time
    is older than the min_age threshold (default 7 days), so briefly
    unreferenced entries aren't prematurely evicted.
  - Directly operating on the filesystem keeps the store easy to inspect
    with ``ls`` / ``sha256sum`` — no proprietary format.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from attocode.code_intel.artifacts import Provenance

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

CAS_SCHEMA_VERSION = 1
# Default GC age floor — unreferenced entries younger than this are kept.
DEFAULT_GC_MIN_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def _default_cas_root() -> str:
    """XDG-style default CAS location, overridable via ``ATTOCODE_CAS_DIR``."""
    env = os.environ.get("ATTOCODE_CAS_DIR")
    if env:
        return os.path.expanduser(env)
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return os.path.join(os.path.expanduser(xdg_cache), "attocode", "cas")
    return os.path.expanduser("~/.cache/attocode/cas")


def _normalize_key(key: str) -> tuple[str, str]:
    """Return (algo, hex) for a CAS key like ``sha256:abc...`` or ``git:def...``.

    Raises ``ValueError`` if the key has no algo prefix — we want loud
    failure rather than silently hashing in one format on writes and
    looking it up in another format on reads.
    """
    if ":" not in key:
        raise ValueError(
            f"CAS key must be prefixed with an algo (e.g. 'sha256:'); got {key!r}"
        )
    algo, _, hexdigest = key.partition(":")
    if not hexdigest:
        raise ValueError(f"CAS key is empty after algo prefix: {key!r}")
    if algo not in {"sha256", "git"}:
        raise ValueError(f"unsupported CAS algo {algo!r}; use 'sha256' or 'git'")
    # Defensive: strip whitespace, lowercase.
    return algo, hexdigest.strip().lower()


def _shard_path(root: str, subdir: str, key: str) -> str:
    """Two-level sharding to avoid one giant directory."""
    _, hexdigest = _normalize_key(key)
    return os.path.join(root, subdir, hexdigest[:2], hexdigest[2:4], hexdigest[4:])


@dataclass(slots=True)
class CasEntry:
    """One row from the CAS manifest, returned by :meth:`ContentAddressedCache.stat`."""

    key: str
    artifact_type: str
    action_hash: str
    size_bytes: int
    created_at: float
    last_accessed_at: float
    refcount: int
    provenance: Provenance | None


@dataclass(slots=True)
class ContentAddressedCache:
    """Content-addressable cache for source blobs and derived artifacts.

    Usage::

        cas = ContentAddressedCache()
        cas.put(
            key="sha256:abc...",
            data=symbol_set_bytes,
            artifact_type="symbols",
            provenance=Provenance.create(...),
        )
        if cas.exists("sha256:abc...", "symbols"):
            data = cas.get("sha256:abc...", "symbols")
    """

    cas_root: str = field(default_factory=_default_cas_root)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        os.makedirs(self.cas_root, exist_ok=True)
        os.makedirs(os.path.join(self.cas_root, "blobs"), exist_ok=True)
        os.makedirs(os.path.join(self.cas_root, "derived"), exist_ok=True)
        self._conn = sqlite3.connect(
            os.path.join(self.cas_root, "manifest.db"),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cas_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cas_entries (
                key              TEXT NOT NULL,
                artifact_type    TEXT NOT NULL,
                action_hash      TEXT NOT NULL DEFAULT '',
                size_bytes       INTEGER NOT NULL,
                created_at       REAL NOT NULL,
                last_accessed_at REAL NOT NULL,
                refcount         INTEGER NOT NULL DEFAULT 0,
                provenance_json  TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (key, artifact_type)
            );

            CREATE INDEX IF NOT EXISTS ix_cas_type ON cas_entries(artifact_type);
            CREATE INDEX IF NOT EXISTS ix_cas_atime ON cas_entries(last_accessed_at);
            CREATE INDEX IF NOT EXISTS ix_cas_action ON cas_entries(action_hash);
            """
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO cas_meta (key, value) VALUES ('schema_version', ?)",
            (str(CAS_SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Put / Get
    # ------------------------------------------------------------------

    def _path_for(self, key: str, artifact_type: str) -> str:
        subdir = "blobs" if artifact_type == "blob" else f"derived/{artifact_type}"
        return _shard_path(self.cas_root, subdir, key)

    def put(
        self,
        key: str,
        data: bytes,
        *,
        artifact_type: str,
        provenance: Provenance | None = None,
        action_hash: str = "",
    ) -> str:
        """Store ``data`` under ``key`` + ``artifact_type``.

        Returns the on-disk path of the stored file. Idempotent: re-putting
        the same key overwrites the file (should produce identical bytes
        anyway) and refreshes ``last_accessed_at``.
        """
        path = self._path_for(key, artifact_type)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

        now = time.time()
        provenance_json = provenance.to_json() if provenance is not None else "{}"
        size = len(data)

        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                """INSERT INTO cas_entries
                   (key, artifact_type, action_hash, size_bytes,
                    created_at, last_accessed_at, refcount, provenance_json)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(key, artifact_type) DO UPDATE SET
                     size_bytes = excluded.size_bytes,
                     last_accessed_at = excluded.last_accessed_at,
                     action_hash = excluded.action_hash,
                     provenance_json = excluded.provenance_json
                """,
                (
                    key, artifact_type, action_hash, size,
                    now, now, provenance_json,
                ),
            )
            self._conn.commit()
        return path

    def get(self, key: str, artifact_type: str) -> bytes | None:
        """Return stored bytes, or None if the entry does not exist."""
        path = self._path_for(key, artifact_type)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = f.read()
        # Refresh access time (best-effort; a failure here shouldn't break reads).
        try:
            self._touch(key, artifact_type)
        except sqlite3.OperationalError:
            pass
        return data

    def exists(self, key: str, artifact_type: str) -> bool:
        """Cheap existence check: manifest.db + filesystem."""
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM cas_entries WHERE key = ? AND artifact_type = ?",
                (key, artifact_type),
            ).fetchone()
        if row is None:
            return False
        return os.path.exists(self._path_for(key, artifact_type))

    def stat(self, key: str, artifact_type: str) -> CasEntry | None:
        """Return metadata for one entry, or None."""
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                """SELECT key, artifact_type, action_hash, size_bytes, created_at,
                          last_accessed_at, refcount, provenance_json
                   FROM cas_entries WHERE key = ? AND artifact_type = ?""",
                (key, artifact_type),
            ).fetchone()
        if row is None:
            return None
        provenance: Provenance | None
        if row[7] and row[7] != "{}":
            try:
                import json
                provenance = Provenance.from_dict(json.loads(row[7]))
            except (ValueError, KeyError):
                provenance = None
        else:
            provenance = None
        return CasEntry(
            key=row[0],
            artifact_type=row[1],
            action_hash=row[2],
            size_bytes=row[3],
            created_at=row[4],
            last_accessed_at=row[5],
            refcount=row[6],
            provenance=provenance,
        )

    def _touch(self, key: str, artifact_type: str) -> None:
        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                "UPDATE cas_entries SET last_accessed_at = ? "
                "WHERE key = ? AND artifact_type = ?",
                (time.time(), key, artifact_type),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Reference counting
    # ------------------------------------------------------------------

    def incref(self, key: str, artifact_type: str) -> int:
        """Increment refcount; returns new value. Returns 0 if entry not found."""
        assert self._conn is not None
        with self._lock:
            cur = self._conn.execute(
                "UPDATE cas_entries SET refcount = refcount + 1 "
                "WHERE key = ? AND artifact_type = ?",
                (key, artifact_type),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return 0
            row = self._conn.execute(
                "SELECT refcount FROM cas_entries "
                "WHERE key = ? AND artifact_type = ?",
                (key, artifact_type),
            ).fetchone()
            return int(row[0]) if row else 0

    def decref(self, key: str, artifact_type: str) -> int:
        """Decrement refcount (not below zero); returns new value."""
        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                "UPDATE cas_entries "
                "SET refcount = CASE WHEN refcount > 0 THEN refcount - 1 ELSE 0 END "
                "WHERE key = ? AND artifact_type = ?",
                (key, artifact_type),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT refcount FROM cas_entries "
                "WHERE key = ? AND artifact_type = ?",
                (key, artifact_type),
            ).fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # GC
    # ------------------------------------------------------------------

    def iter_orphans(
        self, min_age_seconds: float = DEFAULT_GC_MIN_AGE_SECONDS,
    ) -> Iterator[tuple[str, str, int]]:
        """Yield (key, artifact_type, size_bytes) for entries with refcount=0
        older than the age floor.
        """
        cutoff = time.time() - min_age_seconds
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                """SELECT key, artifact_type, size_bytes FROM cas_entries
                   WHERE refcount <= 0 AND last_accessed_at <= ?
                   ORDER BY last_accessed_at""",
                (cutoff,),
            ).fetchall()
        for row in rows:
            yield row[0], row[1], int(row[2])

    def gc(
        self,
        min_age_seconds: float = DEFAULT_GC_MIN_AGE_SECONDS,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Delete orphaned entries (refcount=0, older than age floor).

        Returns a summary dict with ``{would_delete_count, would_free_bytes,
        deleted_count, freed_bytes, dry_run, examples}``.

        ``examples`` is a short list of entries (up to 10) so callers can
        show a preview of what would (or did) get deleted.
        """
        would_count = 0
        would_bytes = 0
        examples: list[dict[str, Any]] = []

        to_delete: list[tuple[str, str]] = []
        for key, artifact_type, size in self.iter_orphans(min_age_seconds):
            would_count += 1
            would_bytes += size
            if len(examples) < 10:
                examples.append({
                    "key": key,
                    "artifact_type": artifact_type,
                    "size_bytes": size,
                })
            to_delete.append((key, artifact_type))

        if dry_run:
            return {
                "dry_run": True,
                "would_delete_count": would_count,
                "would_free_bytes": would_bytes,
                "deleted_count": 0,
                "freed_bytes": 0,
                "examples": examples,
            }

        deleted = 0
        freed = 0
        assert self._conn is not None
        for key, artifact_type in to_delete:
            path = self._path_for(key, artifact_type)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("cas: failed to unlink %s: %s", path, exc)
                continue
            with self._lock:
                self._conn.execute(
                    "DELETE FROM cas_entries WHERE key = ? AND artifact_type = ?",
                    (key, artifact_type),
                )
                self._conn.commit()
            deleted += 1
            freed += size

        return {
            "dry_run": False,
            "would_delete_count": would_count,
            "would_free_bytes": would_bytes,
            "deleted_count": deleted,
            "freed_bytes": freed,
            "examples": examples,
        }

    # ------------------------------------------------------------------
    # Stats / introspection
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return summary stats for the CAS: per-type counts + total bytes."""
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                """SELECT artifact_type, COUNT(*), SUM(size_bytes),
                          SUM(CASE WHEN refcount <= 0 THEN 1 ELSE 0 END)
                   FROM cas_entries GROUP BY artifact_type"""
            ).fetchall()
        by_type = {
            row[0]: {
                "count": int(row[1] or 0),
                "bytes": int(row[2] or 0),
                "orphans": int(row[3] or 0),
            }
            for row in rows
        }
        total = {
            "count": sum(v["count"] for v in by_type.values()),
            "bytes": sum(v["bytes"] for v in by_type.values()),
            "orphans": sum(v["orphans"] for v in by_type.values()),
        }
        return {
            "cas_root": self.cas_root,
            "schema_version": CAS_SCHEMA_VERSION,
            "by_type": by_type,
            "total": total,
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
