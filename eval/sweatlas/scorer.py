"""Rubric-based scoring for SWE-Atlas QnA evaluation.

Parses SWE-Atlas rubric JSON and scores agent answers against each criterion
using an LLM judge (binary met/unmet per criterion).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RubricCriterion:
    """Single rubric criterion."""

    id: str
    title: str
    criterion_type: str  # "positive hli verifier" or "negative hli verifier"
    importance: str  # "must have", "nice to have", etc.

    @property
    def is_positive(self) -> bool:
        return "positive" in self.criterion_type.lower()


@dataclass
class TaskScore:
    """Scoring result for a single SWE-Atlas task."""

    task_id: str
    category: str
    repo: str
    rubric_total: int = 0
    rubric_met: int = 0
    criteria_results: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def score(self) -> float:
        """Fraction of rubric criteria met (0.0-1.0)."""
        return self.rubric_met / self.rubric_total if self.rubric_total > 0 else 0.0

    @property
    def resolved(self) -> bool:
        """Whether all criteria are met (task resolve rate metric)."""
        return self.rubric_met == self.rubric_total and self.rubric_total > 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "repo": self.repo,
            "rubric_total": self.rubric_total,
            "rubric_met": self.rubric_met,
            "score": round(self.score, 3),
            "resolved": self.resolved,
            "criteria_results": self.criteria_results,
            "error": self.error,
        }


def parse_rubric(rubric_raw: str) -> list[RubricCriterion]:
    """Parse SWE-Atlas rubric JSON into structured criteria."""
    try:
        data = json.loads(rubric_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse rubric JSON, treating as empty")
        return []

    criteria = []
    # Handle both list format and dict-with-list format
    items = data if isinstance(data, list) else data.get("criteria", data.get("items", []))
    if isinstance(data, dict) and not items:
        # Try top-level keys as items
        items = [data] if "title" in data else []

    for item in items:
        if not isinstance(item, dict):
            continue
        annotations = item.get("annotations", {})
        criteria.append(
            RubricCriterion(
                id=item.get("id", ""),
                title=item.get("title", item.get("description", "")),
                criterion_type=annotations.get("type", "positive hli verifier"),
                importance=annotations.get("importance", "must have"),
            )
        )

    return criteria


async def score_answer(
    answer: str,
    reference_answer: str,
    prompt: str,
    criteria: list[RubricCriterion],
    *,
    model: str = "",
    max_concurrent: int = 5,
) -> list[dict]:
    """Score an answer against rubric criteria using LLM judge.

    Returns list of {criterion_id, title, met: bool, reasoning: str}.
    """
    try:
        import anthropic
    except ImportError:
        return [{"criterion_id": c.id, "title": c.title, "met": False,
                 "reasoning": "anthropic SDK not installed"} for c in criteria]

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return [{"criterion_id": c.id, "title": c.title, "met": False,
                 "reasoning": "ANTHROPIC_API_KEY not set"} for c in criteria]

    model = model or os.environ.get("SWEATLAS_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _score_one(criterion: RubricCriterion) -> dict:
        async with semaphore:
            return await _evaluate_criterion(
                client, model, answer, reference_answer, prompt, criterion
            )

    results = await asyncio.gather(*[_score_one(c) for c in criteria])
    return list(results)


async def _evaluate_criterion(
    client,
    model: str,
    answer: str,
    reference_answer: str,
    prompt: str,
    criterion: RubricCriterion,
) -> dict:
    """Evaluate a single rubric criterion against the answer."""
    if criterion.is_positive:
        judge_prompt = f"""You are evaluating whether an AI agent's answer to a codebase question meets a specific criterion.

**Question asked**: {prompt[:500]}

**Criterion to check**: {criterion.title}

**Agent's answer** (evaluate this):
{answer[:4000]}

**Reference answer** (ground truth for context):
{reference_answer[:3000]}

Does the agent's answer satisfy the criterion above?
Think about whether the key information described in the criterion is present and correct in the agent's answer.

Respond with ONLY a JSON object (no markdown fences):
{{"met": true/false, "reasoning": "<one sentence explanation>"}}"""
    else:
        # Negative verifier — criterion should NOT be true in the answer
        judge_prompt = f"""You are evaluating whether an AI agent's answer to a codebase question avoids a specific incorrect claim.

**Question asked**: {prompt[:500]}

**Incorrect claim to check for**: {criterion.title}

**Agent's answer** (evaluate this):
{answer[:4000]}

Does the agent's answer AVOID making the incorrect claim described above?
The criterion is met if the answer does NOT contain this incorrect information.

Respond with ONLY a JSON object (no markdown fences):
{{"met": true/false, "reasoning": "<one sentence explanation>"}}"""

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": judge_prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)

        return {
            "criterion_id": criterion.id,
            "title": criterion.title[:100],
            "type": criterion.criterion_type,
            "importance": criterion.importance,
            "met": bool(data.get("met", False)),
            "reasoning": data.get("reasoning", ""),
        }
    except Exception as e:
        logger.warning("Criterion scoring failed for %s: %s", criterion.id, e)
        return {
            "criterion_id": criterion.id,
            "title": criterion.title[:100],
            "type": criterion.criterion_type,
            "importance": criterion.importance,
            "met": False,
            "reasoning": f"Scoring error: {e}",
        }


def compute_task_score(
    task_id: str,
    category: str,
    repo: str,
    criteria_results: list[dict],
) -> TaskScore:
    """Aggregate criterion-level results into a task score."""
    met_count = sum(1 for r in criteria_results if r.get("met", False))
    return TaskScore(
        task_id=task_id,
        category=category,
        repo=repo,
        rubric_total=len(criteria_results),
        rubric_met=met_count,
        criteria_results=criteria_results,
    )


def format_report(
    scores: list[TaskScore],
    mode: str = "with_code_intel",
    compare_scores: list[TaskScore] | None = None,
) -> str:
    """Generate a markdown report from task scores."""
    lines = [
        "# SWE-Atlas QnA Evaluation Report",
        "",
        f"**Mode**: {mode}",
        f"**Tasks evaluated**: {len(scores)}",
        "",
    ]

    # Overall metrics
    total_resolved = sum(1 for s in scores if s.resolved)
    avg_score = sum(s.score for s in scores) / len(scores) if scores else 0

    lines.append("## Overall Metrics")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Task Resolve Rate | {total_resolved}/{len(scores)} ({100*total_resolved/len(scores):.1f}%) |")
    lines.append(f"| Avg Rubric Score | {avg_score:.3f} |")
    lines.append("")

    # Per-category breakdown
    categories: dict[str, list[TaskScore]] = {}
    for s in scores:
        categories.setdefault(s.category, []).append(s)

    lines.append("## Per-Category Breakdown")
    lines.append("")

    if compare_scores:
        compare_cats: dict[str, list[TaskScore]] = {}
        for s in compare_scores:
            compare_cats.setdefault(s.category, []).append(s)

        lines.append("| Category | Tasks | With CI Score | Baseline Score | Delta |")
        lines.append("|----------|-------|---------------|----------------|-------|")
        for cat, cat_scores in sorted(categories.items()):
            ci_avg = sum(s.score for s in cat_scores) / len(cat_scores)
            bl_scores = compare_cats.get(cat, [])
            bl_avg = sum(s.score for s in bl_scores) / len(bl_scores) if bl_scores else 0
            delta = ci_avg - bl_avg
            lines.append(f"| {cat} | {len(cat_scores)} | {ci_avg:.3f} | {bl_avg:.3f} | {delta:+.3f} |")
    else:
        lines.append("| Category | Tasks | Avg Score | Resolved | Resolve Rate |")
        lines.append("|----------|-------|-----------|----------|--------------|")
        for cat, cat_scores in sorted(categories.items()):
            cat_avg = sum(s.score for s in cat_scores) / len(cat_scores)
            cat_resolved = sum(1 for s in cat_scores if s.resolved)
            rate = 100 * cat_resolved / len(cat_scores) if cat_scores else 0
            lines.append(f"| {cat} | {len(cat_scores)} | {cat_avg:.3f} | {cat_resolved}/{len(cat_scores)} | {rate:.1f}% |")

    lines.append("")

    # Per-repo breakdown
    repos: dict[str, list[TaskScore]] = {}
    for s in scores:
        repos.setdefault(s.repo, []).append(s)

    lines.append("## Per-Repo Breakdown")
    lines.append("")
    lines.append("| Repo | Tasks | Avg Score | Resolved |")
    lines.append("|------|-------|-----------|----------|")
    for repo, repo_scores in sorted(repos.items()):
        repo_avg = sum(s.score for s in repo_scores) / len(repo_scores)
        repo_resolved = sum(1 for s in repo_scores if s.resolved)
        lines.append(f"| {repo} | {len(repo_scores)} | {repo_avg:.3f} | {repo_resolved}/{len(repo_scores)} |")

    lines.append("")
    return "\n".join(lines)
