"""Tests for JSON utility functions."""

from attocode.tricks.json_utils import (
    extract_json,
    extract_json_objects,
    extract_json_array,
    safe_parse,
    fix_trailing_commas,
    fix_single_quotes,
    truncate_json,
)


class TestExtractJson:
    def test_raw_json_object(self):
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_raw_json_array(self):
        result = extract_json("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_json_in_code_fence(self):
        text = 'Here is the result:\n```json\n{"a": 1}\n```\nDone.'
        result = extract_json(text)
        assert result == {"a": 1}

    def test_json_in_plain_fence(self):
        text = "```\n[1, 2]\n```"
        result = extract_json(text)
        assert result == [1, 2]

    def test_json_embedded_in_text(self):
        text = 'The answer is {"x": 42} and that is all.'
        result = extract_json(text)
        assert result == {"x": 42}

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2]}}'
        result = extract_json(text)
        assert result == {"outer": {"inner": [1, 2]}}

    def test_no_json_returns_none(self):
        result = extract_json("no json here at all")
        assert result is None

    def test_empty_string(self):
        result = extract_json("")
        assert result is None


class TestExtractJsonObjects:
    def test_multiple_objects(self):
        text = '{"a": 1} some text {"b": 2}'
        result = extract_json_objects(text)
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_no_objects(self):
        result = extract_json_objects("just text")
        assert result == []


class TestExtractJsonArray:
    def test_array(self):
        result = extract_json_array("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_non_array_returns_none(self):
        result = extract_json_array('{"key": "val"}')
        assert result is None


class TestSafeParse:
    def test_valid_json(self):
        result = safe_parse('{"a": 1}')
        assert result == {"a": 1}

    def test_invalid_json_returns_none(self):
        result = safe_parse("not json")
        assert result is None

    def test_trailing_comma_fixed(self):
        result = safe_parse('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_single_quotes_fixed(self):
        result = safe_parse("{'a': 1}")
        assert result == {"a": 1}

    def test_empty_string(self):
        result = safe_parse("")
        assert result is None

    def test_array_with_trailing_comma(self):
        result = safe_parse("[1, 2, 3,]")
        assert result == [1, 2, 3]


class TestFixTrailingCommas:
    def test_object_trailing_comma(self):
        assert fix_trailing_commas('{"a": 1,}') == '{"a": 1}'

    def test_array_trailing_comma(self):
        assert fix_trailing_commas("[1, 2,]") == "[1, 2]"

    def test_no_trailing_comma(self):
        text = '{"a": 1}'
        assert fix_trailing_commas(text) == text

    def test_nested_trailing_commas(self):
        text = '{"a": [1, 2,], "b": {"c": 3,},}'
        result = fix_trailing_commas(text)
        assert ",}" not in result
        assert ",]" not in result


class TestFixSingleQuotes:
    def test_single_to_double(self):
        result = fix_single_quotes("{'key': 'value'}")
        assert result == '{"key": "value"}'

    def test_already_double_quotes(self):
        text = '{"key": "value"}'
        assert fix_single_quotes(text) == text


class TestTruncateJson:
    def test_shallow_object(self):
        obj = {"a": 1, "b": 2}
        assert truncate_json(obj) == {"a": 1, "b": 2}

    def test_deep_nesting_truncated(self):
        # Build deeply nested object
        obj: dict = {"level": 0}
        current = obj
        for i in range(1, 10):
            current["child"] = {"level": i}
            current = current["child"]

        result = truncate_json(obj, max_depth=3)
        # Should contain truncation marker at some depth
        import json
        text = json.dumps(result)
        assert "truncated" in text

    def test_large_list_truncated(self):
        obj = list(range(100))
        result = truncate_json(obj, max_items=5)
        assert len(result) == 6  # 5 items + truncation marker
        assert "more items" in result[-1]
