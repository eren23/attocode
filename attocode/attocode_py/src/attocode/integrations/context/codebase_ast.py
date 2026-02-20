"""Codebase AST analysis using tree-sitter.

Provides structural code analysis for Python, JavaScript, and TypeScript
using tree-sitter parsers. Falls back to regex-based extraction when
tree-sitter is not available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FunctionDef:
    """A function definition."""

    name: str
    start_line: int
    end_line: int
    params: list[str] = field(default_factory=list)
    return_type: str = ""
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_method: bool = False
    docstring: str = ""


@dataclass(slots=True)
class ClassDef:
    """A class definition."""

    name: str
    start_line: int
    end_line: int
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionDef] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: str = ""


@dataclass(slots=True)
class ImportDef:
    """An import statement."""

    module: str
    names: list[str] = field(default_factory=list)
    alias: str = ""
    is_from: bool = False
    line: int = 0


@dataclass(slots=True)
class FileAST:
    """AST summary for a single file."""

    path: str
    language: str
    functions: list[FunctionDef] = field(default_factory=list)
    classes: list[ClassDef] = field(default_factory=list)
    imports: list[ImportDef] = field(default_factory=list)
    top_level_vars: list[str] = field(default_factory=list)
    line_count: int = 0

    @property
    def symbol_count(self) -> int:
        return len(self.functions) + len(self.classes)

    def get_symbols(self) -> list[str]:
        """Get all top-level symbol names."""
        symbols = [f.name for f in self.functions]
        symbols.extend(c.name for c in self.classes)
        return symbols


# Language detection
LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return LANG_EXTENSIONS.get(ext, "unknown")


# Regex-based fallback parsers (no tree-sitter dependency)

def parse_python(content: str, path: str = "") -> FileAST:
    """Parse Python source using regex patterns."""
    lines = content.split("\n")
    ast = FileAST(path=path, language="python", line_count=len(lines))

    # Parse imports
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from "):
            match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", stripped)
            if match:
                module = match.group(1)
                names = [n.strip().split(" as ")[0].strip() for n in match.group(2).split(",")]
                ast.imports.append(ImportDef(
                    module=module, names=names, is_from=True, line=i + 1,
                ))
        elif stripped.startswith("import "):
            match = re.match(r"import\s+(.+)", stripped)
            if match:
                for part in match.group(1).split(","):
                    parts = part.strip().split(" as ")
                    ast.imports.append(ImportDef(
                        module=parts[0].strip(),
                        alias=parts[1].strip() if len(parts) > 1 else "",
                        line=i + 1,
                    ))

    # Parse classes and functions
    current_class: ClassDef | None = None
    decorators: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Decorators
        if stripped.startswith("@"):
            decorators.append(stripped[1:].split("(")[0])
            continue

        # Class definition
        class_match = re.match(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", stripped)
        if class_match and not line.startswith((" ", "\t")):
            class_name = class_match.group(1)
            bases = []
            if class_match.group(2):
                bases = [b.strip() for b in class_match.group(2).split(",")]

            # Find end of class (next non-indented line)
            end_line = i + 1
            for j in range(i + 1, len(lines)):
                if lines[j].strip() and not lines[j].startswith((" ", "\t")):
                    end_line = j
                    break
            else:
                end_line = len(lines)

            # Extract docstring
            docstring = _extract_docstring(lines, i + 1)

            current_class = ClassDef(
                name=class_name,
                start_line=i + 1,
                end_line=end_line,
                bases=bases,
                decorators=decorators,
                docstring=docstring,
            )
            ast.classes.append(current_class)
            decorators = []
            continue

        # Function definition
        func_match = re.match(
            r"^(\s*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*(.+))?\s*:",
            line,
        )
        if func_match:
            indent = func_match.group(1)
            is_async = func_match.group(2) is not None
            func_name = func_match.group(3)
            params_str = func_match.group(4)
            return_type = (func_match.group(5) or "").strip().rstrip(":")

            params = [p.strip().split(":")[0].strip() for p in params_str.split(",") if p.strip()]

            # Find end of function
            func_indent = len(indent)
            end_line = i + 1
            for j in range(i + 1, len(lines)):
                l = lines[j]
                if l.strip() and not l.startswith((" " * (func_indent + 1))) and not l.startswith("\t" * (func_indent // 4 + 1)):
                    if l.strip() and (len(l) - len(l.lstrip())) <= func_indent:
                        end_line = j
                        break
            else:
                end_line = len(lines)

            docstring = _extract_docstring(lines, i + 1)

            func = FunctionDef(
                name=func_name,
                start_line=i + 1,
                end_line=end_line,
                params=params,
                return_type=return_type,
                decorators=decorators,
                is_async=is_async,
                is_method=func_indent > 0,
                docstring=docstring,
            )

            if current_class and func_indent > 0:
                current_class.methods.append(func)
            else:
                ast.functions.append(func)
                current_class = None

            decorators = []
            continue

        # Top-level variable
        if not line.startswith((" ", "\t")) and "=" in stripped and not stripped.startswith(("#", "def ", "class ", "@", "if ", "for ", "while ", "return ")):
            var_match = re.match(r"^([A-Z_][A-Z_0-9]*)\s*[=:]", stripped)
            if var_match:
                ast.top_level_vars.append(var_match.group(1))

        if stripped and not stripped.startswith(("#", "@")):
            decorators = []

    return ast


def parse_javascript(content: str, path: str = "") -> FileAST:
    """Parse JavaScript/TypeScript source using regex patterns."""
    lines = content.split("\n")
    lang = "typescript" if path.endswith((".ts", ".tsx")) else "javascript"
    ast = FileAST(path=path, language=lang, line_count=len(lines))

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Import statements
        import_match = re.match(r"import\s+(?:type\s+)?(?:\{([^}]+)\}|(\w+))\s+from\s+['\"]([^'\"]+)['\"]", stripped)
        if import_match:
            names = []
            if import_match.group(1):
                names = [n.strip().split(" as ")[0].strip() for n in import_match.group(1).split(",")]
            elif import_match.group(2):
                names = [import_match.group(2)]
            ast.imports.append(ImportDef(
                module=import_match.group(3),
                names=names,
                is_from=True,
                line=i + 1,
            ))

        # Function/method definitions
        func_match = re.match(
            r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(",
            stripped,
        )
        if func_match:
            ast.functions.append(FunctionDef(
                name=func_match.group(1),
                start_line=i + 1,
                end_line=i + 1,
                is_async="async " in stripped,
            ))

        # Class definitions
        class_match = re.match(
            r"^(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?\s*\{",
            stripped,
        )
        if class_match:
            bases = [class_match.group(2)] if class_match.group(2) else []
            ast.classes.append(ClassDef(
                name=class_match.group(1),
                start_line=i + 1,
                end_line=i + 1,
                bases=bases,
            ))

    return ast


def parse_file(file_path: str, content: str | None = None) -> FileAST:
    """Parse a source file and return its AST.

    Uses regex-based parsers. Falls back gracefully for
    unsupported languages.
    """
    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return FileAST(path=file_path, language="unknown")

    lang = detect_language(file_path)

    if lang == "python":
        return parse_python(content, file_path)
    elif lang in ("javascript", "typescript"):
        return parse_javascript(content, file_path)
    else:
        # Minimal parsing for unknown languages
        return FileAST(
            path=file_path,
            language=lang,
            line_count=content.count("\n") + 1,
        )


def _extract_docstring(lines: list[str], start_idx: int) -> str:
    """Extract a Python docstring starting at the given line index."""
    if start_idx >= len(lines):
        return ""

    # Look for triple-quoted string
    for i in range(start_idx, min(start_idx + 3, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.endswith(quote) and len(stripped) > 6:
                return stripped[3:-3].strip()
            # Multi-line docstring
            doc_lines = [stripped[3:]]
            for j in range(i + 1, len(lines)):
                line = lines[j].strip()
                if quote in line:
                    doc_lines.append(line.split(quote)[0])
                    return "\n".join(doc_lines).strip()
                doc_lines.append(line)
            break
    return ""
