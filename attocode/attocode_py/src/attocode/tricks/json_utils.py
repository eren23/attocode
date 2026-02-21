"""JSON extraction utilities.

Provides robust extraction and parsing of JSON from LLM responses,
handling common issues like markdown code fences, trailing commas,
and partial JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> Any | None:
    """Extract JSON from text, handling common LLM output patterns.

    Handles:
    - Raw JSON
    - JSON in markdown code fences (```json ... ```)
    - JSON with trailing commas
    - JSON embedded in explanation text
    """
    # Try raw parse first
    parsed = _try_parse(text.strip())
    if parsed is not None:
        return parsed

    # Try extracting from code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        parsed = _try_parse(fence_match.group(1).strip())
        if parsed is not None:
            return parsed

    # Try finding JSON object/array boundaries
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        extracted = _extract_balanced(text, start_char, end_char)
        if extracted:
            parsed = _try_parse(extracted)
            if parsed is not None:
                return parsed

    return None


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract all JSON objects from text."""
    objects: list[dict[str, Any]] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            extracted = _extract_balanced(text[i:], "{", "}")
            if extracted:
                parsed = _try_parse(extracted)
                if isinstance(parsed, dict):
                    objects.append(parsed)
                    i += len(extracted)
                    continue
        i += 1
    return objects


def extract_json_array(text: str) -> list[Any] | None:
    """Extract a JSON array from text."""
    result = extract_json(text)
    if isinstance(result, list):
        return result
    return None


def fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before closing brackets."""
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text


def fix_single_quotes(text: str) -> str:
    """Convert single-quoted strings to double-quoted (simple cases)."""
    # Only for simple cases where single quotes are used as string delimiters
    result = []
    in_string = False
    quote_char = ""
    i = 0
    while i < len(text):
        c = text[i]
        if not in_string:
            if c == "'":
                result.append('"')
                in_string = True
                quote_char = "'"
            elif c == '"':
                result.append(c)
                in_string = True
                quote_char = '"'
            else:
                result.append(c)
        else:
            if c == quote_char and (i == 0 or text[i - 1] != "\\"):
                result.append('"' if quote_char == "'" else c)
                in_string = False
            else:
                result.append(c)
        i += 1
    return "".join(result)


def safe_parse(text: str) -> Any | None:
    """Parse JSON with automatic fixing of common issues."""
    # Try raw first
    parsed = _try_parse(text)
    if parsed is not None:
        return parsed

    # Try fixing trailing commas
    fixed = fix_trailing_commas(text)
    parsed = _try_parse(fixed)
    if parsed is not None:
        return parsed

    # Try fixing quotes
    fixed = fix_single_quotes(text)
    parsed = _try_parse(fixed)
    if parsed is not None:
        return parsed

    # Try both fixes
    fixed = fix_trailing_commas(fix_single_quotes(text))
    parsed = _try_parse(fixed)
    if parsed is not None:
        return parsed

    return None


def truncate_json(obj: Any, max_depth: int = 5, max_items: int = 50) -> Any:
    """Truncate a JSON-serializable object to limit depth and size."""
    return _truncate(obj, max_depth, max_items, 0)


def _truncate(obj: Any, max_depth: int, max_items: int, depth: int) -> Any:
    if depth >= max_depth:
        if isinstance(obj, dict):
            return {"...": f"({len(obj)} keys truncated)"}
        if isinstance(obj, list):
            return [f"...({len(obj)} items truncated)"]
        return obj

    if isinstance(obj, dict):
        items = list(obj.items())
        if len(items) > max_items:
            truncated = dict(items[:max_items])
            truncated["..."] = f"({len(items) - max_items} more keys)"
            return {k: _truncate(v, max_depth, max_items, depth + 1) for k, v in truncated.items()}
        return {k: _truncate(v, max_depth, max_items, depth + 1) for k, v in items}

    if isinstance(obj, list):
        if len(obj) > max_items:
            truncated = obj[:max_items] + [f"...({len(obj) - max_items} more items)"]
            return [_truncate(item, max_depth, max_items, depth + 1) for item in truncated]
        return [_truncate(item, max_depth, max_items, depth + 1) for item in obj]

    return obj


def _try_parse(text: str) -> Any | None:
    """Try to parse JSON, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_balanced(text: str, open_char: str, close_char: str) -> str | None:
    """Extract a balanced substring between open and close characters."""
    start = text.find(open_char)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        c = text[i]

        if escape:
            escape = False
            continue

        if c == "\\":
            escape = True
            continue

        if c == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None
