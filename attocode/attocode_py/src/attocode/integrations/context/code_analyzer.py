"""Code analyzer using optional tree-sitter for AST parsing.

Extracts code chunks (functions, classes, imports) from source files
for intelligent context selection. Falls back to regex-based parsing
when tree-sitter is not available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _djb2_hash(s: str) -> int:
    """DJB2 hash function for content-based cache invalidation."""
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return h


@dataclass(slots=True)
class CodeChunk:
    """A chunk of code extracted from a file."""

    name: str
    kind: str  # 'function', 'class', 'method', 'import', 'constant'
    start_line: int
    end_line: int
    content: str
    file_path: str = ""
    language: str = ""
    signature: str = ""  # Function/method signature
    parent: str = ""  # Parent class for methods
    docstring: str = ""
    importance: float = 0.5

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(slots=True)
class FileAnalysis:
    """Analysis results for a single file."""

    path: str
    language: str
    chunks: list[CodeChunk]
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    line_count: int = 0
    has_main: bool = False


# Tree-sitter availability flag
_TREE_SITTER_AVAILABLE = False
try:
    import tree_sitter  # type: ignore[import-untyped]
    _TREE_SITTER_AVAILABLE = True
except ImportError:
    pass


def is_tree_sitter_available() -> bool:
    """Check if tree-sitter is available."""
    return _TREE_SITTER_AVAILABLE


class CodeAnalyzer:
    """Analyzes source code files to extract structured chunks.

    Uses tree-sitter when available, falls back to regex-based
    extraction otherwise. Caches results using content hashing
    to avoid re-analysis of unchanged files.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, Any] = {}
        self._cache: dict[str, tuple[int, FileAnalysis]] = {}  # path -> (hash, result)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    @property
    def cache_stats(self) -> dict[str, int]:
        """Return cache hit/miss statistics."""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "entries": len(self._cache),
        }

    def clear_cache(self) -> None:
        """Clear the analysis cache."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def analyze_file(self, path: str, language: str = "") -> FileAnalysis:
        """Analyze a source file.

        Uses content-hash caching: if the file content hasn't changed
        since the last analysis, returns the cached result.

        Args:
            path: File path to analyze.
            language: Language hint (auto-detected from extension if empty).

        Returns:
            FileAnalysis with extracted chunks.
        """
        p = Path(path)
        if not p.exists() or not p.is_file():
            return FileAnalysis(path=path, language=language, chunks=[])

        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return FileAnalysis(path=path, language=language, chunks=[])

        # Check content-hash cache
        content_hash = _djb2_hash(content)
        cached = self._cache.get(path)
        if cached is not None and cached[0] == content_hash:
            self._cache_hits += 1
            return cached[1]

        self._cache_misses += 1

        if not language:
            language = _detect_language(p.suffix)

        lines = content.splitlines()

        if _TREE_SITTER_AVAILABLE and language in ("python", "javascript", "typescript"):
            chunks = self._analyze_with_tree_sitter(content, language, path)
        else:
            chunks = self._analyze_with_regex(content, language, path)

        # Extract imports
        imports = _extract_imports(content, language)

        # Check for main entry point
        has_main = _has_main_guard(content, language)

        result = FileAnalysis(
            path=path,
            language=language,
            chunks=chunks,
            imports=imports,
            line_count=len(lines),
            has_main=has_main,
        )

        # Store in cache
        self._cache[path] = (content_hash, result)
        return result

    def analyze_files(self, paths: list[str]) -> list[FileAnalysis]:
        """Analyze multiple files.

        Args:
            paths: List of file paths.

        Returns:
            List of FileAnalysis results.
        """
        return [self.analyze_file(p) for p in paths]

    def _analyze_with_tree_sitter(
        self, content: str, language: str, path: str
    ) -> list[CodeChunk]:
        """Analyze using tree-sitter (when available)."""
        try:
            import tree_sitter  # type: ignore[import-untyped]

            # Get or create parser
            if language not in self._parsers:
                if language == "python":
                    import tree_sitter_python as ts_python  # type: ignore[import-untyped]
                    lang = tree_sitter.Language(ts_python.language())
                elif language in ("javascript", "typescript"):
                    import tree_sitter_javascript as ts_js  # type: ignore[import-untyped]
                    lang = tree_sitter.Language(ts_js.language())
                else:
                    return self._analyze_with_regex(content, language, path)

                parser = tree_sitter.Parser(lang)
                self._parsers[language] = parser

            parser = self._parsers[language]
            tree = parser.parse(bytes(content, "utf-8"))

            chunks: list[CodeChunk] = []
            self._walk_tree_sitter_node(tree.root_node, content, language, path, chunks)
            return chunks

        except Exception:
            # Fall back to regex on any tree-sitter error
            return self._analyze_with_regex(content, language, path)

    def _walk_tree_sitter_node(
        self,
        node: Any,
        content: str,
        language: str,
        path: str,
        chunks: list[CodeChunk],
        parent_name: str = "",
    ) -> None:
        """Walk tree-sitter AST and extract chunks."""
        lines = content.splitlines()

        for child in node.children:
            kind = ""
            name = ""

            if language == "python":
                if child.type == "function_definition":
                    kind = "method" if parent_name else "function"
                    name_node = child.child_by_field_name("name")
                    name = name_node.text.decode() if name_node else ""
                elif child.type == "class_definition":
                    kind = "class"
                    name_node = child.child_by_field_name("name")
                    name = name_node.text.decode() if name_node else ""
            elif language in ("javascript", "typescript"):
                if child.type in ("function_declaration", "arrow_function"):
                    kind = "function"
                    name_node = child.child_by_field_name("name")
                    name = name_node.text.decode() if name_node else ""
                elif child.type == "class_declaration":
                    kind = "class"
                    name_node = child.child_by_field_name("name")
                    name = name_node.text.decode() if name_node else ""

            if kind and name:
                start_line = child.start_point[0] + 1
                end_line = child.end_point[0] + 1
                chunk_content = "\n".join(lines[start_line - 1:end_line])

                # Extract signature (first line)
                signature = lines[start_line - 1].strip() if start_line <= len(lines) else ""

                # Extract docstring
                docstring = _extract_docstring(chunk_content, language)

                chunks.append(CodeChunk(
                    name=name,
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                    file_path=path,
                    language=language,
                    signature=signature,
                    parent=parent_name,
                    docstring=docstring,
                ))

                # Recurse into class bodies
                if kind == "class":
                    self._walk_tree_sitter_node(
                        child, content, language, path, chunks, parent_name=name
                    )
            else:
                # Recurse into other nodes
                self._walk_tree_sitter_node(
                    child, content, language, path, chunks, parent_name=parent_name
                )

    def _analyze_with_regex(
        self, content: str, language: str, path: str
    ) -> list[CodeChunk]:
        """Fallback regex-based code analysis."""
        if language == "python":
            return _regex_analyze_python(content, path)
        elif language in ("javascript", "typescript"):
            return _regex_analyze_js_ts(content, path, language)
        elif language in ("rust", "go", "java"):
            return _regex_analyze_generic(content, path, language)
        return []


def _regex_analyze_python(content: str, path: str) -> list[CodeChunk]:
    """Extract Python chunks using regex."""
    chunks: list[CodeChunk] = []
    lines = content.splitlines()

    # Match function and class definitions
    patterns = [
        (r"^(class)\s+(\w+)", "class"),
        (r"^(def)\s+(\w+)", "function"),
        (r"^(\s+def)\s+(\w+)", "method"),
    ]

    i = 0
    while i < len(lines):
        line = lines[i]
        for pattern, kind in patterns:
            match = re.match(pattern, line)
            if match:
                name = match.group(2)
                start_line = i + 1

                # Find end of block (next line with same or less indentation)
                indent = len(line) - len(line.lstrip())
                end_line = start_line
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].strip()
                    if not stripped:
                        continue
                    line_indent = len(lines[j]) - len(lines[j].lstrip())
                    if line_indent <= indent and stripped:
                        end_line = j
                        break
                else:
                    end_line = len(lines)

                chunk_content = "\n".join(lines[i:end_line])
                signature = line.strip()
                docstring = _extract_docstring(chunk_content, "python")

                # Determine parent
                parent = ""
                if kind == "method" and indent > 0:
                    # Look backwards for class definition
                    for k in range(i - 1, -1, -1):
                        cls_match = re.match(r"^class\s+(\w+)", lines[k])
                        if cls_match:
                            parent = cls_match.group(1)
                            break

                chunks.append(CodeChunk(
                    name=name,
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                    file_path=path,
                    language="python",
                    signature=signature,
                    parent=parent,
                    docstring=docstring,
                ))
                break
        i += 1

    return chunks


def _regex_analyze_js_ts(content: str, path: str, language: str) -> list[CodeChunk]:
    """Extract JS/TS chunks using regex."""
    chunks: list[CodeChunk] = []
    lines = content.splitlines()

    patterns = [
        (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"(?:export\s+)?class\s+(\w+)", "class"),
        (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", "function"),
    ]

    for i, line in enumerate(lines):
        for pattern, kind in patterns:
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                start_line = i + 1
                # Simple heuristic: find matching brace
                brace_count = line.count("{") - line.count("}")
                end_line = start_line
                for j in range(i + 1, min(i + 500, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    if brace_count <= 0:
                        end_line = j + 1
                        break
                else:
                    end_line = min(i + 50, len(lines))

                chunk_content = "\n".join(lines[i:end_line])
                chunks.append(CodeChunk(
                    name=name,
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                    file_path=path,
                    language=language,
                    signature=line.strip(),
                ))
                break

    return chunks


def _regex_analyze_generic(content: str, path: str, language: str) -> list[CodeChunk]:
    """Basic chunk extraction for other languages."""
    chunks: list[CodeChunk] = []
    lines = content.splitlines()

    # Generic function pattern
    func_pattern = re.compile(r"(?:pub\s+)?(?:fn|func|function|def)\s+(\w+)")

    for i, line in enumerate(lines):
        match = func_pattern.search(line)
        if match:
            name = match.group(1)
            start_line = i + 1
            brace_count = line.count("{") - line.count("}")
            end_line = start_line
            for j in range(i + 1, min(i + 500, len(lines))):
                brace_count += lines[j].count("{") - lines[j].count("}")
                if brace_count <= 0:
                    end_line = j + 1
                    break
            else:
                end_line = min(i + 50, len(lines))

            chunks.append(CodeChunk(
                name=name,
                kind="function",
                start_line=start_line,
                end_line=end_line,
                content="\n".join(lines[i:end_line]),
                file_path=path,
                language=language,
                signature=line.strip(),
            ))

    return chunks


def _detect_language(ext: str) -> str:
    """Detect language from file extension."""
    mapping = {
        ".py": "python", ".pyi": "python",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".rs": "rust", ".go": "go",
        ".java": "java", ".kt": "kotlin",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp",
        ".rb": "ruby", ".php": "php",
    }
    return mapping.get(ext, "")


def _extract_imports(content: str, language: str) -> list[str]:
    """Extract import statements from source code."""
    imports: list[str] = []
    if language == "python":
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
    elif language in ("javascript", "typescript"):
        import_re = re.compile(r"^import\s+.+", re.MULTILINE)
        imports = import_re.findall(content)
    return imports[:50]  # Limit


def _extract_docstring(content: str, language: str) -> str:
    """Extract docstring from a code chunk."""
    if language == "python":
        match = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if match:
            return match.group(1).strip()[:200]
        match = re.search(r"'''(.*?)'''", content, re.DOTALL)
        if match:
            return match.group(1).strip()[:200]
    elif language in ("javascript", "typescript"):
        match = re.search(r"/\*\*(.*?)\*/", content, re.DOTALL)
        if match:
            return match.group(1).strip()[:200]
    return ""


def _has_main_guard(content: str, language: str) -> bool:
    """Check if file has a main guard."""
    if language == "python":
        return 'if __name__' in content
    return False
