"""Tool argument coercion for weaker LLM models.

Weaker models sometimes return wrong types for tool arguments
(e.g., string "true" instead of boolean true, number as string).
This module coerces arguments to their expected types.
"""

from __future__ import annotations

from typing import Any


def coerce_boolean(value: Any) -> bool:
    """Coerce a value to boolean.

    Handles common LLM mistakes like:
    - "true" / "false" strings
    - "yes" / "no" strings
    - 0 / 1 integers
    - None

    Args:
        value: The value to coerce.

    Returns:
        Boolean value.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in ("true", "yes", "1", "on", "enabled"):
            return True
        if lower in ("false", "no", "0", "off", "disabled", "null", "none", ""):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


def coerce_string(value: Any) -> str:
    """Coerce a value to string.

    Handles:
    - None → ""
    - Numbers → str(n)
    - Lists → JSON-like string
    - Dicts → JSON-like string

    Args:
        value: The value to coerce.

    Returns:
        String value.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        import json
        return json.dumps(value)
    return str(value)


def coerce_integer(value: Any) -> int:
    """Coerce a value to integer.

    Handles:
    - Float → int
    - String number → int
    - Boolean → 0/1

    Args:
        value: The value to coerce.

    Returns:
        Integer value.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return int(float(stripped))
            except (ValueError, OverflowError):
                pass
    return 0


def coerce_number(value: Any) -> float:
    """Coerce a value to float.

    Args:
        value: The value to coerce.

    Returns:
        Float value.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return float(stripped)
            except (ValueError, OverflowError):
                pass
    return 0.0


def coerce_tool_arguments(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Coerce tool arguments to match their schema types.

    Args:
        arguments: Raw arguments from LLM.
        schema: Tool parameter schema (JSON Schema format).

    Returns:
        Coerced arguments.
    """
    properties = schema.get("properties", {})
    if not properties:
        return arguments

    coerced = dict(arguments)

    for key, prop_schema in properties.items():
        if key not in coerced:
            continue

        value = coerced[key]
        expected_type = prop_schema.get("type", "")

        # Skip if already correct type
        if expected_type == "string" and isinstance(value, str):
            continue
        if expected_type == "boolean" and isinstance(value, bool):
            continue
        if expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
            continue
        if expected_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            continue

        # Coerce to expected type
        if expected_type == "string":
            coerced[key] = coerce_string(value)
        elif expected_type == "boolean":
            coerced[key] = coerce_boolean(value)
        elif expected_type == "integer":
            coerced[key] = coerce_integer(value)
        elif expected_type == "number":
            coerced[key] = coerce_number(value)

    return coerced
