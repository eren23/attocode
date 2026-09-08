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

    def refresh(self, service):
        from attocode_intel._internal.integrations.context.codebase_context import (
            SKIP_EXTENSIONS,
            SKIP_FILENAMES,
        )

        ignore = IgnoreManager(self.root)
        manifest = {}
        for directory, dirs, files in os.walk(self.root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and not ignore.is_ignored(
                    os.path.relpath(os.path.join(directory, d), self.root) + "/"
                )
            ]
            for name in files:
                path = Path(directory) / name
                rel = path.relative_to(self.root).as_posix()
                if (
                    name.startswith(".")
                    or name in SKIP_FILENAMES
                    or path.suffix in SKIP_EXTENSIONS
                    or ignore.is_ignored(rel)
                ):
                    continue
                try:
                    stat = path.stat()
                    if stat.st_size <= 1_000_000:
                        manifest[rel] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                except OSError:
                    continue
        previous, self.manifest = self.manifest, manifest
        if previous is None or service._ast_service is None:
            return
        changed = {
            p for p in previous.keys() | manifest.keys() if previous.get(p) != manifest.get(p)
        }
        if not changed:
            return
        from attocode_intel.request_context import current_request
        request = current_request.get()
        if request and (precision := request.stores.get("precision")):
            precision.invalidate(changed)
        ast = service._ast_service
        ast.stop_hydration()
        if previous.keys() != manifest.keys():
            ast._context_mgr.discover_files()
        for path in changed:
            ast.notify_file_changed(path)
            if service._semantic_search:
                service._semantic_search.invalidate_file(str(Path(self.root) / path))
                service._semantic_search._kw_index_built = False
        graph = ast._context_mgr.dependency_graph
        if graph:
            ast._index.file_dependencies.clear()
            ast._index.file_dependents.clear()
            for source, targets in graph.forward.items():
                for target in targets:
                    ast._index.add_file_dependency(source, target)
        if ast._hydration_state and ast._hydration_state.phase != "ready":
            ast.start_hydration()


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
