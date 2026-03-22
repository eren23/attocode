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
    # ---------------------------------------------------------------
    # Phase 1: 11 new programming languages (9 → 20)
    # ---------------------------------------------------------------
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
    ),
    # ---------------------------------------------------------------
    # Phase 2: Data/config languages (20 → 25)
    # ---------------------------------------------------------------
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
}

# Aliases
LANGUAGE_CONFIGS["c++"] = LANGUAGE_CONFIGS["cpp"]
LANGUAGE_CONFIGS["c#"] = LANGUAGE_CONFIGS["csharp"]
LANGUAGE_CONFIGS["shell"] = LANGUAGE_CONFIGS["bash"]
LANGUAGE_CONFIGS["sh"] = LANGUAGE_CONFIGS["bash"]
LANGUAGE_CONFIGS["terraform"] = LANGUAGE_CONFIGS["hcl"]
LANGUAGE_CONFIGS["scss"] = LANGUAGE_CONFIGS["css"]


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
        logger.debug("tree-sitter grammar for %s not available: %s", language, e)
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


def _get_visibility(name: str, language: str) -> str:
    """Determine visibility from name conventions."""
    if language == "python":
        if name.startswith("__") and not name.endswith("__"):
            return "private"
        if name.startswith("_"):
            return "private"
        return "public"
    elif language in ("java", "typescript", "c", "cpp", "csharp", "kotlin", "swift", "scala"):
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

            fn_data = {
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

            if parent_class:
                # Will be added as method to the class
                for cls in classes:
                    if cls["name"] == parent_class:
                        cls["methods"].append(fn_data)
                        break
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
                classes.append(cls_data)

                # Process children to find methods
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _process_node(child, parent_class=name)
                else:
                    for child in node.children:
                        _process_node(child, parent_class=name)
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
# Phase 3: Generic tree-sitter extractor (any grammar, no config needed)
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
})

# Node types that indicate imports
_GENERIC_IMPORT_TYPES = frozenset({
    "import_statement", "import_declaration", "import_from_statement",
    "use_declaration", "preproc_include", "using_directive",
    "namespace_use_declaration", "import_header",
    "import",  # Haskell
    "using_namespace_declaration",  # Zig
})


class GenericTreeSitterExtractor:
    """Parse any tree-sitter grammar using heuristic node-type matching.

    This provides "good enough" symbol extraction for any language with a
    tree-sitter grammar installed, without needing per-language config.
    """

    def __init__(self) -> None:
        self._grammar_cache: dict[str, object | None] = {}

    def _get_language_obj(self, grammar_module: str):
        """Try to load a tree-sitter Language from a grammar module."""
        if grammar_module in self._grammar_cache:
            return self._grammar_cache[grammar_module]

        if not _TS_AVAILABLE and not _try_init_tree_sitter():
            self._grammar_cache[grammar_module] = None
            return None

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
            if lang_fn is None:
                raise AttributeError(f"No language function found in {grammar_module}")
            lang = ts.Language(lang_fn())
            self._grammar_cache[grammar_module] = lang
            return lang
        except (ImportError, AttributeError, Exception) as e:
            logger.debug("Generic extractor: grammar %s not available: %s", grammar_module, e)
            self._grammar_cache[grammar_module] = None
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
        lang_obj = self._get_language_obj(grammar_module)
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
# Phase 4: Universal-ctags integration (50 → 100+ languages)
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
