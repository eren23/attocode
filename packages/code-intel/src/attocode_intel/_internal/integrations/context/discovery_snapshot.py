"""Immutable discovery handoff, validated before reuse; never a persistent cache."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass

MAX_GUARDS = 100_000


def path_signature(path: str) -> tuple | None:
    """Metadata includes ctime/inode so same-mtime edits and replacements invalidate.

    Links include their resolved target identity; no outside source is read.
    Missing paths are recorded too (notably a not-yet-created .gitignore).
    """
    def fields(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    result = fields(info)
    if stat.S_ISLNK(info.st_mode):
        try:
            target = fields(os.stat(path))
        except (FileNotFoundError, NotADirectoryError):
            target = None
        result += (os.path.realpath(path), target)
    return result


@dataclass(frozen=True)
class DiscoverySnapshot:
    root: str
    ignores: frozenset[str]
    refreshed_at: float
    # Primitive values only, not shared mutable FileInfo objects.
    files: tuple[tuple, ...]
    guards: tuple[tuple[str, tuple | None], ...]

    def valid_for(self, context) -> bool:
        import time

        if (self.root != os.path.abspath(context.root_dir)
                or self.ignores != frozenset(context.ignore_patterns)
                or not 0 <= time.monotonic() - self.refreshed_at < context._staleness_threshold):
            return False
        for path, signature in self.guards:
            context._check_cancelled()
            try:
                if path_signature(path) != signature:
                    return False
            except (OSError, RuntimeError):
                return False
        return True
