"""Doom loop detection.

Detects when the agent calls the same tool with identical arguments
repeatedly, indicating it's stuck in a loop.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field


@dataclass(slots=True)
class LoopDetection:
    """Result of a loop detection check."""

    is_loop: bool
    tool_name: str = ""
    count: int = 0
    message: str = ""

    @staticmethod
    def no_loop() -> LoopDetection:
        return LoopDetection(is_loop=False)

    @staticmethod
    def detected(tool_name: str, count: int) -> LoopDetection:
        return LoopDetection(
            is_loop=True,
            tool_name=tool_name,
            count=count,
            message=f"Doom loop detected: '{tool_name}' called {count} times with identical arguments",
        )


@dataclass
class LoopDetector:
    """Detects repetitive tool call patterns.

    Tracks tool call signatures (name + serialized args) and flags
    when the same signature appears more than `threshold` times.
    """

    threshold: int = 3
    _history: list[str] = field(default_factory=list, repr=False)
    _counts: Counter[str] = field(default_factory=Counter, repr=False)
    _window_size: int = 20

    def record(self, tool_name: str, arguments: dict) -> LoopDetection:
        """Record a tool call and check for loops.

        Args:
            tool_name: Name of the tool being called.
            arguments: Arguments passed to the tool.

        Returns:
            LoopDetection indicating if a loop was detected.
        """
        try:
            sig = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
        except (TypeError, ValueError):
            sig = f"{tool_name}:{str(arguments)}"

        self._history.append(sig)
        self._counts[sig] += 1

        # Trim old history
        while len(self._history) > self._window_size:
            old = self._history.pop(0)
            self._counts[old] -= 1
            if self._counts[old] <= 0:
                del self._counts[old]

        count = self._counts.get(sig, 0)
        if count >= self.threshold:
            return LoopDetection.detected(tool_name, count)

        return LoopDetection.no_loop()

    def reset(self) -> None:
        """Clear all history."""
        self._history.clear()
        self._counts.clear()

    @property
    def total_calls(self) -> int:
        return len(self._history)

    def get_most_common(self, n: int = 5) -> list[tuple[str, int]]:
        """Get the most frequently repeated tool signatures."""
        return self._counts.most_common(n)
