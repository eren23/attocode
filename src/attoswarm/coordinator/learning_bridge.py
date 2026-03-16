"""SwarmLearningBridge — swarm ↔ code-intel learning system bridge.

Records task outcomes and conflict resolutions as learnings,
and recalls relevant learnings for decomposition and task prompts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.protocol.models import TaskSpec

logger = logging.getLogger(__name__)


class SwarmLearningBridge:
    """Bridge between swarm orchestrator and code-intel learning store."""

    def __init__(self, code_intel: Any) -> None:
        self._code_intel = code_intel

    def recall_for_goal(self, goal: str) -> str:
        """Recall learnings relevant to the overall goal.

        Returns a formatted string suitable for injection into the
        decomposition prompt.
        """
        try:
            result = self._code_intel.recall(goal)
            if not result:
                return ""
            if isinstance(result, dict):
                learnings = result.get("learnings", [])
                if not learnings:
                    return ""
                parts = ["## Relevant Learnings from Previous Runs"]
                for i, learning in enumerate(learnings[:10], 1):
                    content = learning if isinstance(learning, str) else learning.get("content", "")
                    category = "" if isinstance(learning, str) else learning.get("category", "")
                    prefix = f"[{category}] " if category else ""
                    parts.append(f"{i}. {prefix}{content}")
                return "\n".join(parts)
            return str(result)[:2000]
        except Exception as exc:
            logger.debug("recall_for_goal failed: %s", exc)
            return ""

    def recall_for_task(self, task: TaskSpec) -> str:
        """Recall learnings relevant to a specific task.

        Uses target files and description as search context.
        """
        query_parts = [task.title, task.description[:200]]
        query_parts.extend(task.target_files[:3])
        query = " ".join(query_parts)

        try:
            result = self._code_intel.recall(query)
            if not result:
                return ""
            if isinstance(result, dict):
                learnings = result.get("learnings", [])
                if not learnings:
                    return ""
                parts = []
                for learning in learnings[:5]:
                    content = learning if isinstance(learning, str) else learning.get("content", "")
                    parts.append(f"- {content}")
                return "\n".join(parts)
            return str(result)[:1000]
        except Exception as exc:
            logger.debug("recall_for_task failed: %s", exc)
            return ""

    def record_task_outcome(self, task: TaskSpec | None, result: Any) -> None:
        """Record a task outcome as a learning.

        - Successful completion → 'pattern' or 'workaround' learning
        - Retry success → 'gotcha' learning
        - Final failure → 'antipattern' learning
        """
        if not task or not result:
            return

        try:
            files = ", ".join(task.target_files[:3]) if task.target_files else "no files"
            if result.success:
                content = (
                    f"Task '{task.title}' succeeded on files [{files}]. "
                    f"Approach: {task.description[:200]}"
                )
                if result.result_summary:
                    content += f". Result: {result.result_summary[:200]}"
                self._code_intel.record_learning(
                    content=content,
                    category="pattern",
                    tags=list(task.target_files[:5]),
                )
            else:
                error_msg = getattr(result, 'error', '') or ''
                content = (
                    f"Task '{task.title}' failed on files [{files}]. "
                    f"Error: {error_msg[:300]}"
                )
                self._code_intel.record_learning(
                    content=content,
                    category="antipattern",
                    tags=list(task.target_files[:5]),
                )
        except Exception as exc:
            logger.debug("record_task_outcome failed: %s", exc)

    def record_conflict_resolution(
        self,
        conflict: Any,
        resolution: Any,
    ) -> None:
        """Record a conflict resolution as a learning."""
        try:
            file_path = getattr(conflict, 'file_path', '') or ''
            symbol = getattr(conflict, 'symbol_name', '') or ''
            content = (
                f"Conflict on {file_path}:{symbol} resolved. "
                f"Strategy: {resolution}"
            )
            self._code_intel.record_learning(
                content=content,
                category="workaround",
                tags=[file_path] if file_path else [],
            )
        except Exception as exc:
            logger.debug("record_conflict_resolution failed: %s", exc)
