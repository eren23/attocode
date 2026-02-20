"""Task decomposer for breaking complex tasks into steps.

Uses heuristic analysis and optionally LLM to decompose
complex tasks into manageable subtasks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ComplexityTier(StrEnum):
    """Task complexity classification."""

    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    DEEP_RESEARCH = "deep_research"


@dataclass
class ComplexityAssessment:
    """Result of complexity classification."""

    tier: ComplexityTier
    confidence: float
    reasoning: str
    signals: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DecomposedTask:
    """A subtask from decomposition."""

    description: str
    dependencies: list[int] = field(default_factory=list)
    estimated_complexity: ComplexityTier = ComplexityTier.SIMPLE
    tools_needed: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    """Result of task decomposition."""

    original_task: str
    subtasks: list[DecomposedTask]
    complexity: ComplexityAssessment
    strategy: str = ""


# Keywords for complexity classification
_COMPLEX_KEYWORDS = frozenset([
    "refactor", "migrate", "redesign", "rewrite", "overhaul",
    "implement", "build", "create", "develop", "architect",
    "integrate", "optimize", "performance", "security", "audit",
    "first", "then", "after that", "next", "finally",
    "investigate", "analyze", "benchmark", "compare", "evaluate",
])

_SIMPLE_KEYWORDS = frozenset([
    "fix typo", "rename", "update version", "what is", "how does",
    "explain", "show", "list", "find", "check",
])

_DEPENDENCY_PATTERNS = [
    re.compile(r"first\s.*then", re.IGNORECASE),
    re.compile(r"step\s+\d", re.IGNORECASE),
    re.compile(r"phase\s+\d", re.IGNORECASE),
    re.compile(r"after\s+(?:that|this)", re.IGNORECASE),
    re.compile(r"before\s+\w+ing", re.IGNORECASE),
    re.compile(r"once\s+\w+\s+is", re.IGNORECASE),
]


def classify_complexity(
    task: str,
    project_file_count: int | None = None,
) -> ComplexityAssessment:
    """Classify task complexity using heuristic scoring.

    Uses weighted signals: task length, keyword matching,
    dependency patterns, and scope indicators.
    """
    words = task.lower().split()
    word_count = len(words)
    task_lower = task.lower()

    signals: list[dict[str, Any]] = []

    # Signal 1: Task length
    if word_count < 10:
        length_score = 0.0
    elif word_count < 30:
        length_score = 1.0
    elif word_count < 80:
        length_score = 2.0
    else:
        length_score = 3.0
    signals.append({"name": "task_length", "value": length_score, "weight": 0.15})

    # Signal 2: Complex keywords
    complex_count = sum(1 for kw in _COMPLEX_KEYWORDS if kw in task_lower)
    complex_score = min(complex_count * 1.5, 4.0)
    signals.append({"name": "complex_keywords", "value": complex_score, "weight": 0.25})

    # Signal 3: Simple keywords (negative signal)
    simple_match = any(kw in task_lower for kw in _SIMPLE_KEYWORDS)
    simple_score = -2.0 if simple_match else 0.0
    signals.append({"name": "simple_keywords", "value": simple_score, "weight": 0.20})

    # Signal 4: Dependency patterns
    dep_count = sum(1 for p in _DEPENDENCY_PATTERNS if p.search(task))
    dep_score = dep_count * 2.0
    signals.append({"name": "dependency_patterns", "value": dep_score, "weight": 0.20})

    # Signal 5: Question vs action
    question_words = {"what", "how", "why", "when", "where", "which", "who", "is", "are", "can", "does"}
    first_word = words[0] if words else ""
    q_score = -1.0 if first_word in question_words else 1.0
    signals.append({"name": "question_vs_action", "value": q_score, "weight": 0.10})

    # Signal 6: Scope indicators
    ext_count = len(re.findall(r"\.\w{1,4}\b", task))
    dir_count = len(re.findall(r"[\w-]+/", task))
    scope_score = min((ext_count + dir_count) * 0.5, 3.0)
    signals.append({"name": "scope_indicators", "value": scope_score, "weight": 0.10})

    # Weighted sum
    weighted_sum = sum(s["value"] * s["weight"] for s in signals)

    # Determine tier
    if weighted_sum < 0.5:
        tier = ComplexityTier.SIMPLE
    elif weighted_sum < 1.5:
        tier = ComplexityTier.MEDIUM
    elif weighted_sum < 2.5:
        tier = ComplexityTier.COMPLEX
    else:
        tier = ComplexityTier.DEEP_RESEARCH

    # Confidence from signal variance
    values = [s["value"] for s in signals if s["value"] != 0]
    if len(values) > 1:
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        confidence = max(0.3, min(1.0, 1.0 - variance / 10))
    else:
        confidence = 0.7

    return ComplexityAssessment(
        tier=tier,
        confidence=confidence,
        reasoning=f"Weighted score: {weighted_sum:.2f}",
        signals=signals,
    )


def decompose_simple(task: str) -> DecompositionResult:
    """Simple heuristic decomposition without LLM.

    Splits tasks based on conjunctions and sequential indicators.
    """
    complexity = classify_complexity(task)

    if complexity.tier == ComplexityTier.SIMPLE:
        return DecompositionResult(
            original_task=task,
            subtasks=[DecomposedTask(description=task)],
            complexity=complexity,
            strategy="single_task",
        )

    # Try to split on sequential indicators
    parts = re.split(
        r"(?:,\s*then\s+|;\s*then\s+|\.\s*Then\s+|\.\s*Next[,]?\s+|\.\s*After that[,]?\s+|\.\s*Finally[,]?\s+)",
        task,
    )

    if len(parts) <= 1:
        # Try splitting on numbered steps
        parts = re.split(r"\d+[.)]\s*", task)
        parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return DecompositionResult(
            original_task=task,
            subtasks=[DecomposedTask(description=task)],
            complexity=complexity,
            strategy="single_task",
        )

    subtasks = []
    for i, part in enumerate(parts):
        part = part.strip().rstrip(".")
        if not part:
            continue
        deps = [i - 1] if i > 0 else []
        subtasks.append(DecomposedTask(description=part, dependencies=deps))

    return DecompositionResult(
        original_task=task,
        subtasks=subtasks,
        complexity=complexity,
        strategy="sequential_split",
    )
