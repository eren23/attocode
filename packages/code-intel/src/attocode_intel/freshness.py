"""Incremental invalidation based on filesystem identity, including import-only edits."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from attocode_intel._internal.integrations.utilities.ignore import IgnoreManager


class FreshnessTracker:
    def __init__(self, root: str):
        self.root = root
        self.manifest = None
        self.generation = 0
        self._ignore = None
        self._ignore_identity = None
        self._eligibility = {}

    def scan_manifest(self):
        """Stat every eligible file, reusing only path-filter decisions.

        No time window or watcher delivery is required for edit detection.
        DirEntry avoids allocating/resolving a Path for each file on each call.
        """
        from attocode_intel._internal.integrations.context.codebase_context import (
            SKIP_EXTENSIONS,
            SKIP_FILENAMES,
        )

        try:
            stat = os.stat(os.path.join(self.root, ".gitignore"))
            ignore_identity = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except OSError:
            ignore_identity = None
        if self._ignore is None or ignore_identity != self._ignore_identity:
            self._ignore = IgnoreManager(self.root)
            self._ignore_identity = ignore_identity
            self._eligibility.clear()
        ignore = self._ignore
        manifest = {}
        eligibility = {}
        pending = [(self.root, "")]
        while pending:
            directory, prefix = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        name = entry.name
                        if name.startswith("."):
                            continue
                        rel = prefix + name
                        try:
                            is_dir = entry.is_dir()
                            key = rel + "/" if is_dir else rel
                            allowed = self._eligibility.get(key)
                            if allowed is None:
                                allowed = (is_dir or (
                                    name not in SKIP_FILENAMES
                                    and os.path.splitext(name)[1].lower() not in SKIP_EXTENSIONS
                                )) and not ignore.is_ignored(key)
                            eligibility[key] = allowed
                            if not allowed:
                                continue
                            if is_dir:
                                if not entry.is_symlink():
                                    pending.append((entry.path, key))
                            else:
                                stat = entry.stat()
                                if stat.st_size <= 1_000_000:
                                    manifest[rel] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                        except OSError:
                            continue
            except OSError:
                continue
        self._eligibility = eligibility
        return manifest

    def refresh(self, service):
        manifest = self.scan_manifest()
        previous = self.manifest
        if previous is None or service._ast_service is None:
            self.manifest = manifest
            return
        changed = {
            p for p in previous.keys() | manifest.keys() if previous.get(p) != manifest.get(p)
        }
        if not changed:
            self.manifest = manifest
            return
        self.generation += 1
        from attocode_intel.request_context import current_request
        request = current_request.get()
        if request and (precision := request.stores.get("precision")):
            precision.invalidate(changed)
        if request:
            request.stores.pop("reference_pages", None)
        ast = service._ast_service
        if not ast.repair_changed_files(expected_manifest=manifest):
            ast.stop_hydration()
            if previous.keys() != manifest.keys():
                ast._context_mgr.discover_files()
            for path in changed:
                if path not in manifest:
                    ast._store.set_meta("structural_snapshot_v1", "")
                    ast._snapshot_start = None
                    ast._index.remove_file(path)
                    ast._ast_cache.pop(path, None)
                    ast._reference_indexed_files.discard(path)
                else:
                    ast.notify_file_changed(path)
            graph = ast._context_mgr.dependency_graph
            if graph:
                ast._index.file_dependencies.clear()
                ast._index.file_dependents.clear()
                for source, targets in graph.forward.items():
                    for target in targets:
                        ast._index.add_file_dependency(source, target)
            if ast._hydration_state and ast._hydration_state.phase != "ready":
                ast.start_hydration()
        for path in changed:
            if service._semantic_search:
                service._semantic_search.invalidate_file(str(Path(self.root) / path))
                service._semantic_search._kw_index_built = False
        self.manifest = manifest


class WorkspaceWatcher:
    """Watch only; refreshes run on the workspace's serial worker."""

    def __init__(self, root, callback, debounce=500):
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, args=(root, callback, debounce), daemon=True, name="intel-watch"
        )
        self.thread.start()

    def _run(self, root, callback, debounce):
        try:
            from watchfiles import watch

            for changes in watch(root, stop_event=self.stop_event, debounce=max(debounce, 50)):
                if any(".attocode" not in Path(path).parts for _, path in changes):
                    callback()
        except Exception:
            logging.getLogger(__name__).warning(
                "File watcher unavailable; per-operation stat checks remain active", exc_info=True
            )

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
