"""Minimum definition evidence for the bundled language adapters."""
import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel.analysis_coverage import language_capabilities

CASES = [
    ("sample.py", "def greet(name):\n    return name\n", "greet"),
    ("sample.js", "exports.greet = (name) => name;", "greet"),
    ("sample.ts", "export const greet = (name: string): string => name;", "greet"),
    ("sample.rs", "pub fn greet(name: &str) -> &str { name }", "greet"),
    ("sample.go", "package sample\nfunc Greet(name string) string { return name }", "Greet"),
    ("Sample.java", "class Sample { public String greet(String name) { return name; } }", "greet"),
    ("sample.c", "int greet(int name) { return name; }", "greet"),
    ("sample.cpp", "class Sample { public: int greet(int name) { return name; } };", "greet"),
    ("Sample.cs", "class Sample { public string Greet(string name) { return name; } }", "Greet"),
    ("sample.rb", "class Sample\n  def greet(name)\n    name\n  end\nend", "greet"),
    ("sample.php", "<?php class Sample { public function greet($name) { return $name; } }", "greet"),
    ("sample.kt", "class Sample { fun greet(name: String): String { return name } }", "greet"),
    ("sample.swift", "struct Sample { func greet(_ name: String) -> String { return name } }", "greet"),
]


@pytest.mark.parametrize("path,source,name", CASES, ids=[case[0] for case in CASES])
def test_bundled_definition_capability(path, source, name):
    ast = parse_file(path, source)
    symbols = ast.functions + [method for cls in ast.classes for method in cls.methods]
    assert ast.parsing_tier == "tree_sitter"
    assert name in {symbol.name for symbol in symbols}
    assert all(symbol.start_line >= 1 and symbol.end_line >= symbol.start_line for symbol in symbols)
    assert "unrelated_missing_name" not in ast.get_symbols()


def test_capabilities_do_not_conflate_installation_with_verification():
    capabilities = language_capabilities()
    assert capabilities["typescript"]["definitions"] == "syntax"
    assert capabilities["csharp"]["dependencies"] == "unavailable"
    assert all(row["precision_verified"] is False for row in capabilities.values())
