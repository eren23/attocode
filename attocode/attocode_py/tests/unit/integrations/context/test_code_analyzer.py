"""Tests for code analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.context.code_analyzer import (
    CodeAnalyzer,
    CodeChunk,
    FileAnalysis,
    _detect_language,
    _djb2_hash,
    _extract_docstring,
    _extract_imports,
    _has_main_guard,
    _regex_analyze_js_ts,
    _regex_analyze_python,
)


# ============================================================
# Dataclass Tests
# ============================================================


class TestCodeChunk:
    def test_line_count(self) -> None:
        chunk = CodeChunk(
            name="foo", kind="function", start_line=10, end_line=20, content="..."
        )
        assert chunk.line_count == 11

    def test_defaults(self) -> None:
        chunk = CodeChunk(
            name="foo", kind="function", start_line=1, end_line=1, content="x"
        )
        assert chunk.file_path == ""
        assert chunk.language == ""
        assert chunk.signature == ""
        assert chunk.parent == ""
        assert chunk.docstring == ""
        assert chunk.importance == 0.5


class TestFileAnalysis:
    def test_defaults(self) -> None:
        fa = FileAnalysis(path="/tmp/f.py", language="python", chunks=[])
        assert fa.imports == []
        assert fa.exports == []
        assert fa.line_count == 0
        assert not fa.has_main


# ============================================================
# CodeAnalyzer Tests
# ============================================================

SAMPLE_PYTHON = '''\
"""Module docstring."""

import os
from pathlib import Path


def helper():
    """Helper docstring."""
    return 42


class MyClass:
    """A class."""

    def method_one(self):
        """Method one."""
        pass

    def method_two(self, x):
        return x * 2


def standalone():
    pass


if __name__ == "__main__":
    helper()
'''

SAMPLE_JS = '''\
import { foo } from "./bar";

export function greet(name) {
    return `Hello, ${name}`;
}

class Animal {
    constructor(name) {
        this.name = name;
    }

    speak() {
        return this.name;
    }
}

const add = (a, b) => {
    return a + b;
};
'''


class TestAnalyzeFilePython:
    def test_analyze_python_file(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))

        assert result.language == "python"
        assert result.line_count > 0
        assert result.has_main

        names = [c.name for c in result.chunks]
        assert "helper" in names
        assert "MyClass" in names
        assert "standalone" in names

    def test_extracts_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "funcs.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))

        functions = [c for c in result.chunks if c.kind == "function"]
        func_names = [c.name for c in functions]
        assert "helper" in func_names
        assert "standalone" in func_names

    def test_extracts_classes(self, tmp_path: Path) -> None:
        f = tmp_path / "cls.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))

        classes = [c for c in result.chunks if c.kind == "class"]
        assert len(classes) >= 1
        assert classes[0].name == "MyClass"

    def test_extracts_methods_with_parent(self, tmp_path: Path) -> None:
        f = tmp_path / "methods.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))

        methods = [c for c in result.chunks if c.kind == "method"]
        assert len(methods) >= 1
        # Methods should have parent class set
        for m in methods:
            assert m.parent == "MyClass"

    def test_extracts_imports(self, tmp_path: Path) -> None:
        f = tmp_path / "imp.py"
        f.write_text(SAMPLE_PYTHON, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))

        assert "import os" in result.imports
        assert any("from pathlib" in i for i in result.imports)

    def test_nonexistent_file(self) -> None:
        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file("/nonexistent/path.py")
        assert result.chunks == []

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))
        assert result.chunks == []
        assert result.line_count == 0


class TestAnalyzeFileJS:
    def test_analyze_js(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.js"
        f.write_text(SAMPLE_JS, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f), language="javascript")

        assert result.language == "javascript"
        names = [c.name for c in result.chunks]
        assert "greet" in names
        assert "Animal" in names

    def test_analyze_ts_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.ts"
        f.write_text(SAMPLE_JS, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f))
        assert result.language == "typescript"

    def test_js_imports(self, tmp_path: Path) -> None:
        f = tmp_path / "imp.js"
        f.write_text(SAMPLE_JS, encoding="utf-8")

        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(f), language="javascript")
        assert len(result.imports) >= 1
        assert any("import" in i for i in result.imports)


class TestAnalyzeMultiple:
    def test_analyze_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def foo(): pass\n", encoding="utf-8")
        f2.write_text("def bar(): pass\n", encoding="utf-8")

        analyzer = CodeAnalyzer()
        results = analyzer.analyze_files([str(f1), str(f2)])
        assert len(results) == 2


# ============================================================
# Regex Fallback Tests
# ============================================================


class TestRegexPython:
    def test_extracts_functions(self) -> None:
        chunks = _regex_analyze_python(SAMPLE_PYTHON, "test.py")
        func_names = [c.name for c in chunks if c.kind == "function"]
        assert "helper" in func_names

    def test_extracts_classes(self) -> None:
        chunks = _regex_analyze_python(SAMPLE_PYTHON, "test.py")
        classes = [c for c in chunks if c.kind == "class"]
        assert any(c.name == "MyClass" for c in classes)


class TestRegexJsTs:
    def test_extracts_functions(self) -> None:
        chunks = _regex_analyze_js_ts(SAMPLE_JS, "test.js", "javascript")
        func_names = [c.name for c in chunks]
        assert "greet" in func_names

    def test_extracts_classes(self) -> None:
        chunks = _regex_analyze_js_ts(SAMPLE_JS, "test.js", "javascript")
        classes = [c for c in chunks if c.kind == "class"]
        assert any(c.name == "Animal" for c in classes)

    def test_arrow_functions(self) -> None:
        chunks = _regex_analyze_js_ts(SAMPLE_JS, "test.js", "javascript")
        names = [c.name for c in chunks]
        assert "add" in names


# ============================================================
# Helper Function Tests
# ============================================================


class TestDetectLanguage:
    def test_python(self) -> None:
        assert _detect_language(".py") == "python"
        assert _detect_language(".pyi") == "python"

    def test_javascript(self) -> None:
        assert _detect_language(".js") == "javascript"
        assert _detect_language(".jsx") == "javascript"

    def test_typescript(self) -> None:
        assert _detect_language(".ts") == "typescript"
        assert _detect_language(".tsx") == "typescript"

    def test_rust(self) -> None:
        assert _detect_language(".rs") == "rust"

    def test_unknown(self) -> None:
        assert _detect_language(".xyz") == ""


class TestExtractImports:
    def test_python_imports(self) -> None:
        code = "import os\nfrom pathlib import Path\nx = 1\n"
        imports = _extract_imports(code, "python")
        assert "import os" in imports
        assert "from pathlib import Path" in imports
        assert len(imports) == 2

    def test_js_imports(self) -> None:
        code = 'import { foo } from "./bar";\nconst x = 1;\n'
        imports = _extract_imports(code, "javascript")
        assert len(imports) >= 1

    def test_no_imports(self) -> None:
        assert _extract_imports("x = 1\n", "python") == []

    def test_limits_to_50(self) -> None:
        code = "\n".join(f"import mod{i}" for i in range(60))
        imports = _extract_imports(code, "python")
        assert len(imports) == 50


class TestExtractDocstring:
    def test_python_triple_double(self) -> None:
        code = '"""This is a docstring."""\ndef foo(): pass\n'
        assert _extract_docstring(code, "python") == "This is a docstring."

    def test_python_triple_single(self) -> None:
        code = "'''Single quote docstring.'''\ndef foo(): pass\n"
        assert _extract_docstring(code, "python") == "Single quote docstring."

    def test_js_jsdoc(self) -> None:
        code = "/** JSDoc comment. */\nfunction foo() {}\n"
        assert "JSDoc comment" in _extract_docstring(code, "javascript")

    def test_no_docstring(self) -> None:
        assert _extract_docstring("def foo(): pass", "python") == ""

    def test_truncates_long_docstring(self) -> None:
        long_doc = 'x' * 300
        code = f'"""{long_doc}"""\ndef foo(): pass\n'
        result = _extract_docstring(code, "python")
        assert len(result) <= 200


class TestHasMainGuard:
    def test_python_has_main(self) -> None:
        assert _has_main_guard('if __name__ == "__main__":\n    main()\n', "python")

    def test_python_no_main(self) -> None:
        assert not _has_main_guard("def foo(): pass\n", "python")

    def test_non_python(self) -> None:
        assert not _has_main_guard('if __name__ == "__main__":', "javascript")


# ============================================================
# DJB2 Hash Tests
# ============================================================


class TestDjb2Hash:
    def test_deterministic(self) -> None:
        assert _djb2_hash("hello") == _djb2_hash("hello")

    def test_different_for_different_input(self) -> None:
        assert _djb2_hash("hello") != _djb2_hash("world")

    def test_empty_string(self) -> None:
        assert _djb2_hash("") == 5381


# ============================================================
# Content-Hash Caching Tests
# ============================================================


class TestAnalyzerCache:
    def test_cache_hit_on_unchanged_file(self, tmp_path: Path) -> None:
        f = tmp_path / "cached.py"
        f.write_text("def foo(): pass\n", encoding="utf-8")

        analyzer = CodeAnalyzer()
        result1 = analyzer.analyze_file(str(f))
        result2 = analyzer.analyze_file(str(f))

        assert result1 is result2
        assert analyzer.cache_stats["hits"] == 1
        assert analyzer.cache_stats["misses"] == 1

    def test_cache_invalidation_on_change(self, tmp_path: Path) -> None:
        f = tmp_path / "changing.py"
        f.write_text("def foo(): pass\n", encoding="utf-8")

        analyzer = CodeAnalyzer()
        result1 = analyzer.analyze_file(str(f))

        f.write_text("def bar(): pass\ndef baz(): pass\n", encoding="utf-8")
        result2 = analyzer.analyze_file(str(f))

        assert result1 is not result2
        assert analyzer.cache_stats["hits"] == 0
        assert analyzer.cache_stats["misses"] == 2

    def test_clear_cache(self, tmp_path: Path) -> None:
        f = tmp_path / "clear.py"
        f.write_text("x = 1\n", encoding="utf-8")

        analyzer = CodeAnalyzer()
        analyzer.analyze_file(str(f))
        assert analyzer.cache_stats["entries"] == 1

        analyzer.clear_cache()
        assert analyzer.cache_stats["entries"] == 0
        assert analyzer.cache_stats["hits"] == 0
        assert analyzer.cache_stats["misses"] == 0

    def test_cache_stats_property(self) -> None:
        analyzer = CodeAnalyzer()
        stats = analyzer.cache_stats
        assert stats == {"hits": 0, "misses": 0, "entries": 0}

    def test_multiple_files_cached(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def a(): pass\n", encoding="utf-8")
        f2.write_text("def b(): pass\n", encoding="utf-8")

        analyzer = CodeAnalyzer()
        analyzer.analyze_file(str(f1))
        analyzer.analyze_file(str(f2))
        analyzer.analyze_file(str(f1))  # cache hit
        analyzer.analyze_file(str(f2))  # cache hit

        assert analyzer.cache_stats == {"hits": 2, "misses": 2, "entries": 2}
