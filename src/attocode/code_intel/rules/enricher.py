"""Finding enricher — adds surrounding context for agent reasoning."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from attocode.code_intel.rules.model import EnrichedFinding

logger = logging.getLogger(__name__)

_CONTEXT_LINES = 10

# mtime-aware file cache: path -> (mtime, lines)
_file_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_file_cache_lock = threading.Lock()
_CACHE_MAX = 256


def _read_file_lines(file_path: str) -> tuple[str, ...]:
    """Read file lines with mtime-aware caching (invalidates on change)."""
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        return ()
    with _file_cache_lock:
        cached = _file_cache.get(file_path)
        if cached and cached[0] == mtime:
            return cached[1]
    # I/O outside lock
    try:
        lines = tuple(Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()
    with _file_cache_lock:
        _file_cache[file_path] = (mtime, lines)
        if len(_file_cache) > _CACHE_MAX:
            oldest = next(iter(_file_cache))
            del _file_cache[oldest]
    return lines


# Function-def patterns for enclosing function detection
_FUNC_PATTERNS: dict[str, re.Pattern[str]] = {
    "python": re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("),
    "javascript": re.compile(
        r"(?:(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\()"
    ),
    "typescript": re.compile(
        r"(?:(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\()"
    ),
    "go": re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\("),
    "rust": re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
    "java": re.compile(r"^\s*(?:public|private|protected|static|\s)*\s+\w+\s+(\w+)\s*\("),
    "kotlin": re.compile(r"^\s*(?:fun|suspend\s+fun)\s+(\w+)"),
    "ruby": re.compile(r"^\s*def\s+(\w+)"),
    "csharp": re.compile(r"^\s*(?:public|private|protected|static|\s)*\s+\w+\s+(\w+)\s*\("),
    "cpp": re.compile(r"^\s*(?:\w+\s+)*\w+\s+(\w+)\s*\("),
    "c": re.compile(r"^\s*(?:\w+\s+)*\w+\s+(\w+)\s*\("),
}

_EXT_LANG: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".kt": "kotlin", ".rb": "ruby", ".cs": "csharp",
    ".cpp": "cpp", ".hpp": "cpp", ".c": "c", ".h": "c",
}


def _detect_language(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return _EXT_LANG.get(ext, "")


def _find_enclosing_function(lines: tuple[str, ...], target_line: int, language: str) -> str:
    """Find the function name enclosing target_line (1-indexed)."""
    pat = _FUNC_PATTERNS.get(language)
    if pat is None:
        return ""
    for i in range(min(target_line - 1, len(lines) - 1), -1, -1):
        m = pat.search(lines[i])
        if m:
            for g in m.groups():
                if g:
                    return g
    return ""


def enrich_findings(
    findings: list[EnrichedFinding],
    *,
    project_dir: str = "",
    context_lines: int = _CONTEXT_LINES,
) -> list[EnrichedFinding]:
    """Enrich findings with surrounding context and enclosing function.

    Mutates findings in-place and returns them for chaining.
    """
    for finding in findings:
        if project_dir and not os.path.isabs(finding.file):
            abs_path = os.path.join(project_dir, finding.file)
        else:
            abs_path = finding.file

        lines = _read_file_lines(abs_path)
        if not lines:
            continue

        idx = finding.line - 1  # 0-indexed

        # Surrounding context
        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        finding.context_before = list(lines[start:idx])
        finding.context_after = list(lines[idx + 1:end])

        # Enclosing function
        lang = _detect_language(abs_path)
        if lang and not finding.function_name:
            finding.function_name = _find_enclosing_function(lines, finding.line, lang)

    return findings
