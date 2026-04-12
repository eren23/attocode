"""Pluggable rule-based analysis engine.

Provides a unified rule model, registry, loader, executor, enricher,
and formatter for multi-language static analysis with language packs,
user plugins, and deterministic pre-filtering.
"""

from attocode.code_intel.rules.model import (
    AutoFix,
    EnrichedFinding,
    FewShotExample,
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)

__all__ = [
    "AutoFix",
    "EnrichedFinding",
    "FewShotExample",
    "RuleCategory",
    "RuleSeverity",
    "RuleSource",
    "RuleTier",
    "UnifiedRule",
]
