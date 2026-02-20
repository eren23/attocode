"""MCP tool validation and quality scoring.

Provides heuristic quality scoring for MCP tool schemas and
runtime validation of tool results.
"""

from __future__ import annotations

from typing import Any

# Tool names considered too generic to be useful
_GENERIC_NAMES = frozenset({
    "run",
    "do",
    "execute",
    "call",
    "invoke",
    "handle",
    "process",
    "action",
    "task",
    "go",
    "start",
})


class MCPToolValidator:
    """Quality scorer and result validator for MCP tools.

    :meth:`validate_tool` assigns a 0-100 score based on how well
    a tool schema is documented and structured.

    :meth:`validate_result` checks whether a tool's return value
    looks like a successful, non-empty result.
    """

    # ------------------------------------------------------------------
    # Schema quality
    # ------------------------------------------------------------------

    def validate_tool(self, tool_name: str, schema: dict[str, Any]) -> int:
        """Score a tool schema for quality (0-100).

        Scoring rubric (each criterion adds up to 25):

        * **Has description** (+25) -- top-level ``description`` key
          exists and is a non-empty string.
        * **Has parameter descriptions** (+25) -- at least half of the
          declared parameters have their own ``description``.
        * **Reasonable param count** (+25) -- between 1 and 10
          parameters (inclusive).
        * **Specific name** (+25) -- the tool name is not one of the
          overly-generic names like ``run``, ``do``, ``execute``.
        """
        score = 0

        # 1. Has description
        desc = schema.get("description", "")
        if isinstance(desc, str) and desc.strip():
            score += 25

        # 2. Parameter descriptions
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}

        if properties:
            described = sum(
                1
                for p in properties.values()
                if isinstance(p, dict) and p.get("description", "")
            )
            if described >= len(properties) / 2:
                score += 25
        else:
            # No parameters declared -- we can't penalize, give partial
            # credit when the schema is otherwise minimal.
            pass

        # 3. Reasonable parameter count (1..10 inclusive)
        param_count = len(properties)
        if 1 <= param_count <= 10:
            score += 25

        # 4. Specific (non-generic) name
        base_name = tool_name.lower().split(".")[-1].split("/")[-1]
        if base_name not in _GENERIC_NAMES:
            score += 25

        return score

    # ------------------------------------------------------------------
    # Result validation
    # ------------------------------------------------------------------

    def validate_result(self, tool_name: str, result: Any) -> bool:
        """Check whether *result* looks like a valid, non-empty response.

        Returns ``False`` for:
        - ``None``
        - Empty strings
        - Empty collections (list, dict, set)
        - Dicts with a truthy ``error`` key
        """
        if result is None:
            return False

        if isinstance(result, str) and not result.strip():
            return False

        if isinstance(result, (list, dict, set)) and len(result) == 0:
            return False

        if isinstance(result, dict) and result.get("error"):
            return False

        return True
