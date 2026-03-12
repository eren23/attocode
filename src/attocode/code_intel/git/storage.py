"""Clone storage management — disk usage tracking and LRU eviction."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class CloneStorageManager:
    """Manages disk usage for git clone storage.

    Tracks total usage and evicts least-recently-used repos when
    the configured maximum is exceeded.
    """

    def __init__(self, clone_dir: str, max_gb: float = 50.0) -> None:
        self._clone_dir = Path(clone_dir)
        self._max_bytes = int(max_gb * 1024 * 1024 * 1024)
        self._clone_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def total_usage(self) -> int:
        """Calculate total disk usage of all clones in bytes."""
        total = 0
        if not self._clone_dir.exists():
            return 0
        for entry in self._clone_dir.iterdir():
            if entry.is_dir():
                for dirpath, _, filenames in os.walk(entry):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if os.path.isfile(fp):
                            total += os.path.getsize(fp)
        return total

    def has_space(self, needed_bytes: int = 0) -> bool:
        """Check if there's enough space for an additional clone."""
        return (self.total_usage() + needed_bytes) < self._max_bytes

    def evict_lru(self, needed_bytes: int = 0) -> list[str]:
        """Evict least-recently-accessed repos until space is available.

        Returns list of evicted repo directory names.
        """
        if self.has_space(needed_bytes):
            return []

        evicted = []
        # Sort by access time (oldest first)
        entries = []
        for entry in self._clone_dir.iterdir():
            if entry.is_dir():
                try:
                    atime = entry.stat().st_atime
                    entries.append((atime, entry))
                except OSError:
                    continue

        entries.sort(key=lambda x: x[0])

        for _, entry in entries:
            if self.has_space(needed_bytes):
                break
            logger.info("Evicting clone: %s", entry.name)
            shutil.rmtree(entry, ignore_errors=True)
            evicted.append(entry.name)

        return evicted

    def get_repo_usage(self, repo_dir_name: str) -> int:
        """Get disk usage for a specific repo clone."""
        path = self._clone_dir / repo_dir_name
        if not path.exists():
            return 0
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        return total

    def stats(self) -> dict:
        """Get storage statistics."""
        usage = self.total_usage()
        return {
            "total_bytes": usage,
            "max_bytes": self._max_bytes,
            "usage_pct": round(usage / self._max_bytes * 100, 1) if self._max_bytes > 0 else 0,
            "clone_count": sum(1 for e in self._clone_dir.iterdir() if e.is_dir()) if self._clone_dir.exists() else 0,
        }
