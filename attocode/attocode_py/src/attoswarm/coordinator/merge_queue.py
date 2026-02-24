"""Simple merge queue state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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


@dataclass(slots=True)
class MergeQueue:
    items: list[MergeItem] = field(default_factory=list)

    def enqueue(self, task_id: str, artifacts: list[str] | None = None) -> None:
        if any(x.task_id == task_id for x in self.items):
            return
        self.items.append(MergeItem(task_id=task_id, candidate_artifacts=artifacts or []))

    def mark_reviewed(self, task_id: str, quality: float) -> None:
        for item in self.items:
            if item.task_id == task_id:
                item.status = "in_review"
                item.quality_score = quality
                return

    def mark_merged(self, task_id: str) -> None:
        for item in self.items:
            if item.task_id == task_id:
                item.status = "merged"
                return

    def summary(self) -> dict[str, int]:
        pending = sum(1 for i in self.items if i.status == "pending")
        in_review = sum(1 for i in self.items if i.status == "in_review")
        merged = sum(1 for i in self.items if i.status == "merged")
        rejected = sum(1 for i in self.items if i.status == "rejected")
        return {"pending": pending, "in_review": in_review, "merged": merged, "rejected": rejected}

    def to_list(self) -> list[dict]:
        return [asdict(item) for item in self.items]

    @classmethod
    def from_list(cls, raw: list[dict]) -> "MergeQueue":
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
                )
            )
        return cls(items=items)
