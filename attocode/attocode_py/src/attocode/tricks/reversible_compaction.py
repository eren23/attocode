"""Reversible compaction with reference preservation (Trick R).

Compresses conversation history while preserving references to
files, URLs, functions, errors, and commands for later retrieval.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from attocode.integrations.utilities.token_estimate import estimate_tokens


class ReferenceType:
    """Types of extractable references."""

    FILE = "file"
    URL = "url"
    FUNCTION = "function"
    CLASS = "class"
    ERROR = "error"
    COMMAND = "command"
    SNIPPET = "snippet"
    DECISION = "decision"
    CUSTOM = "custom"


@dataclass
class Reference:
    """A preserved reference from compacted content."""

    id: str
    type: str
    value: str
    context: str | None = None
    timestamp: float = field(default_factory=time.time)
    source_index: int | None = None
    relevance: float = 0.5


@dataclass
class CompactionStats:
    """Statistics about a compaction operation."""

    original_messages: int = 0
    original_tokens: int = 0
    compacted_tokens: int = 0
    references_extracted: int = 0
    references_preserved: int = 0
    compression_ratio: float = 0.0


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    summary: str
    references: list[Reference]
    stats: CompactionStats


@dataclass
class ReversibleCompactionConfig:
    """Configuration for reversible compaction."""

    preserve_types: list[str] = field(
        default_factory=lambda: ["file", "url", "function", "error"]
    )
    max_references: int = 100
    deduplicate: bool = True
    min_relevance: float = 0.0


ReferenceExtractor = Callable[[str, int], list[Reference]]
CompactionEventListener = Callable[[str, dict[str, Any]], None]


class ReversibleCompactor:
    """Compacts conversation while preserving key references.

    Extracts file paths, URLs, function names, errors, and commands
    from messages before summarization. References can be retrieved
    later for context reconstruction.
    """

    def __init__(self, config: ReversibleCompactionConfig | None = None) -> None:
        self._config = config or ReversibleCompactionConfig()
        self._references: list[Reference] = []
        self._listeners: list[CompactionEventListener] = []
        self._custom_extractors: dict[str, ReferenceExtractor] = {}

    async def compact(
        self,
        messages: list[dict[str, Any]],
        summarize: Callable[[list[dict[str, Any]]], Any],
        additional_context: str | None = None,
    ) -> CompactionResult:
        """Compact messages with reference preservation.

        Args:
            messages: Messages to compact.
            summarize: Async function that summarizes messages into a string.
            additional_context: Extra context for the summary.
        """
        # Extract references from all messages
        all_refs: list[Reference] = []
        original_tokens = 0

        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            if isinstance(content, str):
                original_tokens += estimate_tokens(content)
                refs = extract_references(
                    content, self._config.preserve_types, i, self._custom_extractors
                )
                all_refs.extend(refs)

        # Deduplicate
        if self._config.deduplicate:
            seen: set[str] = set()
            deduped: list[Reference] = []
            for ref in all_refs:
                key = f"{ref.type}:{ref.value}"
                if key not in seen:
                    seen.add(key)
                    deduped.append(ref)
            all_refs = deduped

        # Filter by relevance
        if self._config.min_relevance > 0:
            all_refs = [r for r in all_refs if r.relevance >= self._config.min_relevance]

        # Enforce max references (keep highest relevance)
        if len(all_refs) > self._config.max_references:
            all_refs.sort(key=lambda r: r.relevance, reverse=True)
            all_refs = all_refs[: self._config.max_references]

        # Store references
        self._references.extend(all_refs)

        # Get summary
        result = summarize(messages)
        if hasattr(result, "__await__"):
            summary = await result
        else:
            summary = result

        compacted_tokens = estimate_tokens(str(summary))

        stats = CompactionStats(
            original_messages=len(messages),
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            references_extracted=len(all_refs),
            references_preserved=len(all_refs),
            compression_ratio=compacted_tokens / max(1, original_tokens),
        )

        self._emit("compaction.completed", {"stats": stats})

        return CompactionResult(
            summary=str(summary),
            references=all_refs,
            stats=stats,
        )

    def format_references_block(self, references: list[Reference] | None = None) -> str:
        """Format references as a text block for context injection."""
        refs = references or self._references
        if not refs:
            return ""

        grouped: dict[str, list[str]] = {}
        for ref in refs:
            label = ref.type.upper() + "S"
            if label not in grouped:
                grouped[label] = []
            grouped[label].append(f"  - {ref.value}")

        lines = ["[Preserved References]"]
        for label, items in grouped.items():
            lines.append(f"{label}:")
            lines.extend(items)
        return "\n".join(lines)

    def get_reference(self, ref_id: str) -> Reference | None:
        """Get a reference by ID."""
        for ref in self._references:
            if ref.id == ref_id:
                return ref
        return None

    def get_references_by_type(self, ref_type: str) -> list[Reference]:
        """Get all references of a given type."""
        return [r for r in self._references if r.type == ref_type]

    def search_references(self, query: str) -> list[Reference]:
        """Search references by value."""
        query_lower = query.lower()
        return [r for r in self._references if query_lower in r.value.lower()]

    def get_preserved_references(self) -> list[Reference]:
        """Get all preserved references."""
        return list(self._references)

    def clear(self) -> None:
        """Clear all stored references."""
        self._references.clear()

    def on(self, listener: CompactionEventListener) -> Callable[[], None]:
        """Subscribe to compaction events."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


# --- Reference extractors ---

def extract_file_references(content: str, source_index: int = 0) -> list[Reference]:
    """Extract file path references."""
    refs: list[Reference] = []
    # Unix/Mac paths with extensions
    for m in re.finditer(r"(?:^|\s|['\"`(])(/[\w./-]+\.\w{1,6})\b", content):
        refs.append(_make_ref(ReferenceType.FILE, m.group(1).strip(), source_index))
    # Relative paths with extensions
    for m in re.finditer(r"(?:^|\s|['\"`(])(\.{0,2}/[\w./-]+\.\w{1,6})\b", content):
        val = m.group(1).strip()
        if not any(r.value == val for r in refs):
            refs.append(_make_ref(ReferenceType.FILE, val, source_index))
    return refs


def extract_url_references(content: str, source_index: int = 0) -> list[Reference]:
    """Extract URL references."""
    refs: list[Reference] = []
    for m in re.finditer(r"https?://[^\s<>\")]+", content):
        url = m.group(0).rstrip(".,;:")
        refs.append(_make_ref(ReferenceType.URL, url, source_index))
    return refs


def extract_function_references(content: str, source_index: int = 0) -> list[Reference]:
    """Extract function/method references."""
    refs: list[Reference] = []
    # Function definitions
    for m in re.finditer(r"(?:def|function|async\s+def)\s+(\w+)", content):
        refs.append(_make_ref(ReferenceType.FUNCTION, m.group(1), source_index))
    # camelCase method calls
    for m in re.finditer(r"\b([a-z][a-zA-Z]{2,})\s*\(", content):
        name = m.group(1)
        if len(name) > 2 and not any(r.value == name for r in refs):
            refs.append(_make_ref(ReferenceType.FUNCTION, name, source_index))
    return refs


def extract_error_references(content: str, source_index: int = 0) -> list[Reference]:
    """Extract error references."""
    refs: list[Reference] = []
    # Error class names
    for m in re.finditer(r"\b(\w+Error|\w+Exception)\b", content):
        if len(refs) < 3:
            refs.append(_make_ref(ReferenceType.ERROR, m.group(1), source_index))
    # Error messages
    for m in re.finditer(r"Error:\s*(.{10,80})", content):
        if len(refs) < 3:
            refs.append(_make_ref(ReferenceType.ERROR, m.group(0).strip(), source_index))
    return refs


def extract_command_references(content: str, source_index: int = 0) -> list[Reference]:
    """Extract command references."""
    refs: list[Reference] = []
    # $ prefix commands
    for m in re.finditer(r"^\$\s+(.+)$", content, re.MULTILINE):
        refs.append(_make_ref(ReferenceType.COMMAND, m.group(1).strip(), source_index))
    # Code block commands
    for m in re.finditer(r"```(?:bash|sh|shell)?\n(.+?)```", content, re.DOTALL):
        lines = m.group(1).strip().split("\n")
        for line in lines[:3]:
            line = line.strip()
            if line and not line.startswith("#"):
                refs.append(_make_ref(ReferenceType.COMMAND, line, source_index))
    # Common CLI patterns
    for m in re.finditer(r"\b((?:npm|git|docker|pip|python|node)\s+\S+(?:\s+\S+){0,3})", content):
        cmd = m.group(1).strip()
        if not any(r.value == cmd for r in refs):
            refs.append(_make_ref(ReferenceType.COMMAND, cmd, source_index))
    return refs


def extract_references(
    content: str,
    types: list[str],
    source_index: int = 0,
    custom_extractors: dict[str, ReferenceExtractor] | None = None,
) -> list[Reference]:
    """Extract all references of specified types from content."""
    _extractors: dict[str, Callable[[str, int], list[Reference]]] = {
        ReferenceType.FILE: extract_file_references,
        ReferenceType.URL: extract_url_references,
        ReferenceType.FUNCTION: extract_function_references,
        ReferenceType.ERROR: extract_error_references,
        ReferenceType.COMMAND: extract_command_references,
    }

    all_refs: list[Reference] = []
    for ref_type in types:
        extractor = (custom_extractors or {}).get(ref_type) or _extractors.get(ref_type)
        if extractor:
            all_refs.extend(extractor(content, source_index))
    return all_refs


def quick_extract(content: str, types: list[str] | None = None) -> list[Reference]:
    """Quick extraction with default types."""
    types = types or ["file", "url", "function", "error"]
    return extract_references(content, types)


def calculate_relevance(
    reference: Reference,
    goal: str | None = None,
    recent_topics: list[str] | None = None,
) -> float:
    """Calculate relevance score for a reference."""
    score = 0.5

    if goal:
        goal_words = {w.lower() for w in goal.split() if len(w) > 3}
        ref_words = {w.lower() for w in reference.value.split("/") + reference.value.split(".")}
        overlap = goal_words & ref_words
        score += len(overlap) * 0.1

    if recent_topics:
        for topic in recent_topics:
            if reference.value.lower() in topic.lower() or topic.lower() in reference.value.lower():
                score += 0.15

    if reference.type == ReferenceType.ERROR:
        score += 0.1
    elif reference.type == ReferenceType.FILE:
        score += 0.05

    return min(1.0, score)


def _make_ref(ref_type: str, value: str, source_index: int) -> Reference:
    """Create a reference with a unique ID."""
    return Reference(
        id=f"ref-{uuid.uuid4().hex[:8]}",
        type=ref_type,
        value=value,
        source_index=source_index,
    )
