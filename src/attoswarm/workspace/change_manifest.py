"""Change Manifest — audit trail of file changes during a swarm run."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChangeEntry:
    """A single file change record."""

    file_path: str
    action: str  # "create" | "modify" | "delete"
    agent_id: str
    task_id: str
    base_hash: str
    new_hash: str
    timestamp: float = 0.0


class ChangeManifest:
    """Tracks all file changes during a swarm run for auditing."""

    def __init__(self, run_dir: str) -> None:
        self._run_dir = run_dir
        self._changes: list[ChangeEntry] = []

    def record_change(
        self,
        file_path: str,
        action: str,
        agent_id: str,
        task_id: str,
        base_hash: str,
        new_hash: str,
    ) -> None:
        """Record a file change."""
        self._changes.append(ChangeEntry(
            file_path=file_path,
            action=action,
            agent_id=agent_id,
            task_id=task_id,
            base_hash=base_hash,
            new_hash=new_hash,
            timestamp=time.time(),
        ))

    def persist(self) -> None:
        """Write changes.json to run_dir."""
        path = Path(self._run_dir) / "changes.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(c) for c in self._changes]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist change manifest: %s", exc)

    def get_summary(self) -> dict[str, Any]:
        """Group changes by agent and count by action type."""
        by_agent: dict[str, list[str]] = {}
        by_action: dict[str, int] = {}

        for c in self._changes:
            by_agent.setdefault(c.agent_id, []).append(c.file_path)
            by_action[c.action] = by_action.get(c.action, 0) + 1

        return {
            "total_changes": len(self._changes),
            "by_action": by_action,
            "by_agent": {k: len(v) for k, v in by_agent.items()},
            "files_modified": list({c.file_path for c in self._changes}),
        }

    @property
    def changes(self) -> list[ChangeEntry]:
        return list(self._changes)
