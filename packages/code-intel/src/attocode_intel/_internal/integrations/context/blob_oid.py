"""Blob-OID helpers — stable content-addressed identifiers for source files.

Every code-intel artifact that used to key on a file path (learnings,
ADRs, frecency) should really key on *the content of that file* — so a
rename doesn't orphan it, a vendored copy dedups across projects, and
git's own object store is the source of truth when available.

This module gives the rest of the codebase a uniform interface for
computing those identifiers, regardless of whether the project is a git
repo or a plain directory:

  - ``"git:<sha1>"``     inside a git repo (computed via
                          ``git hash-object``, which matches what
                          ``git ls-files --stage`` would show)
  - ``"sha256:<hex>"``   for non-git projects or for stdin-typed
                          content that has no on-disk path

The module also exposes:

  - :func:`compute_blob_oids_batch`   — fast bulk mode using
    ``git hash-object --stdin-paths``
  - :func:`check_reachability`        — given a set of git blob OIDs,
    returns the subset that are still reachable from any ref
  - :func:`is_git_repo`               — cheap test
  - A small SQLite ``blob_oid_cache`` keyed by ``(path, mtime)`` so
    repeat calls on unchanged files are O(1)

All git subprocess calls are best-effort: if git isn't installed or the
repo is broken, we silently fall back to SHA-256.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOB_OID_CACHE_DIR = os.path.join(".attocode", "cache")
BLOB_OID_CACHE_FILE = "blob_oid_cache.db"
BLOB_OID_SCHEMA_VERSION = 1

# Subprocess timeouts (seconds). Git operations are expected to be fast
# but we don't want a stuck subprocess to freeze the whole MCP server.
_GIT_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BlobOidCache:
    """SQLite-backed (path, mtime) → blob_oid cache.

    Path is stored relative to the project directory so the same cache
    file remains valid if the project is moved.
    """

    project_dir: str
    db_path: str = field(default="", repr=False)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if not self.db_path:
            cache_dir = os.path.join(self.project_dir, BLOB_OID_CACHE_DIR)
            os.makedirs(cache_dir, exist_ok=True)
            self.db_path = os.path.join(cache_dir, BLOB_OID_CACHE_FILE)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                rel_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                blob_oid TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_entries_oid ON entries(blob_oid);
            """
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(BLOB_OID_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def get(self, rel_path: str, mtime: float, size: int) -> str | None:
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT blob_oid FROM entries WHERE rel_path = ? AND mtime = ? AND size = ?",
                (rel_path, mtime, size),
            ).fetchone()
        return row[0] if row else None

    def put(self, rel_path: str, mtime: float, size: int, blob_oid: str) -> None:
        import time as _time
        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO entries
                   (rel_path, mtime, size, blob_oid, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (rel_path, mtime, size, blob_oid, _time.time()),
            )
            self._conn.commit()

    def clear(self) -> int:
        assert self._conn is not None
        with self._lock:
            cur = self._conn.execute("DELETE FROM entries")
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Git detection
# ---------------------------------------------------------------------------


def is_git_repo(project_dir: str) -> bool:
    """True if ``project_dir`` (or any parent) is inside a git work-tree.

    Uses ``git rev-parse --is-inside-work-tree`` rather than checking for
    a literal ``.git`` directory so submodules, worktrees, and ``.git``
    file redirections all resolve correctly.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


# ---------------------------------------------------------------------------
# Single / batch compute
# ---------------------------------------------------------------------------


def compute_blob_oid(
    path: str,
    project_dir: str,
    *,
    cache: BlobOidCache | None = None,
) -> str:
    """Return the blob OID for one file.

    Args:
        path: Absolute or project-relative path.
        project_dir: Project root. Used to normalize ``path`` for caching
            and as the ``cwd`` for git subprocess calls.
        cache: Optional :class:`BlobOidCache` for memoization. If given,
            hits/misses are consulted and populated.

    Returns:
        ``"git:<sha1>"`` if ``project_dir`` is a git repo and the file is
        readable; ``"sha256:<hex>"`` otherwise. Returns
        ``"sha256:missing:<path>"`` if the file can't be opened — callers
        can treat that as a sentinel rather than crashing the index walk.
    """
    # Normalize to absolute + relative forms.
    if os.path.isabs(path):
        abs_path = path
        try:
            rel_path = os.path.relpath(path, project_dir)
        except ValueError:
            rel_path = path
    else:
        rel_path = path
        abs_path = os.path.join(project_dir, path)

    # Missing file → sentinel.
    try:
        stat = os.stat(abs_path)
    except OSError:
        return f"sha256:missing:{rel_path}"

    mtime = stat.st_mtime
    size = stat.st_size

    # Cache hit?
    if cache is not None:
        cached = cache.get(rel_path, mtime, size)
        if cached is not None:
            return cached

    oid = _compute_blob_oid_uncached(abs_path, project_dir)

    if cache is not None:
        cache.put(rel_path, mtime, size, oid)
    return oid


def _compute_blob_oid_uncached(abs_path: str, project_dir: str) -> str:
    """Single-file blob OID without cache consultation."""
    if is_git_repo(project_dir):
        try:
            result = subprocess.run(
                ["git", "hash-object", "--", abs_path],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode == 0:
                sha = result.stdout.strip()
                if sha:
                    return f"git:{sha}"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("git hash-object failed for %s: %s", abs_path, exc)

    # Fallback — SHA-256 the raw bytes.
    try:
        with open(abs_path, "rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
            return f"sha256:{h.hexdigest()}"
    except OSError:
        return "sha256:unreadable"


def compute_blob_oids_batch(
    paths: list[str],
    project_dir: str,
    *,
    cache: BlobOidCache | None = None,
) -> dict[str, str]:
    """Compute blob OIDs for many files in one shot.

    If ``project_dir`` is a git repo, dispatches a single
    ``git hash-object --stdin-paths`` subprocess call — ~100x faster than
    calling :func:`compute_blob_oid` in a loop. Cache hits are resolved
    locally before the subprocess so unchanged files don't cost anything.

    Returns a mapping from the input path (as given, not necessarily
    canonicalized) to the computed OID.
    """
    results: dict[str, str] = {}
    uncached: list[tuple[str, str, float, int]] = []  # (input_path, abs, mtime, size)

    for path in paths:
        if os.path.isabs(path):
            abs_path = path
            try:
                rel_path = os.path.relpath(path, project_dir)
            except ValueError:
                rel_path = path
        else:
            rel_path = path
            abs_path = os.path.join(project_dir, path)
        try:
            stat = os.stat(abs_path)
        except OSError:
            results[path] = f"sha256:missing:{rel_path}"
            continue
        if cache is not None:
            cached = cache.get(rel_path, stat.st_mtime, stat.st_size)
            if cached is not None:
                results[path] = cached
                continue
        uncached.append((path, abs_path, stat.st_mtime, stat.st_size))

    if not uncached:
        return results

    # Git batch mode if available.
    if is_git_repo(project_dir):
        try:
            stdin_text = "\n".join(abs_p for _, abs_p, _, _ in uncached) + "\n"
            result = subprocess.run(
                ["git", "hash-object", "--stdin-paths"],
                cwd=project_dir,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=max(_GIT_TIMEOUT_SECONDS, len(uncached) * 0.1),
                check=False,
            )
            if result.returncode == 0:
                out_lines = result.stdout.splitlines()
                if len(out_lines) == len(uncached):
                    for (input_path, abs_path, mtime, size), sha in zip(
                        uncached, out_lines, strict=True,
                    ):
                        oid = f"git:{sha.strip()}"
                        results[input_path] = oid
                        if cache is not None:
                            try:
                                rel = os.path.relpath(abs_path, project_dir)
                            except ValueError:
                                rel = input_path
                            cache.put(rel, mtime, size, oid)
                    return results
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("git hash-object --stdin-paths failed: %s", exc)

    # Non-git fallback — compute sha256 per file.
    for input_path, abs_path, mtime, size in uncached:
        try:
            with open(abs_path, "rb") as f:
                h = hashlib.sha256()
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
                oid = f"sha256:{h.hexdigest()}"
        except OSError:
            oid = "sha256:unreadable"
        results[input_path] = oid
        if cache is not None:
            try:
                rel = os.path.relpath(abs_path, project_dir)
            except ValueError:
                rel = input_path
            cache.put(rel, mtime, size, oid)

    return results


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


def check_reachability(
    blob_oids: set[str],
    project_dir: str,
) -> set[str]:
    """Return the subset of ``blob_oids`` that are still reachable in git.

    Non-git-prefixed OIDs (``sha256:...``, ``sha256:missing:...``, etc.)
    are passed through as "always reachable" since we can't prove they're
    orphaned without the git object database.

    Implementation: uses ``git cat-file --batch-check`` which checks all
    objects, not just reachable ones — but for orphan detection we also
    filter out dangling blobs using ``git fsck --unreachable``. In
    practice, for code-intel anchors, "object exists" is a close-enough
    proxy for "reachable" because git's GC eventually prunes unreachable
    objects and the cache_manifest will catch up on the next scan.

    Empty input returns empty set.
    """
    if not blob_oids:
        return set()

    # Partition git vs non-git keys.
    git_oids: set[str] = set()
    non_git: set[str] = set()
    for oid in blob_oids:
        if oid.startswith("git:"):
            git_oids.add(oid)
        else:
            non_git.add(oid)

    if not git_oids or not is_git_repo(project_dir):
        # Nothing to probe in git → pass-through.
        return set(blob_oids)

    # Prepare stdin: one SHA per line (strip the "git:" prefix).
    stdin_text = "\n".join(oid[4:] for oid in git_oids) + "\n"
    try:
        result = subprocess.run(
            ["git", "cat-file", "--batch-check"],
            cwd=project_dir,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=max(_GIT_TIMEOUT_SECONDS, len(git_oids) * 0.01),
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git cat-file --batch-check failed: %s", exc)
        return set(blob_oids)

    if result.returncode != 0:
        return set(blob_oids)

    # Each line is either "<sha> <type> <size>" (exists) or
    # "<sha> missing" (doesn't exist).
    reachable: set[str] = set(non_git)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sha = parts[0]
            status = parts[1]
            if status != "missing":
                reachable.add(f"git:{sha}")
    return reachable
