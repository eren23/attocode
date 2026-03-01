"""Comprehensive tests for MCP tool validator.

Covers MCPToolValidator.validate_tool (schema scoring) and
MCPToolValidator.validate_result (result checking).
"""

from __future__ import annotations

import pytest

from attocode.integrations.mcp.tool_validator import MCPToolValidator, _GENERIC_NAMES


# =====================================================================
# validate_tool -- schema quality scoring
# =====================================================================


class TestValidateToolSchemaScoring:
    """Tests for the validate_tool 0-100 quality scoring rubric."""

    def _full_schema(self) -> dict:
        return {
            "description": "A well-documented tool.",
            "properties": {
                "path": {"type": "string", "description": "File path."},
                "recursive": {"type": "boolean", "description": "Recurse dirs."},
            },
        }

    # ----- Perfect score -----

    def test_perfect_score(self) -> None:
        v = MCPToolValidator()
        score = v.validate_tool("read_file", self._full_schema())
        assert score == 100

    # ----- Description criterion (+25) -----

    def test_no_description_key(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        del schema["description"]
        assert v.validate_tool("read_file", schema) == 75

    def test_empty_description_string(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        schema["description"] = ""
        assert v.validate_tool("read_file", schema) == 75

    def test_whitespace_only_description(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        schema["description"] = "   \t\n  "
        assert v.validate_tool("read_file", schema) == 75

    def test_non_string_description_ignored(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        schema["description"] = 42
        assert v.validate_tool("read_file", schema) == 75

    # ----- Parameter descriptions criterion (+25) -----

    def test_no_param_descriptions(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        for p in schema["properties"].values():
            del p["description"]
        # Loses param descriptions, but keeps everything else
        assert v.validate_tool("read_file", schema) == 75

    def test_half_params_described_gets_credit(self) -> None:
        """At least half of params having descriptions earns the +25."""
        v = MCPToolValidator()
        schema = {
            "description": "Tool with mixed params.",
            "properties": {
                "a": {"type": "string", "description": "Described."},
                "b": {"type": "string"},  # no description
            },
        }
        # 1 out of 2 described = 50% >= 50%: gets +25
        assert v.validate_tool("my_tool", schema) == 100

    def test_less_than_half_params_described_loses_credit(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Tool.",
            "properties": {
                "a": {"type": "string", "description": "Ok."},
                "b": {"type": "string"},
                "c": {"type": "string"},
            },
        }
        # 1 out of 3 described = 33% < 50%: loses +25
        assert v.validate_tool("my_tool", schema) == 75

    def test_no_properties_key_no_penalty(self) -> None:
        """When properties key is missing, no param count or description penalty."""
        v = MCPToolValidator()
        schema = {"description": "Minimal tool."}
        # Has description (+25), no properties so no param desc check (+0),
        # 0 params so loses param count (+0), specific name (+25) => 50
        assert v.validate_tool("specific_tool", schema) == 50

    def test_properties_not_dict_treated_as_empty(self) -> None:
        v = MCPToolValidator()
        schema = {"description": "Tool.", "properties": "not_a_dict"}
        # properties reset to {} => 0 params => loses param count
        # specific name (+25), description (+25), no params scored => 50
        assert v.validate_tool("specific_tool", schema) == 50

    # ----- Reasonable param count criterion (+25) -----

    def test_one_param_gets_credit(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Single param tool.",
            "properties": {
                "input": {"type": "string", "description": "The input."},
            },
        }
        assert v.validate_tool("my_tool", schema) == 100

    def test_ten_params_gets_credit(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Max reasonable params.",
            "properties": {
                f"p{i}": {"type": "string", "description": f"param {i}"}
                for i in range(10)
            },
        }
        assert v.validate_tool("my_tool", schema) == 100

    def test_eleven_params_loses_credit(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Too many params.",
            "properties": {
                f"p{i}": {"type": "string", "description": f"param {i}"}
                for i in range(11)
            },
        }
        assert v.validate_tool("my_tool", schema) == 75

    def test_zero_params_loses_credit(self) -> None:
        v = MCPToolValidator()
        schema = {"description": "No params.", "properties": {}}
        # desc (+25), no param descs (no params, +0), 0 params (+0), name (+25)
        assert v.validate_tool("specific_tool", schema) == 50

    def test_fifteen_params_loses_credit(self) -> None:
        v = MCPToolValidator()
        schema = {
            "description": "Bloated.",
            "properties": {
                f"p{i}": {"type": "string", "description": f"param {i}"}
                for i in range(15)
            },
        }
        assert v.validate_tool("specific_tool", schema) == 75

    # ----- Specific name criterion (+25) -----

    def test_all_generic_names_lose_credit(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        for name in _GENERIC_NAMES:
            score = v.validate_tool(name, schema)
            assert score == 75, f"Generic name '{name}' should lose 25 points"

    def test_specific_name_gets_credit(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        assert v.validate_tool("read_file", schema) == 100
        assert v.validate_tool("search_code", schema) == 100
        assert v.validate_tool("git_commit", schema) == 100

    def test_dotted_name_uses_last_segment(self) -> None:
        """Dotted names like 'server.run' should check only 'run'."""
        v = MCPToolValidator()
        schema = self._full_schema()
        assert v.validate_tool("myserver.run", schema) == 75  # "run" is generic
        assert v.validate_tool("myserver.search_files", schema) == 100

    def test_slashed_name_uses_last_segment(self) -> None:
        """Slashed names like 'namespace/execute' should check only 'execute'."""
        v = MCPToolValidator()
        schema = self._full_schema()
        assert v.validate_tool("ns/execute", schema) == 75  # "execute" is generic
        assert v.validate_tool("ns/read_file", schema) == 100

    def test_case_insensitive_generic_check(self) -> None:
        v = MCPToolValidator()
        schema = self._full_schema()
        assert v.validate_tool("RUN", schema) == 75
        assert v.validate_tool("Execute", schema) == 75
        assert v.validate_tool("DO", schema) == 75

    # ----- Combined edge cases -----

    def test_empty_schema_generic_name_scores_zero(self) -> None:
        v = MCPToolValidator()
        assert v.validate_tool("do", {}) == 0

    def test_empty_schema_specific_name_scores_25(self) -> None:
        v = MCPToolValidator()
        assert v.validate_tool("read_file", {}) == 25

    def test_generic_name_no_desc_no_params(self) -> None:
        v = MCPToolValidator()
        schema = {"properties": {}}
        assert v.validate_tool("run", schema) == 0

    def test_multiple_penalties_stack(self) -> None:
        """Generic name + no description + too many params + no param descs = 0."""
        v = MCPToolValidator()
        schema = {
            "properties": {
                f"p{i}": {"type": "string"} for i in range(15)
            },
        }
        assert v.validate_tool("execute", schema) == 0


# =====================================================================
# validate_result -- result validation
# =====================================================================


class TestValidateResult:
    """Tests for MCPToolValidator.validate_result."""

    def test_none_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", None) is False

    def test_empty_string_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", "") is False

    def test_whitespace_only_string_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", "   ") is False
        assert v.validate_result("tool", "\t\n") is False

    def test_empty_list_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", []) is False

    def test_empty_dict_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {}) is False

    def test_empty_set_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", set()) is False

    def test_dict_with_error_key_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {"error": "something failed"}) is False

    def test_dict_with_truthy_error_is_invalid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {"error": True}) is False
        assert v.validate_result("tool", {"error": 1}) is False

    def test_dict_with_falsy_error_is_valid(self) -> None:
        """A dict with error=None or error='' is valid (error is falsy)."""
        v = MCPToolValidator()
        assert v.validate_result("tool", {"error": None}) is True
        assert v.validate_result("tool", {"error": ""}) is True
        assert v.validate_result("tool", {"error": 0}) is True
        assert v.validate_result("tool", {"error": False}) is True

    def test_non_empty_string_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", "ok") is True
        assert v.validate_result("tool", "some output") is True

    def test_non_empty_list_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", [1, 2, 3]) is True

    def test_non_empty_dict_without_error_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {"data": "value"}) is True

    def test_number_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", 42) is True
        assert v.validate_result("tool", 0) is True
        assert v.validate_result("tool", 3.14) is True

    def test_boolean_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", True) is True
        assert v.validate_result("tool", False) is True

    def test_nested_structure_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {"items": [1, 2], "count": 2}) is True

    def test_non_empty_set_is_valid(self) -> None:
        v = MCPToolValidator()
        assert v.validate_result("tool", {1, 2, 3}) is True

    def test_tool_name_does_not_affect_validation(self) -> None:
        """The tool_name parameter should not affect the result validation logic."""
        v = MCPToolValidator()
        assert v.validate_result("any_tool", "ok") is True
        assert v.validate_result("another_tool", "ok") is True
        assert v.validate_result("", "ok") is True


# =====================================================================
# _GENERIC_NAMES constant
# =====================================================================


class TestGenericNames:
    """Tests for the _GENERIC_NAMES frozenset."""

    def test_is_frozenset(self) -> None:
        assert isinstance(_GENERIC_NAMES, frozenset)

    def test_contains_expected_names(self) -> None:
        expected = {"run", "do", "execute", "call", "invoke", "handle",
                    "process", "action", "task", "go", "start"}
        assert _GENERIC_NAMES == expected

    def test_not_modifiable(self) -> None:
        with pytest.raises(AttributeError):
            _GENERIC_NAMES.add("new")  # type: ignore[attr-defined]
