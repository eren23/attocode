"""Pre-flight task validator — checks before dispatch.

Validates each task right before it is sent to a worker:
1. Target files exist (or task creates new files)
2. Read files exist (hard blocker)
3. Model health above threshold
4. Budget allows dispatch
5. No active OCC claim conflicts
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.budget_gate import BudgetGate
    from attoswarm.coordinator.health_monitor import HealthMonitor
    from attoswarm.protocol.models import TaskSpec

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PreflightResult:
    """Result of a pre-flight check for a single task."""

    task_id: str
    passed: bool = True
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "blockers": self.blockers,
            "warnings": self.warnings,
        }


class PreflightValidator:
    """Validates tasks before dispatch.

    Usage::

        validator = PreflightValidator(
            root_dir="/path/to/repo",
            health_monitor=monitor,
            budget_gate=gate,
            file_ledger=ledger,
        )
        result = await validator.check(task, model="claude-3")
        if not result.passed:
            defer_task(task.task_id, blockers=result.blockers)
    """

    def __init__(
        self,
        root_dir: str,
        health_monitor: HealthMonitor | None = None,
        budget_gate: BudgetGate | None = None,
        file_ledger: Any = None,
    ) -> None:
        self._root_dir = root_dir
        self._health = health_monitor
        self._budget_gate = budget_gate
        self._ledger = file_ledger

    async def check(
        self,
        task: TaskSpec,
        model: str = "",
    ) -> PreflightResult:
        """Run all pre-flight checks for a task."""
        result = PreflightResult(task_id=task.task_id)

        self._check_read_files(task, result)
        self._check_target_files(task, result)
        self._check_model_health(model, result)
        self._check_budget(task.task_id, result)
        await self._check_claim_conflicts(task, result)

        result.passed = len(result.blockers) == 0
        return result

    def _check_read_files(self, task: TaskSpec, result: PreflightResult) -> None:
        """Check that all read_files exist."""
        for f in task.read_files:
            abs_path = os.path.join(self._root_dir, f)
            if not os.path.exists(abs_path):
                result.blockers.append(f"read file '{f}' does not exist")

    def _check_target_files(self, task: TaskSpec, result: PreflightResult) -> None:
        """Check target files — warning only for non-creation tasks."""
        if task.task_kind in ("implement", "design"):
            return  # task may create new files

        for f in task.target_files:
            abs_path = os.path.join(self._root_dir, f)
            if not os.path.exists(abs_path):
                result.warnings.append(f"target file '{f}' does not exist")

    def _check_model_health(self, model: str, result: PreflightResult) -> None:
        """Check that the assigned model is healthy enough."""
        if not self._health or not model:
            return

        if self._health.should_throttle(model):
            health = self._health.get_health(model)
            score = health.health_score if health else 0.0
            result.blockers.append(
                f"model '{model}' health score {score:.2f} below threshold"
            )

    def _check_budget(self, task_id: str, result: PreflightResult) -> None:
        """Check budget gate."""
        if not self._budget_gate:
            return

        estimated = self._budget_gate.estimated_task_cost()
        decision = self._budget_gate.can_dispatch(task_id, estimated_cost=estimated)
        if not decision.allowed:
            result.blockers.append(f"budget: {decision.reason}")

    async def _check_claim_conflicts(
        self,
        task: TaskSpec,
        result: PreflightResult,
    ) -> None:
        """Check for active OCC claim conflicts on target files."""
        if not self._ledger or not task.target_files:
            return

        try:
            for f in task.target_files:
                claim = await self._ledger.get_claim(f) if hasattr(self._ledger, "get_claim") else None
                if claim and claim.get("agent_id") and claim.get("agent_id") != f"agent-{task.task_id}":
                    result.warnings.append(
                        f"file '{f}' currently claimed by {claim.get('agent_id')}"
                    )
        except Exception as exc:
            logger.debug("Claim conflict check failed: %s", exc)
