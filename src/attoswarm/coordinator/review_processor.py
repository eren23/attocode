"""Review queue processing logic extracted from HybridCoordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from attoswarm.protocol.models import TaskSpec

if TYPE_CHECKING:
    from attoswarm.coordinator.loop import HybridCoordinator


async def process_review_queue(coordinator: HybridCoordinator) -> None:
    """Walk the merge queue and create/resolve review and merge tasks."""
    if coordinator.manifest is None:
        raise RuntimeError("Manifest not initialized — cannot process review queue")
    authority = coordinator.config.merge.authority_role
    review_roles = coordinator._review_roles()

    for item in coordinator.merge_queue.items:
        if item.status == "pending":
            created: list[str] = []
            for rid in review_roles:
                review_id = f"review-{item.task_id}-{rid}"
                if coordinator._find_task(review_id) is not None:
                    created.append(review_id)
                    continue
                rt = TaskSpec(
                    task_id=review_id,
                    title=f"Review {item.task_id}",
                    description=f"Validate completion claim for {item.task_id}",
                    deps=[item.task_id],
                    role_hint=rid,
                    task_kind="judge" if coordinator._role_type(rid) == "judge" else "critic",
                    status="pending",
                )
                coordinator._append_task(rt)
                coordinator._transition_task(rt.task_id, "ready", "coordinator", "review_created")
                created.append(review_id)
            item.judge_task_ids = created
            item.status = "in_review"
            item.decision = "reviewing"

        if item.status == "in_review":
            if not item.judge_task_ids:
                item.status = "approved"
                item.decision = "approved_without_review_roles"
            else:
                statuses = [
                    coordinator.task_state.get(tid, "pending") for tid in item.judge_task_ids
                ]
                if any(s in {"pending", "ready", "running", "reviewing"} for s in statuses):
                    continue
                passed = sum(1 for s in statuses if s == "done")
                score = passed / max(len(statuses), 1)
                item.quality_score = score
                if score >= coordinator.config.merge.quality_threshold:
                    item.status = "approved"
                    item.decision = "approved"
                else:
                    item.status = "rejected"
                    item.decision = "rejected"
                    coordinator._transition_task(
                        item.task_id, "failed", "review", "insufficient_quality"
                    )

        if item.status == "approved":
            if item.merge_task_id is None:
                merge_id = f"merge-{item.task_id}"
                if coordinator._find_task(merge_id) is None:
                    t = TaskSpec(
                        task_id=merge_id,
                        title=f"Merge {item.task_id}",
                        description=f"Apply and reconcile outputs for {item.task_id}",
                        deps=[item.task_id] + item.judge_task_ids,
                        role_hint=authority,
                        task_kind="merge",
                        status="pending",
                    )
                    coordinator._append_task(t)
                    coordinator._transition_task(merge_id, "ready", "coordinator", "merge_created")
                item.merge_task_id = merge_id
            else:
                status = coordinator.task_state.get(item.merge_task_id, "pending")
                if status == "done":
                    item.status = "merged"
                    item.decision = "merged"
                    coordinator._transition_task(
                        item.task_id, "done", "merger", "merge_completed"
                    )
                    task = coordinator._find_task(item.task_id)
                    if task is not None:
                        coordinator._persist_task(task, status="done")
                elif status == "failed":
                    item.merge_attempts += 1
                    if item.merge_attempts >= coordinator.config.retries.max_task_attempts:
                        item.status = "rejected"
                        item.decision = "merge_failed"
