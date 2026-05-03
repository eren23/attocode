"""Codebase AST analysis using tree-sitter.

Provides structural code analysis for Python, JavaScript, and TypeScript
using tree-sitter parsers. Falls back to regex-based extraction when
tree-sitter is not available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Parameter and property detail types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ParamDef:
    """Detailed parameter definition for a function/method."""

    name: str
    type_annotation: str = ""
    default_value: str = ""
    is_rest: bool = False       # *args
    is_kwonly: bool = False     # after *
    is_kwargs: bool = False     # **kwargs


@dataclass(slots=True)
class PropertyDef:
    """A class property (attribute) definition."""

    name: str
    start_line: int
    type_annotation: str = ""
    has_default: bool = False
    visibility: str = "public"  # public / private (_prefix) / name_mangled (__prefix)


# ---------------------------------------------------------------------------
# Core AST node types
# ---------------------------------------------------------------------------


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
    # --- Extended fields ---
    parameters: list[ParamDef] = field(default_factory=list)
    visibility: str = "public"
    is_generator: bool = False
    is_staticmethod: bool = False
    is_classmethod: bool = False
    is_property: bool = False
    type_params: list[str] = field(default_factory=list)


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
    # --- Extended fields ---
    properties: list[PropertyDef] = field(default_factory=list)
    is_abstract: bool = False
    metaclass: str = ""


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
    parsing_tier: str = ""  # "tree_sitter", "regex", "generic_ts", "ctags", "minimal"

    @property
    def symbol_count(self) -> int:
        return len(self.functions) + len(self.classes) + len(self.top_level_vars)

    def get_symbols(self) -> list[str]:
        """Get all top-level symbol names (functions, classes, and constants)."""
        symbols = [f.name for f in self.functions]
        symbols.extend(c.name for c in self.classes)
        symbols.extend(self.top_level_vars)
        return symbols


# ---------------------------------------------------------------------------
# Change tracking types (for incremental updates)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DependencyChanges:
    """Changes to a file's import dependencies."""

    added: list[ImportDef] = field(default_factory=list)
    removed: list[ImportDef] = field(default_factory=list)


@dataclass(slots=True)
class SymbolChange:
    """A change to a symbol detected by AST diffing."""

    kind: Literal["added", "removed", "modified"]
    symbol_name: str
    symbol_kind: str  # 'function', 'class', 'method'
    file_path: str
    previous: FunctionDef | ClassDef | None = None


@dataclass(slots=True)
class FileChangeResult:
    """Result of incrementally updating a single file's AST."""

    file_path: str
    symbol_changes: list[SymbolChange] = field(default_factory=list)
    dependency_changes: DependencyChanges = field(default_factory=DependencyChanges)
    was_incremental: bool = True


# Language detection
LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".metal": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".hs": "haskell",
    ".lhs": "haskell",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".tfvars": "hcl",
    ".zig": "zig",
    ".nim": "nim",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".fsx": "fsharp",
    ".cr": "crystal",
    ".m": "objc",
    ".mm": "objc",
    # Data/config languages
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".jsonc": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return LANG_EXTENSIONS.get(ext, "unknown")


# Regex-based fallback parsers (no tree-sitter dependency)


def _parse_python_params(params_str: str) -> tuple[list[str], list[ParamDef]]:
    """Parse a Python function parameter string into both simple names and detailed ParamDefs.

    Handles type annotations, default values, *args, **kwargs, and keyword-only params.

    Returns:
        Tuple of (simple name list for backward compat, detailed ParamDef list).
    """
    simple: list[str] = []
    detailed: list[ParamDef] = []

    if not params_str.strip():
        return simple, detailed

    # Split parameters respecting brackets and string literals
    params_raw: list[str] = []
    depth = 0
    current: list[str] = []
    i = 0
    while i < len(params_str):
        ch = params_str[i]
        if ch in ('"', "'"):
            # Skip string literals
            quote = ch
            current.append(ch)
            i += 1
            while i < len(params_str) and params_str[i] != quote:
                if params_str[i] == "\\":
                    current.append(params_str[i])
                    i += 1
                    if i < len(params_str):
                        current.append(params_str[i])
                        i += 1
                    continue
                current.append(params_str[i])
                i += 1
            if i < len(params_str):
                current.append(params_str[i])  # closing quote
            i += 1
            continue
        if ch in ("(", "[", "{"):
            depth += 1
            current.append(ch)
        elif ch in (")", "]", "}"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            params_raw.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        params_raw.append("".join(current).strip())

    seen_star = False
    for raw in params_raw:
        raw = raw.strip()
        if not raw:
            continue

        # Bare * separator
        if raw == "*":
            seen_star = True
            continue

        is_rest = raw.startswith("*") and not raw.startswith("**")
        is_kwargs = raw.startswith("**")

        # Strip * / **
        cleaned = raw.lstrip("*")

        # Split name : type = default
        name = cleaned
        type_ann = ""
        default_val = ""

        if "=" in cleaned:
            before_eq, default_val = cleaned.split("=", 1)
            default_val = default_val.strip()
            cleaned = before_eq.strip()

        if ":" in cleaned:
            name, type_ann = cleaned.split(":", 1)
            name = name.strip()
            type_ann = type_ann.strip()
        else:
            name = cleaned.strip()

        simple.append(name)
        detailed.append(ParamDef(
            name=name,
            type_annotation=type_ann,
            default_value=default_val,
            is_rest=is_rest,
            is_kwonly=seen_star and not is_rest and not is_kwargs,
            is_kwargs=is_kwargs,
        ))

        if is_rest:
            seen_star = True

    return simple, detailed


def _detect_visibility(name: str) -> str:
    """Detect Python visibility from naming convention."""
    if name.startswith("__") and not name.endswith("__"):
        return "name_mangled"
    if name.startswith("_") and not name.startswith("__"):
        return "private"
    return "public"


def _check_generator(lines: list[str], start: int, end: int, indent: int) -> bool:
    """Check if a function body contains yield/yield from statements."""
    for j in range(start + 1, min(end, len(lines))):
        stripped = lines[j].strip()
        if stripped.startswith(("yield ", "yield\n", "yield\r")) or "yield " in stripped:
            # Verify it's at the right indentation level (not in a nested def)
            line_indent = len(lines[j]) - len(lines[j].lstrip())
            if line_indent > indent:
                return True
    return False


def _extract_class_properties(
    lines: list[str], class_start: int, class_end: int,
) -> list[PropertyDef]:
    """Extract class properties from __init__ body and class-level annotations."""
    props: list[PropertyDef] = []
    seen_names: set[str] = set()

    for j in range(class_start, min(class_end, len(lines))):
        stripped = lines[j].strip()

        # self.x = ... or self.x: type = ...
        init_match = re.match(r"self\.(\w+)\s*(?::\s*(\S+))?\s*=", stripped)
        if init_match:
            attr_name = init_match.group(1)
            if attr_name not in seen_names:
                seen_names.add(attr_name)
                props.append(PropertyDef(
                    name=attr_name,
                    start_line=j + 1,
                    type_annotation=init_match.group(2) or "",
                    has_default=True,
                    visibility=_detect_visibility(attr_name),
                ))

        # Class-level annotation: name: type (no self.)
        # Must be at one indent level inside class
        if not stripped.startswith("self.") and not stripped.startswith("def "):
            ann_match = re.match(r"^(\w+)\s*:\s*(\S+)(?:\s*=\s*(.+))?$", stripped)
            if ann_match:
                line_indent = len(lines[j]) - len(lines[j].lstrip())
                # Must be indented (inside class body)
                if line_indent > 0:
                    attr_name = ann_match.group(1)
                    if attr_name not in seen_names and attr_name not in ("class", "def", "return"):
                        seen_names.add(attr_name)
                        props.append(PropertyDef(
                            name=attr_name,
                            start_line=j + 1,
                            type_annotation=ann_match.group(2) or "",
                            has_default=ann_match.group(3) is not None,
                            visibility=_detect_visibility(attr_name),
                        ))

    return props


_STRINGS_AND_COMMENTS_RE = re.compile(
    r'#.*$|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', re.MULTILINE,
)


def _count_parens(line: str) -> int:
    """Count unbalanced parentheses, ignoring those inside strings and comments."""
    stripped = _STRINGS_AND_COMMENTS_RE.sub("", line)
    return stripped.count("(") - stripped.count(")")


def _join_multiline_defs(lines: list[str]) -> list[tuple[int, int, str]]:
    """Preprocess lines to join multi-line ``def`` and ``class`` signatures.

    Detects lines that start a ``def`` or ``class`` statement but have
    unbalanced parentheses, then accumulates subsequent lines until
    parentheses balance and the line ends with ``:``.

    Returns:
        A list of ``(start_line_index, end_line_index, joined_line)`` tuples.
        *start_line_index* is the original line where the statement begins.
        *end_line_index* is the last raw line consumed (equal to start for
        single-line statements).  Lines that were folded into a preceding
        signature are omitted (their content is merged into the signature
        line).
    """
    result: list[tuple[int, int, str]] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Quick check: does this line start a def or class?
        is_def = bool(re.match(r"\s*(async\s+)?def\s+\w+", line))
        is_class = bool(re.match(r"\s*class\s+\w+", stripped))

        if (is_def or is_class) and "(" in line:
            # Count parentheses balance on this line (ignoring strings/comments)
            depth = _count_parens(line)
            if depth > 0:
                # Multi-line signature — accumulate until balanced
                # Strip comments from each line before joining so embedded
                # comments don't confuse downstream parsing.
                start_idx = i
                parts = [_STRINGS_AND_COMMENTS_RE.sub(
                    lambda m: m.group() if m.group()[0] != "#" else "", line,
                ).rstrip()]
                i += 1
                while i < n and depth > 0:
                    continuation = lines[i]
                    depth += _count_parens(continuation)
                    cleaned = _STRINGS_AND_COMMENTS_RE.sub(
                        lambda m: m.group() if m.group()[0] != "#" else "", continuation,
                    ).strip()
                    parts.append(cleaned)
                    i += 1
                # i now points to the line AFTER the last continuation line
                end_idx = i - 1
                joined = " ".join(parts)
                result.append((start_idx, end_idx, joined))
                continue

        # Regular line — pass through
        result.append((i, i, line))
        i += 1

    return result


def _match_function_def(line: str) -> re.Match[str] | None:
    """Match a function definition with balanced-paren-aware parameter extraction.

    Handles nested parens in default values like ``def foo(x: int = max(0, 1))``.
    Returns a match-like object with groups:
        1: indent, 2: async prefix or None, 3: name,
        4: type params or "", 5: params string, 6: return type or ""
    """
    m = re.match(r"^(\s*)(async\s+)?def\s+(\w+)\s*(?:\[([^\]]*)\])?\s*\(", line)
    if not m:
        return None
    # Find the matching closing paren by counting depth
    paren_start = m.end() - 1  # index of the opening '('
    depth = 1
    i = paren_start + 1
    while i < len(line) and depth > 0:
        ch = line[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch in ('"', "'"):
            # Skip string literals
            quote = ch
            i += 1
            while i < len(line) and line[i] != quote:
                if line[i] == "\\":
                    i += 1
                i += 1
        i += 1
    if depth != 0:
        return None
    paren_end = i - 1  # index of closing ')'
    params_str = line[paren_start + 1:paren_end]
    rest = line[paren_end + 1:]
    # Match optional return type and colon
    ret_match = re.match(r"\s*(?:->\s*(.+?))?\s*:\s*$", rest)
    if not ret_match:
        return None
    return_type = ret_match.group(1) or ""
    # Build a synthetic match via a simple namespace
    class _FuncMatch:
        def group(self, n: int) -> str | None:
            return [
                line,  # 0: full match
                m.group(1),  # 1: indent
                m.group(2),  # 2: async prefix
                m.group(3),  # 3: name
                m.group(4) or "",  # 4: type params
                params_str,  # 5: params
                return_type,  # 6: return type
            ][n]
    return _FuncMatch()


def parse_python(content: str, path: str = "") -> FileAST:
    """Parse Python source using regex patterns.

    Extracts functions, classes, imports, and top-level variables.
    Populates extended fields: ParamDef details, visibility, decorator flags,
    generator detection, class properties, abstract detection, metaclass.
    """
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

    # Preprocess lines to join multi-line def/class signatures
    preprocessed = _join_multiline_defs(lines)

    # Parse classes and functions
    current_class: ClassDef | None = None
    decorators: list[str] = []

    for orig_line_idx, sig_end_idx, line in preprocessed:
        i = orig_line_idx
        stripped = line.strip()

        # Decorators
        if stripped.startswith("@"):
            decorators.append(stripped[1:].split("(")[0])
            continue

        # Class definition
        class_match = re.match(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", stripped)
        if class_match and not line.startswith((" ", "\t")):
            class_name = class_match.group(1)
            bases_str = class_match.group(2) or ""
            bases = [b.strip() for b in bases_str.split(",") if b.strip()] if bases_str else []

            # Extract metaclass from bases (metaclass=ABCMeta)
            metaclass = ""
            filtered_bases: list[str] = []
            for b in bases:
                mc_match = re.match(r"metaclass\s*=\s*(\w+)", b)
                if mc_match:
                    metaclass = mc_match.group(1)
                else:
                    filtered_bases.append(b)

            # Find end of class (next non-indented line)
            # Start scanning from after the last line of the signature
            body_start = sig_end_idx + 1
            end_line = body_start
            for j in range(body_start, len(lines)):
                if lines[j].strip() and not lines[j].startswith((" ", "\t")):
                    end_line = j
                    break
            else:
                end_line = len(lines)

            # Extract docstring (body starts after the signature)
            docstring = _extract_docstring(lines, body_start)

            # Detect abstract class
            is_abstract = (
                "ABC" in filtered_bases
                or "ABCMeta" in metaclass
                or "abstractmethod" in decorators
            )

            # Extract properties
            properties = _extract_class_properties(lines, body_start, end_line)

            current_class = ClassDef(
                name=class_name,
                start_line=i + 1,
                end_line=end_line,
                bases=filtered_bases,
                decorators=decorators,
                docstring=docstring,
                properties=properties,
                is_abstract=is_abstract,
                metaclass=metaclass,
            )
            ast.classes.append(current_class)
            decorators = []
            continue

        # Function definition (with optional PEP 695 type params)
        # Use balanced-paren-aware extraction instead of [^)]*
        func_match = _match_function_def(line)
        if func_match:
            indent = func_match.group(1)
            is_async = func_match.group(2) is not None
            func_name = func_match.group(3)
            type_params_str = func_match.group(4) or ""
            params_str = func_match.group(5)
            return_type = (func_match.group(6) or "").strip().rstrip(":")

            # Parse type params (PEP 695)
            type_params = [t.strip() for t in type_params_str.split(",") if t.strip()] if type_params_str else []

            # Parse parameters (both simple and detailed)
            params, parameters = _parse_python_params(params_str)

            # Find end of function
            # Start scanning from after the last line of the signature
            func_indent = len(indent)
            func_body_start = sig_end_idx + 1
            end_line = func_body_start
            for j in range(func_body_start, len(lines)):
                line = lines[j]
                if line.strip() and not line.startswith(" " * (func_indent + 1)) and not line.startswith("\t" * (func_indent // 4 + 1)) and (len(line) - len(line.lstrip())) <= func_indent:
                    end_line = j
                    break
            else:
                end_line = len(lines)

            docstring = _extract_docstring(lines, func_body_start)

            # Detect decorator-based flags
            is_staticmethod = "staticmethod" in decorators
            is_classmethod = "classmethod" in decorators
            is_property_flag = "property" in decorators
            is_abstract_method = "abstractmethod" in decorators

            # Detect visibility
            visibility = _detect_visibility(func_name)

            # Detect generator
            is_generator = _check_generator(lines, i, end_line, func_indent)

            # If abstract method found on a function inside a class, mark class abstract
            if is_abstract_method and current_class and not current_class.is_abstract:
                current_class.is_abstract = True

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
                parameters=parameters,
                visibility=visibility,
                is_generator=is_generator,
                is_staticmethod=is_staticmethod,
                is_classmethod=is_classmethod,
                is_property=is_property_flag,
                type_params=type_params,
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
            var_match = re.match(r"^([A-Z][A-Za-z_0-9]*|[A-Z_][A-Z_0-9]*)\s*[=:]", stripped)
            if var_match:
                ast.top_level_vars.append(var_match.group(1))

        if stripped and not stripped.startswith(("#", "@")):
            decorators = []

    return ast


def _parse_js_params(params_str: str) -> tuple[list[str], list[ParamDef]]:
    """Parse a JS/TS parameter string into param names and ParamDef list."""
    params: list[str] = []
    parameters: list[ParamDef] = []
    if not params_str.strip():
        return params, parameters
    for p in params_str.split(","):
        p = p.strip()
        if not p:
            continue
        is_rest = p.startswith("...")
        p_cleaned = p.lstrip(".")
        name = p_cleaned
        type_ann = ""
        default_val = ""
        if "=" in p_cleaned:
            name, default_val = p_cleaned.split("=", 1)
            name = name.strip()
            default_val = default_val.strip()
        if ":" in name:
            name, type_ann = name.split(":", 1)
            name = name.strip()
            type_ann = type_ann.strip()
        # Strip optional ? from name
        name = name.rstrip("?")
        params.append(name)
        parameters.append(ParamDef(
            name=name,
            type_annotation=type_ann,
            default_value=default_val,
            is_rest=is_rest,
        ))
    return params, parameters


def parse_javascript(content: str, path: str = "") -> FileAST:
    """Parse JavaScript/TypeScript source using regex patterns.

    Extracts functions with parameter details, classes with methods and end
    lines, and TypeScript visibility modifiers.
    """
    lines = content.split("\n")
    lang = "typescript" if path.endswith((".ts", ".tsx")) else "javascript"
    ast = FileAST(path=path, language=lang, line_count=len(lines))

    decorators: list[str] = []
    # Track class body for method extraction
    current_class: ClassDef | None = None
    class_brace_depth: int = 0

    # Method pattern: matches class methods like `async foo(x: number): void {`
    # including optional visibility, static, abstract, get/set modifiers.
    _method_re = re.compile(
        r"^(?:(?:public|private|protected|readonly)\s+)*"
        r"(?:static\s+)?(?:abstract\s+)?(?:async\s+)?"
        r"(?:get\s+|set\s+)?"
        r"(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
        r"(?:\s*:\s*([^{]+?))?\s*\{"
    )

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track brace depth inside a class body
        if current_class is not None:
            class_brace_depth += stripped.count("{") - stripped.count("}")
            if class_brace_depth <= 0:
                current_class = None
                class_brace_depth = 0

        # Decorators (TypeScript)
        if stripped.startswith("@"):
            decorators.append(stripped[1:].split("(")[0])
            continue

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

        # Function definitions (top-level `function` keyword)
        func_match = re.match(
            r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
            r"(?:\s*:\s*([^{]+?))?\s*\{",
            stripped,
        )
        if func_match:
            func_name = func_match.group(1)
            params, parameters = _parse_js_params(func_match.group(2))
            return_type = (func_match.group(3) or "").strip()

            # Find end line via brace matching
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break

            ast.functions.append(FunctionDef(
                name=func_name,
                start_line=i + 1,
                end_line=end_line,
                params=params,
                parameters=parameters,
                return_type=return_type,
                is_async="async " in stripped,
                decorators=decorators,
            ))
            decorators = []
            continue

        # Class definitions
        class_match = re.match(
            r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([^{]+))?\s*\{",
            stripped,
        )
        if class_match:
            bases = [class_match.group(2)] if class_match.group(2) else []
            is_abstract = "abstract " in stripped.split("class")[0]

            # Find end line via brace matching
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 1000, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break

            current_class = ClassDef(
                name=class_match.group(1),
                start_line=i + 1,
                end_line=end_line,
                bases=bases,
                decorators=decorators,
                is_abstract=is_abstract,
            )
            ast.classes.append(current_class)
            # Track brace depth: start at 1 (the opening brace of the class)
            class_brace_depth = stripped.count("{") - stripped.count("}")
            decorators = []
            continue

        # Method definitions inside a class body
        if current_class is not None and class_brace_depth > 0:
            method_match = _method_re.match(stripped)
            if method_match:
                method_name = method_match.group(1)
                # Skip constructor as a special case — still include it
                params, parameters = _parse_js_params(method_match.group(2))
                return_type = (method_match.group(3) or "").strip()

                # Find method end line via brace matching
                end_line = i + 1
                m_brace = stripped.count("{") - stripped.count("}")
                if m_brace > 0:
                    for j in range(i + 1, min(i + 500, len(lines))):
                        m_brace += lines[j].count("{") - lines[j].count("}")
                        if m_brace <= 0:
                            end_line = j + 1
                            break

                current_class.methods.append(FunctionDef(
                    name=method_name,
                    start_line=i + 1,
                    end_line=end_line,
                    params=params,
                    parameters=parameters,
                    return_type=return_type,
                    is_async="async " in stripped.split(method_name)[0],
                    decorators=decorators,
                ))
                decorators = []
                continue

        if stripped and not stripped.startswith("@"):
            decorators = []

    return ast


def parse_rust(content: str, path: str = "") -> FileAST:
    """Parse Rust source using regex patterns.

    Extracts functions, structs, enums, traits, impl blocks, imports (use/mod).
    """
    lines = content.split("\n")
    ast = FileAST(path=path, language="rust", line_count=len(lines))

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Imports: use ... ;
        use_match = re.match(r"^(?:pub\s+)?use\s+(.+);", stripped)
        if use_match:
            module = use_match.group(1).strip()
            # Extract the base path (before :: { ... })
            base = re.sub(r"\s*::\s*\{[^}]*\}", "", module)
            base = re.sub(r"\s*::\s*\w+$", "", base)
            ast.imports.append(ImportDef(module=module, is_from=True, line=i + 1))
            continue

        # mod declarations: mod foo;
        mod_match = re.match(r"^(?:pub\s+)?mod\s+(\w+)\s*;", stripped)
        if mod_match:
            ast.imports.append(ImportDef(
                module=mod_match.group(1), is_from=False, line=i + 1,
            ))
            continue

        # Functions: (pub)? (async)? fn name(...)
        fn_match = re.match(
            r"^(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+(\w+)",
            stripped,
        )
        if fn_match:
            func_name = fn_match.group(1)
            # Find end via brace matching
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            is_async = "async " in stripped.split("fn")[0]
            ast.functions.append(FunctionDef(
                name=func_name,
                start_line=i + 1,
                end_line=end_line,
                is_async=is_async,
            ))
            continue

        # Structs: (pub)? struct Name
        struct_match = re.match(r"^(?:pub(?:\([\w:]+\))?\s+)?struct\s+(\w+)", stripped)
        if struct_match:
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.classes.append(ClassDef(
                name=struct_match.group(1),
                start_line=i + 1,
                end_line=end_line,
            ))
            continue

        # Enums: (pub)? enum Name
        enum_match = re.match(r"^(?:pub(?:\([\w:]+\))?\s+)?enum\s+(\w+)", stripped)
        if enum_match:
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.classes.append(ClassDef(
                name=enum_match.group(1),
                start_line=i + 1,
                end_line=end_line,
            ))
            continue

        # Traits: (pub)? trait Name
        trait_match = re.match(r"^(?:pub(?:\([\w:]+\))?\s+)?(?:unsafe\s+)?trait\s+(\w+)", stripped)
        if trait_match:
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.classes.append(ClassDef(
                name=trait_match.group(1),
                start_line=i + 1,
                end_line=end_line,
            ))
            continue

        # Top-level constants: (pub)? const NAME: ...
        const_match = re.match(r"^(?:pub\s+)?(?:const|static)\s+(\w+)\s*:", stripped)
        if const_match:
            ast.top_level_vars.append(const_match.group(1))

    return ast


def parse_go(content: str, path: str = "") -> FileAST:
    """Parse Go source using regex patterns.

    Extracts functions, methods, structs, interfaces, imports.
    """
    lines = content.split("\n")
    ast = FileAST(path=path, language="go", line_count=len(lines))

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Import block: import ( ... )
        if stripped == "import (" or stripped.startswith("import ("):
            i += 1
            while i < len(lines):
                imp_line = lines[i].strip()
                if imp_line == ")":
                    break
                # Parse "pkg" or alias "pkg"
                imp_match = re.match(r'^(?:\w+\s+)?"([^"]+)"', imp_line)
                if imp_match:
                    ast.imports.append(ImportDef(
                        module=imp_match.group(1), is_from=False, line=i + 1,
                    ))
                i += 1
            i += 1
            continue

        # Single import: import "pkg"
        single_imp = re.match(r'^import\s+(?:\w+\s+)?"([^"]+)"', stripped)
        if single_imp:
            ast.imports.append(ImportDef(
                module=single_imp.group(1), is_from=False, line=i + 1,
            ))
            i += 1
            continue

        # Method: func (receiver) Name(...)
        method_match = re.match(r"^func\s+\([^)]+\)\s+(\w+)\s*\(", stripped)
        if method_match:
            func_name = method_match.group(1)
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.functions.append(FunctionDef(
                name=func_name,
                start_line=i + 1,
                end_line=end_line,
                is_method=True,
            ))
            i += 1
            continue

        # Function: func Name(...)
        fn_match = re.match(r"^func\s+(\w+)\s*\(", stripped)
        if fn_match:
            func_name = fn_match.group(1)
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.functions.append(FunctionDef(
                name=func_name,
                start_line=i + 1,
                end_line=end_line,
            ))
            i += 1
            continue

        # Struct: type Name struct {
        struct_match = re.match(r"^type\s+(\w+)\s+struct\s*\{", stripped)
        if struct_match:
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.classes.append(ClassDef(
                name=struct_match.group(1),
                start_line=i + 1,
                end_line=end_line,
            ))
            i += 1
            continue

        # Interface: type Name interface {
        iface_match = re.match(r"^type\s+(\w+)\s+interface\s*\{", stripped)
        if iface_match:
            end_line = i + 1
            brace_count = stripped.count("{") - stripped.count("}")
            if brace_count > 0:
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
            ast.classes.append(ClassDef(
                name=iface_match.group(1),
                start_line=i + 1,
                end_line=end_line,
            ))
            i += 1
            continue

        # Top-level constants
        const_match = re.match(r"^(?:var|const)\s+(\w+)\s+", stripped)
        if const_match:
            ast.top_level_vars.append(const_match.group(1))

        i += 1

    return ast


def _ts_result_to_file_ast(result: dict, file_path: str) -> FileAST:
    """Convert tree-sitter parse result dict into a FileAST dataclass."""
    language = result.get("language", "unknown")

    # Convert function dicts to FunctionDef
    functions: list[FunctionDef] = []
    for fn in result.get("functions", []):
        params = fn.get("parameters", [])
        param_defs = [
            ParamDef(name=p) if isinstance(p, str) else p
            for p in params
        ]
        functions.append(FunctionDef(
            name=fn["name"],
            start_line=fn.get("start_line", 0),
            end_line=fn.get("end_line", 0),
            parameters=param_defs,
            return_type=fn.get("return_type", ""),
            decorators=fn.get("decorators", []),
            is_async=fn.get("is_async", False),
            visibility=fn.get("visibility", "public"),
            docstring=fn.get("docstring", ""),
        ))

    # Convert class dicts to ClassDef
    classes: list[ClassDef] = []
    for cls in result.get("classes", []):
        methods: list[FunctionDef] = []
        for m in cls.get("methods", []):
            m_params = m.get("parameters", [])
            m_param_defs = [
                ParamDef(name=p) if isinstance(p, str) else p
                for p in m_params
            ]
            methods.append(FunctionDef(
                name=m["name"],
                start_line=m.get("start_line", 0),
                end_line=m.get("end_line", 0),
                parameters=m_param_defs,
                return_type=m.get("return_type", ""),
                decorators=m.get("decorators", []),
                is_async=m.get("is_async", False),
                visibility=m.get("visibility", "public"),
                docstring=m.get("docstring", ""),
            ))
        classes.append(ClassDef(
            name=cls["name"],
            start_line=cls.get("start_line", 0),
            end_line=cls.get("end_line", 0),
            bases=cls.get("bases", []),
            methods=methods,
            decorators=cls.get("decorators", []),
            docstring=cls.get("docstring", ""),
        ))

    # Convert import dicts to ImportDef
    imports: list[ImportDef] = []
    for imp in result.get("imports", []):
        imports.append(ImportDef(
            module=imp.get("module", ""),
            is_from=imp.get("is_from", False),
        ))

    return FileAST(
        path=file_path,
        language=language,
        functions=functions,
        classes=classes,
        imports=imports,
        top_level_vars=result.get("top_level_vars", []),
        line_count=result.get("line_count", 0),
    )


def parse_file(file_path: str, content: str | None = None) -> FileAST:
    """Parse a source file and return its AST.

    Uses a tiered fallback strategy:
      1. Tree-sitter with per-language config (25 languages)
      2. Generic tree-sitter heuristics (30+ additional languages)
      3. Regex-based parsers for Python/JS/TS/Rust/Go
      4. Universal-ctags subprocess (150+ languages)
      5. Minimal FileAST for truly unknown languages

    Returns a FileAST for any input file.
    """
    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return FileAST(path=file_path, language="unknown")

    lang = detect_language(file_path)

    # Tier 1: Tree-sitter with per-language config (25 languages)
    try:
        from attocode.integrations.context.ts_parser import ts_parse_file

        ts_result = ts_parse_file(file_path, content=content, language=lang)
        if ts_result is not None:
            result = _ts_result_to_file_ast(ts_result, file_path)
            result.parsing_tier = "tree_sitter"
            return result
    except ImportError:
        pass  # tree-sitter not installed

    # Tier 2: Regex fallback for Python, JavaScript/TypeScript, Rust, Go
    regex_result: FileAST | None = None
    if lang == "python":
        regex_result = parse_python(content, file_path)
    elif lang in ("javascript", "typescript"):
        regex_result = parse_javascript(content, file_path)
    elif lang == "rust":
        regex_result = parse_rust(content, file_path)
    elif lang == "go":
        regex_result = parse_go(content, file_path)
    if regex_result is not None:
        regex_result.parsing_tier = "regex"
        return regex_result

    # Tier 3: Generic tree-sitter heuristics (30+ additional languages)
    try:
        from attocode.integrations.context.ts_parser import ts_parse_file_generic

        generic_result = ts_parse_file_generic(file_path, content=content, language=lang)
        if generic_result is not None:
            result = _ts_result_to_file_ast(generic_result, file_path)
            result.parsing_tier = "generic_ts"
            return result
    except ImportError:
        pass

    # Tier 4: Universal-ctags fallback (150+ languages)
    try:
        from attocode.integrations.context.ts_parser import ctags_parse_file

        ctags_result = ctags_parse_file(file_path, content=content)
        if ctags_result is not None:
            if lang:
                ctags_result["language"] = lang
            result = _ts_result_to_file_ast(ctags_result, file_path)
            result.parsing_tier = "ctags"
            return result
    except Exception:
        pass  # ctags not installed or other error

    # Tier 5: Minimal parsing for unknown languages
    return FileAST(
        path=file_path,
        language=lang if lang != "unknown" else lang,
        line_count=content.count("\n") + 1,
        parsing_tier="minimal",
    )


def diff_file_ast(old: FileAST, new: FileAST) -> list[SymbolChange]:
    """Compute symbol-level diff between two versions of a file's AST.

    Compares functions and classes by name and detects additions,
    removals, and modifications (signature or line range changes).

    Args:
        old: Previous AST for the file.
        new: Current AST for the file.

    Returns:
        List of SymbolChange objects describing what changed.
    """
    changes: list[SymbolChange] = []
    file_path = new.path or old.path

    # --- Functions ---
    old_funcs = {f.name: f for f in old.functions}
    new_funcs = {f.name: f for f in new.functions}

    for name in new_funcs:
        if name not in old_funcs:
            changes.append(SymbolChange(
                kind="added", symbol_name=name, symbol_kind="function",
                file_path=file_path,
            ))
        else:
            of, nf = old_funcs[name], new_funcs[name]
            if (of.params != nf.params or of.return_type != nf.return_type
                    or of.decorators != nf.decorators or of.is_async != nf.is_async
                    or of.start_line != nf.start_line or of.end_line != nf.end_line):
                changes.append(SymbolChange(
                    kind="modified", symbol_name=name, symbol_kind="function",
                    file_path=file_path, previous=of,
                ))

    for name in old_funcs:
        if name not in new_funcs:
            changes.append(SymbolChange(
                kind="removed", symbol_name=name, symbol_kind="function",
                file_path=file_path, previous=old_funcs[name],
            ))

    # --- Classes ---
    old_classes = {c.name: c for c in old.classes}
    new_classes = {c.name: c for c in new.classes}

    for name in new_classes:
        if name not in old_classes:
            changes.append(SymbolChange(
                kind="added", symbol_name=name, symbol_kind="class",
                file_path=file_path,
            ))
        else:
            oc, nc = old_classes[name], new_classes[name]
            old_method_names = {m.name for m in oc.methods}
            new_method_names = {m.name for m in nc.methods}
            if (oc.bases != nc.bases or oc.decorators != nc.decorators
                    or old_method_names != new_method_names
                    or oc.start_line != nc.start_line or oc.end_line != nc.end_line):
                changes.append(SymbolChange(
                    kind="modified", symbol_name=name, symbol_kind="class",
                    file_path=file_path, previous=oc,
                ))
            # Check individual method changes
            old_methods = {m.name: m for m in oc.methods}
            new_methods = {m.name: m for m in nc.methods}
            for mname in new_methods:
                if mname not in old_methods:
                    changes.append(SymbolChange(
                        kind="added", symbol_name=f"{name}.{mname}",
                        symbol_kind="method", file_path=file_path,
                    ))
                else:
                    om, nm = old_methods[mname], new_methods[mname]
                    if (om.params != nm.params or om.return_type != nm.return_type
                            or om.start_line != nm.start_line):
                        changes.append(SymbolChange(
                            kind="modified", symbol_name=f"{name}.{mname}",
                            symbol_kind="method", file_path=file_path, previous=om,
                        ))
            for mname in old_methods:
                if mname not in new_methods:
                    changes.append(SymbolChange(
                        kind="removed", symbol_name=f"{name}.{mname}",
                        symbol_kind="method", file_path=file_path, previous=old_methods[mname],
                    ))

    return changes


def diff_imports(old: FileAST, new: FileAST) -> DependencyChanges:
    """Compute import-level diff between two versions of a file's AST.

    Args:
        old: Previous AST for the file.
        new: Current AST for the file.

    Returns:
        DependencyChanges with added and removed imports.
    """
    old_set = {(i.module, tuple(i.names), i.is_from) for i in old.imports}
    new_set = {(i.module, tuple(i.names), i.is_from) for i in new.imports}

    added = [
        ImportDef(module=m, names=list(n), is_from=f)
        for m, n, f in (new_set - old_set)
    ]
    removed = [
        ImportDef(module=m, names=list(n), is_from=f)
        for m, n, f in (old_set - new_set)
    ]

    return DependencyChanges(added=added, removed=removed)


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
