"""Minimum definition evidence for the bundled language adapters."""
import threading

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
    ("sample.sh", "greet() { echo hello; }\n", "greet"),
    ("sample.ex", "defmodule Sample do\n  def greet(name), do: name\nend\n", "greet"),
    ("sample.lua", "function greet(name)\n return name\nend\n", "greet"),
    ("Sample.scala", "object Sample { def greet(name: String): String = name }", "greet"),
    ("sample.zig", "pub fn greet(name: i32) i32 { return name; }", "greet"),
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
    assert capabilities["csharp"]["dependencies"] == "partial"
    assert all(row["precision_verified"] is False for row in capabilities.values())


def test_cpp_header_export_annotation_preserves_original_source_ranges():
    source = '// ü: exported type\nnamespace logging {\nclass LIB_API Logger {\n public: void log() {}\n};\n}\n'
    ast = parse_file('logger.h', source)
    assert ast.language == 'cpp'
    cls = next(c for c in ast.classes if c.name == 'Logger')
    assert (cls.start_line, cls.end_line) == (3, 5)
    assert 'LIB_API Logger' in source.splitlines()[cls.start_line - 1]
    assert [m.name for m in cls.methods] == ['log']
    assert 'LIB_API' not in ast.get_symbols()


def test_c_header_cpp_words_in_comments_and_strings_do_not_switch_grammar():
    ast = parse_file('ordinary.h', '// class LIB_API Foo {};\nconst char *s = "namespace fake {}";\nstruct Record { int x; };')
    assert ast.language == 'c'
    assert [c.name for c in ast.classes] == ['Record']


def test_timed_out_grammar_resets_before_parsing_a_different_document(monkeypatch):
    from attocode_intel._internal.integrations.context import ts_parser
    parser = ts_parser._get_parser('python')
    monkeypatch.setattr(ts_parser, 'PARSE_TIMEOUT_MICROS', 1)
    assert ts_parser.bounded_parse(parser, b'def expensive():\n' + b'    value = 1\n' * 10000) is None
    monkeypatch.setattr(ts_parser, 'PARSE_TIMEOUT_MICROS', 100_000)
    ast = parse_file('new.py', 'def fresh(): return 1\n')
    assert [f.name for f in ast.functions] == ['fresh']
    assert ast.line_count == 2


def test_quoted_include_with_angle_comment_is_not_a_system_include():
    ast = parse_file('main.c', '#include "local.h" /* x < y */\n#include <system.h>\n')
    assert [(i.module, i.include_system) for i in ast.imports] == [('local.h', False), ('system.h', True)]


def test_objc_forward_declaration_is_not_a_cpp_class_definition():
    ast = parse_file('session.h', '@class Session;\n')
    assert ast.language != 'cpp'
    assert 'Session' not in ast.get_symbols()


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("generic", [False, True])
def test_optional_grammar_discovery_never_downloads(monkeypatch, cached, generic):
    import sys
    from types import SimpleNamespace

    import tree_sitter
    import tree_sitter_python
    from attocode_intel._internal.integrations.context import ts_parser
    calls = []
    def language(name):
        assert cached, "get_language would download an uncached grammar"
        calls.append(name)
        return tree_sitter.Language(tree_sitter_python.language())
    # An absent individual grammar forces the optional-pack path.
    monkeypatch.setitem(ts_parser.LANGUAGE_CONFIGS, "quality_optional", SimpleNamespace(
        grammar_module="quality_deliberately_absent_grammar", language_func="language"))
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", SimpleNamespace(
        download=lambda names: pytest.fail("Navigation must not acquire grammars"),
        downloaded_languages=lambda: ["quality_optional"] if cached else [], get_language=language))
    monkeypatch.setattr(ts_parser, "_PARSERS", threading.local())
    result = (ts_parser.GenericTreeSitterExtractor()._get_language_obj(
        "quality_deliberately_absent_grammar", "quality_optional") if generic else
        ts_parser._get_parser("quality_optional"))
    assert (result is not None) is cached
    assert calls == (["quality_optional"] if cached else [])


def test_download_capable_pack_without_cache_inventory_is_not_called(monkeypatch):
    import sys
    from types import SimpleNamespace

    from attocode_intel._internal.integrations.context import ts_parser
    monkeypatch.setitem(ts_parser.LANGUAGE_CONFIGS, "quality_optional", SimpleNamespace(
        grammar_module="quality_deliberately_absent_grammar", language_func="language"))
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", SimpleNamespace(
        download=lambda names: None, get_language=lambda name: pytest.fail("No safe cache inventory")))
    monkeypatch.setattr(ts_parser, "_PARSERS", threading.local())
    assert ts_parser._get_parser("quality_optional") is None


OPTIONAL_CASES = [
    ("sample.hs", "greet name = name\n", "greet"),
    ("sample.erl", "-module(sample).\ngreet(Name) -> Name.\n", "greet"),
    ("sample.clj", "(defn greet [name] name)\n", "greet"),
    ("sample.pl", "sub greet { return $_[0]; }\n", "greet"),
    ("sample.dart", "String greet(String name) { return name; }\n", "greet"),
    ("sample.ml", "let greet name = name\n", "greet"),
    ("sample.fs", "module Sample\nlet greet name = name\n", "greet"),
    ("sample.jl", "function greet(name)\n name\nend\n", "greet"),
    ("sample.nim", "proc greet(name: string): string = name\n", "greet"),
    ("sample.R", "greet <- function(name) { name }\n", "greet"),
    ("sample.m", "@implementation Sample\n- (int)greet:(int)name { return name; }\n@end\n", "greet"),
    ("sample.cr", "def greet(name)\n name\nend\n", "greet"),
]
FORMAT_CASES = [
    ("sample.json", '{"quality": true}', "quality"),
    ("sample.yaml", "quality: true\n", "quality"),
    ("sample.toml", "quality = true\n", "quality"),
    ("sample.tf", 'resource "null_resource" "quality" {}\n', "quality"),
    ("sample.html", '<div id="quality">Hello</div>', "div#quality"),
    ("sample.css", ".quality { color: red; }", ".quality"),
]


@pytest.mark.parametrize("path,source,name", OPTIONAL_CASES, ids=[c[0] for c in OPTIONAL_CASES])
def test_optional_definition_capability_without_acquisition(path, source, name):
    from attocode_intel._internal.integrations.context.codebase_ast import detect_language
    from attocode_intel._internal.integrations.context.ts_parser import is_available
    if not is_available(detect_language(path)):
        pytest.skip("Optional grammar is not installed/cached; no acquisition during navigation")
    test_bundled_definition_capability(path, source, name)


@pytest.mark.parametrize("path,source,name", FORMAT_CASES, ids=[c[0] for c in FORMAT_CASES])
def test_format_symbols(path, source, name):
    ast = parse_file(path, source)
    assert ast.parsing_tier == "tree_sitter"
    assert name in ast.get_symbols()


def test_html_resource_attributes_are_paths_not_entire_elements():
    ast = parse_file("page.html", '<script id="boot" src="app.js"></script><link href="style.css"/>')
    assert {i.module for i in ast.imports} == {"app.js", "style.css"}
    assert "script#boot" in ast.get_symbols()


def test_all_configured_adapters_reach_repository_discovery(tmp_path):
    from attocode_intel._internal.integrations.context.codebase_ast import detect_language
    from attocode_intel._internal.integrations.context.codebase_context import (
        CodebaseContextManager,
    )
    fixtures = CASES + OPTIONAL_CASES + FORMAT_CASES
    assert len(fixtures) == len({detect_language(p) for p, _, _ in fixtures}) == 36
    for path, source, _ in fixtures:
        (tmp_path / path).write_text(source)
    files = CodebaseContextManager(str(tmp_path)).discover_files()
    by_path = {f.relative_path: f.language for f in files}
    for path, _, _ in fixtures:
        assert by_path[path] == detect_language(path)


def test_incompatible_ctags_is_probed_once_without_per_file_spawns(tmp_path, monkeypatch):
    import shutil
    import subprocess
    from types import SimpleNamespace

    from attocode_intel._internal.integrations.context import ts_parser
    binary = tmp_path / 'ctags'
    binary.write_text('incompatible executable')
    monkeypatch.setattr(shutil, 'which', lambda name: str(binary))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command == [str(binary), '--list-features']
        return SimpleNamespace(returncode=1, stdout='')
    monkeypatch.setattr(subprocess, 'run', run)
    ts_parser._ctags_supports_json.cache_clear()
    for i in range(10):
        assert ts_parser.ctags_parse_file(str(tmp_path / f'{i}.unknown'), 'source') is None
    assert len(calls) == 1


def test_compatible_ctags_accepts_existing_file_and_removes_content_copy(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace

    from attocode_intel._internal.integrations.context import ts_parser
    binary, source = tmp_path / 'ctags', tmp_path / 'example.extra'
    binary.write_text('compatible executable')
    source.write_text('original source')
    monkeypatch.setattr(shutil, 'which', lambda name: str(binary))
    copies = []
    def run(command, **kwargs):
        if command[-1] == '--list-features':
            return SimpleNamespace(returncode=0, stdout='json\n')
        path = Path(command[-1])
        assert path.read_text() in {'original source', 'edited source'}
        if path != source:
            copies.append(path)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'name':'greet','kind':'function','line':1}))
    monkeypatch.setattr(subprocess, 'run', run)
    ts_parser._ctags_supports_json.cache_clear()
    assert ts_parser.ctags_parse_file(str(source))['functions'][0]['name'] == 'greet'
    assert ts_parser.ctags_parse_file(str(source), 'edited source')['functions'][0]['name'] == 'greet'
    assert source.read_text() == 'original source'
    assert copies and all(not path.exists() for path in copies)


def test_julia_where_signature_keeps_function_name_and_source_range():
    from attocode_intel._internal.integrations.context.ts_parser import is_available
    if not is_available('julia'):
        pytest.skip('Optional cached Julia grammar unavailable')
    ast = parse_file('array.jl', 'function vect(X::T...) where T\n X\nend\n')
    assert [(fn.name, fn.start_line, fn.end_line) for fn in ast.functions] == [('vect', 1, 3)]


def test_optional_fsharp_mutually_recursive_type_declarations_have_distinct_names():
    from attocode_intel._internal.integrations.context.ts_parser import is_available
    if not is_available('fsharp'):
        pytest.skip('Optional F# grammar is not cached')
    ast = parse_file('types.fs', "type Shape<'T> =\n    | Leaf of 'T\n    | Branch of Shapes<'T>\nand Shapes<'T> = Shape<'T> list\n")
    assert {c.name for c in ast.classes} == {'Shape', 'Shapes'}
