"""Complexity classifier for task analysis.

Classifies tasks by complexity to inform tool selection,
budget allocation, and execution strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Complexity(StrEnum):
    """Task complexity level."""

    TRIVIAL = "trivial"  # Simple question, one-liner
    SIMPLE = "simple"  # Single file change, clear instructions
    MODERATE = "moderate"  # Multi-file change, some ambiguity
    COMPLEX = "complex"  # Architectural change, multiple systems
    DEEP_RESEARCH = "deep_research"  # Requires extensive exploration


@dataclass(slots=True)
class ComplexityAssessment:
    """Assessment of task complexity."""

    level: Complexity
    confidence: float  # 0.0-1.0
    reason: str
    estimated_iterations: int
    suggested_budget_multiplier: float = 1.0


# Keyword patterns for complexity signals
_TRIVIAL_PATTERNS = re.compile(
    r"\b(what is|explain|show|list|tell me|how do|what does)\b",
    re.IGNORECASE,
)

_COMPLEX_PATTERNS = re.compile(
    r"\b(refactor|redesign|architect|migrate|rewrite|overhaul|restructure)\b",
    re.IGNORECASE,
)

_DEEP_RESEARCH_PATTERNS = re.compile(
    r"\b(investigate|research|analyze|audit|compare|evaluate|benchmark|profile)\b",
    re.IGNORECASE,
)

_MULTI_FILE_INDICATORS = re.compile(
    r"\b(all files|every file|across|throughout|everywhere|multiple|several|many)\b",
    re.IGNORECASE,
)


def classify_complexity(
    prompt: str,
    *,
    file_count: int = 0,
    has_code_context: bool = False,
) -> ComplexityAssessment:
    """Classify the complexity of a task prompt.

    Args:
        prompt: The user's task description.
        file_count: Number of files in the project (0 = unknown).
        has_code_context: Whether codebase context is available.

    Returns:
        ComplexityAssessment with level and metadata.
    """
    prompt_lower = prompt.lower()
    word_count = len(prompt.split())

    # Very short prompts are usually trivial
    if word_count <= 5 and not _COMPLEX_PATTERNS.search(prompt):
        return ComplexityAssessment(
            level=Complexity.TRIVIAL,
            confidence=0.7,
            reason="Very short prompt",
            estimated_iterations=2,
            suggested_budget_multiplier=0.5,
        )

    # Check for deep research patterns
    if _DEEP_RESEARCH_PATTERNS.search(prompt):
        return ComplexityAssessment(
            level=Complexity.DEEP_RESEARCH,
            confidence=0.6,
            reason="Research/analysis keywords detected",
            estimated_iterations=30,
            suggested_budget_multiplier=2.0,
        )

    # Check for complex patterns
    if _COMPLEX_PATTERNS.search(prompt):
        multi_file = bool(_MULTI_FILE_INDICATORS.search(prompt))
        return ComplexityAssessment(
            level=Complexity.COMPLEX,
            confidence=0.7,
            reason="Architectural/refactoring keywords detected",
            estimated_iterations=20 if multi_file else 15,
            suggested_budget_multiplier=1.5,
        )

    # Check for trivial patterns (questions, simple queries)
    if _TRIVIAL_PATTERNS.search(prompt) and word_count <= 15:
        return ComplexityAssessment(
            level=Complexity.TRIVIAL,
            confidence=0.6,
            reason="Question/explanation pattern",
            estimated_iterations=3,
            suggested_budget_multiplier=0.5,
        )

    # Multi-file indicators without complex keywords = moderate
    if _MULTI_FILE_INDICATORS.search(prompt):
        return ComplexityAssessment(
            level=Complexity.MODERATE,
            confidence=0.5,
            reason="Multi-file scope indicators",
            estimated_iterations=10,
            suggested_budget_multiplier=1.2,
        )

    # Default based on prompt length
    if word_count > 50:
        return ComplexityAssessment(
            level=Complexity.MODERATE,
            confidence=0.4,
            reason="Long prompt suggests moderate complexity",
            estimated_iterations=10,
            suggested_budget_multiplier=1.0,
        )

    return ComplexityAssessment(
        level=Complexity.SIMPLE,
        confidence=0.5,
        reason="Default classification",
        estimated_iterations=5,
        suggested_budget_multiplier=1.0,
    )
