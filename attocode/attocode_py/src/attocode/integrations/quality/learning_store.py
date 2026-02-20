"""Learning store for persisting agent learnings.

Stores patterns, workarounds, antipatterns, and best practices
discovered during agent operation, with FTS search for retrieval.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class LearningStatus(StrEnum):
    """Status of a learning."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class LearningType(StrEnum):
    """Type of learning."""

    PATTERN = "pattern"
    WORKAROUND = "workaround"
    ANTIPATTERN = "antipattern"
    BEST_PRACTICE = "best_practice"
    GOTCHA = "gotcha"


@dataclass
class Learning:
    """A stored learning entry."""

    id: str
    created_at: float
    updated_at: float
    type: LearningType
    status: LearningStatus
    description: str
    details: str = ""
    categories: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    apply_count: int = 0
    help_count: int = 0
    confidence: float = 0.5
    source_failure_ids: list[str] = field(default_factory=list)
    user_notes: str | None = None


@dataclass
class LearningProposal:
    """Proposal for a new learning."""

    type: LearningType
    description: str
    details: str = ""
    categories: list[str] | None = None
    actions: list[str] | None = None
    keywords: list[str] | None = None
    source_failures: list[str] | None = None
    confidence: float = 0.5


@dataclass
class LearningStoreConfig:
    """Configuration for the learning store."""

    db_path: str = ".agent/learnings.db"
    require_validation: bool = True
    auto_validate_threshold: float = 0.9
    max_learnings: int = 500
    in_memory: bool = False


LearningEventListener = Callable[[str, dict[str, Any]], None]

# Stop words for keyword extraction
_STOP_WORDS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must", "need", "this",
    "that", "these", "those", "with", "from", "into", "upon", "about",
    "for", "and", "but", "not", "nor", "yet", "also", "than", "then",
    "when", "while", "where", "which", "what", "who", "whom", "how",
])


class LearningStore:
    """SQLite-backed store for agent learnings.

    Supports FTS5 search, confidence tracking, and
    automatic eviction when max capacity is reached.
    """

    def __init__(self, config: LearningStoreConfig | None = None) -> None:
        self._config = config or LearningStoreConfig()
        self._listeners: list[LearningEventListener] = []

        if self._config.in_memory:
            self._db = sqlite3.connect(":memory:")
        else:
            self._db = sqlite3.connect(self._config.db_path)

        self._db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS learnings (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                description TEXT NOT NULL,
                details TEXT DEFAULT '',
                categories TEXT DEFAULT '[]',
                actions TEXT DEFAULT '[]',
                keywords TEXT DEFAULT '[]',
                apply_count INTEGER DEFAULT 0,
                help_count INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                source_failure_ids TEXT DEFAULT '[]',
                user_notes TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_learnings_status ON learnings(status);
            CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type);
            CREATE INDEX IF NOT EXISTS idx_learnings_confidence ON learnings(confidence);
        """)
        # FTS5 table (may fail if not available)
        try:
            self._db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts
                USING fts5(id, description, details, keywords, actions)
            """)
            self._has_fts = True
        except sqlite3.OperationalError:
            self._has_fts = False

    def propose_learning(self, proposal: LearningProposal) -> Learning:
        """Propose a new learning."""
        now = time.time()
        learning_id = f"learn-{uuid.uuid4().hex[:8]}"

        # Auto-extract keywords if not provided
        keywords = proposal.keywords or _extract_keywords(proposal.description)

        # Determine initial status
        if (
            not self._config.require_validation
            or proposal.confidence >= self._config.auto_validate_threshold
        ):
            status = LearningStatus.VALIDATED
        else:
            status = LearningStatus.PROPOSED

        learning = Learning(
            id=learning_id,
            created_at=now,
            updated_at=now,
            type=proposal.type,
            status=status,
            description=proposal.description,
            details=proposal.details,
            categories=proposal.categories or [],
            actions=proposal.actions or [],
            keywords=keywords,
            confidence=proposal.confidence,
            source_failure_ids=proposal.source_failures or [],
        )

        self._save_learning(learning)
        self._enforce_max_learnings()

        event = "learning.validated" if status == LearningStatus.VALIDATED else "learning.proposed"
        self._emit(event, {"learning_id": learning_id, "type": proposal.type})

        return learning

    def validate_learning(self, learning_id: str, approved: bool, reason: str | None = None) -> bool:
        """Validate or reject a proposed learning."""
        learning = self.get_learning(learning_id)
        if learning is None or learning.status != LearningStatus.PROPOSED:
            return False

        if approved:
            learning.status = LearningStatus.VALIDATED
            self._emit("learning.validated", {"learning_id": learning_id})
        else:
            learning.status = LearningStatus.REJECTED
            if reason:
                learning.user_notes = reason
            self._emit("learning.rejected", {"learning_id": learning_id})

        learning.updated_at = time.time()
        self._save_learning(learning)
        return True

    def record_apply(self, learning_id: str, context: str = "") -> bool:
        """Record that a learning was applied."""
        learning = self.get_learning(learning_id)
        if learning is None:
            return False

        learning.apply_count += 1
        learning.updated_at = time.time()
        self._save_learning(learning)
        self._emit("learning.applied", {"learning_id": learning_id, "context": context})
        return True

    def record_helped(self, learning_id: str) -> bool:
        """Record that a learning helped. Boosts confidence."""
        learning = self.get_learning(learning_id)
        if learning is None:
            return False

        learning.help_count += 1
        learning.confidence = min(1.0, learning.confidence + 0.05)
        learning.updated_at = time.time()
        self._save_learning(learning)
        self._emit("learning.helped", {"learning_id": learning_id})
        return True

    def get_learning(self, learning_id: str) -> Learning | None:
        """Get a learning by ID."""
        row = self._db.execute(
            "SELECT * FROM learnings WHERE id = ?", (learning_id,)
        ).fetchone()
        return _row_to_learning(row) if row else None

    def get_validated_learnings(self) -> list[Learning]:
        """Get all validated learnings, ordered by confidence."""
        rows = self._db.execute(
            "SELECT * FROM learnings WHERE status = ? ORDER BY confidence DESC",
            (LearningStatus.VALIDATED,),
        ).fetchall()
        return [_row_to_learning(r) for r in rows]

    def get_pending_learnings(self) -> list[Learning]:
        """Get all pending learnings."""
        rows = self._db.execute(
            "SELECT * FROM learnings WHERE status = ? ORDER BY created_at DESC",
            (LearningStatus.PROPOSED,),
        ).fetchall()
        return [_row_to_learning(r) for r in rows]

    def retrieve_relevant(self, query: str, limit: int = 10) -> list[Learning]:
        """Retrieve learnings relevant to a query using FTS."""
        if self._has_fts and query.strip():
            sanitized = _sanitize_fts_query(query)
            if sanitized:
                try:
                    rows = self._db.execute(
                        """SELECT l.* FROM learnings l
                        JOIN learnings_fts fts ON l.id = fts.id
                        WHERE learnings_fts MATCH ?
                        AND l.status = ?
                        LIMIT ?""",
                        (sanitized, LearningStatus.VALIDATED, limit),
                    ).fetchall()
                    if rows:
                        return [_row_to_learning(r) for r in rows]
                except sqlite3.OperationalError:
                    pass

        # Fallback to LIKE search
        like_query = f"%{query}%"
        rows = self._db.execute(
            """SELECT * FROM learnings
            WHERE status = ?
            AND (description LIKE ? OR details LIKE ? OR keywords LIKE ?)
            ORDER BY confidence DESC LIMIT ?""",
            (LearningStatus.VALIDATED, like_query, like_query, like_query, limit),
        ).fetchall()
        return [_row_to_learning(r) for r in rows]

    def retrieve_by_category(self, category: str, limit: int = 10) -> list[Learning]:
        """Retrieve learnings by failure category."""
        like = f'%"{category}"%'
        rows = self._db.execute(
            """SELECT * FROM learnings WHERE status = ?
            AND categories LIKE ? ORDER BY confidence DESC LIMIT ?""",
            (LearningStatus.VALIDATED, like, limit),
        ).fetchall()
        return [_row_to_learning(r) for r in rows]

    def retrieve_by_action(self, action: str, limit: int = 10) -> list[Learning]:
        """Retrieve learnings by action/tool name."""
        like = f'%"{action}"%'
        rows = self._db.execute(
            """SELECT * FROM learnings WHERE status = ?
            AND actions LIKE ? ORDER BY confidence DESC LIMIT ?""",
            (LearningStatus.VALIDATED, like, limit),
        ).fetchall()
        return [_row_to_learning(r) for r in rows]

    def get_learning_context(
        self,
        query: str | None = None,
        categories: list[str] | None = None,
        actions: list[str] | None = None,
        max_learnings: int = 10,
    ) -> str:
        """Get formatted learning context for LLM injection."""
        learnings: dict[str, Learning] = {}

        if query:
            for l in self.retrieve_relevant(query, max_learnings):
                learnings[l.id] = l

        if categories:
            for cat in categories:
                for l in self.retrieve_by_category(cat, 5):
                    learnings[l.id] = l

        if actions:
            for act in actions:
                for l in self.retrieve_by_action(act, 5):
                    learnings[l.id] = l

        if not learnings:
            return ""

        items = sorted(learnings.values(), key=lambda l: l.confidence, reverse=True)
        return format_learnings_context(items[:max_learnings])

    def archive_learning(self, learning_id: str) -> bool:
        """Archive a learning."""
        learning = self.get_learning(learning_id)
        if learning is None:
            return False
        learning.status = LearningStatus.ARCHIVED
        learning.updated_at = time.time()
        self._save_learning(learning)
        return True

    def delete_learning(self, learning_id: str) -> bool:
        """Delete a learning permanently."""
        result = self._db.execute("DELETE FROM learnings WHERE id = ?", (learning_id,))
        self._db.commit()
        if self._has_fts:
            try:
                self._db.execute("DELETE FROM learnings_fts WHERE id = ?", (learning_id,))
                self._db.commit()
            except sqlite3.OperationalError:
                pass
        return result.rowcount > 0

    def get_stats(self) -> dict[str, Any]:
        """Get store statistics."""
        rows = self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM learnings GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["cnt"] for r in rows}

        rows = self._db.execute(
            "SELECT type, COUNT(*) as cnt FROM learnings GROUP BY type"
        ).fetchall()
        by_type = {r["type"]: r["cnt"] for r in rows}

        total = sum(by_status.values())

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
        }

    def on(self, listener: LearningEventListener) -> Callable[[], None]:
        """Subscribe to store events. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def close(self) -> None:
        """Close the database."""
        self._db.close()

    def _save_learning(self, learning: Learning) -> None:
        """Save a learning to the database."""
        self._db.execute(
            """INSERT OR REPLACE INTO learnings
            (id, created_at, updated_at, type, status, description, details,
             categories, actions, keywords, apply_count, help_count,
             confidence, source_failure_ids, user_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                learning.id,
                learning.created_at,
                learning.updated_at,
                learning.type,
                learning.status,
                learning.description,
                learning.details,
                json.dumps(learning.categories),
                json.dumps(learning.actions),
                json.dumps(learning.keywords),
                learning.apply_count,
                learning.help_count,
                learning.confidence,
                json.dumps(learning.source_failure_ids),
                learning.user_notes,
            ),
        )
        self._db.commit()

        # Update FTS
        if self._has_fts:
            try:
                self._db.execute("DELETE FROM learnings_fts WHERE id = ?", (learning.id,))
                self._db.execute(
                    "INSERT INTO learnings_fts (id, description, details, keywords, actions) VALUES (?, ?, ?, ?, ?)",
                    (
                        learning.id,
                        learning.description,
                        learning.details,
                        " ".join(learning.keywords),
                        " ".join(learning.actions),
                    ),
                )
                self._db.commit()
            except sqlite3.OperationalError:
                pass

    def _enforce_max_learnings(self) -> None:
        """Evict oldest/lowest-confidence learnings if over limit."""
        count = self._db.execute("SELECT COUNT(*) as cnt FROM learnings").fetchone()["cnt"]
        if count <= self._config.max_learnings:
            return

        excess = count - self._config.max_learnings
        # First evict rejected/archived
        self._db.execute(
            """DELETE FROM learnings WHERE id IN (
                SELECT id FROM learnings
                WHERE status IN ('rejected', 'archived')
                ORDER BY created_at ASC LIMIT ?
            )""",
            (excess,),
        )
        self._db.commit()

        # If still over, evict lowest confidence
        count = self._db.execute("SELECT COUNT(*) as cnt FROM learnings").fetchone()["cnt"]
        if count > self._config.max_learnings:
            excess = count - self._config.max_learnings
            self._db.execute(
                """DELETE FROM learnings WHERE id IN (
                    SELECT id FROM learnings
                    ORDER BY confidence ASC, created_at ASC LIMIT ?
                )""",
                (excess,),
            )
            self._db.commit()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Emit an event to listeners."""
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def _row_to_learning(row: sqlite3.Row) -> Learning:
    """Convert a database row to a Learning."""
    return Learning(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        type=LearningType(row["type"]),
        status=LearningStatus(row["status"]),
        description=row["description"],
        details=row["details"] or "",
        categories=json.loads(row["categories"]) if row["categories"] else [],
        actions=json.loads(row["actions"]) if row["actions"] else [],
        keywords=json.loads(row["keywords"]) if row["keywords"] else [],
        apply_count=row["apply_count"],
        help_count=row["help_count"],
        confidence=row["confidence"],
        source_failure_ids=json.loads(row["source_failure_ids"]) if row["source_failure_ids"] else [],
        user_notes=row["user_notes"],
    )


def _extract_keywords(text: str) -> list[str]:
    """Extract keywords from text, filtering stop words."""
    import re

    words = re.split(r"\W+", text.lower())
    keywords = [w for w in words if len(w) > 3 and w not in _STOP_WORDS]
    return list(dict.fromkeys(keywords))[:10]  # Deduplicate, keep order


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query for FTS5."""
    import re

    # Remove special FTS characters
    cleaned = re.sub(r"[\"'(){}*:^~]", " ", query)
    tokens = [t for t in cleaned.split() if len(t) > 1]
    return " OR ".join(tokens)


def format_learnings_context(learnings: list[Learning]) -> str:
    """Format learnings for LLM context injection."""
    if not learnings:
        return ""

    icons = {
        LearningType.PATTERN: "[pattern]",
        LearningType.WORKAROUND: "[workaround]",
        LearningType.ANTIPATTERN: "[antipattern]",
        LearningType.BEST_PRACTICE: "[best_practice]",
        LearningType.GOTCHA: "[gotcha]",
    }

    lines = ["[Previous Learnings]"]
    for l in learnings:
        icon = icons.get(l.type, "")
        conf = f"({l.confidence:.0%})"
        lines.append(f"- {icon} {conf} {l.description}")
        if l.details:
            lines.append(f"  {l.details}")
    return "\n".join(lines)
