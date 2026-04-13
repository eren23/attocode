"""Finding formatter — produces agent-optimized text output."""

from __future__ import annotations

from collections import Counter

from attocode.code_intel.rules.model import (
    EnrichedFinding,
    FewShotExample,
    RuleCategory,
    RuleSeverity,
)


def format_findings(
    findings: list[EnrichedFinding],
    *,
    max_findings: int = 50,
    include_context: bool = True,
    include_examples: bool = True,
) -> str:
    """Format findings as agent-optimized markdown text.

    Designed to give the connected coding agent everything it needs
    to triage, fix, and explain the findings to the user.
    """
    if not findings:
        return "No findings detected."

    sev_counts = Counter(f.severity for f in findings)
    file_count = len(set(f.file for f in findings))
    parts = []
    for sev in (RuleSeverity.CRITICAL, RuleSeverity.HIGH, RuleSeverity.MEDIUM, RuleSeverity.LOW, RuleSeverity.INFO):
        c = sev_counts.get(sev, 0)
        if c:
            parts.append(f"{c} {sev}")
    summary = ", ".join(parts)

    lines: list[str] = []
    lines.append(f"## Analysis: {len(findings)} findings ({summary}) across {file_count} files")
    lines.append("")

    shown = findings[:max_findings]
    if len(findings) > max_findings:
        lines.append(f"_Showing top {max_findings} of {len(findings)} findings._\n")

    for finding in shown:
        lines.append(_format_single(finding, include_context=include_context, include_examples=include_examples))
        lines.append("")

    return "\n".join(lines)


def _format_single(
    f: EnrichedFinding,
    *,
    include_context: bool = True,
    include_examples: bool = True,
) -> str:
    lines: list[str] = []

    # Header
    sev_tag = f.severity.upper()
    lines.append(f"### [{sev_tag}] {f.rule_id}")

    # Location
    loc = f"File: {f.file}:{f.line}"
    if f.function_name:
        loc += f" | in {f.function_name}()"
    lines.append(loc)

    # Metadata
    meta_parts = [f"Category: {f.category}"]
    meta_parts.append(f"Confidence: {f.confidence:.0%}")
    if f.pack:
        meta_parts.append(f"Pack: {f.pack}")
    if f.cwe:
        meta_parts.append(f.cwe)
    lines.append(" | ".join(meta_parts))
    lines.append("")

    # Code context
    if include_context and (f.context_before or f.context_after):
        lines.append("```")
        start_line = f.line - len(f.context_before)
        for i, ctx_line in enumerate(f.context_before):
            lines.append(f"  {start_line + i:>4} | {ctx_line}")
        lines.append(f"> {f.line:>4} | {f.code_snippet}")
        for i, ctx_line in enumerate(f.context_after):
            lines.append(f"  {f.line + 1 + i:>4} | {ctx_line}")
        lines.append("```")
    elif f.code_snippet:
        lines.append("```")
        lines.append(f"> {f.line:>4} | {f.code_snippet}")
        lines.append("```")
    lines.append("")

    # Description
    if f.description:
        lines.append(f"**What:** {f.description}")

    # Explanation
    if f.explanation:
        lines.append(f"**Why this matters:** {f.explanation}")

    # Recommendation
    if f.recommendation:
        lines.append(f"**Recommendation:** {f.recommendation}")

    # Suggested fix
    if f.suggested_fix:
        lines.append("**Suggested fix:**")
        lines.append("```")
        lines.append(f"{f.suggested_fix}")
        lines.append("```")

    # Taint path
    if f.taint_path:
        lines.append(f"**Taint flow:** {f.taint_path}")

    # Few-shot examples
    if include_examples and f.examples:
        for ex in f.examples[:2]:
            lines.append(_format_example(ex))

    # References
    if f.references:
        lines.append("**References:** " + ", ".join(f.references))

    return "\n".join(lines)


def _format_example(ex: FewShotExample) -> str:
    lines = ["**Example (bad -> good):**"]
    lines.append(f"  BAD:  {ex.bad_code}")
    lines.append(f"  GOOD: {ex.good_code}")
    if ex.explanation:
        lines.append(f"  Why: {ex.explanation}")
    return "\n".join(lines)


def format_summary(findings: list[EnrichedFinding]) -> str:
    """Brief summary without code context."""
    return format_findings(findings, include_context=False, include_examples=False, max_findings=100)


def format_rules_list(
    rules: list,  # list[UnifiedRule] — loose typing to avoid circular import
    *,
    verbose: bool = False,
) -> str:
    """Format a list of rules for the list_rules MCP tool."""
    if not rules:
        return "No rules match the given filters."

    lines: list[str] = []
    lines.append(f"## Rules: {len(rules)} total\n")

    by_cat: dict[str, list] = {}
    for rule in rules:
        cat = str(getattr(rule, "category", "unknown"))
        by_cat.setdefault(cat, []).append(rule)

    for cat in sorted(by_cat.keys()):
        cat_rules = by_cat[cat]
        lines.append(f"### {cat} ({len(cat_rules)})")
        for rule in cat_rules:
            sev = str(getattr(rule, "severity", "?"))
            qid = getattr(rule, "qualified_id", getattr(rule, "id", "?"))
            desc = getattr(rule, "description", "")[:80]
            enabled = getattr(rule, "enabled", True)
            status = "" if enabled else " [disabled]"
            lines.append(f"  [{sev:>8}] {qid}{status}")
            if verbose and desc:
                lines.append(f"             {desc}")
        lines.append("")

    return "\n".join(lines)


def format_packs_list(packs: list[dict]) -> str:
    """Format language pack info for list_packs MCP tool."""
    if not packs:
        return "No language packs installed."

    lines = [f"## Language Packs: {len(packs)} installed\n"]
    for pack in packs:
        name = pack.get("name", "?")
        langs = ", ".join(pack.get("languages", []))
        rules_count = pack.get("rules_count", 0)
        desc = pack.get("description", "")
        lines.append(f"### {name}")
        lines.append(f"  Languages: {langs}")
        lines.append(f"  Rules: {rules_count}")
        if desc:
            lines.append(f"  {desc}")
        lines.append("")

    return "\n".join(lines)
