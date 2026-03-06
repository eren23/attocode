"""LLM-powered task decomposition.

Splits a high-level task description into a list of concrete subtasks
with dependency and complexity annotations.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class SubTaskComplexity(StrEnum):
    """Estimated complexity tier for a subtask."""

    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


@dataclass(slots=True)
class SubTask:
    """A decomposed subtask produced by :class:`TaskSplitter`."""

    id: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    estimated_complexity: SubTaskComplexity = SubTaskComplexity.SIMPLE
    category: str = ""


# ---------------------------------------------------------------------------
# LLM provider protocol
# ---------------------------------------------------------------------------


class _LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.2,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_split_prompt(task: str, context: str) -> str:
    """Build the LLM prompt for task splitting."""
    return (
        "You are a task decomposition expert. Break the following task "
        "into smaller, concrete subtasks.\n\n"
        f"## Task\n{task}\n\n"
        f"## Context\n{context or 'No additional context.'}\n\n"
        "## Instructions\n"
        "Return a JSON array of subtask objects. Each object has:\n"
        '  - "id": unique ID like "sub-1", "sub-2", ...\n'
        '  - "description": concise description of the subtask\n'
        '  - "dependencies": list of subtask IDs this depends on\n'
        '  - "estimated_complexity": one of "simple", "medium", "complex"\n'
        '  - "category": a short label (e.g. "setup", "implementation", '
        '"testing", "documentation")\n\n'
        "Return ONLY the JSON array, no markdown fences or extra text."
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_split_response(response: str) -> list[SubTask]:
    """Parse the LLM response into a list of :class:`SubTask` objects."""
    # Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", response.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        raw_tasks = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON array in the text
        match = re.search(r"\[[\s\S]*\]", response)
        if match:
            try:
                raw_tasks = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("Failed to parse split response JSON")
                return []
        else:
            logger.warning("No JSON array found in split response")
            return []

    subtasks: list[SubTask] = []
    for i, raw in enumerate(raw_tasks):
        complexity_str = raw.get("estimated_complexity", "simple")
        try:
            complexity = SubTaskComplexity(complexity_str)
        except ValueError:
            complexity = SubTaskComplexity.SIMPLE

        subtasks.append(
            SubTask(
                id=raw.get("id", f"sub-{i + 1}"),
                description=raw.get("description", f"Subtask {i + 1}"),
                dependencies=raw.get("dependencies", []),
                estimated_complexity=complexity,
                category=raw.get("category", ""),
            )
        )

    return subtasks


# ---------------------------------------------------------------------------
# Complexity estimation (heuristic fallback)
# ---------------------------------------------------------------------------


_COMPLEX_SIGNALS = frozenset([
    "refactor", "migrate", "redesign", "architect", "integrate",
    "security", "performance", "optimize", "concurrent", "distributed",
])

_SIMPLE_SIGNALS = frozenset([
    "rename", "typo", "comment", "log", "print", "version",
    "config", "constant", "import",
])


def estimate_complexity(subtask: SubTask) -> SubTaskComplexity:
    """Heuristic complexity estimate for a subtask.

    If the subtask already has a non-default complexity, it is returned
    as-is.  Otherwise, keyword analysis is used.
    """
    if subtask.estimated_complexity != SubTaskComplexity.SIMPLE:
        return subtask.estimated_complexity

    desc_lower = subtask.description.lower()

    complex_hits = sum(1 for kw in _COMPLEX_SIGNALS if kw in desc_lower)
    simple_hits = sum(1 for kw in _SIMPLE_SIGNALS if kw in desc_lower)

    if complex_hits >= 2:
        return SubTaskComplexity.COMPLEX
    if complex_hits >= 1 and simple_hits == 0:
        return SubTaskComplexity.MEDIUM
    return SubTaskComplexity.SIMPLE


# ---------------------------------------------------------------------------
# TaskSplitter
# ---------------------------------------------------------------------------


class TaskSplitter:
    """Splits a task description into subtasks using an LLM.

    Falls back to a single subtask if no provider is configured or
    the LLM call fails.
    """

    def __init__(
        self,
        provider: _LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model

    async def split(
        self,
        task_description: str,
        context: str = "",
    ) -> list[SubTask]:
        """Decompose *task_description* into subtasks via LLM."""
        if self._provider is None:
            return self._fallback_split(task_description)

        prompt = build_split_prompt(task_description, context)
        try:
            response = await self._provider.chat(
                [{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=2000,
                temperature=0.2,
            )
            content = _extract_content(response)
            subtasks = parse_split_response(content)
            if subtasks:
                # Refine complexity estimates
                for st in subtasks:
                    st.estimated_complexity = estimate_complexity(st)
                return subtasks
        except Exception:
            logger.warning("Task split LLM call failed, using fallback")

        return self._fallback_split(task_description)

    @staticmethod
    def _fallback_split(task_description: str) -> list[SubTask]:
        """Produce a single subtask when LLM splitting is unavailable."""
        return [
            SubTask(
                id="sub-1",
                description=task_description,
                estimated_complexity=SubTaskComplexity.MEDIUM,
                category="general",
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_content(response: dict[str, Any] | str) -> str:
    if isinstance(response, str):
        return response
    content = response.get("content", "")
    if not content:
        msg = response.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
    return content
