"""Tool recommendation engine.

Analyzes task context and past tool usage patterns to suggest the most
effective tools for current tasks. Learns from successful tool sequences.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolRecommendation:
    """A tool recommendation with confidence score."""

    tool_name: str
    confidence: float  # 0.0 to 1.0
    reason: str
    context_match: float = 0.0  # How well the context matches past usage


@dataclass(slots=True)
class ToolUsageRecord:
    """Record of a tool usage in context."""

    tool_name: str
    task_type: str
    success: bool
    context_keywords: list[str] = field(default_factory=list)
    following_tool: str | None = None  # What tool was used next


class ToolRecommendationEngine:
    """Recommends tools based on task context and past usage patterns.

    Learning sources:
    - Frequency analysis: which tools are used most for which task types
    - Sequence analysis: which tools commonly follow each other
    - Success correlation: which tools succeed in which contexts
    - Keyword matching: match task description to past contexts
    """

    def __init__(self, max_history: int = 5000) -> None:
        self._max_history = max_history
        self._records: list[ToolUsageRecord] = []

        # Learned patterns
        self._task_tool_freq: dict[str, Counter[str]] = defaultdict(Counter)
        self._tool_sequences: dict[str, Counter[str]] = defaultdict(Counter)
        self._tool_success_rate: dict[str, list[bool]] = defaultdict(list)
        self._keyword_tool_map: dict[str, Counter[str]] = defaultdict(Counter)

    def record_usage(
        self,
        tool_name: str,
        task_type: str,
        success: bool,
        context_keywords: list[str] | None = None,
    ) -> None:
        """Record a tool usage for learning."""
        keywords = context_keywords or []

        # Update sequence tracking
        if self._records:
            prev = self._records[-1]
            self._tool_sequences[prev.tool_name][tool_name] += 1

        record = ToolUsageRecord(
            tool_name=tool_name,
            task_type=task_type,
            success=success,
            context_keywords=keywords,
        )
        self._records.append(record)

        # Update patterns
        self._task_tool_freq[task_type][tool_name] += 1
        self._tool_success_rate[tool_name].append(success)

        for kw in keywords:
            self._keyword_tool_map[kw.lower()][tool_name] += 1

        # Trim history
        if len(self._records) > self._max_history:
            self._records = self._records[-self._max_history:]

    def recommend(
        self,
        task_type: str = "",
        context: str = "",
        current_tools: list[str] | None = None,
        max_results: int = 5,
    ) -> list[ToolRecommendation]:
        """Get tool recommendations for a task.

        Args:
            task_type: Type of task (e.g., "debug", "implement", "refactor")
            context: Task description or context text
            current_tools: Tools already used in this session
            max_results: Maximum recommendations to return
        """
        scores: dict[str, float] = defaultdict(float)
        reasons: dict[str, list[str]] = defaultdict(list)

        # 1. Task type frequency
        if task_type and task_type in self._task_tool_freq:
            freq = self._task_tool_freq[task_type]
            total = sum(freq.values())
            for tool, count in freq.most_common(10):
                score = count / total
                scores[tool] += score * 0.4
                reasons[tool].append(f"Used {count}x for {task_type} tasks")

        # 2. Sequence prediction
        if current_tools:
            last_tool = current_tools[-1]
            if last_tool in self._tool_sequences:
                seq = self._tool_sequences[last_tool]
                total = sum(seq.values())
                for tool, count in seq.most_common(5):
                    score = count / total
                    scores[tool] += score * 0.3
                    reasons[tool].append(f"Commonly follows {last_tool}")

        # 3. Keyword matching
        if context:
            words = context.lower().split()
            for word in words:
                if word in self._keyword_tool_map:
                    for tool, count in self._keyword_tool_map[word].most_common(3):
                        scores[tool] += 0.1
                        if f"Matches keyword '{word}'" not in reasons[tool]:
                            reasons[tool].append(f"Matches keyword '{word}'")

        # 4. Success rate bonus
        for tool in scores:
            if tool in self._tool_success_rate:
                successes = self._tool_success_rate[tool]
                if successes:
                    rate = sum(successes) / len(successes)
                    scores[tool] *= (0.5 + 0.5 * rate)  # Scale by success rate

        # Filter already-used tools lower
        if current_tools:
            for tool in current_tools:
                scores[tool] *= 0.5

        # Sort and return top results
        sorted_tools = sorted(scores.items(), key=lambda x: -x[1])
        return [
            ToolRecommendation(
                tool_name=tool,
                confidence=min(1.0, score),
                reason="; ".join(reasons.get(tool, ["General recommendation"])),
                context_match=score,
            )
            for tool, score in sorted_tools[:max_results]
            if score > 0.05
        ]

    def get_next_tool_prediction(self, current_tool: str) -> str | None:
        """Predict the most likely next tool."""
        if current_tool not in self._tool_sequences:
            return None
        seq = self._tool_sequences[current_tool]
        if not seq:
            return None
        return seq.most_common(1)[0][0]

    def get_success_rate(self, tool_name: str) -> float | None:
        """Get the success rate for a tool."""
        rates = self._tool_success_rate.get(tool_name)
        if not rates:
            return None
        return sum(rates) / len(rates)

    def get_stats(self) -> dict[str, Any]:
        """Get recommendation engine statistics."""
        return {
            "total_records": len(self._records),
            "unique_tools": len(self._tool_success_rate),
            "task_types": len(self._task_tool_freq),
            "keyword_entries": len(self._keyword_tool_map),
        }

    def clear(self) -> None:
        """Clear all learned patterns."""
        self._records.clear()
        self._task_tool_freq.clear()
        self._tool_sequences.clear()
        self._tool_success_rate.clear()
        self._keyword_tool_map.clear()
