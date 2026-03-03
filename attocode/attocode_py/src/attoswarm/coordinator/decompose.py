"""Complexity-aware goal decomposition for swarm orchestration.

Classifies goal complexity and adjusts the LLM decomposition prompt
accordingly, producing more granular task graphs for complex goals.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from attoswarm.protocol.models import TaskSpec

logger = logging.getLogger(__name__)

# Complexity tier → (min_tasks, max_tasks)
_TASK_RANGE: dict[str, tuple[int, int]] = {
    "simple": (2, 3),
    "medium": (3, 5),
    "complex": (6, 10),
    "deep_research": (8, 15),
}

# Keywords that signal high complexity (each match adds weight)
_COMPLEX_KEYWORDS = re.compile(
    r"\b(?:distributed|replicated|consensus|gossip|vector.clock|quorum|"
    r"anti.entropy|raft|paxos|crdt|sharding|partitioning|fault.tolerant|"
    r"load.balanc\w*|circuit.breaker|chaos|mesh|microservice\w*|event.sourc\w*|"
    r"saga|cqrs|websocket\w*|streaming|real.time|concurrent|parallel|"
    r"authentication|authorization|oauth|jwt|encryption|tls|ssl|"
    r"migration\w*|schema\w*|index\w*|cach\w*|queue\w*|pubsub|webhook\w*)",
    re.IGNORECASE,
)

# Structural markers that indicate multiple distinct subsystems
_SUBSYSTEM_MARKERS = re.compile(
    r"(?:^\s*[-*•]\s+|\d+\.\s+|#{1,3}\s+|\b(?:module|component|service|layer|subsystem)\b)",
    re.MULTILINE | re.IGNORECASE,
)


def classify_goal_complexity(goal: str) -> str:
    """Classify goal complexity into simple/medium/complex/deep_research.

    Uses heuristics: word count, keyword density, subsystem count,
    and structural indicators.
    """
    words = goal.split()
    word_count = len(words)

    # Keyword matches
    keyword_hits = len(_COMPLEX_KEYWORDS.findall(goal))

    # Subsystem markers (bullet points, numbered lists, headings)
    subsystem_hits = len(_SUBSYSTEM_MARKERS.findall(goal))

    # Line count
    line_count = len(goal.strip().splitlines())

    # Scoring
    score = 0.0

    # Word count signal
    if word_count > 500:
        score += 3.0
    elif word_count > 200:
        score += 2.0
    elif word_count > 80:
        score += 1.0

    # Keyword density
    if keyword_hits >= 8:
        score += 3.0
    elif keyword_hits >= 4:
        score += 2.0
    elif keyword_hits >= 2:
        score += 1.0

    # Subsystem count
    if subsystem_hits >= 6:
        score += 3.0
    elif subsystem_hits >= 3:
        score += 2.0
    elif subsystem_hits >= 1:
        score += 0.5

    # Line count
    if line_count >= 30:
        score += 1.0

    # Classify
    if score >= 6.0:
        return "deep_research"
    if score >= 3.0:
        return "complex"
    if score >= 1.0:
        return "medium"
    return "simple"


def build_decompose_prompt(
    goal: str,
    *,
    complexity: str,
    max_tasks: int,
    role_descriptions: str = "",
    custom_instructions: str = "",
) -> str:
    """Build a complexity-aware decomposition prompt."""
    min_tasks, target_max = _TASK_RANGE.get(complexity, (3, 5))
    # Respect config max but use complexity-informed defaults
    effective_max = min(max_tasks, target_max) if max_tasks else target_max

    prefix = ""
    if custom_instructions:
        prefix = f"## Custom Instructions\n{custom_instructions}\n\n"

    granularity_guidance = ""
    if complexity in ("complex", "deep_research"):
        granularity_guidance = (
            "\n## Granularity Guidelines (CRITICAL)\n"
            "- Each task should focus on ONE specific subsystem or concern.\n"
            "- Do NOT bundle multiple independent features into a single task.\n"
            "- If a task description mentions 3+ distinct features separated by "
            "commas or 'and', split it into separate tasks.\n"
            "- Prefer more fine-grained tasks over fewer large tasks.\n"
            f"- Target {min_tasks}-{effective_max} tasks for this goal's complexity.\n"
        )
    else:
        granularity_guidance = (
            f"\n## Task Count\n"
            f"- Produce between {min_tasks} and {effective_max} tasks.\n"
        )

    return (
        prefix
        + "You are a task decomposition engine for a multi-agent coding swarm.\n\n"
        "Given the following goal, decompose it into a DAG of concrete, actionable tasks.\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Available Roles\n{role_descriptions or '  (none configured -- omit role_hint)'}\n"
        f"{granularity_guidance}\n"
        "## Constraints\n"
        "- Each task should be completable by a single agent in one pass.\n"
        "- Tasks should have clear boundaries -- avoid overlapping target files.\n"
        "- Use deps to express dependencies (task_id references).\n"
        "- Assign role_hint matching an available role_id when appropriate.\n"
        "- Include integration/test tasks that verify the components work together.\n\n"
        "## Output Format\n"
        "Respond with ONLY a JSON array (no markdown fences, no explanation):\n"
        "[\n"
        '  {\n'
        '    "task_id": "task-1",\n'
        '    "title": "Short title (one subsystem only)",\n'
        '    "description": "Detailed description of what to do",\n'
        '    "deps": [],\n'
        '    "target_files": ["src/foo.py"],\n'
        '    "role_hint": "impl",\n'
        '    "task_kind": "implement"\n'
        "  }\n"
        "]\n\n"
        "task_kind should be one of: analysis, design, implement, test, integrate, judge, critic, merge"
    )


def build_retry_prompt(
    goal: str,
    *,
    complexity: str,
    custom_instructions: str = "",
) -> str:
    """Simpler retry prompt that still respects complexity."""
    min_tasks, max_tasks = _TASK_RANGE.get(complexity, (3, 5))
    prefix = ""
    if custom_instructions:
        prefix = f"## Custom Instructions\n{custom_instructions}\n\n"
    return (
        prefix
        + f"Decompose this goal into {min_tasks}-{max_tasks} coding tasks. "
        "Return ONLY a JSON array.\n\n"
        f"Goal: {goal}\n\n"
        'Format: [{{"task_id": "task-1", "title": "...", "description": "...", '
        '"deps": [], "target_files": [], "role_hint": "", "task_kind": "implement"}}]'
    )


def validate_decomposition(tasks: list[dict[str, Any]], complexity: str) -> list[dict[str, Any]]:
    """Validate and warn about task granularity issues.

    Returns a list of warning dicts (empty = all good).
    """
    warnings: list[dict[str, Any]] = []
    min_tasks, _ = _TASK_RANGE.get(complexity, (3, 5))

    if len(tasks) < min_tasks and complexity in ("complex", "deep_research"):
        warnings.append({
            "type": "too_few_tasks",
            "expected_min": min_tasks,
            "actual": len(tasks),
            "message": f"Only {len(tasks)} tasks for {complexity} goal (expected >= {min_tasks})",
        })

    # Check for tasks that bundle too many features
    for task in tasks:
        desc = task.get("description", "")
        title = task.get("title", "")
        # Count distinct feature mentions (separated by commas/and)
        combined = f"{title} {desc}"
        # Simple heuristic: count "and" or comma-separated clauses in title
        and_count = title.count(" and ") + title.count(",")
        if and_count >= 2:
            warnings.append({
                "type": "bundled_features",
                "task_id": task.get("task_id", ""),
                "and_count": and_count,
                "message": f"Task '{task.get('task_id')}' title has {and_count + 1} features — consider splitting",
            })

    return warnings
