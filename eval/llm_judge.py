"""LLM-as-judge evaluation scorer.

Uses Claude to evaluate code intelligence output quality on a structured
rubric. Supports both single-output scoring and pairwise comparison
(code-intel vs grep baseline).

Usage:
    from eval.llm_judge import score_output, compare_outputs

    # Single scoring
    result = await score_output(query="find all callers of main()", output=ci_output)

    # Pairwise comparison
    result = await compare_outputs(
        query="find all callers of main()",
        output_a=ci_output,   # code-intel
        output_b=grep_output,  # grep baseline
    )
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

RUBRIC_DIMENSIONS = {
    "completeness": "Does the output fully answer the question? Are all relevant files, symbols, or relationships included?",
    "accuracy": "Are the file paths, symbols, line numbers, and relationships factually correct?",
    "depth": "Does the output provide transitive/structural insights beyond surface-level grep matches? (e.g., dependency chains, impact analysis, community detection)",
    "actionability": "Could a developer immediately act on this information? Are next steps clear?",
    "signal_to_noise": "Is the output focused and relevant, or cluttered with irrelevant files/results?",
}


@dataclass
class JudgeResult:
    """Result from LLM judge evaluation."""
    scores: dict[str, float] = field(default_factory=dict)  # dimension -> 1-5 score
    overall: float = 0.0
    reasoning: str = ""
    error: str = ""

    @property
    def avg_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.scores.values()) / len(self.scores)


@dataclass
class ComparisonResult:
    """Result from pairwise comparison."""
    winner: str = ""  # "a", "b", "tie"
    scores_a: dict[str, float] = field(default_factory=dict)
    scores_b: dict[str, float] = field(default_factory=dict)
    overall_a: float = 0.0
    overall_b: float = 0.0
    reasoning: str = ""
    error: str = ""


def _build_scoring_prompt(query: str, output: str, task_type: str = "") -> str:
    """Build the prompt for single-output scoring."""
    rubric_text = "\n".join(
        f"- **{dim}** (1-5): {desc}" for dim, desc in RUBRIC_DIMENSIONS.items()
    )
    return f"""You are evaluating the quality of a code intelligence tool's output.

**Task/Query**: {query}
{f'**Task Type**: {task_type}' if task_type else ''}

**Output to evaluate**:
```
{output[:3000]}
```

**Scoring Rubric** (score each dimension 1-5):
{rubric_text}

Respond with ONLY a JSON object (no markdown fences):
{{
    "completeness": <1-5>,
    "accuracy": <1-5>,
    "depth": <1-5>,
    "actionability": <1-5>,
    "signal_to_noise": <1-5>,
    "overall": <1-5>,
    "reasoning": "<brief explanation>"
}}"""


def _build_comparison_prompt(query: str, output_a: str, output_b: str) -> str:
    """Build the prompt for pairwise comparison."""
    rubric_text = "\n".join(
        f"- **{dim}** (1-5): {desc}" for dim, desc in RUBRIC_DIMENSIONS.items()
    )
    return f"""You are comparing two code analysis outputs for the same query. Output A is from a code intelligence tool with AST parsing, dependency graphs, and semantic search. Output B is from grep/ripgrep text search only.

**Query**: {query}

**Output A (Code Intelligence)**:
```
{output_a[:2500]}
```

**Output B (Grep Baseline)**:
```
{output_b[:2500]}
```

**Scoring Rubric** (score each dimension 1-5 for BOTH outputs):
{rubric_text}

Respond with ONLY a JSON object (no markdown fences):
{{
    "scores_a": {{"completeness": <1-5>, "accuracy": <1-5>, "depth": <1-5>, "actionability": <1-5>, "signal_to_noise": <1-5>}},
    "scores_b": {{"completeness": <1-5>, "accuracy": <1-5>, "depth": <1-5>, "actionability": <1-5>, "signal_to_noise": <1-5>}},
    "overall_a": <1-5>,
    "overall_b": <1-5>,
    "winner": "a" | "b" | "tie",
    "reasoning": "<brief explanation of why one is better>"
}}"""


async def score_output(
    query: str,
    output: str,
    task_type: str = "",
    model: str = "",
) -> JudgeResult:
    """Score a single output using LLM judge."""
    try:
        import anthropic
    except ImportError:
        return JudgeResult(error="anthropic SDK not installed: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JudgeResult(error="ANTHROPIC_API_KEY not set")

    model = model or os.environ.get("LLM_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    prompt = _build_scoring_prompt(query, output, task_type)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON — handle potential markdown fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)

        return JudgeResult(
            scores={k: float(data.get(k, 0)) for k in RUBRIC_DIMENSIONS},
            overall=float(data.get("overall", 0)),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("LLM judge failed: %s", e)
        return JudgeResult(error=str(e))


async def compare_outputs(
    query: str,
    output_a: str,
    output_b: str,
    model: str = "",
) -> ComparisonResult:
    """Compare two outputs using LLM judge (pairwise)."""
    try:
        import anthropic
    except ImportError:
        return ComparisonResult(error="anthropic SDK not installed: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ComparisonResult(error="ANTHROPIC_API_KEY not set")

    model = model or os.environ.get("LLM_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    prompt = _build_comparison_prompt(query, output_a, output_b)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)

        return ComparisonResult(
            winner=data.get("winner", "tie"),
            scores_a={k: float(v) for k, v in data.get("scores_a", {}).items()},
            scores_b={k: float(v) for k, v in data.get("scores_b", {}).items()},
            overall_a=float(data.get("overall_a", 0)),
            overall_b=float(data.get("overall_b", 0)),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("LLM comparison failed: %s", e)
        return ComparisonResult(error=str(e))


# Synchronous wrappers for non-async contexts
def score_output_sync(query: str, output: str, **kwargs: Any) -> JudgeResult:
    """Synchronous wrapper for score_output."""
    import asyncio
    return asyncio.run(score_output(query, output, **kwargs))


def compare_outputs_sync(query: str, output_a: str, output_b: str, **kwargs: Any) -> ComparisonResult:
    """Synchronous wrapper for compare_outputs."""
    import asyncio
    return asyncio.run(compare_outputs(query, output_a, output_b, **kwargs))
