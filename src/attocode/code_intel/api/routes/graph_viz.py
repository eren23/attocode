"""Graph visualization endpoint — D3-compatible JSON for force-directed graphs."""

from __future__ import annotations

import logging
from collections import deque

from fastapi import APIRouter, Depends

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import get_service_or_404

router = APIRouter(
    prefix="/api/v2/projects/{project_id}/graph-viz",
    tags=["graph-viz"],
    dependencies=[Depends(verify_auth)],
)
logger = logging.getLogger(__name__)


@router.get("")
async def get_graph_data(
    project_id: str,
    root: str = "",
    depth: int = 3,
    max_nodes: int = 100,
) -> dict:
    """Return graph data in D3 force-directed compatible format.

    If *root* is provided, performs BFS from that file up to *depth* hops.
    Otherwise returns the top *max_nodes* files ranked by importance.
    Community detection data is included when available.
    """
    depth = min(max(depth, 1), 6)
    max_nodes = min(max(max_nodes, 10), 500)

    svc = await get_service_or_404(project_id)

    # Get underlying data structures
    ast_svc = svc._get_ast_service()
    ctx = svc._get_context_mgr()
    idx = ast_svc._index
    files_list = ctx._files  # list[FileInfo]

    # Build lookup: relative_path -> FileInfo
    file_info: dict[str, object] = {}
    for fi in files_list:
        file_info[fi.relative_path] = fi

    # Determine which files to include
    selected_files: list[str]

    if root:
        # BFS from root up to depth hops (both directions)
        rel_root = ast_svc._to_rel(root)
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(rel_root, 0)])
        order: list[str] = []

        while queue and len(order) < max_nodes:
            current, d = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            order.append(current)
            if d < depth:
                # Expand both directions
                for neighbor in sorted(ast_svc.get_dependencies(current)):
                    if neighbor not in visited:
                        queue.append((neighbor, d + 1))
                for neighbor in sorted(ast_svc.get_dependents(current)):
                    if neighbor not in visited:
                        queue.append((neighbor, d + 1))

        selected_files = order
    else:
        # Top files by importance
        ranked = sorted(files_list, key=lambda f: f.importance, reverse=True)
        # Only include files that participate in the dependency graph
        graph_files: set[str] = set()
        graph_files.update(idx.file_dependencies.keys())
        graph_files.update(idx.file_dependents.keys())
        for deps in idx.file_dependencies.values():
            graph_files.update(deps)

        selected_files = []
        for fi in ranked:
            if fi.relative_path in graph_files:
                selected_files.append(fi.relative_path)
            if len(selected_files) >= max_nodes:
                break

        # If we still have room, add remaining important files
        if len(selected_files) < max_nodes:
            seen = set(selected_files)
            for fi in ranked:
                if fi.relative_path not in seen:
                    selected_files.append(fi.relative_path)
                    seen.add(fi.relative_path)
                if len(selected_files) >= max_nodes:
                    break

    selected_set = set(selected_files)

    # --- Community detection ---
    # Build file -> community_id mapping
    file_to_community: dict[str, int] = {}
    communities_list: list[dict] = []
    try:
        cd = svc.community_detection_data(min_community_size=2, max_communities=30)
        for comm in cd.get("communities", []):
            cid = comm["id"]
            comm_files_in_view = [f for f in comm["files"] if f in selected_set]
            if comm_files_in_view:
                communities_list.append({
                    "id": cid,
                    "files": comm_files_in_view,
                    "size": len(comm_files_in_view),
                })
            for f in comm["files"]:
                file_to_community[f] = cid
    except Exception:
        logger.debug("Community detection unavailable, skipping", exc_info=True)

    # --- Build nodes ---
    nodes: list[dict] = []
    for path in selected_files:
        fi = file_info.get(path)
        node: dict = {
            "id": path,
            "language": fi.language if fi else "",
            "importance": round(fi.importance, 3) if fi else 0.0,
            "lines": fi.line_count if fi else 0,
            "group": file_to_community.get(path, -1),
        }
        nodes.append(node)

    # --- Build links ---
    links: list[dict] = []
    for src in selected_files:
        for tgt in idx.file_dependencies.get(src, set()):
            if tgt in selected_set:
                links.append({
                    "source": src,
                    "target": tgt,
                    "type": "imports",
                })

    return {
        "nodes": nodes,
        "links": links,
        "communities": communities_list,
    }
