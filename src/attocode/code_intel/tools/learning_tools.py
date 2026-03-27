"""Learning / memory tools for the code-intel MCP server.

Tools: recall, record_learning, learning_feedback, list_learnings.
"""

from __future__ import annotations

import logging
import threading

from attocode.code_intel._shared import (
    _get_project_dir,
    mcp,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy memory store singleton
# ---------------------------------------------------------------------------

_memory_store_lock = threading.Lock()


def _get_memory_store():
    """Lazily initialize and return the MemoryStore singleton (thread-safe).

    Uses ``server._memory_store`` as the authoritative location so tests
    can reset it by setting ``srv._memory_store = None``.
    """
    import attocode.code_intel.server as _srv

    if _srv._memory_store is not None:
        return _srv._memory_store
    # server._memory_store is None — create a fresh instance
    with _memory_store_lock:
        # Double-check after acquiring lock
        if _srv._memory_store is not None:
            return _srv._memory_store
        from attocode.integrations.context.memory_store import MemoryStore

        store = MemoryStore(_get_project_dir())
        _srv._memory_store = store
        return store


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def recall(query: str, scope: str = "", max_results: int = 10) -> str:
    """Retrieve relevant project learnings (patterns, conventions, gotchas).

    Call this at the start of a task or when working in unfamiliar code.
    Scope narrows results to a directory subtree (e.g. 'src/api/').

    Args:
        query: Natural language description of what you're working on.
        scope: Optional directory scope to filter learnings.
        max_results: Maximum number of learnings to return.
    """
    store = _get_memory_store()
    results = store.recall(query, scope=scope, max_results=max_results)
    if not results:
        return "No relevant learnings found for this project."

    lines = [f"## Project Learnings ({len(results)} relevant)\n"]
    for r in results:
        lines.append(f"- **[{r['type']}]** (confidence: {r['confidence']:.0%}, id: {r['id']})")
        lines.append(f"  {r['description']}")
        if r["details"]:
            lines.append(f"  _{r['details']}_")

    # Increment apply_count for returned learnings (best-effort)
    for r in results:
        try:
            store.record_applied(r["id"])
        except Exception:
            logger.debug("Failed to record_applied for learning %d", r["id"])

    return "\n".join(lines)


@mcp.tool()
def record_learning(
    type: str,  # noqa: A002
    description: str,
    details: str = "",
    scope: str = "",
    confidence: float = 0.7,
) -> str:
    """Record a project learning for future recall.

    Call this when you discover something important about the codebase:
    patterns, conventions, gotchas, workarounds, or anti-patterns.

    Args:
        type: One of 'pattern', 'antipattern', 'workaround', 'convention', 'gotcha'.
        description: Short description (1-2 sentences).
        details: Optional longer explanation or example.
        scope: Optional directory scope (e.g. 'src/api/').
        confidence: Initial confidence 0.0-1.0 (default 0.7).
    """
    store = _get_memory_store()
    try:
        learning_id = store.add(
            type=type, description=description,
            details=details, scope=scope, confidence=confidence,
        )
    except ValueError as e:
        return f"Error: {e}"
    return f"Recorded learning #{learning_id}: [{type}] {description}"


@mcp.tool()
def learning_feedback(learning_id: int, helpful: bool) -> str:
    """Mark a previously recalled learning as helpful or unhelpful.

    Call this after a recalled learning influenced your work, to improve
    future recall quality. Unhelpful learnings are eventually auto-archived.

    Args:
        learning_id: The ID from a previous recall result.
        helpful: Whether the learning was actually useful.
    """
    store = _get_memory_store()
    store.record_feedback(learning_id, helpful)
    action = "boosted" if helpful else "reduced"
    return f"Feedback recorded — confidence {action} for learning #{learning_id}."


@mcp.tool()
def list_learnings(
    status: str = "active",
    type: str = "",  # noqa: A002
    scope: str = "",
) -> str:
    """List all stored project learnings.

    Args:
        status: Filter by status: 'active' or 'archived'.
        type: Optional filter by type (pattern/antipattern/workaround/convention/gotcha).
        scope: Optional filter by directory scope.
    """
    store = _get_memory_store()
    results = store.list_all(status=status, type=type or None)
    if scope:
        results = [r for r in results if r["scope"].startswith(scope) or r["scope"] == ""]
    if not results:
        return "No learnings found matching the filters."

    lines = [f"## Learnings ({len(results)} total)\n"]
    lines.append("| ID | Type | Description | Confidence | Applied | Scope |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        desc = r["description"][:60] + ("..." if len(r["description"]) > 60 else "")
        lines.append(
            f"| {r['id']} | {r['type']} | {desc} "
            f"| {r['confidence']:.0%} | {r['apply_count']}x "
            f"| {r['scope'] or '(global)'} |"
        )
    return "\n".join(lines)
