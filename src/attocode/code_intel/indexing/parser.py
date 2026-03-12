"""Parser bridge — connects indexing pipeline with existing AST/CodeAnalyzer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Language detection by extension
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".sh": "bash",
    ".bash": "bash",
    ".zig": "zig",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
}


def detect_language(path: str) -> str | None:
    """Detect programming language from file extension."""
    ext = Path(path).suffix.lower()
    return _EXT_TO_LANG.get(ext)


def parse_content(content_sha: str, content: bytes, filename: str) -> dict:
    """Parse file content and return structured result keyed by content SHA.

    Bridge function for the content-hash-gated incremental pipeline.
    Returns: {content_sha, language, symbols, imports}
    """
    language = detect_language(filename)
    symbols = extract_symbols(content, filename)
    imports = _extract_imports(content, filename, language)

    return {
        "content_sha": content_sha,
        "language": language,
        "symbols": symbols,
        "imports": imports,
    }


def _extract_imports(content: bytes, path: str, language: str | None) -> list[str]:
    """Extract import statements from file content. Returns list of module names."""
    import re

    if language is None:
        return []

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return []

    imports = []
    if language == "python":
        for m in re.finditer(r"^from\s+([\w.]+)\s+import\s+", text, re.MULTILINE):
            imports.append(m.group(1))
        for m in re.finditer(r"^import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", text, re.MULTILINE):
            for name in m.group(1).split(","):
                name = name.strip().split(" as ")[0].strip()
                if name:
                    imports.append(name)
    elif language in ("javascript", "typescript"):
        # import X from 'module'; import { X } from 'module'; import 'module'
        for m in re.finditer(r"""import\s+(?:.*?\s+from\s+)?['"]([\w@/.\\-]+)['"]""", text):
            imports.append(m.group(1))
        # require('module')
        for m in re.finditer(r"""require\s*\(\s*['"]([\w@/.\\-]+)['"]""", text):
            imports.append(m.group(1))
    elif language == "go":
        # M3 fix: restrict to Go import block context, not all quoted strings
        import_block = re.search(r'import\s*\((.*?)\)', text, re.DOTALL)
        if import_block:
            for m in re.finditer(r'"([\w/.\\-]+)"', import_block.group(1)):
                imports.append(m.group(1))
        # Single import: import "pkg"
        for m in re.finditer(r'^import\s+"([\w/.\\-]+)"', text, re.MULTILINE):
            imports.append(m.group(1))
    elif language == "rust":
        for m in re.finditer(r"^use\s+([\w:]+)", text, re.MULTILINE):
            imports.append(m.group(1))
    elif language == "java":
        for m in re.finditer(r"^import\s+([\w.]+);", text, re.MULTILINE):
            imports.append(m.group(1))

    return imports


def extract_symbols(content: bytes, path: str) -> list[dict]:
    """Extract symbols from file content using tree-sitter if available.

    Falls back to regex-based extraction for common patterns.
    Returns list of symbol dicts with keys: name, kind, line_start, line_end,
    signature, exported.
    """
    language = detect_language(path)
    if not language:
        return []

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return []

    # Try tree-sitter first
    try:
        return _extract_with_tree_sitter(text, language)
    except Exception:
        pass

    # Fallback to regex
    return _extract_with_regex(text, language)


def _extract_with_tree_sitter(text: str, language: str) -> list[dict]:
    """Extract symbols using tree-sitter."""
    import tree_sitter

    # This will raise if tree-sitter is not available
    from attocode.code_intel.helpers import get_parser

    parser = get_parser(language)
    if parser is None:
        raise RuntimeError("No parser available")

    tree = parser.parse(bytes(text, "utf-8"))
    symbols = []

    # Walk tree for function/class definitions
    _walk_tree(tree.root_node, symbols, language)
    return symbols


def _walk_tree(node, symbols: list[dict], language: str) -> None:
    """Recursively walk AST nodes to extract symbol definitions."""
    kind_map = {
        "function_definition": "function",
        "function_declaration": "function",
        "method_definition": "method",
        "class_definition": "class",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "variable_declaration": "variable",
        "const_declaration": "constant",
    }

    node_type = node.type
    if node_type in kind_map:
        name_node = node.child_by_field_name("name")
        if name_node:
            symbols.append({
                "name": name_node.text.decode("utf-8"),
                "kind": kind_map[node_type],
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "signature": None,
                "exported": False,
            })

    for child in node.children:
        _walk_tree(child, symbols, language)


def _extract_with_regex(text: str, language: str) -> list[dict]:
    """Regex-based symbol extraction fallback."""
    import re

    symbols = []
    lines = text.split("\n")

    patterns = {
        "python": [
            (r"^(?:async\s+)?def\s+(\w+)", "function"),
            (r"^class\s+(\w+)", "class"),
        ],
        "javascript": [
            (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"(?:export\s+)?class\s+(\w+)", "class"),
            (r"(?:export\s+)?const\s+(\w+)\s*=", "constant"),
        ],
        "typescript": [
            (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"(?:export\s+)?class\s+(\w+)", "class"),
            (r"(?:export\s+)?interface\s+(\w+)", "interface"),
            (r"(?:export\s+)?type\s+(\w+)", "type"),
        ],
    }

    lang_patterns = patterns.get(language, patterns.get("javascript", []))

    for i, line in enumerate(lines, 1):
        for pattern, kind in lang_patterns:
            match = re.match(pattern, line.strip())
            if match:
                symbols.append({
                    "name": match.group(1),
                    "kind": kind,
                    "line_start": i,
                    "line_end": i,
                    "signature": None,
                    "exported": "export" in line,
                })
                break

    return symbols
