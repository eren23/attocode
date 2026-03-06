"""Auto-checkpoint for periodic state saving.

Automatically saves agent state at configurable intervals
to enable recovery from crashes or interruptions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CheckpointConfig:
    """Configuration for auto-checkpointing."""

    interval_seconds: float = 120.0  # 2 minutes
    max_checkpoints: int = 5
    on_milestone: bool = True  # Checkpoint on milestones
    on_tool_batch: bool = True  # Checkpoint after tool batches


@dataclass
class Checkpoint:
    """A saved checkpoint."""

    id: str
    timestamp: float
    iteration: int
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


CheckpointSaver = Callable[[int, str], str | None]  # (iteration, description) -> checkpoint_id


class AutoCheckpointManager:
    """Manages automatic checkpointing during agent execution.

    Triggers checkpoints based on time intervals, milestones,
    and tool batch completions.
    """

    def __init__(
        self,
        config: CheckpointConfig | None = None,
        saver: CheckpointSaver | None = None,
    ) -> None:
        self._config = config or CheckpointConfig()
        self._saver = saver
        self._checkpoints: list[Checkpoint] = []
        self._last_checkpoint_time: float = time.monotonic()
        self._last_checkpoint_iteration: int = 0

    def check_and_save(
        self,
        iteration: int,
        description: str = "",
        force: bool = False,
    ) -> Checkpoint | None:
        """Check if a checkpoint should be saved and save if needed."""
        now = time.monotonic()
        elapsed = now - self._last_checkpoint_time

        should_save = force or elapsed >= self._config.interval_seconds

        if not should_save:
            return None

        return self._save_checkpoint(iteration, description or f"Auto-checkpoint at iteration {iteration}")

    def on_milestone(self, iteration: int, description: str) -> Checkpoint | None:
        """Trigger checkpoint on milestone if enabled."""
        if not self._config.on_milestone:
            return None
        return self._save_checkpoint(iteration, f"Milestone: {description}")

    def on_tool_batch_complete(self, iteration: int, tool_count: int) -> Checkpoint | None:
        """Trigger checkpoint after tool batch if enabled."""
        if not self._config.on_tool_batch:
            return None
        if tool_count < 3:
            return None
        return self._save_checkpoint(iteration, f"After {tool_count} tool calls")

    @property
    def checkpoints(self) -> list[Checkpoint]:
        """Get all saved checkpoints."""
        return list(self._checkpoints)

    @property
    def last_checkpoint(self) -> Checkpoint | None:
        """Get the most recent checkpoint."""
        return self._checkpoints[-1] if self._checkpoints else None

    @property
    def checkpoint_count(self) -> int:
        return len(self._checkpoints)

    def set_saver(self, saver: CheckpointSaver) -> None:
        """Set the checkpoint saver callback."""
        self._saver = saver

    def clear(self) -> None:
        """Clear checkpoint history."""
        self._checkpoints.clear()

    def _save_checkpoint(self, iteration: int, description: str) -> Checkpoint | None:
        """Save a checkpoint."""
        checkpoint_id: str | None = None

        if self._saver:
            try:
                checkpoint_id = self._saver(iteration, description)
            except Exception:
                return None

        cp_id = checkpoint_id or f"cp-{int(time.time())}-{iteration}"
        checkpoint = Checkpoint(
            id=cp_id,
            timestamp=time.monotonic(),
            iteration=iteration,
            description=description,
        )

        self._checkpoints.append(checkpoint)
        self._last_checkpoint_time = time.monotonic()
        self._last_checkpoint_iteration = iteration

        # Enforce max checkpoints
        while len(self._checkpoints) > self._config.max_checkpoints:
            self._checkpoints.pop(0)

        return checkpoint
