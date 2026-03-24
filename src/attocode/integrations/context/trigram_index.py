"""Memory-mapped trigram inverted index for fast regex candidate pre-filtering.

Two-file mmap storage layout:

Lookup file  (.attocode/index/trigrams.lookup):
    Header : magic(u32) + version(u16) + entry_count(u32) + padding(u16) = 12 bytes
    Entries: sorted by trigram_hash -- [trigram_hash:u32, postings_offset:u64,
             postings_length:u32] = 16 bytes each

Postings file (.attocode/index/trigrams.postings):
    Per posting list: [count:u32] + [file_id:u32] * count

File-ID mapping: SQLite table in .attocode/index/trigrams.db
    trigram_files(file_id INTEGER PRIMARY KEY, path TEXT UNIQUE,
                  content_hash TEXT, mtime REAL)
"""

from __future__ import annotations

import logging
import mmap
import os
import sqlite3
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAGIC: int = 0x54524933        # "TRI3" as little-endian u32
_VERSION: int = 1
_HEADER_SIZE: int = 12          # magic(4) + version(2) + entry_count(4) + pad(2)
_ENTRY_SIZE: int = 16           # hash(4) + offset(8) + length(4)
_MAX_FILE_SIZE: int = 1_000_000  # Skip files larger than 1 MB
_SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z",
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".pyd",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".exe", ".o", ".a", ".obj",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".lock",
})
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".venv", "venv", ".env",
    ".tox", "dist", "build", ".eggs", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
})


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _trigram_hash(tri: bytes) -> int:
    """CRC32 of a 3-byte sequence, masked to u32."""
    return zlib.crc32(tri) & 0xFFFFFFFF


def _extract_trigrams_from_bytes(content: bytes) -> set[int]:
    """Return the set of unique trigram hashes present in *content*.

    Trigrams containing control characters (except \\t, \\n, \\r which appear
    in normal source) are skipped -- this acts as a lightweight binary guard.
    """
    hashes: set[int] = set()
    n = len(content)
    for i in range(n - 2):
        a, b, c = content[i], content[i + 1], content[i + 2]
        # Allow: 0x09=\t, 0x0A=\n, 0x0D=\r; reject everything else < 0x20
        if (
            (a < 0x09 or (0x0E <= a <= 0x1F))
            or (b < 0x09 or (0x0E <= b <= 0x1F))
            or (c < 0x09 or (0x0E <= c <= 0x1F))
        ):
            continue
        hashes.add(zlib.crc32(content[i : i + 3]) & 0xFFFFFFFF)
    return hashes


def _is_likely_binary(data: bytes, sample_size: int = 8192) -> bool:
    """Return True if *data* looks like binary content.

    Checks the first *sample_size* bytes for control characters.
    A ratio > 10% is a reliable indicator of binary data.
    """
    sample = data[:sample_size]
    if not sample:
        return False
    control_count = sum(
        1 for b in sample
        if b < 0x09 or (0x0E <= b <= 0x1F) or b == 0x7F
    )
    return control_count / len(sample) > 0.10


# ---------------------------------------------------------------------------
# TrigramIndex
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TrigramIndex:
    """Memory-mapped trigram inverted index for fast regex candidate filtering.

    Usage::

        idx = TrigramIndex(index_dir=".attocode/index")
        if not idx.load():
            stats = idx.build(project_dir=".")
        candidates = idx.query("def grep_search")
        # None  -> caller falls back to full scan
        # []    -> no files match (definitive fast exit)
        # [str] -> relative paths of candidate files
    """

    index_dir: str

    _db_path: str = field(default="", init=False, repr=False)
    _lookup_path: str = field(default="", init=False, repr=False)
    _postings_path: str = field(default="", init=False, repr=False)

    _lookup_fd: int = field(default=-1, init=False, repr=False)
    _postings_fd: int = field(default=-1, init=False, repr=False)
    _lookup_mmap: mmap.mmap | None = field(default=None, init=False, repr=False)
    _postings_mmap: mmap.mmap | None = field(default=None, init=False, repr=False)

    _entry_count: int = field(default=0, init=False, repr=False)
    _file_id_to_path: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _path_to_file_id: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _ready: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        os.makedirs(self.index_dir, exist_ok=True)
        self._db_path = os.path.join(self.index_dir, "trigrams.db")
        self._lookup_path = os.path.join(self.index_dir, "trigrams.lookup")
        self._postings_path = os.path.join(self.index_dir, "trigrams.postings")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, project_dir: str) -> dict[str, Any]:
        """Build the trigram index by walking *project_dir*.

        Writes lookup and postings files atomically (write .tmp, os.replace).
        Stores the file-ID mapping in SQLite.

        Returns:
            dict with keys: files_indexed, trigrams_count,
            build_time_ms, index_size_bytes, loaded (bool).
        """
        t0 = time.monotonic()
        project_path = Path(project_dir).resolve()

        with self._lock:
            # Phase 1: enumerate candidate files
            file_paths = self._enumerate_files(project_path)

            # Phase 2: build inverted index
            file_map: dict[str, int] = {}           # rel_path -> file_id
            postings: dict[int, list[int]] = {}      # trigram_hash -> [file_ids]
            content_hashes: dict[str, str] = {}
            mtimes: dict[str, float] = {}

            for file_id, rel_path in enumerate(file_paths):
                abs_path = project_path / rel_path
                try:
                    raw = abs_path.read_bytes()
                except OSError:
                    continue
                if _is_likely_binary(raw):
                    continue

                file_map[rel_path] = file_id
                try:
                    mtimes[rel_path] = abs_path.stat().st_mtime
                except OSError:
                    mtimes[rel_path] = 0.0
                content_hashes[rel_path] = format(zlib.crc32(raw) & 0xFFFFFFFF, "08x")

                for h in _extract_trigrams_from_bytes(raw):
                    if h not in postings:
                        postings[h] = []
                    postings[h].append(file_id)

            # Phase 3: write index files atomically
            self._write_index(postings, file_map)

            # Phase 4: persist file map to SQLite
            self._init_db()
            self._save_file_map(file_map, content_hashes, mtimes)

            # Phase 5: load the freshly built index into mmap
            self._ready = False
            self._close_mmap()
            success = self._load_unlocked()

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        lookup_size = (
            os.path.getsize(self._lookup_path)
            if os.path.exists(self._lookup_path)
            else 0
        )
        postings_size = (
            os.path.getsize(self._postings_path)
            if os.path.exists(self._postings_path)
            else 0
        )
        return {
            "files_indexed": len(file_map),
            "trigrams_count": len(postings),
            "build_time_ms": elapsed_ms,
            "index_size_bytes": lookup_size + postings_size,
            "loaded": success,
        }

    def load(self) -> bool:
        """Load an existing index from disk into memory-mapped buffers.

        Returns True if the index was loaded and is ready for queries.
        Returns False if files are missing, corrupt, or version-mismatched.
        """
        with self._lock:
            self._ready = False
            self._close_mmap()
            return self._load_unlocked()

    def query(
        self,
        pattern: str,
        *,
        case_insensitive: bool = False,
    ) -> list[str] | None:
        """Return candidate file paths that MAY contain a match for *pattern*.

        Extracts required trigrams from the regex, intersects their posting
        lists, and maps file-IDs back to relative paths.

        Returns:
            None  -- no trigrams extractable; caller must scan all files.
            []    -- trigrams found but no file contains all of them.
            [str] -- relative file paths that contain all required trigrams.
        """
        if not self._ready:
            return None

        from attocode.integrations.context.trigram_regex import extract_required_trigrams

        required = extract_required_trigrams(pattern, case_insensitive=case_insensitive)
        if not required:
            return None

        with self._lock:
            if not self._ready:
                return None
            return self._intersect_postings(required)

    def update_file(self, rel_path: str, content: bytes) -> None:
        """Invalidate the index for *rel_path*.

        Marks the index not-ready so callers fall back to brute force until
        the next ``build()`` call rebuilds it.
        """
        with self._lock:
            self._ready = False

    def remove_file(self, rel_path: str) -> None:
        """Remove *rel_path* from the in-memory ID mapping.

        The mmap files are not modified; call ``build()`` for a full refresh.
        """
        with self._lock:
            fid = self._path_to_file_id.pop(rel_path, None)
            if fid is not None:
                self._file_id_to_path.pop(fid, None)

    def is_ready(self) -> bool:
        """Return True if the index is loaded and ready for queries."""
        return self._ready

    def close(self) -> None:
        """Unmap memory regions and close all file descriptors."""
        with self._lock:
            self._close_mmap()
            self._ready = False

    # ------------------------------------------------------------------
    # Internal: file enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def _enumerate_files(project_path: Path) -> list[str]:
        """Walk *project_path* and return relative paths of indexable files."""
        result: list[str] = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [
                d for d in dirs
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            for fname in sorted(files):
                fpath = Path(root) / fname
                if fpath.suffix.lower() in _SKIP_EXTENSIONS:
                    continue
                if fname.startswith("."):
                    continue
                try:
                    if fpath.stat().st_size > _MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                try:
                    rel = str(fpath.relative_to(project_path))
                except ValueError:
                    rel = str(fpath)
                result.append(rel)
        return result

    # ------------------------------------------------------------------
    # Internal: index writing
    # ------------------------------------------------------------------

    def _write_index(
        self,
        postings: dict[int, list[int]],
        file_map: dict[str, int],
    ) -> None:
        """Atomically write lookup and postings binary files."""
        sorted_hashes = sorted(postings.keys())
        n_entries = len(sorted_hashes)

        # Build postings blob -- one posting list per unique trigram hash
        postings_parts: list[bytes] = []
        postings_offsets: dict[int, tuple[int, int]] = {}
        current_offset = 0

        for h in sorted_hashes:
            file_ids = sorted(postings[h])
            count = len(file_ids)
            part = struct.pack(f"<I{count}I", count, *file_ids)
            postings_offsets[h] = (current_offset, len(part))
            postings_parts.append(part)
            current_offset += len(part)

        postings_blob = b"".join(postings_parts)

        # Build lookup blob
        # Header: magic(u32) + version(u16) + entry_count(u32) + padding(u16)
        header = struct.pack("<IHIh", _MAGIC, _VERSION, n_entries, 0)
        assert len(header) == _HEADER_SIZE

        lookup_parts: list[bytes] = [header]
        for h in sorted_hashes:
            off, length = postings_offsets[h]
            entry = struct.pack("<IQI", h, off, length)
            assert len(entry) == _ENTRY_SIZE
            lookup_parts.append(entry)

        lookup_blob = b"".join(lookup_parts)

        # Atomic write: write to .tmp, then os.replace
        lookup_tmp = self._lookup_path + ".tmp"
        postings_tmp = self._postings_path + ".tmp"
        try:
            with open(lookup_tmp, "wb") as f:
                f.write(lookup_blob)
            with open(postings_tmp, "wb") as f:
                f.write(postings_blob)
            os.replace(lookup_tmp, self._lookup_path)
            os.replace(postings_tmp, self._postings_path)
        except Exception:
            for tmp in (lookup_tmp, postings_tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    # ------------------------------------------------------------------
    # Internal: loading
    # ------------------------------------------------------------------

    def _load_unlocked(self) -> bool:
        """Load index files. Caller must hold _lock."""
        for path in (self._lookup_path, self._postings_path, self._db_path):
            if not os.path.exists(path):
                return False

        # Load file-ID mapping from SQLite
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                rows = conn.execute(
                    "SELECT file_id, path FROM trigram_files"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.debug("trigram_index: DB read failed: %s", exc)
            return False

        id_to_path: dict[int, str] = {}
        path_to_id: dict[str, int] = {}
        for fid, fpath in rows:
            id_to_path[fid] = fpath
            path_to_id[fpath] = fid

        # mmap the lookup file
        try:
            lookup_fd = os.open(self._lookup_path, os.O_RDONLY)
            lookup_size = os.path.getsize(self._lookup_path)
        except OSError as exc:
            logger.debug("trigram_index: cannot open lookup: %s", exc)
            return False

        if lookup_size < _HEADER_SIZE:
            os.close(lookup_fd)
            return False

        try:
            lookup_mm = mmap.mmap(lookup_fd, 0, access=mmap.ACCESS_READ)
        except OSError as exc:
            os.close(lookup_fd)
            logger.debug("trigram_index: mmap lookup failed: %s", exc)
            return False

        # Validate header
        try:
            magic, version, entry_count, _pad = struct.unpack_from("<IHIh", lookup_mm, 0)
        except struct.error as exc:
            lookup_mm.close()
            os.close(lookup_fd)
            logger.debug("trigram_index: corrupt header: %s", exc)
            return False

        if magic != _MAGIC or version != _VERSION:
            lookup_mm.close()
            os.close(lookup_fd)
            return False

        expected_lookup_size = _HEADER_SIZE + entry_count * _ENTRY_SIZE
        if lookup_size < expected_lookup_size:
            lookup_mm.close()
            os.close(lookup_fd)
            return False

        # mmap the postings file
        postings_size = os.path.getsize(self._postings_path)
        if postings_size == 0:
            postings_fd = -1
            postings_mm: mmap.mmap | None = None
        else:
            try:
                postings_fd = os.open(self._postings_path, os.O_RDONLY)
                postings_mm = mmap.mmap(postings_fd, 0, access=mmap.ACCESS_READ)
            except OSError as exc:
                lookup_mm.close()
                os.close(lookup_fd)
                logger.debug("trigram_index: mmap postings failed: %s", exc)
                return False

        # Commit
        self._close_mmap()
        self._lookup_fd = lookup_fd
        self._postings_fd = postings_fd
        self._lookup_mmap = lookup_mm
        self._postings_mmap = postings_mm
        self._entry_count = entry_count
        self._file_id_to_path = id_to_path
        self._path_to_file_id = path_to_id
        self._ready = True

        logger.debug(
            "trigram_index: loaded -- %d entries, %d files",
            entry_count, len(id_to_path),
        )
        return True

    # ------------------------------------------------------------------
    # Internal: query helpers
    # ------------------------------------------------------------------

    def _intersect_postings(self, required_hashes: list[int]) -> list[str] | None:
        """Intersect posting lists for all required trigram hashes."""
        candidate_ids: set[int] | None = None

        for h in required_hashes:
            result = self._binary_search(h)
            if result is None:
                return []
            offset, length = result
            file_ids = self._read_posting_list(offset, length)
            if candidate_ids is None:
                candidate_ids = set(file_ids)
            else:
                candidate_ids &= set(file_ids)
            if not candidate_ids:
                return []

        if candidate_ids is None:
            return None

        paths: list[str] = []
        for fid in candidate_ids:
            path = self._file_id_to_path.get(fid)
            if path is not None:
                paths.append(path)
        return paths

    def _binary_search(self, trigram_hash: int) -> tuple[int, int] | None:
        """Binary search the lookup mmap for *trigram_hash*.

        Returns (postings_offset, postings_length) on hit, None on miss.
        """
        if self._lookup_mmap is None:
            return None
        lo, hi = 0, self._entry_count - 1
        mm = self._lookup_mmap
        while lo <= hi:
            mid = (lo + hi) >> 1
            offset = _HEADER_SIZE + mid * _ENTRY_SIZE
            entry_hash = struct.unpack_from("<I", mm, offset)[0]
            if entry_hash == trigram_hash:
                postings_offset, postings_length = struct.unpack_from(
                    "<QI", mm, offset + 4
                )
                return (postings_offset, postings_length)
            elif entry_hash < trigram_hash:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def _read_posting_list(self, offset: int, length: int) -> list[int]:
        """Read and decode a posting list from the postings mmap."""
        if self._postings_mmap is None:
            return []
        mm = self._postings_mmap
        try:
            raw = mm[offset : offset + length]
            if len(raw) < 4:
                return []
            (count,) = struct.unpack_from("<I", raw, 0)
            expected = 4 + count * 4
            if len(raw) < expected:
                return []
            return list(struct.unpack_from(f"<{count}I", raw, 4))
        except (struct.error, ValueError):
            return []

    # ------------------------------------------------------------------
    # Internal: SQLite
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the trigram_files table if it does not exist."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trigram_files (
                    file_id      INTEGER PRIMARY KEY,
                    path         TEXT    NOT NULL UNIQUE,
                    content_hash TEXT    NOT NULL DEFAULT '',
                    mtime        REAL    NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_trigram_files_path "
                "ON trigram_files(path)"
            )
            conn.commit()
        finally:
            conn.close()

    def _save_file_map(
        self,
        file_map: dict[str, int],
        content_hashes: dict[str, str],
        mtimes: dict[str, float],
    ) -> None:
        """Persist the file-ID map to SQLite, replacing all previous rows."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("DELETE FROM trigram_files")
            conn.executemany(
                "INSERT INTO trigram_files (file_id, path, content_hash, mtime) "
                "VALUES (?, ?, ?, ?)",
                [
                    (fid, rp, content_hashes.get(rp, ""), mtimes.get(rp, 0.0))
                    for rp, fid in file_map.items()
                ],
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal: mmap lifecycle
    # ------------------------------------------------------------------

    def _close_mmap(self) -> None:
        """Close mmaps and file descriptors. Caller must hold _lock."""
        if self._lookup_mmap is not None:
            try:
                self._lookup_mmap.close()
            except Exception:
                pass
            self._lookup_mmap = None
        if self._postings_mmap is not None:
            try:
                self._postings_mmap.close()
            except Exception:
                pass
            self._postings_mmap = None
        if self._lookup_fd >= 0:
            try:
                os.close(self._lookup_fd)
            except OSError:
                pass
            self._lookup_fd = -1
        if self._postings_fd >= 0:
            try:
                os.close(self._postings_fd)
            except OSError:
                pass
            self._postings_fd = -1

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
