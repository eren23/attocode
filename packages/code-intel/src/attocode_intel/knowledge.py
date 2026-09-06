"""Repository-scoped durable knowledge shared by MCP and HTTP."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid, cast, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from attocode_intel.db.base import Base

KNOWLEDGE_TOOLS = frozenset(
    {
        "recall",
        "record_learning",
        "list_learnings",
        "learning_feedback",
        "record_adr",
        "list_adrs",
        "get_adr",
        "update_adr_status",
        "update_learning",
    }
)


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16), default="learning")
    status: Mapped[str] = mapped_column(String(16), default="active")
    scope: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[str] = mapped_column(String(64), default="")
    anchor_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def anchor_hash(root: str, scope: str) -> str:
    if not scope:
        return ""
    base = Path(root).resolve()
    path = (base / scope).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Knowledge scope must remain inside the selected repository")
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PostgresKnowledge:
    """Session-injected store; every lookup includes the authorized repository ID."""

    def __init__(self, session, context):
        self.session = session
        self.context = context
        self.repo_id = uuid.UUID(context.workspace)

    def statement(self):
        return select(KnowledgeEntry).where(KnowledgeEntry.repo_id == self.repo_id)

    def serialize(self, entry):
        current_hash = anchor_hash(self.context.project_dir, entry.scope)
        anchors = entry.payload.get("file_anchors", {})
        stale = bool(entry.anchor_hash and current_hash != entry.anchor_hash) or any(
            anchor_hash(self.context.project_dir, path) != digest
            for path, digest in anchors.items()
        )
        origin_anchor = entry.payload.get("anchor_blob_oid", "")
        if origin_anchor and entry.scope:
            target = Path(self.context.project_dir) / entry.scope
            if not target.is_file():
                stale = True
            elif origin_anchor.startswith("sha256:"):
                stale = stale or origin_anchor != "sha256:" + current_hash
            elif origin_anchor.startswith("git:"):
                data = target.read_bytes()
                stale = (
                    stale
                    or origin_anchor
                    != "git:"
                    + hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                )
        return {
            **entry.payload,
            "id": entry.id,
            "number": entry.id,
            "kind": entry.kind,
            "status": entry.status,
            "scope": entry.scope,
            "author_id": entry.author_id,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "revision": entry.revision,
            "stale": stale,
        }

    async def execute(self, operation: str, arguments: dict):
        args = dict(arguments)
        if operation in {"record_learning", "record_adr"}:
            kind = "adr" if operation == "record_adr" else "learning"
            description = args.get("description") if kind == "learning" else args.get("title")
            if not description or not description.strip():
                raise ValueError("A non-empty description or title is required")
            if kind == "learning":
                from attocode_intel._internal.integrations.context.memory_store import VALID_TYPES

                if args.get("type") not in VALID_TYPES:
                    raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
            confidence = float(args.get("confidence", 0.7))
            if not 0 <= confidence <= 1:
                raise ValueError("confidence must be between zero and one")
            scope = args.pop("scope", "")
            if kind == "adr":
                args["file_anchors"] = {
                    path: anchor_hash(self.context.project_dir, path)
                    for path in args.get("related_files") or []
                }
            entry = KnowledgeEntry(
                repo_id=self.repo_id,
                kind=kind,
                payload=args,
                scope=scope,
                author_id=str(self.context.identity.user_id or "service"),
                status="proposed" if kind == "adr" else "active",
                revision=self.context.revision,
                anchor_hash=anchor_hash(self.context.project_dir, scope),
            )
            self.session.add(entry)
            await self.session.flush()
            await self.session.refresh(entry)
            return self.serialize(entry)
        if operation in {"learning_feedback", "update_adr_status", "get_adr", "update_learning"}:
            number = args.get("learning_id", args.get("number", args.get("adr_number")))
            stmt = self.statement().where(KnowledgeEntry.id == number)
            if operation != "get_adr":
                stmt = stmt.with_for_update()
            entry = (await self.session.execute(stmt)).scalar_one_or_none()
            if entry is None:
                raise ValueError("Knowledge entry not found in this repository")
            expected = "adr" if operation in {"get_adr", "update_adr_status"} else "learning"
            if entry.kind != expected:
                raise ValueError(f"Entry is not a {expected}")
            if operation == "learning_feedback":
                payload = dict(entry.payload)
                key = "helpful_count" if args.get("helpful") else "unhelpful_count"
                payload[key] = payload.get(key, 0) + 1
                payload["confidence"] = max(
                    0.1,
                    min(
                        1.0,
                        payload.get("confidence", 0.7) + (0.05 if args.get("helpful") else -0.1),
                    ),
                )
                if payload.get("unhelpful_count", 0) >= 5 and payload["confidence"] < 0.15:
                    entry.status = "archived"
                entry.payload = payload
            elif operation == "update_learning":
                if entry.kind != "learning":
                    raise ValueError("Entry is not a learning")
                payload = dict(entry.payload)
                for key in ("description", "details", "confidence"):
                    if key in args:
                        payload[key] = args[key]
                if (
                    not payload.get("description", "").strip()
                    or not 0 <= payload.get("confidence", 0.7) <= 1
                ):
                    raise ValueError(
                        "A non-empty description and confidence between zero and one are required"
                    )
                status = args.get("status", entry.status)
                if status not in {"active", "archived"}:
                    raise ValueError("Learning status must be active or archived")
                entry.status, entry.payload = status, payload
            elif operation == "update_adr_status":
                from attocode_intel.tools.adr_tools import _STATUS_TRANSITIONS

                status = args.get("new_status", args.get("status"))
                if status not in _STATUS_TRANSITIONS.get(entry.status, set()):
                    raise ValueError("Invalid ADR status transition")
                replacement = args.get("superseded_by")
                if status == "superseded" and replacement is None:
                    raise ValueError("superseded_by is required")
                if replacement is not None:
                    target = (
                        await self.session.execute(
                            self.statement().where(
                                KnowledgeEntry.id == replacement, KnowledgeEntry.kind == "adr"
                            )
                        )
                    ).scalar_one_or_none()
                    if target is None or target.id == entry.id:
                        raise ValueError(
                            "Superseding ADR must exist in this repository and differ from this ADR"
                        )
                entry.status = status
                entry.payload = {**entry.payload, "superseded_by": args.get("superseded_by")}
            if operation != "get_adr":
                entry.updated_at = datetime.now(UTC)
            await self.session.flush()
            return self.serialize(entry)
        kind = "adr" if operation == "list_adrs" else "learning"
        stmt = self.statement().where(KnowledgeEntry.kind == kind)
        status = args.get("status", "active" if kind == "learning" else "")
        if status:
            stmt = stmt.where(KnowledgeEntry.status == status)
        query = args.get("query", args.get("search", "")).lower().split()
        if query:
            stmt = stmt.where(
                or_(
                    *(
                        cast(KnowledgeEntry.payload, Text).icontains(term, autoescape=True)
                        for term in query[:20]
                    )
                )
            )
        entries = (
            (
                await self.session.execute(
                    stmt.order_by(KnowledgeEntry.updated_at.desc()).limit(1000)
                )
            )
            .scalars()
            .all()
        )
        scope = args.get("scope", "").rstrip("/")
        rows = [
            self.serialize(e)
            for e in entries
            if not scope or not e.scope or e.scope == scope or e.scope.startswith(scope + "/")
        ]
        if args.get("type"):
            rows = [r for r in rows if r.get("type") == args["type"]]
        if args.get("tag"):
            rows = [r for r in rows if args["tag"] in r.get("tags", [])]
        if query:
            rows.sort(
                key=lambda r: (
                    sum(term in json.dumps(r).lower() for term in query),
                    not r["stale"],
                    r.get("confidence", 0.7),
                ),
                reverse=True,
            )
        return rows[: min(int(args.get("max_results", 100)), 1000)]


async def execute_knowledge(context, operation, arguments):
    from attocode_intel.db.engine import get_session

    async for session in get_session():
        result = await PostgresKnowledge(session, context).execute(operation, arguments)
        await session.commit()
        return result
    raise RuntimeError("Knowledge database unavailable")
