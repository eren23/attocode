"""Simple merge queue state with timeout support."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

# Default timeout for items stuck in pending/in_review (1 hour)
DEFAULT_ITEM_TIMEOUT_SECONDS: float = 3600.0


@dataclass(slots=True)
class MergeItem:
    task_id: str
    status: str = "pending"
    quality_score: float = 0.0
    judge_task_ids: list[str] = field(default_factory=list)
    merge_task_id: str | None = None
    candidate_artifacts: list[str] = field(default_factory=list)
    decision: str = "undecided"
    merge_attempts: int = 0
    enqueued_at: float = field(default_factory=time.time)
    last_status_change: float = field(default_factory=time.time)


@dataclass(slots=True)
class MergeQueue:
    items: list[MergeItem] = field(default_factory=list)
    item_timeout_seconds: float = DEFAULT_ITEM_TIMEOUT_SECONDS

    def enqueue(self, task_id: str, artifacts: list[str] | None = None) -> None:
        if any(x.task_id == task_id for x in self.items):
            return
        self.items.append(MergeItem(task_id=task_id, candidate_artifacts=artifacts or []))

    def mark_reviewed(self, task_id: str, quality: float) -> None:
        for item in self.items:
            if item.task_id == task_id:
                item.status = "in_review"
                item.quality_score = quality
                item.last_status_change = time.time()
                return

    def mark_merged(self, task_id: str) -> None:
        for item in self.items:
            if item.task_id == task_id:
                item.status = "merged"
                item.last_status_change = time.time()
                return

    def expire_stale_items(self) -> list[str]:
        """Expire items stuck in pending/in_review beyond the timeout.

        Returns a list of task_ids that were expired.
        """
        if self.item_timeout_seconds <= 0:
            return []
        now = time.time()
        expired: list[str] = []
        for item in self.items:
            if item.status not in ("pending", "in_review"):
                continue
            age = now - item.last_status_change
            if age > self.item_timeout_seconds:
                logger.warning(
                    "Merge queue item %s expired (status=%s, age=%.0fs)",
                    item.task_id, item.status, age,
                )
                item.status = "expired"
                item.decision = f"expired_after_{age:.0f}s"
                expired.append(item.task_id)
        return expired

    def summary(self) -> dict[str, int]:
        pending = sum(1 for i in self.items if i.status == "pending")
        in_review = sum(1 for i in self.items if i.status == "in_review")
        merged = sum(1 for i in self.items if i.status == "merged")
        rejected = sum(1 for i in self.items if i.status == "rejected")
        expired = sum(1 for i in self.items if i.status == "expired")
        return {
            "pending": pending, "in_review": in_review,
            "merged": merged, "rejected": rejected, "expired": expired,
        }

    def to_list(self) -> list[dict]:
        return [asdict(item) for item in self.items]

    @classmethod
    def from_list(cls, raw: list[dict]) -> MergeQueue:
        items: list[MergeItem] = []
        for item in raw:
            if not isinstance(item, dict) or "task_id" not in item:
                continue
            items.append(
                MergeItem(
                    task_id=str(item["task_id"]),
                    status=str(item.get("status", "pending")),
                    quality_score=float(item.get("quality_score", 0.0)),
                    judge_task_ids=[str(x) for x in item.get("judge_task_ids", []) if isinstance(x, str)],
                    merge_task_id=str(item["merge_task_id"]) if item.get("merge_task_id") else None,
                    candidate_artifacts=[str(x) for x in item.get("candidate_artifacts", []) if isinstance(x, str)],
                    decision=str(item.get("decision", "undecided")),
                    merge_attempts=int(item.get("merge_attempts", 0)),
                    enqueued_at=float(item.get("enqueued_at", 0.0)) or time.time(),
                    last_status_change=float(item.get("last_status_change", 0.0)) or time.time(),
                )
            )
        return cls(items=items)
