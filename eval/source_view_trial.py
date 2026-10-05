"""Path-only source-view trial; not connected to production search."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult


_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".sh",
})
_NON_IMPLEMENTATION_DIRS = frozenset({
    "test", "tests", "doc", "docs", "docs_src", "examples", "legacy",
    "lessons", "eval", "asv_bench", "benchmark", "benchmarks", "deps",
    "vendor", "node_modules", "fixtures", "samples",
})


def is_implementation_source(path: str) -> bool:
    """Use path/type only; never infer relevance from source-body coincidences."""
    parsed = PurePosixPath(path.replace("\\", "/").lower())
    if parsed.suffix not in _SOURCE_EXTENSIONS:
        return False
    if any(part in _NON_IMPLEMENTATION_DIRS for part in parsed.parts[:-1]):
        return False
    name = parsed.stem
    return not (name.startswith("test_") or name.endswith(("_test", ".test", ".spec")))


def source_view_candidates(
    query: str, candidates: list[SemanticSearchResult], top_k: int,
    file_filter: str = "",
) -> list[SemanticSearchResult]:
    """Preserve original rank among distinct implementation-source files."""
    if top_k <= 0:
        return []
    if file_filter or re.search(r"\b(tests?|docs?|documentation|examples?)\b", query, re.I):
        return candidates[:top_k]
    selected: list[SemanticSearchResult] = []
    seen: set[str] = set()
    for row in candidates:
        if row.file_path in seen or not is_implementation_source(row.file_path):
            continue
        selected.append(row)
        seen.add(row.file_path)
        if len(selected) >= top_k:
            break
    return selected
