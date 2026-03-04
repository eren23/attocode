"""AST-aware code chunking for semantic search.

Produces structural chunks at function/method/class boundaries that include
actual source code, not just metadata summaries. This significantly improves
search recall for code-understanding queries (cAST paper: +4.3pts Recall@5).

Used by ``SemanticSearchManager`` in two-stage retrieval mode.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CodeChunk:
    """A structural code chunk extracted from AST boundaries."""

    id: str  # unique chunk ID (e.g. "func:path:name")
    file_path: str  # relative path
    chunk_type: str  # "file", "function", "class", "method"
    name: str  # symbol name
    text: str  # actual code content (for embedding)
    start_line: int
    end_line: int
    metadata: str  # additional context (imports, params, bases)


def chunk_file(
    file_path: str,
    relative_path: str,
    content: str | None = None,
    max_chunk_lines: int = 80,
) -> list[CodeChunk]:
    """Extract structural code chunks from a file using AST boundaries.

    Chunks at function, method, and class boundaries. Each chunk includes
    the actual source code (truncated to ``max_chunk_lines``) plus metadata
    (imports, parameters, return types, base classes).

    Args:
        file_path: Absolute path to the source file.
        relative_path: Relative path for chunk IDs.
        content: Optional file content (read from disk if not provided).
        max_chunk_lines: Maximum lines of code to include per chunk.

    Returns:
        List of CodeChunk objects.
    """
    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

    from attocode.integrations.context.codebase_ast import parse_file

    try:
        ast = parse_file(file_path, content=content)
    except Exception:
        return []

    lines = content.splitlines()
    chunks: list[CodeChunk] = []

    # File-level chunk: imports + top-level summary
    imports = [imp.module for imp in ast.imports[:15]]
    symbols = ast.get_symbols()[:15]
    file_meta_parts = []
    if imports:
        file_meta_parts.append(f"imports: {', '.join(imports)}")
    if symbols:
        file_meta_parts.append(f"defines: {', '.join(symbols)}")

    # Take first N lines as file overview (docstring + imports area)
    file_preview_end = min(40, len(lines))
    file_text = "\n".join(lines[:file_preview_end])
    if len(lines) > file_preview_end:
        file_text += f"\n... ({len(lines) - file_preview_end} more lines)"

    chunks.append(CodeChunk(
        id=f"file:{relative_path}",
        file_path=relative_path,
        chunk_type="file",
        name=os.path.basename(relative_path),
        text=file_text,
        start_line=1,
        end_line=len(lines),
        metadata=" | ".join(file_meta_parts),
    ))

    # Function-level chunks
    for func in ast.functions:
        start = max(0, func.start_line - 1)
        end = min(len(lines), func.end_line)
        code_lines = lines[start:end]
        if len(code_lines) > max_chunk_lines:
            code_lines = code_lines[:max_chunk_lines]
            code_lines.append(f"    # ... ({func.end_line - func.start_line - max_chunk_lines} more lines)")

        params = ", ".join(p.name for p in func.parameters[:8])
        meta_parts = [f"function {func.name}({params})"]
        if func.return_type:
            meta_parts.append(f"-> {func.return_type}")
        if func.decorators:
            meta_parts.append(f"decorators: {', '.join(func.decorators[:3])}")

        chunks.append(CodeChunk(
            id=f"func:{relative_path}:{func.name}",
            file_path=relative_path,
            chunk_type="function",
            name=func.name,
            text="\n".join(code_lines),
            start_line=func.start_line,
            end_line=func.end_line,
            metadata=" | ".join(meta_parts),
        ))

    # Class-level chunks
    for cls in ast.classes:
        start = max(0, cls.start_line - 1)
        end = min(len(lines), cls.end_line)
        code_lines = lines[start:end]
        if len(code_lines) > max_chunk_lines:
            code_lines = code_lines[:max_chunk_lines]
            code_lines.append(f"    # ... ({cls.end_line - cls.start_line - max_chunk_lines} more lines)")

        meta_parts = [f"class {cls.name}"]
        if cls.bases:
            meta_parts.append(f"extends: {', '.join(cls.bases[:5])}")
        methods = [m.name for m in cls.methods[:10]]
        if methods:
            meta_parts.append(f"methods: {', '.join(methods)}")

        chunks.append(CodeChunk(
            id=f"cls:{relative_path}:{cls.name}",
            file_path=relative_path,
            chunk_type="class",
            name=cls.name,
            text="\n".join(code_lines),
            start_line=cls.start_line,
            end_line=cls.end_line,
            metadata=" | ".join(meta_parts),
        ))

        # Method-level chunks for large classes
        for method in cls.methods:
            m_start = max(0, method.start_line - 1)
            m_end = min(len(lines), method.end_line)
            m_lines = lines[m_start:m_end]
            if len(m_lines) > max_chunk_lines:
                m_lines = m_lines[:max_chunk_lines]
                m_lines.append(f"        # ... ({method.end_line - method.start_line - max_chunk_lines} more lines)")

            m_params = ", ".join(p.name for p in method.parameters[:8])
            m_meta_parts = [f"method {cls.name}.{method.name}({m_params})"]
            if method.return_type:
                m_meta_parts.append(f"-> {method.return_type}")

            chunks.append(CodeChunk(
                id=f"method:{relative_path}:{cls.name}.{method.name}",
                file_path=relative_path,
                chunk_type="method",
                name=f"{cls.name}.{method.name}",
                text="\n".join(m_lines),
                start_line=method.start_line,
                end_line=method.end_line,
                metadata=" | ".join(m_meta_parts),
            ))

    return chunks


def reciprocal_rank_fusion(
    *result_lists: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Each input is a list of (id, score) tuples sorted by score descending.
    Returns a merged list sorted by fused score descending.

    Args:
        *result_lists: Variable number of ranked result lists.
        k: RRF constant (default 60, standard from literature).

    Returns:
        Merged list of (id, fused_score) sorted by score descending.
    """
    fused: dict[str, float] = {}

    for results in result_lists:
        for rank, (item_id, _score) in enumerate(results):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank + 1)

    sorted_results = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return sorted_results
