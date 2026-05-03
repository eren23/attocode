"""Unified tree-sitter parser for multi-language AST extraction.

Provides tree-sitter-based parsing for 25+ languages including Python,
JavaScript, TypeScript, Go, Rust, Java, Ruby, C/C++, C#, PHP, Swift,
Kotlin, Scala, Lua, Elixir, Haskell, Bash, HCL, Zig, and data formats
(YAML, TOML, JSON, HTML, CSS). Falls back gracefully when grammars are
not installed.

Also includes a ``GenericTreeSitterExtractor`` that can parse any language
with an installed tree-sitter grammar using heuristic node-type matching,
extending coverage to 50+ languages without per-language config.

The main entry point is ``ts_parse_file()`` which returns a ``FileAST``
(the same dataclass used by the regex parsers in ``codebase_ast.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Language config: maps language name to tree-sitter grammar module name,
# and provides node type queries for each language.

_TS_AVAILABLE = False
_PARSERS: dict[str, object] = {}  # lang -> tree_sitter.Parser


@dataclass(slots=True)
class _LangConfig:
    """Configuration for parsing a specific language via tree-sitter."""

    grammar_module: str  # e.g. "tree_sitter_python"
    function_types: tuple[str, ...]  # node types that represent functions
    class_types: tuple[str, ...]  # node types that represent classes
    import_types: tuple[str, ...]  # node types that represent imports
    method_types: tuple[str, ...] = ()  # method declarations inside classes
    var_types: tuple[str, ...] = ()  # top-level variable/constant declarations
    name_field: str = "name"  # tree-sitter field for the identifier
    language_func: str = "language"  # function name to call on grammar module


LANGUAGE_CONFIGS: dict[str, _LangConfig] = {
    # ---------------------------------------------------------------
    # Tier 1: Original 9 languages (production-ready)
    # ---------------------------------------------------------------
    "python": _LangConfig(
        grammar_module="tree_sitter_python",
        function_types=("function_definition",),
        class_types=("class_definition",),
        import_types=("import_statement", "import_from_statement"),
    ),
    "javascript": _LangConfig(
        grammar_module="tree_sitter_javascript",
        function_types=("function_declaration", "arrow_function", "generator_function_declaration"),
        class_types=("class_declaration",),
        import_types=("import_statement",),
        method_types=("method_definition",),
    ),
    "typescript": _LangConfig(
        grammar_module="tree_sitter_javascript",
        function_types=("function_declaration", "arrow_function", "generator_function_declaration"),
        class_types=("class_declaration",),
        import_types=("import_statement",),
        method_types=("method_definition",),
    ),
    "go": _LangConfig(
        grammar_module="tree_sitter_go",
        function_types=("function_declaration", "method_declaration"),
        class_types=("type_declaration",),
        import_types=("import_declaration",),
        var_types=("const_declaration", "var_declaration"),
    ),
    "rust": _LangConfig(
        grammar_module="tree_sitter_rust",
        function_types=("function_item",),
        class_types=("struct_item", "enum_item", "impl_item", "trait_item"),
        import_types=("use_declaration",),
    ),
    "java": _LangConfig(
        grammar_module="tree_sitter_java",
        function_types=("method_declaration", "constructor_declaration"),
        class_types=("class_declaration", "interface_declaration", "enum_declaration"),
        import_types=("import_declaration",),
    ),
    "ruby": _LangConfig(
        grammar_module="tree_sitter_ruby",
        function_types=("method",),
        class_types=("class", "module"),
        import_types=("call",),  # require/require_relative
    ),
    "c": _LangConfig(
        grammar_module="tree_sitter_c",
        function_types=("function_definition",),
        class_types=("struct_specifier", "enum_specifier", "union_specifier"),
        import_types=("preproc_include",),
    ),
    "cpp": _LangConfig(
        grammar_module="tree_sitter_cpp",
        function_types=("function_definition",),
        class_types=(
            "class_specifier", "struct_specifier", "enum_specifier",
            "namespace_definition",
        ),
        import_types=("preproc_include",),
    ),
    "csharp": _LangConfig(
        grammar_module="tree_sitter_c_sharp",
        function_types=("method_declaration", "constructor_declaration", "local_function_statement"),
        class_types=(
            "class_declaration", "struct_declaration", "interface_declaration",
            "enum_declaration", "record_declaration", "namespace_declaration",
        ),
        import_types=("using_directive",),
    ),
    "php": _LangConfig(
        grammar_module="tree_sitter_php",
        function_types=("function_definition", "method_declaration"),
        class_types=(
            "class_declaration", "interface_declaration", "trait_declaration",
            "enum_declaration",
        ),
        import_types=("namespace_use_declaration",),
        method_types=("method_declaration",),
        language_func="language_php",
    ),
    "swift": _LangConfig(
        grammar_module="tree_sitter_swift",
        function_types=("function_declaration", "init_declaration"),
        class_types=(
            "class_declaration", "struct_declaration", "protocol_declaration",
            "enum_declaration", "extension_declaration",
        ),
        import_types=("import_declaration",),
    ),
    "kotlin": _LangConfig(
        grammar_module="tree_sitter_kotlin",
        function_types=("function_declaration",),
        class_types=(
            "class_declaration", "object_declaration", "interface_declaration",
            "enum_class_body",
        ),
        import_types=("import_header", "import"),
    ),
    "scala": _LangConfig(
        grammar_module="tree_sitter_scala",
        function_types=("function_definition",),
        class_types=(
            "class_definition", "object_definition", "trait_definition",
            "enum_definition",
        ),
        import_types=("import_declaration",),
    ),
    "lua": _LangConfig(
        grammar_module="tree_sitter_lua",
        function_types=("function_declaration", "function_definition"),
        class_types=(),  # Lua has no native classes
        import_types=(),  # require() is a regular function call
    ),
    "elixir": _LangConfig(
        grammar_module="tree_sitter_elixir",
        # Elixir uses macro calls for everything — handled specially in _process_node
        function_types=(),
        class_types=(),
        import_types=(),
    ),
    "haskell": _LangConfig(
        grammar_module="tree_sitter_haskell",
        function_types=("function", "bind"),
        class_types=("data_type", "newtype", "type_synonym", "class", "instance"),
        import_types=("import",),
    ),
    "bash": _LangConfig(
        grammar_module="tree_sitter_bash",
        function_types=("function_definition",),
        class_types=(),  # No classes in bash
        import_types=("command",),  # source/. commands
    ),
    "hcl": _LangConfig(
        grammar_module="tree_sitter_hcl",
        function_types=(),  # HCL doesn't have functions
        class_types=("block",),  # resource, data, module blocks
        import_types=(),  # No imports in HCL
    ),
    "zig": _LangConfig(
        grammar_module="tree_sitter_zig",
        function_types=("function_declaration",),
        class_types=("struct_declaration", "enum_declaration", "union_declaration"),
        import_types=(),  # @import is a builtin call
        var_types=("variable_declaration",),
    ),
    # Data/config languages
    "yaml": _LangConfig(
        grammar_module="tree_sitter_yaml",
        function_types=(),
        class_types=(),
        import_types=(),
    ),
    "toml": _LangConfig(
        grammar_module="tree_sitter_toml",
        function_types=(),
        class_types=("table",),  # [section] headers
        import_types=(),
    ),
    "json": _LangConfig(
        grammar_module="tree_sitter_json",
        function_types=(),
        class_types=(),
        import_types=(),
    ),
    "html": _LangConfig(
        grammar_module="tree_sitter_html",
        function_types=(),
        class_types=("element",),  # HTML elements
        import_types=("script_element", "style_element"),  # External resources
    ),
    "css": _LangConfig(
        grammar_module="tree_sitter_css",
        function_types=(),
        class_types=("rule_set",),  # CSS selectors
        import_types=("import_statement",),  # @import
    ),
    "erlang": _LangConfig(
        grammar_module="tree_sitter_erlang",
        function_types=("function_clause",),
        class_types=("module_attribute",),  # -module(name). attribute
        import_types=("attribute",),  # -import(Module, [Functions]).
    ),
    "clojure": _LangConfig(
        grammar_module="tree_sitter_clojure",
        # Clojure uses macro calls for everything — handled specially in _process_node
        function_types=(),
        class_types=(),
        import_types=(),
    ),
    "perl": _LangConfig(
        grammar_module="tree_sitter_perl",
        function_types=("subroutine_declaration_statement", "function_definition"),
        class_types=("package_statement",),  # package Foo;
        import_types=("use_statement", "require_statement"),
    ),
    "crystal": _LangConfig(
        grammar_module="tree_sitter_crystal",
        function_types=("method_def", "fun_def"),
        class_types=("class_def", "module_def", "struct_def", "lib_def"),
        import_types=("require",),
    ),
    "dart": _LangConfig(
        grammar_module="tree_sitter_dart",
        function_types=("function_signature", "method_signature", "function_body"),
        class_types=(
            "class_definition", "enum_declaration",
            "mixin_declaration", "extension_declaration",
        ),
        import_types=("import_or_export",),
    ),
    "ocaml": _LangConfig(
        grammar_module="tree_sitter_ocaml",
        function_types=("value_definition", "let_binding"),
        class_types=("type_definition", "module_definition", "class_definition"),
        import_types=("open_statement",),
        language_func="language_ocaml",
    ),
    "fsharp": _LangConfig(
        grammar_module="tree_sitter_fsharp",
        function_types=("function_or_value_defn", "member_defn"),
        class_types=("type_definition", "module_defn", "namespace_defn"),
        import_types=("open_declaration", "module_abbrev"),
    ),
    "julia": _LangConfig(
        grammar_module="tree_sitter_julia",
        function_types=("function_definition", "short_function_definition", "macro_definition"),
        class_types=("struct_definition", "abstract_definition", "module_definition"),
        import_types=("import_statement", "using_statement"),
    ),
    "nim": _LangConfig(
        grammar_module="tree_sitter_nim",
        function_types=(
            "proc_declaration", "func_declaration", "method_declaration",
            "template_declaration", "macro_declaration",
        ),
        class_types=("type_section", "object_declaration"),
        import_types=("import_statement", "from_statement"),
    ),
    "r": _LangConfig(
        grammar_module="tree_sitter_r",
        # R functions are assignments like `f <- function() {}` — handled specially
        function_types=(),
        class_types=(),  # R uses S4/R6 classes via function calls
        import_types=("call",),  # library() and require() are function calls
    ),
    "objc": _LangConfig(
        grammar_module="tree_sitter_objc",
        function_types=("function_definition",),  # C-style functions
        class_types=(
            "class_interface", "class_implementation",
            "protocol_declaration", "category_interface",
        ),
        import_types=("preproc_import", "preproc_include"),
        method_types=("method_declaration",),
    ),
}

# Aliases
LANGUAGE_CONFIGS["c++"] = LANGUAGE_CONFIGS["cpp"]
LANGUAGE_CONFIGS["c#"] = LANGUAGE_CONFIGS["csharp"]
LANGUAGE_CONFIGS["shell"] = LANGUAGE_CONFIGS["bash"]
LANGUAGE_CONFIGS["sh"] = LANGUAGE_CONFIGS["bash"]
LANGUAGE_CONFIGS["terraform"] = LANGUAGE_CONFIGS["hcl"]
LANGUAGE_CONFIGS["scss"] = LANGUAGE_CONFIGS["css"]
LANGUAGE_CONFIGS["objective-c"] = LANGUAGE_CONFIGS["objc"]
LANGUAGE_CONFIGS["objective_c"] = LANGUAGE_CONFIGS["objc"]
LANGUAGE_CONFIGS["f#"] = LANGUAGE_CONFIGS["fsharp"]
LANGUAGE_CONFIGS["metal"] = LANGUAGE_CONFIGS["cpp"]


def _try_init_tree_sitter() -> bool:
    """Try to import tree-sitter. Returns True if available."""
    global _TS_AVAILABLE
    try:
        import tree_sitter  # noqa: F401

        _TS_AVAILABLE = True
    except ImportError:
        _TS_AVAILABLE = False
    return _TS_AVAILABLE


def _get_parser(language: str):
    """Get or create a tree-sitter Parser for the given language.

    Returns None if the grammar is not installed.
    """
    if language in _PARSERS:
        return _PARSERS[language]

    if not _TS_AVAILABLE and not _try_init_tree_sitter():
        return None

    config = LANGUAGE_CONFIGS.get(language)
    if config is None:
        return None

    try:
        import importlib

        import tree_sitter as ts

        grammar_mod = importlib.import_module(config.grammar_module)
        lang_fn = getattr(grammar_mod, config.language_func, None) or grammar_mod.language
        lang = ts.Language(lang_fn())
        parser = ts.Parser(lang)
        _PARSERS[language] = parser
        return parser
    except (ImportError, AttributeError, Exception) as e:
        logger.debug("tree-sitter grammar for %s not available via module: %s", language, e)

    # Fallback: try tree-sitter-language-pack
    try:
        import tree_sitter as ts
        from tree_sitter_language_pack import get_language as _pack_get_language

        lang = _pack_get_language(language)
        parser = ts.Parser(lang)
        _PARSERS[language] = parser
        return parser
    except Exception as e2:
        logger.debug("tree-sitter grammar for %s not in language-pack: %s", language, e2)
        _PARSERS[language] = None  # Cache the failure
        return None


def is_available(language: str = "") -> bool:
    """Check if tree-sitter parsing is available for a language (or any language)."""
    if not _TS_AVAILABLE and not _try_init_tree_sitter():
        return False
    if language:
        return _get_parser(language) is not None
    return True


def supported_languages() -> list[str]:
    """Return list of languages with tree-sitter configs defined."""
    return list(LANGUAGE_CONFIGS.keys())


# ---------------------------------------------------------------------------
# AST extraction helpers
# ---------------------------------------------------------------------------


def _node_text(node, source_bytes: bytes) -> str:
    """Extract the text content of a tree-sitter node."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_name(node, source_bytes: bytes) -> str:
    """Extract the name identifier from a node (function/class/etc)."""
    # Try the standard 'name' field first
    name_node = node.child_by_field_name("name")
    if name_node:
        return _node_text(name_node, source_bytes)

    # C/C++: name is inside declarator → function_declarator → identifier
    declarator = node.child_by_field_name("declarator")
    if declarator:
        if declarator.type == "function_declarator":
            for child in declarator.children:
                if child.type == "identifier":
                    return _node_text(child, source_bytes)
        # pointer_declarator or other wrappers around function_declarator
        for sub in declarator.children:
            if sub.type == "function_declarator":
                for child in sub.children:
                    if child.type == "identifier":
                        return _node_text(child, source_bytes)

    # Fallback: look for identifier child
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source_bytes)
        if child.type == "type_identifier":
            return _node_text(child, source_bytes)

    # Go: type_declaration → type_spec → type_identifier
    for child in node.children:
        if child.type == "type_spec":
            for grandchild in child.children:
                if grandchild.type == "type_identifier":
                    return _node_text(grandchild, source_bytes)

    return ""


def _find_parameters(node, source_bytes: bytes) -> list[str]:
    """Extract parameter names from a function node."""
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        # Some languages use "formal_parameters"
        for child in node.children:
            if child.type in ("parameters", "formal_parameters", "parameter_list"):
                params_node = child
                break

    if params_node is None:
        return []

    param_names: list[str] = []
    for child in params_node.children:
        if child.type in (
            "identifier", "typed_parameter", "default_parameter",
            "typed_default_parameter", "list_splat_pattern",
            "dictionary_splat_pattern", "formal_parameter",
            "required_parameter", "optional_parameter",
            "rest_parameter", "spread_element",
        ):
            name = _find_name(child, source_bytes)
            if not name:
                name = _node_text(child, source_bytes).split(":")[0].split("=")[0].strip()
                name = name.lstrip("*").lstrip("&")
            if name and name not in ("self", "cls", ",", "(", ")"):
                param_names.append(name)
    return param_names


def _find_return_type(node, source_bytes: bytes) -> str:
    """Extract return type annotation from a function node."""
    ret = node.child_by_field_name("return_type")
    if ret:
        text = _node_text(ret, source_bytes)
        return text.lstrip("->").lstrip(":").strip()
    return ""


def _is_async(node, source_bytes: bytes) -> bool:
    """Check if a function node is async."""
    text = _node_text(node, source_bytes)
    return text.lstrip().startswith("async ")


def _find_decorators(node, source_bytes: bytes) -> list[str]:
    """Extract decorators from a function/class node."""
    decorators: list[str] = []
    # Check previous siblings for decorator nodes
    prev = node.prev_named_sibling
    while prev and prev.type == "decorator":
        text = _node_text(prev, source_bytes).lstrip("@").strip()
        decorators.insert(0, text)
        prev = prev.prev_named_sibling
    return decorators


def _find_go_doc_comment(node, source_bytes: bytes) -> str:
    """Extract Go-style doc comment from comment lines immediately above a node.

    Go doc comments are consecutive ``// Comment`` lines directly preceding a
    declaration with no blank lines in between.  This walks backward through
    previous named siblings collecting ``comment`` nodes whose end line is
    adjacent to (or the same as) the start line of the next element.
    """
    comment_lines: list[str] = []
    expected_line = node.start_point[0]  # 0-based line of the declaration

    prev = node.prev_named_sibling
    while prev is not None and prev.type == "comment":
        # The comment must end exactly one line before the expected line
        if prev.end_point[0] + 1 != expected_line:
            break
        text = _node_text(prev, source_bytes).strip()
        # Strip leading "//" (single-line) or "/* ... */" (block)
        if text.startswith("//"):
            text = text[2:].strip()
        elif text.startswith("/*") and text.endswith("*/"):
            text = text[2:-2].strip()
        comment_lines.insert(0, text)
        expected_line = prev.start_point[0]
        prev = prev.prev_named_sibling

    return "\n".join(comment_lines) if comment_lines else ""


def _extract_go_receiver(node, source_bytes: bytes) -> str:
    """Extract receiver type name from a Go method_declaration node.

    Go methods look like ``func (r *Receiver) MethodName(...) ...``.
    The tree-sitter Go grammar exposes a ``receiver`` field containing a
    ``parameter_list`` with one ``parameter_declaration`` whose ``type``
    child holds the receiver type (possibly wrapped in ``pointer_type``).
    """
    receiver_node = node.child_by_field_name("receiver")
    if receiver_node is None:
        return ""

    for child in receiver_node.children:
        if child.type == "parameter_declaration":
            type_node = child.child_by_field_name("type")
            if type_node is None:
                # Fallback: look for type_identifier or pointer_type child
                for sub in child.children:
                    if sub.type in ("type_identifier", "pointer_type"):
                        type_node = sub
                        break
            if type_node is not None:
                # pointer_type wraps the actual type_identifier
                if type_node.type == "pointer_type":
                    for sub in type_node.children:
                        if sub.type == "type_identifier":
                            return _node_text(sub, source_bytes)
                return _node_text(type_node, source_bytes)
    return ""


def _get_visibility(name: str, language: str) -> str:
    """Determine visibility from name conventions."""
    if language == "python":
        if name.startswith("__") and not name.endswith("__"):
            return "private"
        if name.startswith("_"):
            return "private"
        return "public"
    elif language == "go":
        # Go convention: uppercase first letter = exported (public)
        if name and name[0].isupper():
            return "public"
        return "private"
    elif language in ("java", "typescript", "c", "cpp", "csharp", "kotlin", "swift", "scala",
                       "dart", "objc", "crystal", "fsharp"):
        # Would need modifier parsing; default to public
        return "public"
    elif language == "php":
        # PHP uses explicit modifiers; convention: __ prefix is magic
        if name.startswith("__"):
            return "public"  # magic methods
        return "public"
    elif language == "ruby":
        return "public"
    elif language == "lua":
        # Lua convention: _prefix means private
        if name.startswith("_"):
            return "private"
        return "public"
    elif language == "erlang":
        # Erlang: all exported functions are public; default to public
        return "public"
    elif language == "clojure":
        # Handled by _process_clojure_call which checks defn vs defn-
        return "public"
    elif language == "perl":
        # Perl convention: _ prefix means private
        if name.startswith("_"):
            return "private"
        return "public"
    elif language == "ocaml":
        # OCaml: visibility determined by .mli files; default to public
        return "public"
    elif language == "julia":
        # Julia convention: _ prefix means private/internal
        if name.startswith("_"):
            return "private"
        return "public"
    elif language == "nim":
        # Nim: exported procs use * suffix, but that's in the type, not the name
        # Convention: default to public
        return "public"
    elif language == "r":
        # R: . prefix means hidden/private
        if name.startswith("."):
            return "private"
        return "public"
    return "public"


def _extract_import_module(node, source_bytes: bytes, language: str) -> str:
    """Extract the module name from an import node."""
    text = _node_text(node, source_bytes).strip()

    if language == "python":
        # "from X import Y" or "import X"
        if text.startswith("from "):
            parts = text.split()
            return parts[1] if len(parts) > 1 else ""
        if text.startswith("import "):
            return text[7:].split(",")[0].strip().split(" as ")[0].strip()
    elif language in ("javascript", "typescript"):
        # "import X from 'Y'" or "import 'Y'"
        if "from " in text:
            parts = text.split("from ")
            return parts[-1].strip().strip("'\"`;")
        if text.startswith("import "):
            return text[7:].strip().strip("'\"`;")
    elif language == "go":
        # import "fmt" or import ( "fmt" "os" )
        # Tree-sitter Go grammar: import_declaration → import_spec → path
        # or import_declaration → import_spec_list → import_spec* → path
        for child in node.children:
            if child.type == "import_spec":
                path_node = child.child_by_field_name("path")
                if path_node:
                    return _node_text(path_node, source_bytes).strip('"')
            elif child.type == "import_spec_list":
                # Grouped imports: return first one
                for spec in child.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        if path_node:
                            return _node_text(path_node, source_bytes).strip('"')
        # Fallback: try direct path field (some grammar versions)
        mod_node = node.child_by_field_name("path")
        if mod_node:
            return _node_text(mod_node, source_bytes).strip('"')
    elif language == "rust":
        # use std::collections::HashMap;
        arg_node = node.child_by_field_name("argument")
        if arg_node:
            return _node_text(arg_node, source_bytes).rstrip(";")
    elif language == "java":
        # import java.util.List;
        return text.replace("import ", "").rstrip(";").strip()
    elif language == "ruby":
        # require 'foo' or require_relative 'foo'
        if "require" in text:
            parts = text.split("'")
            if len(parts) >= 2:
                return parts[1]
            parts = text.split('"')
            if len(parts) >= 2:
                return parts[1]
    elif language in ("c", "cpp"):
        # #include <stdio.h> or #include "header.h"
        for ch in ('<', '"'):
            if ch in text:
                return text.split(ch)[1].split('>' if ch == '<' else '"')[0]
    elif language == "csharp":
        # using System.Collections.Generic;
        text = text.replace("using ", "").rstrip(";").strip()
        # Remove "static" keyword for static usings
        if text.startswith("static "):
            text = text[7:]
        return text
    elif language == "php":
        # use App\Models\User;
        text = text.replace("use ", "").rstrip(";").strip()
        return text
    elif language == "swift":
        # import Foundation
        return text.replace("import ", "").strip()
    elif language == "kotlin":
        # import kotlin.collections.mutableListOf
        return text.replace("import ", "").strip()
    elif language == "scala":
        # import scala.collection.mutable._
        return text.replace("import ", "").strip()
    elif language == "haskell":
        # import Data.Map (Map, fromList)
        parts = text.split()
        if len(parts) >= 2:
            # Handle "import qualified X as Y" or "import X"
            idx = 1
            if idx < len(parts) and parts[idx] == "qualified":
                idx += 1
            if idx < len(parts):
                return parts[idx]
    elif language == "erlang":
        # -import(module, [func/arity, ...]). or -module(name).
        # Attribute text looks like: -import(lists, [map/2]).
        if text.startswith("-import("):
            inner = text[8:].rstrip(").").strip()
            return inner.split(",")[0].strip()
        if text.startswith("-module("):
            inner = text[8:].rstrip(").").strip()
            return inner
        # Generic attribute: extract attribute name
        if text.startswith("-"):
            return text.split("(")[0].lstrip("-").strip()
    elif language == "clojure":
        # Handled by _process_clojure_call; fallback for raw import text
        return text
    elif language == "perl":
        # use Module::Name; or use Module::Name qw(...);
        # require Module::Name;
        if text.startswith("use "):
            mod = text[4:].rstrip(";").strip()
            return mod.split()[0].split("(")[0]
        if text.startswith("require "):
            mod = text[8:].rstrip(";").strip()
            return mod.split()[0].strip("'\"")
    elif language == "crystal":
        # require "module_name"
        if "require" in text:
            parts = text.split('"')
            if len(parts) >= 2:
                return parts[1]
    elif language == "dart":
        # import 'package:flutter/material.dart'; or export '...';
        for quote in ("'", '"'):
            if quote in text:
                parts = text.split(quote)
                if len(parts) >= 2:
                    return parts[1]
    elif language == "ocaml":
        # open Module_name
        if text.startswith("open "):
            return text[5:].strip()
    elif language == "fsharp":
        # open System.Collections.Generic or module M = Module.Path
        if text.startswith("open "):
            return text[5:].strip()
        if text.startswith("module ") and "=" in text:
            return text.split("=")[1].strip()
    elif language == "julia":
        # import Module or import Module: func1, func2
        # using Module or using Module: func1, func2
        if text.startswith(("import ", "using ")):
            mod = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
            return mod.split(":")[0].strip()
    elif language == "nim":
        # import module or from module import symbol
        if text.startswith("from "):
            parts = text.split()
            if len(parts) >= 2:
                return parts[1]
        if text.startswith("import "):
            return text[7:].strip().split(",")[0].strip()
    elif language == "r":
        # library(pkg) or require(pkg)
        if "library(" in text or "require(" in text:
            inner = text.split("(")[1].split(")")[0].strip() if "(" in text else ""
            return inner.strip('"').strip("'")
    elif language == "objc":
        # #import <Foundation/Foundation.h> or #import "header.h"
        # #include <stdio.h> or #include "header.h"
        for ch in ('<', '"'):
            if ch in text:
                return text.split(ch)[1].split('>' if ch == '<' else '"')[0]

    return text


def _extract_bases(node, source_bytes: bytes, language: str) -> list[str]:
    """Extract base classes/interfaces from a class node."""
    bases: list[str] = []

    if language == "python":
        args_node = node.child_by_field_name("superclasses")
        if args_node:
            for child in args_node.children:
                if child.type in ("identifier", "attribute"):
                    bases.append(_node_text(child, source_bytes))
    elif language in ("javascript", "typescript", "java"):
        # Look for extends/implements
        for child in node.children:
            if child.type in ("class_heritage", "superclass", "super_interfaces"):
                for ident in child.children:
                    if ident.type in ("identifier", "type_identifier", "generic_type"):
                        bases.append(_node_text(ident, source_bytes))
    elif language == "rust":
        # trait bounds for impl blocks
        for child in node.children:
            if child.type in ("trait_type", "type_identifier"):
                bases.append(_node_text(child, source_bytes))
    elif language == "csharp":
        for child in node.children:
            if child.type == "base_list":
                for ident in child.children:
                    if ident.type in ("identifier", "generic_name", "qualified_name"):
                        bases.append(_node_text(ident, source_bytes))
    elif language in ("kotlin", "swift"):
        for child in node.children:
            if child.type in ("delegation_specifier", "type_identifier", "user_type",
                              "inheritance_specifier"):
                bases.append(_node_text(child, source_bytes))
    elif language == "scala":
        for child in node.children:
            if child.type in ("extends_clause",):
                for ident in child.children:
                    if ident.type in ("type_identifier", "generic_type"):
                        bases.append(_node_text(ident, source_bytes))
    elif language == "dart":
        # class Foo extends Bar implements Baz, Qux
        for child in node.children:
            if child.type in ("superclass", "interfaces", "mixins"):
                for ident in child.children:
                    if ident.type in ("type_identifier", "identifier", "generic_type"):
                        bases.append(_node_text(ident, source_bytes))
    elif language == "crystal":
        # class Foo < Bar
        for child in node.children:
            if child.type in ("superclass", "type_identifier"):
                text = _node_text(child, source_bytes).strip()
                if text and text != "<":
                    bases.append(text)
    elif language == "objc":
        # @interface Foo : Bar <Protocol1, Protocol2>
        for child in node.children:
            if child.type in ("superclass_reference", "type_identifier",
                              "protocol_qualifiers", "parameterized_class_type_arguments"):
                text = _node_text(child, source_bytes).strip()
                if text:
                    bases.append(text)
    elif language == "nim":
        # type Foo = ref object of Bar
        for child in node.children:
            if child.type in ("of_clause", "type_identifier"):
                text = _node_text(child, source_bytes).strip()
                if text.startswith("of "):
                    text = text[3:].strip()
                if text:
                    bases.append(text)

    return bases


# ---------------------------------------------------------------------------
# Elixir-specific helpers (macro-based definitions)
# ---------------------------------------------------------------------------


_ELIXIR_FN_MACROS = frozenset({"def", "defp", "defmacro", "defmacrop", "defguard", "defdelegate"})
_ELIXIR_MOD_MACROS = frozenset({"defmodule", "defprotocol", "defimpl"})
_ELIXIR_IMPORT_MACROS = frozenset({"import", "use", "require", "alias"})


def _process_elixir_call(
    node, source_bytes: bytes,
    functions: list[dict], classes: list[dict], imports: list[dict],
    parent_class: str,
) -> str:
    """Handle Elixir call nodes that represent def/defmodule/import macros.

    Returns the module name if a defmodule was found (for use as parent_class
    when recursing into the do_block), empty string otherwise.
    """
    # Get the macro name (first identifier child — Elixir AST has no "target" field)
    target = node.child_by_field_name("target")
    if not target:
        for child in node.children:
            if child.type == "identifier":
                target = child
                break
    if not target:
        return ""
    macro_name = _node_text(target, source_bytes).strip()

    # Get the arguments (first "arguments" child — may not be a named field)
    args = node.child_by_field_name("arguments")
    if not args:
        for child in node.children:
            if child.type == "arguments":
                args = child
                break

    if macro_name in _ELIXIR_FN_MACROS:
        # def/defp: first arg is the function head (a call node with the fn name)
        if args and args.children:
            head = args.children[0]
            name = ""
            if head.type == "call":
                # Inner call also uses identifier children, not "target" field
                head_target = head.child_by_field_name("target")
                if not head_target:
                    for child in head.children:
                        if child.type == "identifier":
                            head_target = child
                            break
                if head_target:
                    name = _node_text(head_target, source_bytes).strip()
            elif head.type == "identifier":
                name = _node_text(head, source_bytes).strip()
            if name:
                functions.append({
                    "name": name,
                    "parameters": [],
                    "return_type": "",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "is_async": False,
                    "decorators": [macro_name] if macro_name != "def" else [],
                    "visibility": "public" if macro_name in ("def", "defmacro") else "private",
                    "parent_class": parent_class,
                })
        return ""

    elif macro_name in _ELIXIR_MOD_MACROS:
        # defmodule: first arg is the module name (an alias like MyApp.Repo)
        if args and args.children:
            name_node = args.children[0]
            name = _node_text(name_node, source_bytes).strip()
            if name:
                classes.append({
                    "name": name,
                    "bases": [],
                    "methods": [],
                    "decorators": [macro_name] if macro_name != "defmodule" else [],
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
                return name
        return ""

    elif macro_name in _ELIXIR_IMPORT_MACROS:
        # import/use/require/alias: first arg is the module reference
        if args and args.children:
            mod_node = args.children[0]
            module = _node_text(mod_node, source_bytes).strip()
            if module:
                imports.append({
                    "module": module,
                    "is_from": macro_name == "alias",
                    "start_line": node.start_point[0] + 1,
                })

    return ""


# ---------------------------------------------------------------------------
# Clojure-specific helpers (macro-based definitions)
# ---------------------------------------------------------------------------

_CLOJURE_FN_MACROS = frozenset({"defn", "defn-", "defmacro", "defmulti", "defmethod", "defonce"})
_CLOJURE_CLASS_MACROS = frozenset({"defprotocol", "defrecord", "deftype"})


def _process_clojure_call(
    node, source_bytes: bytes,
    functions: list[dict], classes: list[dict], imports: list[dict],
    parent_class: str,
) -> str:
    """Handle Clojure list nodes that represent defn/defprotocol/ns forms.

    Returns the name if a namespace/protocol was found (for use as parent_class
    when recursing into children), empty string otherwise.
    """
    # Clojure forms are lists: (defn name [args] body)
    # The first child is the macro symbol
    children = [c for c in node.children if c.type not in ("(", ")", "meta_lit", "metadata")]
    if not children:
        return ""

    head = children[0]
    macro_name = _node_text(head, source_bytes).strip()

    if macro_name in _CLOJURE_FN_MACROS:
        # (defn name [params] ...) or (defn- name [params] ...)
        if len(children) >= 2:
            name = _node_text(children[1], source_bytes).strip()
            if name:
                decorators = [macro_name] if macro_name != "defn" else []
                visibility = "public" if macro_name != "defn-" else "private"
                functions.append({
                    "name": name,
                    "parameters": [],
                    "return_type": "",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "is_async": False,
                    "decorators": decorators,
                    "visibility": visibility,
                    "parent_class": parent_class,
                })
        return ""

    elif macro_name in _CLOJURE_CLASS_MACROS:
        # (defprotocol Name ...) / (defrecord Name [...] ...) / (deftype Name [...] ...)
        if len(children) >= 2:
            name = _node_text(children[1], source_bytes).strip()
            if name:
                decorators = [macro_name] if macro_name != "defprotocol" else []
                classes.append({
                    "name": name,
                    "bases": [],
                    "methods": [],
                    "decorators": decorators,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
                return name
        return ""

    elif macro_name == "ns":
        # (ns my.namespace (:require [dep1] [dep2]))
        if len(children) >= 2:
            name = _node_text(children[1], source_bytes).strip()
            if name:
                classes.append({
                    "name": name,
                    "bases": [],
                    "methods": [],
                    "decorators": [],
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                })
                # Extract :require dependencies
                for child in children[2:]:
                    child_text = _node_text(child, source_bytes).strip()
                    if ":require" in child_text:
                        # Extract module names from require vector
                        for sub in child.children:
                            sub_text = _node_text(sub, source_bytes).strip()
                            if sub_text.startswith("["):
                                mod = sub_text.strip("[]").split()[0] if sub_text.strip("[]") else ""
                                if mod and mod != ":require":
                                    imports.append({
                                        "module": mod,
                                        "is_from": False,
                                        "start_line": sub.start_point[0] + 1,
                                    })
                            elif sub.type == "sym_lit" and sub_text != ":require":
                                imports.append({
                                    "module": sub_text,
                                    "is_from": False,
                                    "start_line": sub.start_point[0] + 1,
                                })
                return name
        return ""

    return ""


# ---------------------------------------------------------------------------
# R-specific helpers (function assignment detection)
# ---------------------------------------------------------------------------


def _process_r_assignment(
    node, source_bytes: bytes,
    functions: list[dict], parent_class: str,
) -> bool:
    """Handle R assignment nodes where RHS is a function_definition.

    R defines functions via `f <- function(x) { ... }` or `f = function(x) { ... }`.
    Returns True if a function was extracted.
    """
    # Left side: variable name
    left = node.child_by_field_name("left")
    if not left:
        # Try first child
        children = [c for c in node.children if c.type not in ("<-", "=", "<<-")]
        if len(children) >= 2:
            left = children[0]
        else:
            return False

    # Right side: check for function_definition
    right = node.child_by_field_name("right")
    if not right:
        children = [c for c in node.children if c.type not in ("<-", "=", "<<-")]
        if len(children) >= 2:
            right = children[-1]
        else:
            return False

    if right.type != "function_definition":
        return False

    name = _node_text(left, source_bytes).strip()
    if not name:
        return False

    params = _find_parameters(right, source_bytes)
    functions.append({
        "name": name,
        "parameters": params,
        "return_type": "",
        "start_line": node.start_point[0] + 1,
        "end_line": node.end_point[0] + 1,
        "is_async": False,
        "decorators": [],
        "visibility": "public",
        "parent_class": parent_class,
    })
    return True


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------


def ts_parse_file(file_path: str, content: str | None = None, language: str = "") -> dict | None:
    """Parse a file using tree-sitter and return structured AST data.

    Returns a dict with keys: functions, classes, imports, top_level_vars,
    line_count — matching the fields of ``FileAST`` from ``codebase_ast.py``.

    Returns None if tree-sitter is not available or the language is unsupported.

    Args:
        file_path: Path to the source file.
        content: Optional file content (read from disk if not provided).
        language: Language name (auto-detected from extension if empty).
    """
    if not language:
        from attocode.integrations.context.codebase_ast import detect_language
        language = detect_language(file_path)

    if language not in LANGUAGE_CONFIGS:
        return None

    parser = _get_parser(language)
    if parser is None:
        return None

    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    source_bytes = content.encode("utf-8")

    try:
        tree = parser.parse(source_bytes)
    except Exception as e:
        logger.debug("tree-sitter parse error for %s: %s", file_path, e)
        return None

    config = LANGUAGE_CONFIGS[language]
    root = tree.root_node

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[dict] = []
    top_level_vars: list[str] = []

    def _process_node(node, parent_class: str = "") -> None:
        """Recursively process tree-sitter nodes."""
        ntype = node.type

        # Functions
        if ntype in config.function_types:
            name = _find_name(node, source_bytes)
            if not name:
                return

            params = _find_parameters(node, source_bytes)
            ret_type = _find_return_type(node, source_bytes)
            decorators = _find_decorators(node, source_bytes)
            is_async_fn = _is_async(node, source_bytes)
            visibility = _get_visibility(name, language)

            # Go: extract receiver type for method_declaration → parent_class
            effective_parent = parent_class
            if language == "go" and ntype == "method_declaration":
                receiver_type = _extract_go_receiver(node, source_bytes)
                if receiver_type:
                    effective_parent = receiver_type

            # Go: extract doc comment from preceding // comment lines
            docstring = ""
            if language == "go":
                docstring = _find_go_doc_comment(node, source_bytes)

            fn_data = {
                "name": name,
                "parameters": params,
                "return_type": ret_type,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "is_async": is_async_fn,
                "decorators": decorators,
                "visibility": visibility,
                "parent_class": effective_parent,
            }
            if docstring:
                fn_data["docstring"] = docstring

            if effective_parent:
                # Will be added as method to the class
                for cls in classes:
                    if cls["name"] == effective_parent:
                        cls["methods"].append(fn_data)
                        break
                else:
                    # Go: receiver type may not have a matching type_declaration
                    # in the same file; record as a standalone function with parent_class set
                    functions.append(fn_data)
            else:
                functions.append(fn_data)
            return

        # Methods inside classes (some languages have specific method types)
        if ntype in config.method_types and parent_class:
            name = _find_name(node, source_bytes)
            if name:
                params = _find_parameters(node, source_bytes)
                ret_type = _find_return_type(node, source_bytes)
                decorators = _find_decorators(node, source_bytes)
                is_async_fn = _is_async(node, source_bytes)
                visibility = _get_visibility(name, language)

                method_data = {
                    "name": name,
                    "parameters": params,
                    "return_type": ret_type,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "is_async": is_async_fn,
                    "decorators": decorators,
                    "visibility": visibility,
                    "parent_class": parent_class,
                }
                for cls in classes:
                    if cls["name"] == parent_class:
                        cls["methods"].append(method_data)
                        break
            return

        # Classes
        if ntype in config.class_types:
            name = _find_name(node, source_bytes)
            if not name:
                # For impl blocks in Rust, try type field
                type_node = node.child_by_field_name("type")
                if type_node:
                    name = _node_text(type_node, source_bytes)

            # HCL blocks: resource "aws_eks_cluster" "this" { ... }
            # Extract resource type as a top-level var in addition to
            # using the block keyword (resource/data/module) as class name
            if language == "hcl" and ntype == "block":
                string_lits = [
                    c for c in node.children if c.type == "string_lit"
                ]
                for sl in string_lits:
                    for sc in sl.children:
                        if sc.type == "template_literal":
                            resource_name = _node_text(sc, source_bytes)
                            if resource_name and resource_name not in top_level_vars:
                                top_level_vars.append(resource_name)

            if name:
                decorators = _find_decorators(node, source_bytes)
                bases = _extract_bases(node, source_bytes, language)

                cls_data = {
                    "name": name,
                    "bases": bases,
                    "methods": [],
                    "decorators": decorators,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }

                # Go: extract doc comment for type declarations
                if language == "go":
                    docstring = _find_go_doc_comment(node, source_bytes)
                    if docstring:
                        cls_data["docstring"] = docstring

                classes.append(cls_data)

                # Process children to find methods
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _process_node(child, parent_class=name)
                else:
                    for child in node.children:
                        _process_node(child, parent_class=name)

                # Go interface methods: type_declaration → type_spec → interface_type → method_elem
                if language == "go":
                    for child in node.children:
                        if child.type == "type_spec":
                            for gchild in child.children:
                                if gchild.type == "interface_type":
                                    for method in gchild.children:
                                        if method.type == "method_elem":
                                            # Name is in field_identifier child
                                            mname = ""
                                            for mc in method.children:
                                                if mc.type == "field_identifier":
                                                    mname = _node_text(mc, source_bytes)
                                                    break
                                            if not mname:
                                                mname = _find_name(method, source_bytes)
                                            if mname:
                                                params = _find_parameters(method, source_bytes)
                                                fn_data = {
                                                    "name": mname, "parameters": params,
                                                    "return_type": "",
                                                    "start_line": method.start_point[0] + 1,
                                                    "end_line": method.end_point[0] + 1,
                                                    "is_async": False, "decorators": [],
                                                    "visibility": "public",
                                                    "parent_class": name,
                                                }
                                                cls_data["methods"].append(fn_data)
                return

        # Imports
        if ntype in config.import_types:
            module = _extract_import_module(node, source_bytes, language)
            if module:
                is_from = language == "python" and ntype == "import_from_statement"
                imports.append({
                    "module": module,
                    "is_from": is_from,
                    "start_line": node.start_point[0] + 1,
                })
            return

        # Top-level variable assignments (Python-specific)
        if language == "python" and ntype == "expression_statement" and not parent_class:
            child = node.children[0] if node.children else None
            if child and child.type == "assignment":
                left = child.child_by_field_name("left")
                if left and left.type == "identifier":
                    var_name = _node_text(left, source_bytes)
                    if var_name.isupper() or var_name == "__all__":
                        top_level_vars.append(var_name)
            return

        # Config-driven top-level variable/constant declarations (Go, Zig, etc.)
        if config.var_types and ntype in config.var_types and not parent_class:
            if language == "go":
                # Go const/var blocks: const ( X = 1; Y = 2 )
                for child in node.children:
                    if child.type in ("const_spec", "var_spec"):
                        var_name = _find_name(child, source_bytes)
                        if var_name:
                            top_level_vars.append(var_name)
            else:
                var_name = _find_name(node, source_bytes)
                if var_name:
                    top_level_vars.append(var_name)
            return

        # Elixir: macro calls (def, defmodule, import, etc.)
        if language == "elixir" and ntype == "call":
            mod_name = _process_elixir_call(
                node, source_bytes, functions, classes, imports, parent_class,
            )
            # Recurse into do_block for nested defs inside defmodule
            inner_parent = mod_name or parent_class
            for child in node.children:
                if child.type == "do_block":
                    for sub in child.children:
                        _process_node(sub, parent_class=inner_parent)
            return

        # Clojure: list nodes represent forms like (defn ...), (ns ...), etc.
        if language == "clojure" and ntype in ("list_lit", "list"):
            mod_name = _process_clojure_call(
                node, source_bytes, functions, classes, imports, parent_class,
            )
            # Recurse into children for nested definitions
            if mod_name:
                for child in node.children:
                    _process_node(child, parent_class=mod_name)
            return

        # R: detect function assignments (f <- function(...) { ... })
        if language == "r" and ntype in ("left_assignment", "equals_assignment", "binary_operator"):
            if _process_r_assignment(node, source_bytes, functions, parent_class):
                return

        # R: filter import calls to only library() and require()
        if language == "r" and ntype == "call":
            # Only treat library() and require() as imports
            fn_node = node.child_by_field_name("function")
            if not fn_node:
                for child in node.children:
                    if child.type == "identifier":
                        fn_node = child
                        break
            if fn_node:
                fn_name = _node_text(fn_node, source_bytes).strip()
                if fn_name in ("library", "require"):
                    module = _extract_import_module(node, source_bytes, language)
                    if module:
                        imports.append({
                            "module": module,
                            "is_from": False,
                            "start_line": node.start_point[0] + 1,
                        })
                        return

        # Recurse into children
        for child in node.children:
            _process_node(child, parent_class=parent_class)

    # Process top-level nodes
    for child in root.children:
        _process_node(child)

    # Data/config language extraction: extract top-level keys as vars
    if language in ("yaml", "toml", "json"):
        _extract_data_symbols(root, source_bytes, language, top_level_vars, classes)

    # HTML: extract meaningful elements (IDs, component tags)
    if language == "html":
        _extract_html_symbols(root, source_bytes, classes, imports)

    # CSS: extract selectors as class names
    if language == "css":
        _extract_css_symbols(root, source_bytes, classes)

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "top_level_vars": top_level_vars,
        "line_count": content.count("\n") + 1,
        "language": language,
    }


# ---------------------------------------------------------------------------
# Data/config language helpers (Phase 2)
# ---------------------------------------------------------------------------


def _extract_data_symbols(
    root, source_bytes: bytes, language: str,
    top_level_vars: list[str], classes: list[dict],
) -> None:
    """Extract structural symbols from data/config files."""
    if language == "yaml":
        # Extract top-level mapping keys
        # Tree-sitter YAML: root → document → block_node → block_mapping → block_mapping_pair
        def _find_yaml_pairs(node, depth: int = 0):
            if depth > 5:
                return
            if node.type == "block_mapping_pair":
                key_node = node.child_by_field_name("key")
                if key_node:
                    key = _node_text(key_node, source_bytes).strip()
                    if key:
                        top_level_vars.append(key)
                return  # don't recurse into values
            for child in node.children:
                _find_yaml_pairs(child, depth + 1)
        _find_yaml_pairs(root)
    elif language == "toml":
        # Extract table names and top-level keys
        for child in root.children:
            if child.type == "table":
                # [section] headers become class-like entries
                for sub in child.children:
                    if sub.type in ("bare_key", "dotted_key", "quoted_key"):
                        name = _node_text(sub, source_bytes).strip("[]\"'")
                        if name:
                            classes.append({
                                "name": name,
                                "bases": [],
                                "methods": [],
                                "decorators": [],
                                "start_line": sub.start_point[0] + 1,
                                "end_line": sub.end_point[0] + 1,
                            })
            elif child.type == "pair":
                key_node = child.child_by_field_name("key") or (
                    child.children[0] if child.children else None
                )
                if key_node:
                    key = _node_text(key_node, source_bytes).strip()
                    if key:
                        top_level_vars.append(key)
    elif language == "json":
        # Extract top-level object keys
        obj = root.children[0] if root.children else None
        if obj and obj.type == "object":
            for child in obj.children:
                if child.type == "pair":
                    key_node = child.child_by_field_name("key")
                    if key_node:
                        key = _node_text(key_node, source_bytes).strip('"')
                        if key:
                            top_level_vars.append(key)


def _extract_html_symbols(
    root, source_bytes: bytes, classes: list[dict], imports: list[dict],
) -> None:
    """Extract meaningful symbols from HTML."""
    def _walk_html(node) -> None:
        if node.type == "element":
            tag_node = node.child_by_field_name("tag_name")
            if not tag_node:
                # Try first child for self-closing
                for child in node.children:
                    if child.type == "start_tag":
                        for sub in child.children:
                            if sub.type == "tag_name":
                                tag_node = sub
                                break
                        break

            if tag_node:
                tag = _node_text(tag_node, source_bytes)
                # Track script/link imports
                if tag in ("script", "link"):
                    _extract_html_resource(node, source_bytes, imports)
                # Track elements with IDs as named symbols
                _extract_html_id(node, source_bytes, tag, classes)

        for child in node.children:
            _walk_html(child)

    _walk_html(root)


def _extract_html_resource(node, source_bytes: bytes, imports: list[dict]) -> None:
    """Extract src/href from script/link tags."""
    for child in node.children:
        if child.type in ("start_tag", "self_closing_tag"):
            for attr in child.children:
                if attr.type == "attribute":
                    name_node = attr.child_by_field_name("name")
                    val_node = attr.child_by_field_name("value")
                    if name_node and val_node:
                        attr_name = _node_text(name_node, source_bytes)
                        if attr_name in ("src", "href"):
                            val = _node_text(val_node, source_bytes).strip('"\'')
                            if val:
                                imports.append({
                                    "module": val,
                                    "is_from": False,
                                    "start_line": node.start_point[0] + 1,
                                })


def _extract_html_id(
    node, source_bytes: bytes, tag: str, classes: list[dict],
) -> None:
    """Extract elements with id attributes as named symbols."""
    for child in node.children:
        if child.type in ("start_tag", "self_closing_tag"):
            for attr in child.children:
                if attr.type == "attribute":
                    name_node = attr.child_by_field_name("name")
                    val_node = attr.child_by_field_name("value")
                    if name_node and val_node and _node_text(name_node, source_bytes) == "id":
                        id_val = _node_text(val_node, source_bytes).strip('"\'')
                        if id_val:
                            classes.append({
                                "name": f"{tag}#{id_val}",
                                "bases": [],
                                "methods": [],
                                "decorators": [],
                                "start_line": node.start_point[0] + 1,
                                "end_line": node.end_point[0] + 1,
                            })


def _extract_css_symbols(root, source_bytes: bytes, classes: list[dict]) -> None:
    """Extract CSS selectors as symbols."""
    for child in root.children:
        if child.type == "rule_set":
            # Get the selector
            for sub in child.children:
                if sub.type == "selectors":
                    selector = _node_text(sub, source_bytes).strip()
                    if selector:
                        classes.append({
                            "name": selector,
                            "bases": [],
                            "methods": [],
                            "decorators": [],
                            "start_line": child.start_point[0] + 1,
                            "end_line": child.end_point[0] + 1,
                        })
                    break


# ---------------------------------------------------------------------------
# Generic tree-sitter extractor (any grammar, no config needed)
# ---------------------------------------------------------------------------

# Heuristic node types that commonly represent definitions across languages.
# Used by the generic extractor to identify symbols without per-language config.

# Node types that indicate a "function-like" definition
_GENERIC_FUNCTION_TYPES = frozenset({
    "function_definition", "function_declaration", "function_item",
    "method_definition", "method_declaration", "method",
    "local_function_statement", "constructor_declaration",
    "init_declaration", "arrow_function", "generator_function_declaration",
    "function",  # Haskell
    "bind",  # Haskell
    "proc_declaration", "template_declaration",  # Nim
    "fun_def", "val_def", "let_binding",  # OCaml, F#
    "defn", "defn-", "defmacro",  # Clojure
    "function_clause",  # Erlang
    "macro_definition",  # Clojure, Elixir
    "subroutine_definition", "subroutine",  # Fortran
    "class_method_definition", "instance_method_definition",  # Obj-C
    "fun_declaration",  # Crystal, Dart
    "abstract_method_signature",  # Dart
    "short_function_definition",  # Julia
    "function_assignment",  # R
})

# Node types that indicate a "class-like" definition
_GENERIC_CLASS_TYPES = frozenset({
    "class_definition", "class_declaration",
    "struct_definition", "struct_declaration", "struct_specifier", "struct_item",
    "enum_definition", "enum_declaration", "enum_specifier", "enum_item",
    "interface_declaration", "trait_definition", "trait_item", "protocol_declaration",
    "type_declaration", "type_definition", "type_alias",
    "module_definition", "module_declaration", "namespace_definition",
    "object_declaration", "record_declaration",
    "data_type", "newtype", "type_synonym",  # Haskell
    "union_declaration",  # Zig
    "type_section", "object_type",  # Nim
    "deftype", "defrecord", "defprotocol",  # Clojure
    "record_definition", "type_spec",  # Erlang
    "category_interface", "category_implementation",  # Obj-C
    "class_interface", "class_implementation",  # Obj-C
    "abstract_type_definition",  # Julia
    "mixin_declaration",  # Dart
    "lib_declaration",  # Crystal
})

# Node types that indicate imports
_GENERIC_IMPORT_TYPES = frozenset({
    "import_statement", "import_declaration", "import_from_statement",
    "use_declaration", "preproc_include", "using_directive",
    "namespace_use_declaration", "import_header",
    "import",  # Haskell
    "using_namespace_declaration",  # Zig
    "open_directive", "open_statement",  # OCaml, F#
    "require_expression", "require",  # Clojure, Crystal
    "include_statement", "include_directive",  # Nim, C
    "import_attribute", "attribute",  # Erlang
    "import_header",  # Obj-C
    "using_statement",  # Julia
    "library_import",  # R
})


class GenericTreeSitterExtractor:
    """Parse any tree-sitter grammar using heuristic node-type matching.

    This provides "good enough" symbol extraction for any language with a
    tree-sitter grammar installed, without needing per-language config.
    """

    def __init__(self) -> None:
        self._grammar_cache: dict[str, object | None] = {}

    def _get_language_obj(self, grammar_module: str, language: str = ""):
        """Try to load a tree-sitter Language from a grammar module.

        Attempts in order:
        1. Individual PyPI grammar package (e.g. tree_sitter_perl)
        2. tree-sitter-language-pack (170+ bundled languages)
        """
        cache_key = grammar_module or language
        if cache_key in self._grammar_cache:
            return self._grammar_cache[cache_key]

        if not _TS_AVAILABLE and not _try_init_tree_sitter():
            self._grammar_cache[cache_key] = None
            return None

        # Strategy 1: Individual grammar package
        if grammar_module:
            try:
                import importlib

                import tree_sitter as ts

                mod = importlib.import_module(grammar_module)
                # Try standard language(), fall back to language_<name>() for
                # grammars like tree_sitter_php that export language_php()
                lang_fn = getattr(mod, "language", None)
                if lang_fn is None:
                    # Search for language_* functions
                    for attr in dir(mod):
                        if attr.startswith("language_") and callable(getattr(mod, attr)):
                            lang_fn = getattr(mod, attr)
                            break
                if lang_fn is not None:
                    lang = ts.Language(lang_fn())
                    self._grammar_cache[cache_key] = lang
                    return lang
            except (ImportError, AttributeError, Exception) as e:
                logger.debug("Generic extractor: grammar %s not available: %s", grammar_module, e)

        # Strategy 2: tree-sitter-language-pack fallback
        if language:
            try:
                from tree_sitter_language_pack import get_language
                lang_obj = get_language(language)
                self._grammar_cache[cache_key] = lang_obj
                logger.debug("Loaded %s from tree-sitter-language-pack", language)
                return lang_obj
            except (ImportError, KeyError, Exception) as e:
                logger.debug("language-pack fallback for %s not available: %s", language, e)

        self._grammar_cache[cache_key] = None
        return None

    def parse(
        self, file_path: str, content: str, grammar_module: str, language: str = "",
    ) -> dict | None:
        """Parse a file using generic heuristics.

        Args:
            file_path: Path for error messages.
            content: Source code content.
            grammar_module: Python module name for the grammar (e.g. "tree_sitter_dart").
            language: Optional language label.

        Returns:
            Dict matching ``ts_parse_file`` output format, or None on failure.
        """
        lang_obj = self._get_language_obj(grammar_module, language=language)
        if lang_obj is None:
            return None

        try:
            import tree_sitter as ts
            parser = ts.Parser(lang_obj)
        except Exception:
            return None

        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as e:
            logger.debug("Generic parse error for %s: %s", file_path, e)
            return None

        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        top_level_vars: list[str] = []

        def _walk(node, depth: int = 0) -> None:
            ntype = node.type

            if ntype in _GENERIC_FUNCTION_TYPES:
                name = _find_name(node, source_bytes)
                if name:
                    functions.append({
                        "name": name,
                        "parameters": _find_parameters(node, source_bytes),
                        "return_type": _find_return_type(node, source_bytes),
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "is_async": _is_async(node, source_bytes),
                        "decorators": [],
                        "visibility": "public",
                        "parent_class": "",
                    })
                    return

            if ntype in _GENERIC_CLASS_TYPES:
                name = _find_name(node, source_bytes)
                if name:
                    classes.append({
                        "name": name,
                        "bases": [],
                        "methods": [],
                        "decorators": [],
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                    })
                    # Don't return — recurse into children for methods

            if ntype in _GENERIC_IMPORT_TYPES:
                text = _node_text(node, source_bytes).strip()
                if text:
                    imports.append({
                        "module": text,
                        "is_from": False,
                        "start_line": node.start_point[0] + 1,
                    })
                return

            # Only recurse a few levels deep to avoid noise
            if depth < 5:
                for child in node.children:
                    _walk(child, depth + 1)

        for child in tree.root_node.children:
            _walk(child)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "top_level_vars": top_level_vars,
            "line_count": content.count("\n") + 1,
            "language": language or "unknown",
        }


# Singleton for use by ts_parse_file_generic
_generic_extractor = GenericTreeSitterExtractor()


# Additional grammar modules for languages beyond the 25 configured ones.
# Maps language name → grammar module name. Users can extend this.
EXTRA_GRAMMAR_MODULES: dict[str, str] = {
    "dart": "tree_sitter_dart",
    "r": "tree_sitter_r",
    "julia": "tree_sitter_julia",
    "perl": "tree_sitter_perl",
    "ocaml": "tree_sitter_ocaml",
    "clojure": "tree_sitter_clojure",
    "elm": "tree_sitter_elm",
    "erlang": "tree_sitter_erlang",
    "nix": "tree_sitter_nix",
    "solidity": "tree_sitter_solidity",
    "protobuf": "tree_sitter_proto",
    "graphql": "tree_sitter_graphql",
    "sql": "tree_sitter_sql",
    "latex": "tree_sitter_latex",
    "make": "tree_sitter_make",
    "cmake": "tree_sitter_cmake",
    "dockerfile": "tree_sitter_dockerfile",
    "verilog": "tree_sitter_verilog",
    "vhdl": "tree_sitter_vhdl",
    "wasm": "tree_sitter_wasm",
    "awk": "tree_sitter_awk",
    "fish": "tree_sitter_fish",
    "powershell": "tree_sitter_powershell",
    "groovy": "tree_sitter_groovy",
    "gleam": "tree_sitter_gleam",
    "odin": "tree_sitter_odin",
    "v": "tree_sitter_v",
    "pascal": "tree_sitter_pascal",
    "fortran": "tree_sitter_fortran",
    "ada": "tree_sitter_ada",
    "d": "tree_sitter_d",
    "objc": "tree_sitter_objc",
    "nim": "tree_sitter_nim",
    "fsharp": "tree_sitter_fsharp",
    "crystal": "tree_sitter_crystal",
    "haskell": "tree_sitter_haskell",
}

# Extension mapping for extra grammars
EXTRA_LANG_EXTENSIONS: dict[str, str] = {
    ".dart": "dart",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".pl": "perl",
    ".pm": "perl",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".elm": "elm",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".nix": "nix",
    ".sol": "solidity",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".sql": "sql",
    ".tex": "latex",
    ".mk": "make",
    ".cmake": "cmake",
    ".v": "verilog",
    ".sv": "verilog",
    ".vhd": "vhdl",
    ".vhdl": "vhdl",
    ".wat": "wasm",
    ".wast": "wasm",
    ".awk": "awk",
    ".fish": "fish",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".gleam": "gleam",
    ".odin": "odin",
    ".pas": "pascal",
    ".pp": "pascal",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".adb": "ada",
    ".ads": "ada",
    ".d": "d",
    ".nim": "nim",
    ".nimble": "nim",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".fsx": "fsharp",
    ".cr": "crystal",
    ".m": "objc",
    ".mm": "objc",
    ".hs": "haskell",
    ".lhs": "haskell",
}


def ts_parse_file_generic(
    file_path: str, content: str | None = None, language: str = "",
) -> dict | None:
    """Parse a file using the generic tree-sitter extractor.

    This handles languages beyond the 25 configured ones, using heuristic
    node-type matching. Falls back gracefully when grammars aren't installed.

    Args:
        file_path: Path to the source file.
        content: Optional content (read from disk if not provided).
        language: Language name (auto-detected from extension if empty).

    Returns:
        Dict matching ``ts_parse_file`` format, or None if grammar not available.
    """
    if not language:
        ext = Path(file_path).suffix
        language = EXTRA_LANG_EXTENSIONS.get(ext, "")
        if not language:
            return None

    grammar_module = EXTRA_GRAMMAR_MODULES.get(language)
    if not grammar_module:
        return None

    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    return _generic_extractor.parse(file_path, content, grammar_module, language)


# ---------------------------------------------------------------------------
# Universal-ctags integration (fallback for languages without grammars)
# ---------------------------------------------------------------------------


def ctags_parse_file(file_path: str, content: str | None = None) -> dict | None:
    """Parse a file using universal-ctags as a subprocess fallback.

    Provides symbol extraction for 150+ languages when ctags is installed.
    Returns None if ctags is not available or produces no output.
    """
    import json as json_mod
    import subprocess

    # Write content to a temp file if provided (ctags needs a file on disk)
    target_path = file_path
    if content is not None:
        import tempfile
        suffix = Path(file_path).suffix
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, encoding="utf-8",
            ) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                target_path = temp_file.name
        except OSError:
            return None

    try:
        result = subprocess.run(
            [
                "ctags", "--output-format=json", "--fields=+neKS",
                "--kinds-all=*", "-f", "-", target_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    finally:
        if temp_file:
            Path(temp_file.name).unlink(missing_ok=True)

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[dict] = []
    top_level_vars: list[str] = []

    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            tag = json_mod.loads(line)
        except json_mod.JSONDecodeError:
            continue

        name = tag.get("name", "")
        kind = tag.get("kind", "")
        line_no = tag.get("line", 0)
        end_line = tag.get("end", line_no)

        if not name:
            continue

        if kind in ("function", "method", "subroutine", "procedure", "def"):
            functions.append({
                "name": name,
                "parameters": [],
                "return_type": tag.get("typeref", ""),
                "start_line": line_no,
                "end_line": end_line,
                "is_async": False,
                "decorators": [],
                "visibility": "public",
                "parent_class": tag.get("scope", ""),
            })
        elif kind in ("class", "struct", "interface", "enum", "trait",
                       "module", "namespace", "type", "union"):
            classes.append({
                "name": name,
                "bases": [],
                "methods": [],
                "decorators": [],
                "start_line": line_no,
                "end_line": end_line,
            })
        elif kind in ("import", "include", "using"):
            imports.append({
                "module": name,
                "is_from": False,
                "start_line": line_no,
            })
        elif kind in ("variable", "constant", "define"):
            top_level_vars.append(name)

    if not functions and not classes and not imports and not top_level_vars:
        return None

    # Read line count
    if content is not None:
        line_count = content.count("\n") + 1
    else:
        try:
            line_count = Path(file_path).read_text(encoding="utf-8", errors="replace").count("\n") + 1
        except OSError:
            line_count = 0

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "top_level_vars": top_level_vars,
        "line_count": line_count,
        "language": "unknown",
    }
