"""Architecture Decision Record (ADR) tools for the code-intel MCP server.

Tools: record_adr, list_adrs, get_adr, update_adr_status.

Local mode stores ADRs in a SQLite database at ``.attocode/adrs.db``,
following the same lazy-singleton pattern as ``learning_tools.py``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from attocode.code_intel._shared import (
    _get_project_dir,
    _get_remote_service,
    mcp,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid statuses and transitions
# ---------------------------------------------------------------------------

VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded"}

# Allowed status transitions: current -> set of valid next statuses
_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"accepted", "deprecated", "superseded"},
    "accepted": {"deprecated", "superseded"},
    "deprecated": {"superseded"},
    "superseded": set(),  # terminal
}

# ---------------------------------------------------------------------------
# ADRStore — SQLite-backed persistence
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ADRStore:
    """SQLite-backed persistent store for Architecture Decision Records.

    Stores ADRs with auto-incrementing numbers, status tracking,
    JSON-encoded related_files and tags, and LIKE-based search.
    """

    project_dir: str
    db_path: str = field(default="", repr=False)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.db_path:
            store_dir = os.path.join(self.project_dir, ".attocode")
            os.makedirs(store_dir, exist_ok=True)
            self.db_path = os.path.join(store_dir, "adrs.db")

        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if closed."""
        if self._conn is None:
            raise RuntimeError("ADRStore connection is closed")
        return self._conn

    def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS adrs (
                number INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                context TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL DEFAULT '',
                consequences TEXT NOT NULL DEFAULT '',
                related_files TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                author TEXT NOT NULL DEFAULT '',
                superseded_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (superseded_by) REFERENCES adrs(number)
            );

            CREATE INDEX IF NOT EXISTS idx_adrs_status ON adrs(status);
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str = "",
        related_files: list[str] | None = None,
        tags: list[str] | None = None,
        author: str = "",
    ) -> int:
        """Record a new ADR. Returns the ADR number."""
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        cursor = conn.execute(
            """INSERT INTO adrs
               (title, status, context, decision, consequences,
                related_files, tags, author, created_at, updated_at)
               VALUES (?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                context,
                decision,
                consequences,
                json.dumps(related_files or []),
                json.dumps(tags or []),
                author,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_status(
        self,
        number: int,
        new_status: str,
        superseded_by: int | None = None,
    ) -> None:
        """Update an ADR's status with transition validation.

        Raises:
            ValueError: If the status or transition is invalid.
            KeyError: If the ADR number doesn't exist.
        """
        conn = self._get_conn()
        new_status = new_status.lower()

        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{new_status}'. Must be one of: {sorted(VALID_STATUSES)}"
            )

        # Fetch current status
        row = conn.execute(
            "SELECT status FROM adrs WHERE number = ?", (number,)
        ).fetchone()
        if row is None:
            raise KeyError(f"ADR #{number} not found")

        current_status = row[0]
        allowed = _STATUS_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition ADR #{number} from '{current_status}' to "
                f"'{new_status}'. Allowed transitions: {sorted(allowed) if allowed else 'none (terminal)'}"
            )

        if new_status == "superseded" and superseded_by is None:
            raise ValueError(
                "Must provide 'superseded_by' ADR number when setting status to 'superseded'"
            )

        # Validate superseded_by target exists if provided
        if superseded_by is not None:
            target = conn.execute(
                "SELECT number FROM adrs WHERE number = ?", (superseded_by,)
            ).fetchone()
            if target is None:
                raise ValueError(f"Superseding ADR #{superseded_by} not found")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            """UPDATE adrs
               SET status = ?, superseded_by = ?, updated_at = ?
               WHERE number = ?""",
            (new_status, superseded_by, now, number),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, number: int) -> dict | None:
        """Get a single ADR by number. Returns None if not found."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT number, title, status, context, decision, consequences,
                      related_files, tags, author, superseded_by,
                      created_at, updated_at
               FROM adrs WHERE number = ?""",
            (number,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_all(
        self,
        status: str = "",
        tag: str = "",
        search: str = "",
    ) -> list[dict]:
        """List ADRs with optional filtering.

        Args:
            status: Filter by status (proposed/accepted/deprecated/superseded).
            tag: Filter by tag (matches any tag in the JSON array).
            search: Search term matched via LIKE on title + context + decision.
        """
        conn = self._get_conn()

        query = (
            "SELECT number, title, status, context, decision, consequences,"
            " related_files, tags, author, superseded_by,"
            " created_at, updated_at"
            " FROM adrs WHERE 1=1"
        )
        params: list[str] = []

        if status:
            query += " AND status = ?"
            params.append(status.lower())

        if search:
            like_term = f"%{search}%"
            query += " AND (title LIKE ? OR context LIKE ? OR decision LIKE ?)"
            params.extend([like_term, like_term, like_term])

        query += " ORDER BY number DESC"

        rows = conn.execute(query, params).fetchall()
        results = [self._row_to_dict(row) for row in rows]

        # Post-filter by tag (JSON array stored as text)
        if tag:
            tag_lower = tag.lower()
            results = [
                r for r in results
                if any(t.lower() == tag_lower for t in r["tags"])
            ]

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: tuple) -> dict:
        """Convert a row tuple to a dict."""
        return {
            "number": row[0],
            "title": row[1],
            "status": row[2],
            "context": row[3],
            "decision": row[4],
            "consequences": row[5],
            "related_files": json.loads(row[6]) if row[6] else [],
            "tags": json.loads(row[7]) if row[7] else [],
            "author": row[8],
            "superseded_by": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Lazy ADR store singleton
# ---------------------------------------------------------------------------

_adr_store_lock = threading.Lock()
_adr_store: ADRStore | None = None


def _get_adr_store() -> ADRStore:
    """Lazily initialize and return the ADRStore singleton (thread-safe)."""
    global _adr_store

    if _adr_store is not None:
        return _adr_store

    with _adr_store_lock:
        # Double-check after acquiring lock
        if _adr_store is not None:
            return _adr_store

        store = ADRStore(_get_project_dir())
        _adr_store = store
        return store


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def record_adr(
    title: str,
    context: str,
    decision: str,
    consequences: str = "",
    related_files: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Record an architecture decision.

    Call this when making significant design choices that affect the codebase
    structure, technology selections, or cross-cutting concerns. ADRs create
    a persistent record of *why* decisions were made.

    Args:
        title: Short title for the decision (e.g. "Use SQLite for local storage").
        context: What is the issue or problem motivating this decision?
        decision: What is the change being proposed or decided?
        consequences: What are the trade-offs and implications? (optional)
        related_files: List of file paths affected by this decision (optional).
        tags: List of tags for categorization, e.g. ["database", "performance"] (optional).
    """
    remote = _get_remote_service()
    if remote is not None:
        return remote.record_adr(
            title=title,
            context=context,
            decision=decision,
            consequences=consequences,
            related_files=related_files,
            tags=tags,
        )

    store = _get_adr_store()
    try:
        adr_number = store.add(
            title=title,
            context=context,
            decision=decision,
            consequences=consequences,
            related_files=related_files,
            tags=tags,
        )
    except Exception as e:
        return f"Error recording ADR: {e}"

    return (
        f"Recorded ADR #{adr_number}: {title}\n"
        f"Status: proposed\n"
        f"Use `update_adr_status` to accept, deprecate, or supersede this decision."
    )


@mcp.tool()
def list_adrs(status: str = "", tag: str = "", search: str = "") -> str:
    """List architecture decision records.

    Browse recorded ADRs with optional filtering by status, tag, or search text.

    Args:
        status: Filter by status: proposed, accepted, deprecated, superseded.
        tag: Filter by tag (e.g. "database").
        search: Free text search across title, context, and decision.
    """
    remote = _get_remote_service()
    if remote is not None:
        return remote.list_adrs(status=status, tag=tag, search=search)

    store = _get_adr_store()
    results = store.list_all(status=status, tag=tag, search=search)

    if not results:
        filters = []
        if status:
            filters.append(f"status={status}")
        if tag:
            filters.append(f"tag={tag}")
        if search:
            filters.append(f"search={search}")
        filter_desc = f" (filters: {', '.join(filters)})" if filters else ""
        return f"No ADRs found{filter_desc}."

    lines = [f"## Architecture Decision Records ({len(results)} total)\n"]
    lines.append("| # | Title | Status | Tags | Created |")
    lines.append("|---|-------|--------|------|---------|")
    for r in results:
        title = r["title"][:50] + ("..." if len(r["title"]) > 50 else "")
        tags_str = ", ".join(r["tags"]) if r["tags"] else "-"
        created = r["created_at"][:10]  # YYYY-MM-DD
        superseded_note = f" (by #{r['superseded_by']})" if r["superseded_by"] else ""
        lines.append(
            f"| {r['number']} | {title} | {r['status']}{superseded_note} "
            f"| {tags_str} | {created} |"
        )
    return "\n".join(lines)


@mcp.tool()
def get_adr(number: int) -> str:
    """Get a specific ADR by number.

    Retrieves the full details of an architecture decision record.

    Args:
        number: The ADR number (auto-assigned when recorded).
    """
    remote = _get_remote_service()
    if remote is not None:
        return remote.get_adr(number)

    store = _get_adr_store()
    adr = store.get(number)

    if adr is None:
        return f"ADR #{number} not found."

    lines = [f"# ADR #{adr['number']}: {adr['title']}\n"]
    lines.append(f"**Status:** {adr['status']}")
    if adr["superseded_by"]:
        lines.append(f"**Superseded by:** ADR #{adr['superseded_by']}")
    if adr["author"]:
        lines.append(f"**Author:** {adr['author']}")
    lines.append(f"**Created:** {adr['created_at']}")
    lines.append(f"**Updated:** {adr['updated_at']}")

    if adr["tags"]:
        lines.append(f"**Tags:** {', '.join(adr['tags'])}")

    lines.append(f"\n## Context\n\n{adr['context']}")
    lines.append(f"\n## Decision\n\n{adr['decision']}")

    if adr["consequences"]:
        lines.append(f"\n## Consequences\n\n{adr['consequences']}")

    if adr["related_files"]:
        lines.append("\n## Related Files\n")
        for f in adr["related_files"]:
            lines.append(f"- `{f}`")

    return "\n".join(lines)


@mcp.tool()
def update_adr_status(
    number: int,
    status: str,
    superseded_by: int | None = None,
) -> str:
    """Update an ADR's status.

    Transitions follow a defined lifecycle:
    proposed -> accepted -> deprecated -> superseded.

    When superseding, provide the number of the new ADR that replaces this one.

    Args:
        number: The ADR number to update.
        status: New status: proposed, accepted, deprecated, superseded.
        superseded_by: The ADR number that supersedes this one (required when status is 'superseded').
    """
    remote = _get_remote_service()
    if remote is not None:
        return remote.update_adr_status(
            number=number,
            status=status,
            superseded_by=superseded_by,
        )

    store = _get_adr_store()
    try:
        store.update_status(number, status, superseded_by=superseded_by)
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"

    msg = f"ADR #{number} status updated to '{status}'."
    if superseded_by is not None:
        msg += f" Superseded by ADR #{superseded_by}."
    return msg
