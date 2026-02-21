"""Recursive context retrieval technique.

Implements a strategy where the agent progressively deepens context
by following references found in initial results. Useful for understanding
complex code flows that span multiple files.

Strategy:
1. Start with a seed query (file path, symbol, etc.)
2. Retrieve initial context
3. Extract references/imports from the context
4. Recursively retrieve context for those references
5. Stop at a depth/token budget limit
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


class ContentProvider(Protocol):
    """Protocol for retrieving file content."""

    def get_content(self, file_path: str) -> str | None: ...


@dataclass(slots=True)
class ContextNode:
    """A node in the recursive context tree."""

    file_path: str
    content: str
    depth: int
    references: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    is_truncated: bool = False

    def __post_init__(self) -> None:
        if self.estimated_tokens == 0 and self.content:
            self.estimated_tokens = len(self.content) // 4


@dataclass(slots=True)
class RecursiveContextResult:
    """Result of recursive context retrieval."""

    nodes: list[ContextNode]
    total_tokens: int
    max_depth_reached: int
    files_visited: int
    budget_exhausted: bool = False

    @property
    def content(self) -> str:
        """Combined content from all nodes."""
        parts: list[str] = []
        for node in self.nodes:
            header = f"--- {node.file_path} (depth {node.depth}) ---"
            parts.append(f"{header}\n{node.content}")
        return "\n\n".join(parts)


def extract_python_references(content: str, current_file: str = "") -> list[str]:
    """Extract file references from Python import statements.

    Returns a list of potential file paths derived from imports.
    """
    references: list[str] = []

    # from X import Y
    for match in re.finditer(r"from\s+([\w.]+)\s+import", content):
        module = match.group(1)
        # Convert module path to file path
        path = module.replace(".", "/") + ".py"
        references.append(path)

    # import X
    for match in re.finditer(r"^import\s+([\w.]+)", content, re.MULTILINE):
        module = match.group(1)
        path = module.replace(".", "/") + ".py"
        references.append(path)

    return references


def extract_js_references(content: str, current_file: str = "") -> list[str]:
    """Extract file references from JS/TS import statements.

    Returns a list of potential file paths.
    """
    references: list[str] = []

    # import ... from 'path'
    for match in re.finditer(r"""from\s+['"]([^'"]+)['"]""", content):
        ref = match.group(1)
        if ref.startswith("."):
            # Relative import
            if not ref.endswith((".js", ".ts", ".tsx", ".jsx")):
                references.append(ref + ".ts")
                references.append(ref + ".js")
            else:
                references.append(ref)

    # require('path')
    for match in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", content):
        ref = match.group(1)
        if ref.startswith("."):
            references.append(ref + ".js")

    return references


def extract_references(content: str, file_path: str) -> list[str]:
    """Extract file references based on file type."""
    if file_path.endswith(".py"):
        return extract_python_references(content, file_path)
    elif file_path.endswith((".js", ".ts", ".tsx", ".jsx")):
        return extract_js_references(content, file_path)
    return []


class RecursiveContextRetriever:
    """Retrieves context by recursively following references.

    Starting from a seed file, follows imports and references
    up to a configurable depth and token budget.

    Args:
        provider: Content provider for reading files.
        max_depth: Maximum recursion depth (default 3).
        token_budget: Maximum total tokens across all files.
        max_files: Maximum number of files to visit.
    """

    def __init__(
        self,
        provider: ContentProvider,
        *,
        max_depth: int = 3,
        token_budget: int = 50_000,
        max_files: int = 20,
    ) -> None:
        self._provider = provider
        self._max_depth = max_depth
        self._token_budget = token_budget
        self._max_files = max_files

    def retrieve(
        self,
        seed_files: list[str],
        *,
        max_content_per_file: int = 10_000,
    ) -> RecursiveContextResult:
        """Recursively retrieve context starting from seed files.

        Args:
            seed_files: Initial files to start from.
            max_content_per_file: Maximum characters per file content.

        Returns:
            A :class:`RecursiveContextResult` with all gathered context.
        """
        visited: set[str] = set()
        nodes: list[ContextNode] = []
        total_tokens = 0
        max_depth_reached = 0

        # BFS queue: (file_path, depth)
        queue: list[tuple[str, int]] = [(f, 0) for f in seed_files]

        while queue:
            file_path, depth = queue.pop(0)

            # Skip if already visited
            if file_path in visited:
                continue

            # Check limits
            if depth > self._max_depth:
                continue
            if len(visited) >= self._max_files:
                break
            if total_tokens >= self._token_budget:
                break

            visited.add(file_path)

            # Get content
            content = self._provider.get_content(file_path)
            if content is None:
                continue

            # Truncate if needed
            is_truncated = False
            if len(content) > max_content_per_file:
                content = content[:max_content_per_file]
                is_truncated = True

            # Check if adding this would exceed budget
            est_tokens = len(content) // 4
            if total_tokens + est_tokens > self._token_budget:
                # Try to fit with truncation
                remaining = self._token_budget - total_tokens
                chars = remaining * 4
                if chars < 200:
                    break
                content = content[:chars]
                is_truncated = True
                est_tokens = remaining

            # Extract references for next depth
            references = extract_references(content, file_path)

            node = ContextNode(
                file_path=file_path,
                content=content,
                depth=depth,
                references=references,
                estimated_tokens=est_tokens,
                is_truncated=is_truncated,
            )
            nodes.append(node)
            total_tokens += est_tokens
            max_depth_reached = max(max_depth_reached, depth)

            # Enqueue references for next depth
            for ref in references:
                if ref not in visited:
                    queue.append((ref, depth + 1))

        return RecursiveContextResult(
            nodes=nodes,
            total_tokens=total_tokens,
            max_depth_reached=max_depth_reached,
            files_visited=len(visited),
            budget_exhausted=total_tokens >= self._token_budget,
        )

    def retrieve_with_priority(
        self,
        seed_files: list[str],
        priority_files: list[str] | None = None,
        *,
        max_content_per_file: int = 10_000,
    ) -> RecursiveContextResult:
        """Retrieve with priority files getting budget preference.

        Priority files are loaded first and given more token budget.
        Remaining budget is used for recursive exploration.
        """
        priority = set(priority_files or [])
        visited: set[str] = set()
        nodes: list[ContextNode] = []
        total_tokens = 0
        max_depth_reached = 0

        # Phase 1: Load priority files first (use 50% of budget)
        priority_budget = self._token_budget // 2
        for file_path in (priority_files or []):
            if file_path in visited:
                continue
            content = self._provider.get_content(file_path)
            if content is None:
                continue
            visited.add(file_path)
            is_truncated = False
            if len(content) > max_content_per_file:
                content = content[:max_content_per_file]
                is_truncated = True
            est_tokens = len(content) // 4
            if total_tokens + est_tokens > priority_budget:
                remaining = priority_budget - total_tokens
                chars = remaining * 4
                if chars < 200:
                    break
                content = content[:chars]
                is_truncated = True
                est_tokens = remaining
            references = extract_references(content, file_path)
            nodes.append(ContextNode(
                file_path=file_path,
                content=content,
                depth=0,
                references=references,
                estimated_tokens=est_tokens,
                is_truncated=is_truncated,
            ))
            total_tokens += est_tokens

        # Phase 2: BFS from seeds with remaining budget
        queue: list[tuple[str, int]] = [(f, 0) for f in seed_files if f not in visited]
        # Also enqueue references from priority files
        for node in nodes:
            for ref in node.references:
                if ref not in visited:
                    queue.append((ref, 1))

        while queue and total_tokens < self._token_budget and len(visited) < self._max_files:
            file_path, depth = queue.pop(0)
            if file_path in visited or depth > self._max_depth:
                continue
            visited.add(file_path)
            content = self._provider.get_content(file_path)
            if content is None:
                continue
            is_truncated = False
            if len(content) > max_content_per_file:
                content = content[:max_content_per_file]
                is_truncated = True
            est_tokens = len(content) // 4
            if total_tokens + est_tokens > self._token_budget:
                remaining = self._token_budget - total_tokens
                chars = remaining * 4
                if chars < 200:
                    break
                content = content[:chars]
                is_truncated = True
                est_tokens = remaining
            references = extract_references(content, file_path)
            nodes.append(ContextNode(
                file_path=file_path,
                content=content,
                depth=depth,
                references=references,
                estimated_tokens=est_tokens,
                is_truncated=is_truncated,
            ))
            total_tokens += est_tokens
            max_depth_reached = max(max_depth_reached, depth)
            for ref in references:
                if ref not in visited:
                    queue.append((ref, depth + 1))

        return RecursiveContextResult(
            nodes=nodes,
            total_tokens=total_tokens,
            max_depth_reached=max_depth_reached,
            files_visited=len(visited),
            budget_exhausted=total_tokens >= self._token_budget,
        )
