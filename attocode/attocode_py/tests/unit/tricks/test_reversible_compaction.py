"""Tests for reversible compaction with reference preservation (Trick R)."""

from __future__ import annotations

from attocode.tricks.reversible_compaction import (
    ReversibleCompactor,
    ReversibleCompactionConfig,
    Reference,
    extract_file_references,
    extract_url_references,
    extract_function_references,
    extract_error_references,
    quick_extract,
)


class TestExtractFileReferences:
    def test_absolute_unix_path(self):
        refs = extract_file_references("Opening /src/main.py for editing")
        values = [r.value for r in refs]
        assert "/src/main.py" in values

    def test_nested_path(self):
        refs = extract_file_references("Read /home/user/project/src/utils/helpers.ts")
        values = [r.value for r in refs]
        assert "/home/user/project/src/utils/helpers.ts" in values

    def test_relative_path(self):
        refs = extract_file_references("Look at ./src/config.json")
        values = [r.value for r in refs]
        assert "./src/config.json" in values

    def test_parent_relative_path(self):
        refs = extract_file_references("File at ../tests/test_main.py")
        values = [r.value for r in refs]
        assert "../tests/test_main.py" in values

    def test_quoted_path(self):
        refs = extract_file_references('The file "/src/app.tsx" contains the component')
        values = [r.value for r in refs]
        assert "/src/app.tsx" in values

    def test_no_paths(self):
        refs = extract_file_references("No file paths in this text at all")
        assert refs == []

    def test_multiple_paths(self):
        refs = extract_file_references(
            "Modified /src/a.py and /src/b.py and ./c.ts"
        )
        assert len(refs) >= 3

    def test_sets_file_type(self):
        refs = extract_file_references("/src/main.py")
        assert all(r.type == "file" for r in refs)

    def test_sets_source_index(self):
        refs = extract_file_references("/src/main.py", source_index=5)
        assert all(r.source_index == 5 for r in refs)


class TestExtractUrlReferences:
    def test_http_url(self):
        refs = extract_url_references("Visit http://example.com for more")
        values = [r.value for r in refs]
        assert "http://example.com" in values

    def test_https_url(self):
        refs = extract_url_references("See https://docs.python.org/3/library/re.html")
        values = [r.value for r in refs]
        assert "https://docs.python.org/3/library/re.html" in values

    def test_url_with_query_params(self):
        refs = extract_url_references("Go to https://api.example.com/v2/search?q=test&page=1")
        assert len(refs) >= 1
        assert "api.example.com" in refs[0].value

    def test_strips_trailing_punctuation(self):
        refs = extract_url_references("Check https://example.com.")
        values = [r.value for r in refs]
        assert "https://example.com" in values

    def test_no_urls(self):
        refs = extract_url_references("No URLs here")
        assert refs == []

    def test_multiple_urls(self):
        refs = extract_url_references(
            "See https://a.com and https://b.com for details"
        )
        assert len(refs) == 2

    def test_sets_url_type(self):
        refs = extract_url_references("https://example.com")
        assert all(r.type == "url" for r in refs)


class TestExtractFunctionReferences:
    def test_python_def(self):
        refs = extract_function_references("def calculate_total(items):")
        values = [r.value for r in refs]
        assert "calculate_total" in values

    def test_async_def(self):
        refs = extract_function_references("async def fetch_data(url):")
        values = [r.value for r in refs]
        assert "fetch_data" in values

    def test_js_function(self):
        refs = extract_function_references("function handleClick(event) {")
        values = [r.value for r in refs]
        assert "handleClick" in values

    def test_camel_case_method_call(self):
        refs = extract_function_references("result = processInput(data)")
        values = [r.value for r in refs]
        assert "processInput" in values

    def test_no_functions(self):
        refs = extract_function_references("just some plain text here")
        assert refs == []

    def test_multiple_functions(self):
        code = """
def foo(x):
    pass

def bar(y):
    pass
"""
        refs = extract_function_references(code)
        values = [r.value for r in refs]
        assert "foo" in values
        assert "bar" in values

    def test_sets_function_type(self):
        refs = extract_function_references("def my_func():")
        assert all(r.type == "function" for r in refs)


class TestExtractErrorReferences:
    def test_error_class_name(self):
        refs = extract_error_references("Caught a ValueError from the parser")
        values = [r.value for r in refs]
        assert "ValueError" in values

    def test_exception_class_name(self):
        refs = extract_error_references("RuntimeException was raised")
        values = [r.value for r in refs]
        assert "RuntimeException" in values

    def test_error_message(self):
        refs = extract_error_references("Error: could not connect to database at localhost:5432")
        values = [r.value for r in refs]
        # Should capture the error message pattern
        assert any("Error:" in v for v in values)

    def test_no_errors(self):
        refs = extract_error_references("Everything worked fine")
        assert refs == []

    def test_caps_at_3_per_type(self):
        text = "ValueError TypeError SyntaxError RuntimeError IndexError KeyError"
        refs = extract_error_references(text)
        # Each category (class names vs error messages) caps at 3
        assert len(refs) <= 6  # max 3 class + 3 message

    def test_sets_error_type(self):
        refs = extract_error_references("FileNotFoundError")
        assert all(r.type == "error" for r in refs)


class TestQuickExtract:
    def test_extracts_all_default_types(self):
        text = (
            "Edited /src/main.py and saw ValueError. "
            "Check https://docs.python.org/3/ for help. "
            "def fix_bug(): pass"
        )
        refs = quick_extract(text)
        types = {r.type for r in refs}
        assert "file" in types
        assert "url" in types
        assert "function" in types
        assert "error" in types

    def test_custom_types(self):
        text = "Edited /src/main.py and https://example.com"
        refs = quick_extract(text, types=["file"])
        types = {r.type for r in refs}
        assert "file" in types
        assert "url" not in types

    def test_empty_content(self):
        refs = quick_extract("")
        assert refs == []


class TestReversibleCompactorGetReference:
    def test_get_by_id(self):
        compactor = ReversibleCompactor()
        ref = Reference(id="ref-abc123", type="file", value="/src/main.py")
        compactor._references.append(ref)
        found = compactor.get_reference("ref-abc123")
        assert found is not None
        assert found.value == "/src/main.py"

    def test_returns_none_for_unknown_id(self):
        compactor = ReversibleCompactor()
        assert compactor.get_reference("nonexistent") is None


class TestReversibleCompactorSearchReferences:
    def test_search_by_substring(self):
        compactor = ReversibleCompactor()
        compactor._references.extend([
            Reference(id="r1", type="file", value="/src/main.py"),
            Reference(id="r2", type="file", value="/src/utils.py"),
            Reference(id="r3", type="url", value="https://example.com"),
        ])
        results = compactor.search_references("main")
        assert len(results) == 1
        assert results[0].value == "/src/main.py"

    def test_search_case_insensitive(self):
        compactor = ReversibleCompactor()
        compactor._references.append(
            Reference(id="r1", type="file", value="/src/MyComponent.tsx")
        )
        results = compactor.search_references("mycomponent")
        assert len(results) == 1

    def test_search_no_match(self):
        compactor = ReversibleCompactor()
        compactor._references.append(
            Reference(id="r1", type="file", value="/src/main.py")
        )
        results = compactor.search_references("nonexistent")
        assert results == []

    def test_search_multiple_matches(self):
        compactor = ReversibleCompactor()
        compactor._references.extend([
            Reference(id="r1", type="file", value="/src/utils.py"),
            Reference(id="r2", type="file", value="/tests/test_utils.py"),
        ])
        results = compactor.search_references("utils")
        assert len(results) == 2


class TestReversibleCompactorGetReferencesByType:
    def test_filter_by_type(self):
        compactor = ReversibleCompactor()
        compactor._references.extend([
            Reference(id="r1", type="file", value="/src/main.py"),
            Reference(id="r2", type="url", value="https://example.com"),
            Reference(id="r3", type="file", value="/src/utils.py"),
        ])
        file_refs = compactor.get_references_by_type("file")
        assert len(file_refs) == 2
        assert all(r.type == "file" for r in file_refs)

    def test_returns_empty_for_unknown_type(self):
        compactor = ReversibleCompactor()
        assert compactor.get_references_by_type("unknown") == []


class TestReversibleCompactorClear:
    def test_clears_all_references(self):
        compactor = ReversibleCompactor()
        compactor._references.append(
            Reference(id="r1", type="file", value="/src/main.py")
        )
        assert len(compactor.get_preserved_references()) == 1
        compactor.clear()
        assert len(compactor.get_preserved_references()) == 0


class TestReversibleCompactorFormatReferencesBlock:
    def test_formats_grouped_by_type(self):
        compactor = ReversibleCompactor()
        compactor._references.extend([
            Reference(id="r1", type="file", value="/src/main.py"),
            Reference(id="r2", type="url", value="https://example.com"),
        ])
        block = compactor.format_references_block()
        assert "[Preserved References]" in block
        assert "FILES:" in block
        assert "URLS:" in block
        assert "/src/main.py" in block
        assert "https://example.com" in block

    def test_returns_empty_when_no_references(self):
        compactor = ReversibleCompactor()
        assert compactor.format_references_block() == ""

    def test_formats_custom_references(self):
        refs = [Reference(id="r1", type="error", value="ValueError")]
        compactor = ReversibleCompactor()
        block = compactor.format_references_block(refs)
        assert "ERRORS:" in block
        assert "ValueError" in block


class TestReversibleCompactorConfig:
    def test_default_config(self):
        compactor = ReversibleCompactor()
        assert compactor._config.max_references == 100
        assert compactor._config.deduplicate is True

    def test_custom_config(self):
        config = ReversibleCompactionConfig(
            max_references=10,
            deduplicate=False,
            min_relevance=0.3,
        )
        compactor = ReversibleCompactor(config)
        assert compactor._config.max_references == 10
        assert compactor._config.deduplicate is False
        assert compactor._config.min_relevance == 0.3
