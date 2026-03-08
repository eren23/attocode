"""Robust parsing of LLM-generated task decomposition JSON."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract and parse a JSON array from LLM output.

    Tries multiple strategies:
    1. Direct json.loads()
    2. Strip markdown fences + thinking tags
    3. Balanced bracket extraction
    """
    text = raw.strip()

    # Strategy 1: direct parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown fences and thinking tags
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json|JSON)?\s*\n?", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 3: balanced bracket extraction
    start = cleaned.find("[")
    if start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "[":
                depth += 1
            elif cleaned[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(cleaned[start : i + 1])
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON array from LLM output ({len(raw)} chars)")


def validate_task_specs(tasks: list[dict[str, Any]]) -> list[str]:
    """Validate a list of task spec dicts. Returns list of warning messages."""
    warnings: list[str] = []

    if len(tasks) < 1:
        warnings.append("Empty task list")
        return warnings

    ids = set()
    for t in tasks:
        tid = t.get("task_id", "")
        if not tid:
            warnings.append(f"Task missing task_id: {t}")
        if tid in ids:
            warnings.append(f"Duplicate task_id: {tid}")
        ids.add(tid)

        for dep in t.get("deps", []):
            if dep not in ids and dep not in {x.get("task_id") for x in tasks}:
                warnings.append(f"Task {tid} depends on unknown task {dep}")

    return warnings
