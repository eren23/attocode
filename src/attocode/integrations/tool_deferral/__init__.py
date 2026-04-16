"""Tool deferral system — reduce prompt schema by deferring expensive tools.

CC's insight: many tools (LSP, semantic search, etc.) are expensive and not needed
on every turn. By marking them as "deferred", the model's first response can be
a lightweight "ToolSearch" to discover which deferred tools are relevant before
actually calling them.

Benefits:
- Smaller tool schema in the system prompt (deferred tools not listed)
- Reduced per-turn token overhead for unused tools
- Better tool discovery: the model learns which tool matches a query

Deferral levels:
- IMMEDIATE: always available (bash, read_file, edit_file, etc.)
- DEFERRED: available via ToolSearch roundtrip
- DYNAMIC: loaded on-demand from MCP/lazy sources

Flow:
1. Agent responds to user
2. If it calls a DEFERRED tool, instead return a special "ToolSearch" roundtrip
3. The ToolSearch response tells the model which DEFERRED tool matches
4. The model calls the actual tool

This is transparent to the agent execution loop — it intercepts deferred
tool calls and converts them to search-then-execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.tools.registry import ToolRegistry


@dataclass
class DeferredTool:
    """A tool that's deferred via ToolSearch."""

    name: str
    # How this tool matches a user intent
    intent_keywords: list[str] = field(default_factory=list)
    # Human-readable hint shown in ToolSearch results
    search_hint: str = ""
    # File extensions this tool works on (for LSP)
    extensions: list[str] = field(default_factory=list)
    # Languages this tool applies to
    languages: list[str] = field(default_factory=list)
    # Whether this tool requires the file to exist
    requires_file: bool = True


# Default deferred tools (mirrors CC's approach for expensive tools)
DEFAULT_DEFERRED: list[DeferredTool] = [
    DeferredTool(
        name="lsp_definition",
        intent_keywords=["definition", "goto definition", "find definition",
                       "where is", "where's", "type definition", "source of"],
        search_hint="Jump to type-resolved symbol definition",
        languages=["typescript", "javascript", "python", "rust", "go", "java"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java"],
    ),
    DeferredTool(
        name="lsp_references",
        intent_keywords=["references", "find references", "all uses",
                        "who calls", "where used", "usages", "callers"],
        search_hint="Find all type-aware references to a symbol",
        languages=["typescript", "javascript", "python", "rust", "go", "java"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java"],
    ),
    DeferredTool(
        name="lsp_hover",
        intent_keywords=["hover", "type signature", "documentation",
                        "what is", "info about", "docs for", "signature of"],
        search_hint="Get type signature and inline docs for a symbol",
        languages=["typescript", "javascript", "python", "rust", "go", "java"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java"],
    ),
    DeferredTool(
        name="lsp_call_hierarchy",
        intent_keywords=["call hierarchy", "incoming calls", "outgoing calls",
                        "who calls this", "calls what", "call graph"],
        search_hint="Explore call hierarchy — who calls this and what it calls",
        languages=["typescript", "javascript", "python", "rust", "go", "java"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java"],
    ),
    DeferredTool(
        name="semantic_search",
        intent_keywords=["semantic search", "concept search", "search by meaning",
                        "find similar", "semantic", "embeddings", "find code like"],
        search_hint="Natural language semantic search across the codebase",
    ),
    DeferredTool(
        name="codebase_overview",
        intent_keywords=["overview", "architecture", "structure", "code map",
                        "project structure", "tree view", "file tree"],
        search_hint="Get a structured overview of the project architecture",
    ),
    DeferredTool(
        name="security_scan",
        intent_keywords=["security", "vulnerability", "audit", "scan for issues",
                        "security check", "vulnerable"],
        search_hint="Scan for security vulnerabilities and suspicious patterns",
    ),
]


# -----------------------------------------------------------------------------
# Tool Registry Adapter
# -----------------------------------------------------------------------------

@dataclass
class ToolSearchResult:
    """Result of a ToolSearch roundtrip."""

    tool_name: str
    match_reason: str
    confidence: float  # 0-1
    hint: str = ""


class ToolDeferralManager:
    """Manages deferred tool discovery via ToolSearch.

    Intercepts calls to deferred tools and either:
    a) Converts them to a ToolSearch roundtrip response
    b) Immediately executes if the tool is already registered

    The ToolSearch roundtrip is a lightweight model response that
    names the matching deferred tool, rather than a full tool call.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        deferred_tools: list[DeferredTool] | None = None,
    ) -> None:
        self._registry = registry
        self._deferred: dict[str, DeferredTool] = {}
        self._search_index: list[DeferredTool] = []

        for dt in (deferred_tools or DEFAULT_DEFERRED):
            self._deferred[dt.name] = dt
            self._search_index.append(dt)

    def mark_deferred(self, tool_name: str, **kwargs: Any) -> None:
        """Mark a tool as deferred with optional metadata."""
        self._deferred[tool_name] = DeferredTool(
            name=tool_name,
            intent_keywords=kwargs.get("intent_keywords", []),
            search_hint=kwargs.get("search_hint", ""),
            extensions=kwargs.get("extensions", []),
            languages=kwargs.get("languages", []),
            requires_file=kwargs.get("requires_file", True),
        )

    def mark_immediate(self, tool_name: str) -> None:
        """Move a tool back to immediate (always in schema)."""
        self._deferred.pop(tool_name, None)

    def is_deferred(self, tool_name: str) -> bool:
        """Return True if the tool is deferred."""
        return tool_name in self._deferred

    def get_deferred_names(self) -> list[str]:
        """List all deferred tool names."""
        return list(self._deferred.keys())

    def get_immediate_names(self) -> list[str] | None:
        """List all immediate (non-deferred) tool names from the registry."""
        if self._registry is None:
            return None
        all_names = self._registry.list_tools()
        return [n for n in all_names if n not in self._deferred]

    # -------------------------------------------------------------------------
    # ToolSearch — the actual search logic
    # -------------------------------------------------------------------------

    def search(self, query: str) -> list[ToolSearchResult]:
        """Search deferred tools matching a natural language query.

        Args:
            query: A query describing what the user/agent wants to do.

        Returns:
            List of matching DeferredTool entries, sorted by confidence.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        results: list[ToolSearchResult] = []

        for dt in self._search_index:
            confidence = 0.0
            reasons: list[str] = []

            # Keyword matching — exact word overlap
            for kw in dt.intent_keywords:
                kw_lower = kw.lower()
                # Exact keyword match
                if kw_lower in query_lower:
                    confidence = max(confidence, 0.9)
                    reasons.append(f"keyword '{kw}'")
                # Word-level overlap
                kw_words = set(kw_lower.split())
                overlap = query_words & kw_words
                if overlap:
                    overlap_score = len(overlap) / max(len(kw_words), 1)
                    confidence = max(confidence, 0.5 * overlap_score)
                    reasons.append(f"word overlap ({overlap})")

            # Language/extension match
            for lang in dt.languages:
                if lang.lower() in query_lower:
                    confidence = max(confidence, 0.7)
                    reasons.append(f"language '{lang}'")

            for ext in dt.extensions:
                if ext.lstrip(".").lower() in query_lower:
                    confidence = max(confidence, 0.6)
                    reasons.append(f"extension '{ext}'")

            # Name match (tool name in query)
            name_words = set(dt.name.lower().split("_"))
            if name_words & query_words:
                confidence = max(confidence, 0.8)
                reasons.append("name match")

            # Substring match
            if dt.name.lower() in query_lower:
                confidence = max(confidence, 0.85)
                reasons.append(f"'{dt.name}' substring")

            if confidence > 0.1:
                results.append(ToolSearchResult(
                    tool_name=dt.name,
                    match_reason=", ".join(reasons) if reasons else "partial match",
                    confidence=min(confidence, 0.99),
                    hint=dt.search_hint,
                ))

        # Sort by confidence descending
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results[:5]  # Top 5 matches

    def search_for_tool(self, tool_name: str, query: str) -> ToolSearchResult | None:
        """Search specifically for a named tool, returning a result if matched."""
        results = self.search(query)
        for r in results:
            if r.tool_name == tool_name:
                return r
        return None

    # -------------------------------------------------------------------------
    # Integration with the execution loop
    # -------------------------------------------------------------------------

    def should_defer(self, tool_name: str) -> bool:
        """Return True if a tool call should be deferred to a ToolSearch roundtrip."""
        # Deferred tools that ARE in the registry are still deferred
        # (they're available but must go through ToolSearch)
        return self.is_deferred(tool_name)

    def build_toolsearch_message(
        self,
        tool_name: str,
        query: str,
        reason: str = "ToolSearch roundtrip required for deferred tool",
    ) -> str:
        """Build the ToolSearch roundtrip message shown to the model.

        This is the lightweight response that tells the model:
        "You asked for X, here's the deferred tool that does it."
        """
        search_results = self.search(query)
        # Find the matching tool
        match = next((r for r in search_results if r.tool_name == tool_name), None)
        if match is None:
            # Fallback: create a generic result
            dt = self._deferred.get(tool_name)
            match = ToolSearchResult(
                tool_name=tool_name,
                match_reason="named tool",
                confidence=1.0,
                hint=dt.search_hint if dt else "",
            )

        lines = [
            "[ToolSearch Result]",
            f"Matched tool: {match.tool_name}",
            f"Confidence: {match.confidence:.0%}",
            f"Hint: {match.hint}",
        ]
        if match.match_reason:
            lines.append(f"Reason: {match.match_reason}")
        lines.extend([
            "",
            "Now call the tool to proceed:",
            f'{{"name": "{tool_name}", "arguments": {{...}}}}',
        ])
        return "\n".join(lines)

    def build_search_results_message(self, query: str) -> str:
        """Build a full ToolSearch results list for a query."""
        results = self.search(query)
        if not results:
            return (
                f"[ToolSearch] No deferred tools match '{query}'. "
                "Use immediate tools (read_file, bash, edit_file, grep, glob, etc.) instead."
            )

        lines = [
            f"[ToolSearch] {len(results)} result(s) for: {query}",
            "",
        ]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.tool_name}** ({r.confidence:.0%})")
            lines.append(f"   {r.hint}")
            if r.match_reason:
                lines.append(f"   Match: {r.match_reason}")
        lines.append("")
        lines.append("Call the matching tool to proceed.")

        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Schema builder
# -----------------------------------------------------------------------------

def build_deferred_toolsystem(
    deferred_manager: ToolDeferralManager,
    include_in_schema: bool = False,
) -> str:
    """Build the deferred tools section of the system prompt.

    If include_in_schema is False (default), deferred tools are NOT listed
    in the schema and the model must use ToolSearch to discover them.

    If include_in_schema is True, they appear in the schema with a note
    that they require a ToolSearch roundtrip.

    Returns the markdown-formatted tools section.
    """
    deferred = deferred_manager.get_deferred_names()
    if not deferred:
        return ""

    if include_in_schema:
        lines = [
            "## Deferred Tools (require ToolSearch before use)",
            "",
            "These tools are NOT called directly. If you need one, first respond with:",
            '```',
            '{"name": "ToolSearch", "arguments": {"query": "<what you need>"}}',
            '```',
            "",
            "Available deferred tools:",
        ]
        for name in sorted(deferred):
            dt = deferred_manager._deferred.get(name)
            if dt:
                hint = dt.search_hint or "No description"
                lines.append(f"- **{name}**: {hint}")
        return "\n".join(lines)

    # Default: no mention in schema (minimal footprint)
    return ""
