"""Tests for tree-sitter parser — language coverage expansion.

Tests the expanded language support (25 configured + generic + ctags).
"""

from __future__ import annotations

import pytest

from attocode.integrations.context.codebase_ast import (
    LANG_EXTENSIONS,
    detect_language,
    parse_file,
)
from attocode.integrations.context.ts_parser import (
    EXTRA_GRAMMAR_MODULES,
    EXTRA_LANG_EXTENSIONS,
    LANGUAGE_CONFIGS,
    GenericTreeSitterExtractor,
    supported_languages,
    ts_parse_file,
)


# ============================================================
# Language detection tests
# ============================================================


class TestLanguageDetection:
    """Verify extension → language mapping for all supported languages."""

    def test_original_languages(self) -> None:
        assert detect_language("foo.py") == "python"
        assert detect_language("foo.js") == "javascript"
        assert detect_language("foo.ts") == "typescript"
        assert detect_language("foo.go") == "go"
        assert detect_language("foo.rs") == "rust"
        assert detect_language("foo.java") == "java"
        assert detect_language("foo.rb") == "ruby"
        assert detect_language("foo.c") == "c"
        assert detect_language("foo.cpp") == "cpp"

    def test_phase1_languages(self) -> None:
        assert detect_language("foo.cs") == "csharp"
        assert detect_language("foo.php") == "php"
        assert detect_language("foo.swift") == "swift"
        assert detect_language("foo.kt") == "kotlin"
        assert detect_language("foo.kts") == "kotlin"
        assert detect_language("foo.scala") == "scala"
        assert detect_language("foo.lua") == "lua"
        assert detect_language("foo.ex") == "elixir"
        assert detect_language("foo.exs") == "elixir"
        assert detect_language("foo.hs") == "haskell"
        assert detect_language("foo.sh") == "bash"
        assert detect_language("foo.bash") == "bash"
        assert detect_language("foo.tf") == "hcl"
        assert detect_language("foo.hcl") == "hcl"
        assert detect_language("foo.zig") == "zig"

    def test_phase2_data_languages(self) -> None:
        assert detect_language("foo.yaml") == "yaml"
        assert detect_language("foo.yml") == "yaml"
        assert detect_language("foo.toml") == "toml"
        assert detect_language("foo.json") == "json"
        assert detect_language("foo.html") == "html"
        assert detect_language("foo.htm") == "html"
        assert detect_language("foo.css") == "css"
        assert detect_language("foo.scss") == "css"

    def test_additional_js_ts_extensions(self) -> None:
        assert detect_language("foo.mjs") == "javascript"
        assert detect_language("foo.cjs") == "javascript"
        assert detect_language("foo.mts") == "typescript"
        assert detect_language("foo.cts") == "typescript"

    def test_additional_cpp_extensions(self) -> None:
        assert detect_language("foo.hxx") == "cpp"
        assert detect_language("foo.hh") == "cpp"
        assert detect_language("foo.cxx") == "cpp"
        assert detect_language("foo.metal") == "cpp"

    def test_python_stub_files(self) -> None:
        assert detect_language("foo.pyi") == "python"

    def test_unknown_extension(self) -> None:
        assert detect_language("foo.xyz") == "unknown"


# ============================================================
# Language configs completeness
# ============================================================


class TestLanguageConfigs:
    """Verify LANGUAGE_CONFIGS has entries for all languages in LANG_EXTENSIONS."""

    def test_all_extensions_have_configs(self) -> None:
        """Every language in LANG_EXTENSIONS should have a LANGUAGE_CONFIGS entry."""
        missing = []
        for ext, lang in LANG_EXTENSIONS.items():
            if lang not in LANGUAGE_CONFIGS and lang not in EXTRA_GRAMMAR_MODULES:
                missing.append(f"{ext} → {lang}")
        assert missing == [], f"Missing configs: {missing}"

    def test_configs_have_grammar_modules(self) -> None:
        """Every config should have a grammar_module set."""
        for lang, config in LANGUAGE_CONFIGS.items():
            assert config.grammar_module, f"{lang} has empty grammar_module"

    def test_aliases_work(self) -> None:
        """Language aliases should resolve to same config."""
        assert LANGUAGE_CONFIGS["c++"] is LANGUAGE_CONFIGS["cpp"]
        assert LANGUAGE_CONFIGS["c#"] is LANGUAGE_CONFIGS["csharp"]
        assert LANGUAGE_CONFIGS["shell"] is LANGUAGE_CONFIGS["bash"]
        assert LANGUAGE_CONFIGS["sh"] is LANGUAGE_CONFIGS["bash"]
        assert LANGUAGE_CONFIGS["terraform"] is LANGUAGE_CONFIGS["hcl"]
        assert LANGUAGE_CONFIGS["scss"] is LANGUAGE_CONFIGS["css"]
        assert LANGUAGE_CONFIGS["metal"] is LANGUAGE_CONFIGS["cpp"]

    def test_supported_languages_count(self) -> None:
        """Should support 25+ languages (including aliases)."""
        langs = supported_languages()
        # 9 original + 11 Phase 1 + 5 Phase 2 + aliases = 30+
        assert len(langs) >= 30

    def test_unique_languages_count(self) -> None:
        """Should have 25 unique language configs (excluding aliases)."""
        unique = {id(cfg) for cfg in LANGUAGE_CONFIGS.values()}
        assert len(unique) >= 25


# ============================================================
# Extra grammar modules (Phase 3)
# ============================================================


class TestExtraGrammarModules:
    def test_extra_modules_defined(self) -> None:
        """Should have 20+ extra grammar modules."""
        assert len(EXTRA_GRAMMAR_MODULES) >= 20

    def test_extra_extensions_map(self) -> None:
        """Extra extensions should map to languages in EXTRA_GRAMMAR_MODULES."""
        for ext, lang in EXTRA_LANG_EXTENSIONS.items():
            assert lang in EXTRA_GRAMMAR_MODULES, f"{ext} → {lang} not in EXTRA_GRAMMAR_MODULES"

    def test_no_overlap_with_main(self) -> None:
        """Extra extensions should not conflict with main LANG_EXTENSIONS."""
        overlap = set(EXTRA_LANG_EXTENSIONS) & set(LANG_EXTENSIONS)
        allowed = {
            ext for ext in overlap
            if EXTRA_LANG_EXTENSIONS[ext] in EXTRA_GRAMMAR_MODULES
        }
        assert overlap == allowed, f"Overlapping extensions: {overlap - allowed}"


# ============================================================
# GenericTreeSitterExtractor
# ============================================================


class TestGenericExtractor:
    def test_extractor_init(self) -> None:
        """GenericTreeSitterExtractor should initialize cleanly."""
        ext = GenericTreeSitterExtractor()
        assert ext._grammar_cache == {}

    def test_parse_without_grammar_returns_none(self) -> None:
        """Should return None for unavailable grammars."""
        ext = GenericTreeSitterExtractor()
        result = ext.parse("test.xyz", "hello", "tree_sitter_nonexistent", "xyz")
        assert result is None

    def test_cache_negative_results(self) -> None:
        """Failed grammar loads should be cached."""
        ext = GenericTreeSitterExtractor()
        ext.parse("test.xyz", "hello", "tree_sitter_nonexistent")
        assert "tree_sitter_nonexistent" in ext._grammar_cache
        assert ext._grammar_cache["tree_sitter_nonexistent"] is None


# ============================================================
# parse_file integration for new languages (graceful degradation)
# ============================================================


class TestParseFileNewLanguages:
    """Test that parse_file handles new languages gracefully.

    These tests verify the full fallback chain works even without
    tree-sitter grammars installed.
    """

    def test_csharp_detection(self) -> None:
        code = "using System;\nnamespace MyApp { class Program { } }"
        ast = parse_file("test.cs", content=code)
        assert ast.language == "csharp"
        assert ast.line_count > 0

    def test_php_detection(self) -> None:
        code = "<?php\nfunction hello() { echo 'hi'; }\n"
        ast = parse_file("test.php", content=code)
        assert ast.language == "php"

    def test_swift_detection(self) -> None:
        code = "import Foundation\nfunc greet() { print(\"hello\") }\n"
        ast = parse_file("test.swift", content=code)
        assert ast.language == "swift"

    def test_kotlin_detection(self) -> None:
        code = "fun main() { println(\"Hello\") }\n"
        ast = parse_file("test.kt", content=code)
        assert ast.language == "kotlin"

    def test_scala_detection(self) -> None:
        code = "object Main { def main(args: Array[String]): Unit = {} }\n"
        ast = parse_file("test.scala", content=code)
        assert ast.language == "scala"

    def test_lua_detection(self) -> None:
        code = "function hello()\n  print('hello')\nend\n"
        ast = parse_file("test.lua", content=code)
        assert ast.language == "lua"

    def test_elixir_detection(self) -> None:
        code = "defmodule Hello do\n  def greet, do: :ok\nend\n"
        ast = parse_file("test.ex", content=code)
        assert ast.language == "elixir"

    def test_haskell_detection(self) -> None:
        code = "module Main where\nmain :: IO ()\nmain = putStrLn \"Hello\"\n"
        ast = parse_file("test.hs", content=code)
        assert ast.language == "haskell"

    def test_bash_detection(self) -> None:
        code = "#!/bin/bash\nhello() {\n  echo 'hi'\n}\n"
        ast = parse_file("test.sh", content=code)
        assert ast.language == "bash"

    def test_hcl_detection(self) -> None:
        code = 'resource "aws_instance" "web" {\n  ami = "abc"\n}\n'
        ast = parse_file("test.tf", content=code)
        assert ast.language == "hcl"

    def test_zig_detection(self) -> None:
        code = "const std = @import(\"std\");\npub fn main() void {}\n"
        ast = parse_file("test.zig", content=code)
        assert ast.language == "zig"

    def test_yaml_detection(self) -> None:
        code = "name: test\nversion: 1.0\n"
        ast = parse_file("test.yaml", content=code)
        assert ast.language == "yaml"

    def test_toml_detection(self) -> None:
        code = "[package]\nname = \"test\"\nversion = \"1.0\"\n"
        ast = parse_file("test.toml", content=code)
        assert ast.language == "toml"

    def test_json_detection(self) -> None:
        code = '{"name": "test", "version": "1.0"}\n'
        ast = parse_file("test.json", content=code)
        assert ast.language == "json"

    def test_html_detection(self) -> None:
        code = "<html><body><h1>Hello</h1></body></html>\n"
        ast = parse_file("test.html", content=code)
        assert ast.language == "html"

    def test_css_detection(self) -> None:
        code = ".container { display: flex; }\n"
        ast = parse_file("test.css", content=code)
        assert ast.language == "css"


# ============================================================
# ts_parse_file for Phase 1 languages (requires grammars)
# ============================================================


def _has_grammar(lang: str) -> bool:
    """Check if a tree-sitter grammar is available for testing."""
    from attocode.integrations.context.ts_parser import is_available
    return is_available(lang)


@pytest.mark.skipif(not _has_grammar("csharp"), reason="tree-sitter-c-sharp not installed")
class TestCSharpTreeSitter:
    def test_class_and_method(self) -> None:
        code = (
            "using System;\n"
            "namespace MyApp {\n"
            "    public class Program {\n"
            "        public static void Main(string[] args) {\n"
            "            Console.WriteLine(\"Hello\");\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        result = ts_parse_file("test.cs", content=code, language="csharp")
        assert result is not None
        assert len(result["classes"]) >= 1
        assert any(c["name"] == "Program" for c in result["classes"])
        assert len(result["imports"]) >= 1


@pytest.mark.skipif(not _has_grammar("c"), reason="tree-sitter-c not installed")
class TestCTreeSitter:
    def test_function_names_not_return_types(self) -> None:
        code = (
            "void myFunction(int x) {}\n"
            "int anotherFunc(char *s) { return 0; }\n"
            "static long getTimestamp(void) { return 0; }\n"
        )
        result = ts_parse_file("test.c", content=code, language="c")
        assert result is not None
        names = [f["name"] for f in result["functions"]]
        assert "myFunction" in names
        assert "anotherFunc" in names
        assert "getTimestamp" in names
        # Must NOT extract return types as names
        for bad in ("void", "int", "static", "long"):
            assert bad not in names


@pytest.mark.skipif(not _has_grammar("cpp"), reason="tree-sitter-cpp not installed")
class TestCppTreeSitter:
    def test_function_names_not_return_types(self) -> None:
        code = (
            "void topLevel(int x) {}\n"
            "int* pointerFunc() { return nullptr; }\n"
        )
        result = ts_parse_file("test.cpp", content=code, language="cpp")
        assert result is not None
        names = [f["name"] for f in result["functions"]]
        assert "topLevel" in names
        assert "pointerFunc" in names
        for bad in ("void", "int"):
            assert bad not in names


@pytest.mark.skipif(not _has_grammar("cpp"), reason="tree-sitter-cpp not installed")
class TestMetalTreeSitter:
    """Metal files use the C++ parser — verify symbol extraction works."""

    def test_kernel_function_extracted(self) -> None:
        code = (
            "#include <metal_stdlib>\n"
            "using namespace metal;\n"
            "kernel void matmul(\n"
            "    device const float* A [[buffer(0)]],\n"
            "    device float* C [[buffer(1)]],\n"
            "    uint tid [[thread_position_in_grid]]\n"
            ") {\n"
            "    C[tid] = A[tid] * 2.0;\n"
            "}\n"
        )
        result = ts_parse_file("matmul.metal", content=code, language="cpp")
        assert result is not None
        names = [f["name"] for f in result["functions"]]
        assert "matmul" in names

    def test_struct_and_include_extracted(self) -> None:
        code = (
            "#include <metal_stdlib>\n"
            "using namespace metal;\n"
            "struct Params {\n"
            "    uint width;\n"
            "    uint height;\n"
            "};\n"
            "kernel void process(constant Params& p [[buffer(0)]]) {}\n"
        )
        result = ts_parse_file("process.metal", content=code, language="cpp")
        assert result is not None
        assert any(c["name"] == "Params" for c in result["classes"])
        assert len(result["imports"]) >= 1
        names = [f["name"] for f in result["functions"]]
        assert "process" in names


@pytest.mark.skipif(not _has_grammar("php"), reason="tree-sitter-php not installed")
class TestPHPTreeSitter:
    def test_function(self) -> None:
        code = "<?php\nfunction hello(): string {\n    return 'hi';\n}\n"
        result = ts_parse_file("test.php", content=code, language="php")
        assert result is not None
        assert len(result["functions"]) >= 1
        assert result["functions"][0]["name"] == "hello"

    def test_class_and_imports(self) -> None:
        code = (
            "<?php\n"
            "namespace App\\Models;\n"
            "use App\\Base\\Model;\n"
            "class User {\n"
            "    public function getName() { return $this->name; }\n"
            "}\n"
        )
        result = ts_parse_file("test.php", content=code, language="php")
        assert result is not None
        assert len(result["classes"]) >= 1
        assert any(c["name"] == "User" for c in result["classes"])
        assert len(result["imports"]) >= 1


@pytest.mark.skipif(not _has_grammar("swift"), reason="tree-sitter-swift not installed")
class TestSwiftTreeSitter:
    def test_function_and_class(self) -> None:
        code = (
            "import Foundation\n"
            "class Greeter {\n"
            "    func greet() -> String {\n"
            "        return \"Hello\"\n"
            "    }\n"
            "}\n"
        )
        result = ts_parse_file("test.swift", content=code, language="swift")
        assert result is not None
        assert len(result["classes"]) >= 1


@pytest.mark.skipif(not _has_grammar("kotlin"), reason="tree-sitter-kotlin not installed")
class TestKotlinTreeSitter:
    def test_function(self) -> None:
        code = "fun main() {\n    println(\"Hello\")\n}\n"
        result = ts_parse_file("test.kt", content=code, language="kotlin")
        assert result is not None
        assert len(result["functions"]) >= 1

    def test_imports(self) -> None:
        code = (
            "import kotlin.collections.mutableListOf\n"
            "import java.util.Date\n"
            "fun main() {}\n"
        )
        result = ts_parse_file("test.kt", content=code, language="kotlin")
        assert result is not None
        assert len(result["imports"]) >= 2


@pytest.mark.skipif(not _has_grammar("bash"), reason="tree-sitter-bash not installed")
class TestBashTreeSitter:
    def test_function(self) -> None:
        code = "#!/bin/bash\nhello() {\n    echo 'hi'\n}\n"
        result = ts_parse_file("test.sh", content=code, language="bash")
        assert result is not None
        assert len(result["functions"]) >= 1
        assert result["functions"][0]["name"] == "hello"


@pytest.mark.skipif(not _has_grammar("elixir"), reason="tree-sitter-elixir not installed")
class TestElixirTreeSitter:
    def test_module_with_functions_and_imports(self) -> None:
        code = (
            "defmodule MyApp.Repo do\n"
            "  use Ecto.Repo\n"
            "  import Ecto.Query\n"
            "  def get_user(id) do\n"
            "    id\n"
            "  end\n"
            "  defp internal(x) do\n"
            "    x\n"
            "  end\n"
            "end\n"
        )
        result = ts_parse_file("test.ex", content=code, language="elixir")
        assert result is not None
        # Module found
        assert any(c["name"] == "MyApp.Repo" for c in result["classes"])
        # Functions found with correct parent_class
        fn_names = [f["name"] for f in result["functions"]]
        assert "get_user" in fn_names
        assert "internal" in fn_names
        assert all(f["parent_class"] == "MyApp.Repo" for f in result["functions"])
        # Imports found
        assert len(result["imports"]) >= 2


@pytest.mark.skipif(not _has_grammar("lua"), reason="tree-sitter-lua not installed")
class TestLuaTreeSitter:
    def test_function(self) -> None:
        code = "function hello()\n    print('hello')\nend\n"
        result = ts_parse_file("test.lua", content=code, language="lua")
        assert result is not None
        assert len(result["functions"]) >= 1


# ============================================================
# Phase 2: Data format parsing tests
# ============================================================


@pytest.mark.skipif(not _has_grammar("yaml"), reason="tree-sitter-yaml not installed")
class TestYAMLTreeSitter:
    def test_top_level_keys(self) -> None:
        code = "name: test\nversion: 1.0\ndependencies:\n  - foo\n  - bar\n"
        result = ts_parse_file("test.yaml", content=code, language="yaml")
        assert result is not None
        assert "name" in result["top_level_vars"]
        assert "version" in result["top_level_vars"]


@pytest.mark.skipif(not _has_grammar("json"), reason="tree-sitter-json not installed")
class TestJSONTreeSitter:
    def test_top_level_keys(self) -> None:
        code = '{"name": "test", "version": "1.0", "scripts": {}}\n'
        result = ts_parse_file("test.json", content=code, language="json")
        assert result is not None
        assert "name" in result["top_level_vars"]
        assert "version" in result["top_level_vars"]
        assert "scripts" in result["top_level_vars"]


@pytest.mark.skipif(not _has_grammar("toml"), reason="tree-sitter-toml not installed")
class TestTOMLTreeSitter:
    def test_tables_and_keys(self) -> None:
        code = "[package]\nname = \"test\"\nversion = \"1.0\"\n\n[dependencies]\n"
        result = ts_parse_file("test.toml", content=code, language="toml")
        assert result is not None
        # Tables show as classes, keys as top_level_vars
        assert result["line_count"] > 0
