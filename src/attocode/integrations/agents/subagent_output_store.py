"""Subagent output store for tracking and querying subagent results.

Stores outputs from subagent executions with metadata for later retrieval,
analysis, and inclusion in synthesis steps.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SubagentOutput:
    """Stored output from a subagent execution."""

    subagent_id: str
    agent_type: str
    task: str
    output: str
    success: bool
    timestamp: float = 0.0
    tokens_used: int = 0
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    files_modified: list[str] = field(default_factory=list)


class SubagentOutputStore:
    """Store and query subagent execution outputs.

    Enables:
    - Persistent storage of subagent results
    - Querying by agent type, task, or success status
    - Aggregating outputs for synthesis
    - Tracking file modifications across subagents
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._max_entries = max_entries
        self._outputs: list[SubagentOutput] = []
        self._by_agent: dict[str, list[SubagentOutput]] = defaultdict(list)
        self._by_type: dict[str, list[SubagentOutput]] = defaultdict(list)

    def store(
        self,
        subagent_id: str,
        agent_type: str,
        task: str,
        output: str,
        success: bool,
        *,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
        files_modified: list[str] | None = None,
    ) -> SubagentOutput:
        """Store a subagent output."""
        entry = SubagentOutput(
            subagent_id=subagent_id,
            agent_type=agent_type,
            task=task,
            output=output,
            success=success,
            timestamp=time.monotonic(),
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            metadata=metadata or {},
            files_modified=files_modified or [],
        )

        self._outputs.append(entry)
        self._by_agent[subagent_id].append(entry)
        self._by_type[agent_type].append(entry)

        # Evict oldest if at capacity
        while len(self._outputs) > self._max_entries:
            removed = self._outputs.pop(0)
            agent_list = self._by_agent.get(removed.subagent_id, [])
            if removed in agent_list:
                agent_list.remove(removed)
            type_list = self._by_type.get(removed.agent_type, [])
            if removed in type_list:
                type_list.remove(removed)

        return entry

    def get_by_agent(self, subagent_id: str) -> list[SubagentOutput]:
        """Get all outputs from a specific subagent."""
        return list(self._by_agent.get(subagent_id, []))

    def get_by_type(self, agent_type: str) -> list[SubagentOutput]:
        """Get all outputs from a specific agent type."""
        return list(self._by_type.get(agent_type, []))

    def get_successful(self) -> list[SubagentOutput]:
        """Get all successful outputs."""
        return [o for o in self._outputs if o.success]

    def get_failed(self) -> list[SubagentOutput]:
        """Get all failed outputs."""
        return [o for o in self._outputs if not o.success]

    def get_recent(self, count: int = 10) -> list[SubagentOutput]:
        """Get the most recent outputs."""
        return self._outputs[-count:]

    def get_all_modified_files(self) -> list[str]:
        """Get all files modified by any subagent, deduplicated."""
        files: set[str] = set()
        for output in self._outputs:
            files.update(output.files_modified)
        return sorted(files)

    def get_conflicting_files(self) -> dict[str, list[SubagentOutput]]:
        """Find files modified by multiple subagents."""
        file_map: dict[str, list[SubagentOutput]] = defaultdict(list)
        for output in self._outputs:
            for f in output.files_modified:
                file_map[f].append(output)
        return {f: outputs for f, outputs in file_map.items() if len(outputs) > 1}

    def format_for_synthesis(self, max_outputs: int = 20) -> str:
        """Format recent outputs for inclusion in synthesis prompt."""
        recent = self.get_recent(max_outputs)
        if not recent:
            return ""

        parts = [f"## Subagent Outputs ({len(recent)} results)\n"]
        for i, output in enumerate(recent, 1):
            status = "SUCCESS" if output.success else "FAILED"
            parts.append(
                f"### [{status}] {output.agent_type} ({output.subagent_id})\n"
                f"Task: {output.task}\n"
                f"Output: {output.output[:500]}{'...' if len(output.output) > 500 else ''}\n"
            )
        return "\n".join(parts)

    def clear(self) -> None:
        """Clear all stored outputs."""
        self._outputs.clear()
        self._by_agent.clear()
        self._by_type.clear()

    @property
    def size(self) -> int:
        return len(self._outputs)

    def get_stats(self) -> dict[str, Any]:
        """Get output store statistics."""
        return {
            "total": len(self._outputs),
            "successful": sum(1 for o in self._outputs if o.success),
            "failed": sum(1 for o in self._outputs if not o.success),
            "agent_types": len(self._by_type),
            "unique_agents": len(self._by_agent),
            "files_modified": len(self.get_all_modified_files()),
        }
