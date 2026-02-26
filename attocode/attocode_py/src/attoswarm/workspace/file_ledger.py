"""File Ledger — optimistic concurrency control for shared-workspace swarm.

Replaces worktrees for the ``workspace_mode: shared`` path.  All workers
share the same directory; the ledger tracks file versions and enforces
compare-and-swap on writes.

Concurrency flow:
1. Orchestrator calls ``snapshot_file()`` before dispatching a task.
2. Worker gets file content + version hash in its prompt.
3. Worker's write/edit tools call ``attempt_write()`` with the base hash.
4. If ``base_hash == current_hash``: write succeeds (fast path).
5. If hashes differ: CONFLICT — the reconciler attempts AST merge.
6. On task completion: ``release_claim()`` frees advisory locks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.integrations.context.ast_service import ASTService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileVersion:
    """Snapshot of a file at a point in time."""

    file_path: str
    version_hash: str        # SHA-256 of content
    content_snapshot: str    # full content at read time
    reader_agent_id: str
    timestamp: float = 0.0


@dataclass(slots=True)
class FileClaim:
    """Advisory lock on a file."""

    file_path: str
    agent_id: str
    task_id: str
    base_version_hash: str
    claim_type: str = "exclusive"   # "exclusive" | "section"
    timestamp: float = 0.0


@dataclass(slots=True)
class WriteResult:
    """Outcome of an ``attempt_write`` call."""

    success: bool
    conflict: bool = False
    reconciled: bool = False
    final_hash: str = ""
    error: str = ""


@dataclass(slots=True)
class WriteLogEntry:
    """Audit trail entry for a file write."""

    timestamp: float
    file_path: str
    agent_id: str
    task_id: str
    base_hash: str
    new_hash: str
    conflict: bool = False
    reconciled: bool = False


# ---------------------------------------------------------------------------
# FileLedger
# ---------------------------------------------------------------------------


class FileLedger:
    """Optimistic-concurrency file manager for shared-workspace swarm runs.

    Thread-safe via ``asyncio.Lock`` (one lock per file path).
    """

    def __init__(
        self,
        root_dir: str,
        ast_service: "ASTService | None" = None,
        persist_dir: str | None = None,
    ) -> None:
        self._root_dir = os.path.abspath(root_dir)
        self._ast_service = ast_service
        self._persist_dir = persist_dir

        # State
        self._versions: dict[str, str] = {}        # rel_path -> current hash
        self._claims: dict[str, FileClaim] = {}     # rel_path -> active claim
        self._write_log: list[WriteLogEntry] = []
        self._locks: dict[str, asyncio.Lock] = {}

        # Restore persisted state if available
        if persist_dir:
            self._restore(persist_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def snapshot_file(self, path: str, agent_id: str) -> FileVersion:
        """Read a file and return its content + version hash.

        This is called *before* dispatching a task so the worker
        receives a known baseline.
        """
        rel = self._to_rel(path)
        abs_path = self._to_abs(rel)

        p = Path(abs_path)
        content = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        h = self._hash(content)

        # Record known version
        self._versions[rel] = h

        return FileVersion(
            file_path=rel,
            version_hash=h,
            content_snapshot=content,
            reader_agent_id=agent_id,
            timestamp=time.time(),
        )

    async def claim_file(
        self,
        path: str,
        agent_id: str,
        task_id: str,
        claim_type: str = "exclusive",
    ) -> bool:
        """Take an advisory lock on *path*.

        Returns ``True`` if the claim was granted, ``False`` if another
        agent already holds an exclusive claim.
        """
        rel = self._to_rel(path)
        lock = self._get_lock(rel)

        async with lock:
            existing = self._claims.get(rel)
            if existing and existing.agent_id != agent_id:
                if existing.claim_type == "exclusive":
                    return False

            current_hash = self._versions.get(rel, "")
            self._claims[rel] = FileClaim(
                file_path=rel,
                agent_id=agent_id,
                task_id=task_id,
                base_version_hash=current_hash,
                claim_type=claim_type,
                timestamp=time.time(),
            )
            self._persist()
            return True

    async def release_claim(self, path: str, agent_id: str) -> None:
        """Release an advisory lock."""
        rel = self._to_rel(path)
        lock = self._get_lock(rel)

        async with lock:
            claim = self._claims.get(rel)
            if claim and claim.agent_id == agent_id:
                del self._claims[rel]
                self._persist()

    async def release_all_claims(self, agent_id: str) -> None:
        """Release all claims held by *agent_id*."""
        to_release = [
            rel for rel, c in self._claims.items()
            if c.agent_id == agent_id
        ]
        for rel in to_release:
            lock = self._get_lock(rel)
            async with lock:
                claim = self._claims.get(rel)
                if claim and claim.agent_id == agent_id:
                    del self._claims[rel]
        if to_release:
            self._persist()

    async def attempt_write(
        self,
        path: str,
        agent_id: str,
        task_id: str,
        content: str,
        base_hash: str,
    ) -> WriteResult:
        """Compare-and-swap write.

        If *base_hash* matches the current version, the write succeeds.
        Otherwise it's a CONFLICT.
        """
        rel = self._to_rel(path)
        abs_path = self._to_abs(rel)
        lock = self._get_lock(rel)

        async with lock:
            # Read current version from disk
            current_hash = self._versions.get(rel)
            if current_hash is None:
                # File may be new or untracked — snapshot it
                if Path(abs_path).exists():
                    existing = Path(abs_path).read_text(encoding="utf-8", errors="replace")
                    current_hash = self._hash(existing)
                    self._versions[rel] = current_hash
                else:
                    current_hash = ""

            # Fast path: hashes match — write directly
            if base_hash == current_hash or current_hash == "":
                new_hash = self._hash(content)
                Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
                Path(abs_path).write_text(content, encoding="utf-8")
                self._versions[rel] = new_hash

                self._write_log.append(WriteLogEntry(
                    timestamp=time.time(),
                    file_path=rel,
                    agent_id=agent_id,
                    task_id=task_id,
                    base_hash=base_hash,
                    new_hash=new_hash,
                ))
                self._persist()

                # Notify AST service
                if self._ast_service:
                    try:
                        self._ast_service.notify_file_changed(abs_path)
                    except Exception:
                        pass

                return WriteResult(success=True, final_hash=new_hash)

            # Conflict path
            logger.warning(
                "OCC conflict on %s: base=%s current=%s agent=%s",
                rel, base_hash[:8], current_hash[:8], agent_id,
            )
            self._write_log.append(WriteLogEntry(
                timestamp=time.time(),
                file_path=rel,
                agent_id=agent_id,
                task_id=task_id,
                base_hash=base_hash,
                new_hash=self._hash(content),
                conflict=True,
            ))
            self._persist()

            return WriteResult(
                success=False,
                conflict=True,
                final_hash=current_hash,
                error=f"OCC conflict: expected {base_hash[:8]}, got {current_hash[:8]}",
            )

    async def get_active_claims(self) -> dict[str, FileClaim]:
        """Return a copy of all active claims."""
        return dict(self._claims)

    def get_version(self, path: str) -> str | None:
        """Return the current known hash for *path*, or None."""
        return self._versions.get(self._to_rel(path))

    def get_write_log(self) -> list[WriteLogEntry]:
        """Return the audit trail."""
        return list(self._write_log)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_rel(self, path: str) -> str:
        if os.path.isabs(path):
            try:
                return os.path.relpath(path, self._root_dir)
            except ValueError:
                return path
        # Already relative — treat as relative to root_dir
        return path

    def _to_abs(self, rel_path: str) -> str:
        return os.path.join(self._root_dir, rel_path)

    def _get_lock(self, rel_path: str) -> asyncio.Lock:
        if rel_path not in self._locks:
            self._locks[rel_path] = asyncio.Lock()
        return self._locks[rel_path]

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Persist current state to disk (if persist_dir configured)."""
        if not self._persist_dir:
            return
        try:
            d = Path(self._persist_dir)
            d.mkdir(parents=True, exist_ok=True)

            # Versions
            (d / "versions.json").write_text(
                json.dumps(self._versions, indent=2), encoding="utf-8",
            )

            # Claims
            claims_data = {k: asdict(v) for k, v in self._claims.items()}
            (d / "claims.json").write_text(
                json.dumps(claims_data, indent=2), encoding="utf-8",
            )

            # Write log (append-only JSONL)
            if self._write_log:
                with (d / "write_log.jsonl").open("a", encoding="utf-8") as f:
                    entry = self._write_log[-1]
                    f.write(json.dumps(asdict(entry)) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist ledger state: %s", exc)

    def _restore(self, persist_dir: str) -> None:
        """Restore state from persisted files."""
        d = Path(persist_dir)
        if not d.exists():
            return

        # Versions
        versions_path = d / "versions.json"
        if versions_path.exists():
            try:
                self._versions = json.loads(versions_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Claims
        claims_path = d / "claims.json"
        if claims_path.exists():
            try:
                data = json.loads(claims_path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._claims[k] = FileClaim(**v)
            except Exception:
                pass
