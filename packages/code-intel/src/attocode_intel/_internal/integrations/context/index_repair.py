"""Repair a complete structural snapshot after filesystem changes."""

from __future__ import annotations

import re
from pathlib import Path

from .codebase_context import build_dependency_graph
from .cross_references import CrossRefIndex


def changed_paths(before: dict, after: dict) -> set[str]:
    old, new = before["files"], after["files"]
    return {path for path in old.keys() | new.keys() if old.get(path) != new.get(path)}


def repair_index(service, asts: dict, identity: dict, changed: set[str]) -> dict:
    """Keep unaffected references; rebuild graph resolution from current ASTs.

    A definition added or removed can affect calls in unchanged source files.
    Shortlist those files using changed symbol names before extracting their
    references again. All definitions exist before any reference extraction.
    """
    old = service._index
    new = CrossRefIndex()
    for path, ast in asts.items():
        service._index_definitions(path, ast, index=new)

    names = {name.rsplit(".", 1)[-1] for name in old.definitions.keys() ^ new.definitions.keys()}
    affected = changed & asts.keys()
    if names:
        # Broad refactors fall back to complete reference extraction. Small
        # edits scan text once without parsing every call site again.
        pattern = re.compile("|".join(re.escape(name) for name in sorted(names))) if len(names) <= 128 else None
        for path in asts.keys() - affected:
            if pattern is None or pattern.search(
                (Path(service.root_dir) / path).read_text(encoding="utf-8", errors="replace")
            ):
                affected.add(path)

    for refs in old.references.values():
        for ref in refs:
            if ref.file_path in asts and ref.file_path not in affected:
                new.add_reference(ref)
    for path in sorted(affected):
        service._index_references(path, asts[path], index=new)

    graph = build_dependency_graph(service._context_mgr._files, service.root_dir, ast_cache=asts)
    for source, targets in graph.forward.items():
        for target in targets:
            new.add_file_dependency(source, target)
    if service._snapshot_identity() != identity:
        raise ValueError("Workspace changed during index repair; retry")

    # Invalidate before the first write: a crash cannot bless a partial update.
    store = service._store
    store.set_meta("structural_snapshot_v1", "")
    removed = {row.path for row in store.get_all_files()} - asts.keys()
    for path in sorted(removed):
        store.remove_file(path)
    store.save_files_batch([
        service._build_stored_file(path, asts[path], identity["files"][path][0] / 1e9)
        for path in sorted(affected)
    ])
    new.set_store(store)
    new.persist_files(affected)

    service._index = new
    service._ast_cache = asts
    service._reference_indexed_files = set(asts)
    service._context_mgr._dep_graph = graph
    service._context_mgr._ast_cache = dict(asts)
    service._context_mgr._repo_map = None
    service._snapshot_start = identity
    state = service._hydration_state
    state.total_files = state.parsed_files = state.reference_indexed_files = len(asts)
    state.dep_graph_files = len(graph.forward)
    state.phase = "ready"
    if not service._save_snapshot():
        raise ValueError("Workspace changed before index repair completed; retry")
    store.record_scan_time()
    return {
        "changed_files": len(changed),
        "removed_files": len(removed),
        "reindexed_reference_files": len(affected),
        "reused_reference_files": len(asts) - len(affected),
    }
