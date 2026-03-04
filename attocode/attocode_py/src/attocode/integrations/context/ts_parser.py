"""Unified tree-sitter parser for multi-language AST extraction.

Provides tree-sitter-based parsing for 8 languages: Python, JavaScript,
TypeScript, Go, Rust, Java, Ruby, C/C++. Falls back gracefully when
grammars are not installed.

The main entry point is ``ts_parse_file()`` which returns a ``FileAST``
(the same dataclass used by the regex parsers in ``codebase_ast.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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


LANGUAGE_CONFIGS: dict[str, _LangConfig] = {
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
}

# Alias: cpp shares the same config
LANGUAGE_CONFIGS["c++"] = LANGUAGE_CONFIGS["cpp"]


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
        lang = ts.Language(grammar_mod.language())
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
    elif language in ("java", "typescript", "c", "cpp"):
        # Would need modifier parsing; default to public
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

    return bases


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

        # Recurse into children
        for child in node.children:
            _process_node(child, parent_class=parent_class)

    # Process top-level nodes
    for child in root.children:
        _process_node(child)

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "top_level_vars": top_level_vars,
        "line_count": content.count("\n") + 1,
        "language": language,
    }
