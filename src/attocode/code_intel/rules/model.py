"""Unified rule and finding data model.

All analysis tiers (YAML regex, structural/ast-grep, user plugins)
produce the same ``UnifiedRule`` and ``EnrichedFinding`` shapes,
ensuring consistent output regardless of how the rule was defined.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.code_intel.rules.combinators import CompositePattern


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuleSeverity(StrEnum):
    """Finding severity — mirrors existing Severity in patterns.py."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RuleCategory(StrEnum):
    """Clippy-inspired category taxonomy."""

    CORRECTNESS = "correctness"  # likely bugs, logic errors
    SUSPICIOUS = "suspicious"  # almost certainly wrong
    COMPLEXITY = "complexity"  # unnecessarily complex code
    PERFORMANCE = "performance"  # suboptimal patterns (PerfInsights territory)
    STYLE = "style"  # naming, formatting, idioms
    SECURITY = "security"  # vulnerabilities, CWE-tagged
    DEPRECATED = "deprecated"  # outdated APIs/patterns


class RuleSource(StrEnum):
    """Where the rule came from."""

    BUILTIN = "builtin"  # shipped with attocode
    PACK = "pack"  # from a language pack
    USER = "user"  # from .attocode/rules/ or .attocode/plugins/


class RuleTier(StrEnum):
    """Execution tier for the rule."""

    REGEX = "regex"  # Tier 1: regex pattern matching
    STRUCTURAL = "structural"  # Tier 2: ast-grep structural match
    PLUGIN = "plugin"  # Tier 3: user-defined plugin


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FewShotExample:
    """Bad → good code example for agent context."""

    bad_code: str
    good_code: str
    explanation: str


@dataclass(slots=True, frozen=True)
class AutoFix:
    """Deterministic search/replace fix.

    When *uses_metavars* is True, *search* and *replace* are templates
    containing ``$VAR`` references that get resolved from match captures.
    """

    search: str
    replace: str
    uses_metavars: bool = False


@dataclass(slots=True, frozen=True)
class TaintSourceDef:
    """A taint source definition (loaded from pack YAML)."""

    name: str
    patterns: list[str]
    language: str


@dataclass(slots=True, frozen=True)
class TaintSinkDef:
    """A taint sink definition (loaded from pack YAML)."""

    name: str
    patterns: list[str]
    cwe: str
    message: str
    language: str


@dataclass(slots=True, frozen=True)
class TaintSanitizerDef:
    """A sanitizer that breaks taint flow."""

    name: str
    patterns: list[str]
    language: str


# ---------------------------------------------------------------------------
# Core rule model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UnifiedRule:
    """A single analysis rule — the common shape across all tiers.

    Every rule loaded from YAML, adapted from builtins, or registered
    by a user plugin maps to this model before execution.
    """

    id: str
    name: str
    description: str
    severity: RuleSeverity
    category: RuleCategory
    languages: list[str] = field(default_factory=list)  # empty = all
    pattern: re.Pattern[str] | None = None  # compiled regex (tier 1)
    structural_pattern: str = ""  # ast-grep pattern string (tier 2)
    cwe: str = ""
    tags: list[str] = field(default_factory=list)
    source: RuleSource = RuleSource.BUILTIN
    tier: RuleTier = RuleTier.REGEX
    confidence: float = 0.8
    fix: AutoFix | None = None
    enabled: bool = True
    pack: str = ""  # language pack name (e.g. "go", "python")
    explanation: str = ""  # why this matters (for agent context)
    examples: list[FewShotExample] = field(default_factory=list)
    recommendation: str = ""  # how to fix
    scan_comments: bool = False

    # Metavariable support (A1)
    metavars: list[str] = field(default_factory=list)  # metavar names in pattern
    metavar_regex: dict[str, str] = field(default_factory=dict)  # post-match regex constraints
    metavar_comparison: dict[str, str] = field(default_factory=dict)  # post-match numeric constraints

    # Boolean combinators (A3) — when set, executor uses composite evaluation
    composite_pattern: CompositePattern | None = None

    # External references (CWE links, blog posts, doc URLs). Preserved by
    # community pack importers (e.g. semgrep ``metadata.references``) so the
    # provenance of a rule is not lost on conversion.
    references: list[str] = field(default_factory=list)

    @property
    def qualified_id(self) -> str:
        """Pack-qualified ID (e.g. 'go/performance/sprintf-in-loop')."""
        if self.pack:
            return f"{self.pack}/{self.id}"
        return self.id


# ---------------------------------------------------------------------------
# Enriched finding (agent-ready output)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EnrichedFinding:
    """A single analysis finding enriched with context for agent reasoning.

    This is the primary output shape — designed to give the connected
    coding agent everything it needs to triage, fix, and explain.
    """

    # Core identity
    rule_id: str
    rule_name: str
    severity: RuleSeverity
    category: RuleCategory
    confidence: float

    # Location
    file: str
    line: int
    code_snippet: str  # the matched line

    # Rich context for agent reasoning
    context_before: list[str] = field(default_factory=list)  # ~10 lines
    context_after: list[str] = field(default_factory=list)  # ~10 lines
    function_name: str = ""  # enclosing function

    # Explanation & guidance
    description: str = ""  # what was found
    explanation: str = ""  # why it matters
    recommendation: str = ""  # how to fix
    examples: list[FewShotExample] = field(default_factory=list)
    suggested_fix: str = ""  # concrete fix text

    # Metavariable captures (populated when rule uses $VAR patterns)
    captures: dict[str, str] = field(default_factory=dict)

    # Metadata
    cwe: str = ""
    pack: str = ""
    tags: list[str] = field(default_factory=list)
    related_findings: list[str] = field(default_factory=list)  # rule_ids
    taint_path: str = ""  # source → sink description (for dataflow)

    # References
    references: list[str] = field(default_factory=list)  # CWE links, docs


# ---------------------------------------------------------------------------
# Adapters from existing models
# ---------------------------------------------------------------------------


def from_security_pattern(
    pattern: object,
    *,
    pack: str = "",
) -> UnifiedRule:
    """Adapt a ``SecurityPattern`` from ``integrations.security.patterns``
    into a ``UnifiedRule`` without importing that module at top level.
    """
    # Duck-type access to avoid circular imports
    name: str = getattr(pattern, "name", "")
    regex: re.Pattern[str] = getattr(pattern, "pattern", re.compile(""))
    sev: str = str(getattr(pattern, "severity", "medium"))
    cat_str: str = str(getattr(pattern, "category", "anti_pattern"))
    cwe: str = getattr(pattern, "cwe_id", "")
    msg: str = getattr(pattern, "message", "")
    rec: str = getattr(pattern, "recommendation", "")
    langs: list[str] = getattr(pattern, "languages", [])
    scan_comments: bool = getattr(pattern, "scan_comments", False)

    _SEC_CAT_MAP = {
        "secret": RuleCategory.SECURITY,
        "anti_pattern": RuleCategory.SUSPICIOUS,
        "dependency": RuleCategory.SECURITY,
    }
    category = _SEC_CAT_MAP.get(cat_str, RuleCategory.SECURITY)

    return UnifiedRule(
        id=f"security/{name}",
        name=name,
        description=msg,
        severity=RuleSeverity(sev),
        category=category,
        languages=langs,
        pattern=regex,
        cwe=cwe,
        source=RuleSource.BUILTIN,
        tier=RuleTier.REGEX,
        confidence=0.85 if sev in ("critical", "high") else 0.7,
        recommendation=rec,
        scan_comments=scan_comments,
        pack=pack,
    )


def from_bug_pattern(
    regex: str,
    category_str: str,
    severity_str: str,
    description: str,
    confidence: float,
) -> UnifiedRule:
    """Adapt a bug_finder ``_PATTERNS`` tuple into a ``UnifiedRule``."""
    # Map bug_finder categories to RuleCategory
    _CAT_MAP = {
        "logic_error": RuleCategory.CORRECTNESS,
        "edge_case": RuleCategory.SUSPICIOUS,
        "security": RuleCategory.SECURITY,
        "performance": RuleCategory.PERFORMANCE,
        "error_handling": RuleCategory.CORRECTNESS,
        "type_safety": RuleCategory.CORRECTNESS,
        "concurrency": RuleCategory.SUSPICIOUS,
        "resource_leak": RuleCategory.CORRECTNESS,
    }
    cat = _CAT_MAP.get(category_str, RuleCategory.SUSPICIOUS)

    # Derive a stable rule ID from the description
    rule_id = "bug/" + description.lower()[:40].replace(" ", "-").strip("-")

    return UnifiedRule(
        id=rule_id,
        name=description[:60],
        description=description,
        severity=RuleSeverity(severity_str),
        category=cat,
        pattern=re.compile(regex),
        source=RuleSource.BUILTIN,
        tier=RuleTier.REGEX,
        confidence=confidence,
    )
