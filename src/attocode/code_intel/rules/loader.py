"""Rule loader — loads rules from builtins, YAML files, and packs."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from attocode.code_intel.rules.metavar import compile_metavar_pattern, has_metavars
from attocode.code_intel.rules.model import (
    AutoFix,
    FewShotExample,
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
    from_bug_pattern,
    from_security_pattern,
)

logger = logging.getLogger(__name__)

# Category mapping for YAML rules
_YAML_CATEGORY_MAP: dict[str, RuleCategory] = {
    "correctness": RuleCategory.CORRECTNESS,
    "suspicious": RuleCategory.SUSPICIOUS,
    "complexity": RuleCategory.COMPLEXITY,
    "performance": RuleCategory.PERFORMANCE,
    "style": RuleCategory.STYLE,
    "security": RuleCategory.SECURITY,
    "deprecated": RuleCategory.DEPRECATED,
    # Legacy compat (must match from_bug_pattern and from_security_pattern mappings)
    "anti_pattern": RuleCategory.SUSPICIOUS,
    "secret": RuleCategory.SECURITY,
    "logic_error": RuleCategory.CORRECTNESS,
    "error_handling": RuleCategory.CORRECTNESS,
    "edge_case": RuleCategory.SUSPICIOUS,
    "concurrency": RuleCategory.SUSPICIOUS,
    "resource_leak": RuleCategory.CORRECTNESS,
    "type_safety": RuleCategory.CORRECTNESS,
}

_VALID_SEVERITIES = frozenset(s.value for s in RuleSeverity)


def load_builtin_rules() -> list[UnifiedRule]:
    """Load builtin rules from bug_finder and security patterns."""
    rules: list[UnifiedRule] = []

    # 1. Bug finder patterns
    try:
        from attocode.code_intel.bug_finder import _PATTERNS

        for regex, cat, sev, desc, conf in _PATTERNS:
            try:
                rule = from_bug_pattern(regex, cat.value, sev.value, desc, conf)
                rules.append(rule)
            except Exception as exc:
                logger.warning("Failed to adapt builtin bug pattern '%s': %s", desc[:40], exc)
    except ImportError:
        logger.debug("bug_finder not available, skipping builtin bug rules")

    # 2. Security patterns (secrets + anti-patterns)
    try:
        from attocode.integrations.security.patterns import (
            ANTI_PATTERNS,
            SECRET_PATTERNS,
        )

        for pat in SECRET_PATTERNS:
            try:
                rules.append(from_security_pattern(pat))
            except Exception as exc:
                logger.warning("Failed to adapt security pattern '%s': %s", getattr(pat, "name", "?"), exc)
        for pat in ANTI_PATTERNS:
            try:
                rules.append(from_security_pattern(pat))
            except Exception as exc:
                logger.warning("Failed to adapt security pattern '%s': %s", getattr(pat, "name", "?"), exc)
    except ImportError:
        logger.debug("security patterns not available, skipping builtin security rules")

    logger.info("Loaded %d builtin rules", len(rules))
    return rules


def load_yaml_rules(
    rules_dir: str | Path,
    *,
    source: RuleSource = RuleSource.USER,
    pack: str = "",
) -> list[UnifiedRule]:
    """Load rules from YAML files in a directory.

    Supports the existing .attocode/rules/*.yaml format plus the
    expanded format with explanation and examples fields.

    Args:
        rules_dir: Directory containing \\*.yaml rule files.
        source: RuleSource tag for loaded rules.
        pack: Pack name to associate with loaded rules.

    Returns:
        List of parsed UnifiedRule instances. Invalid rules are skipped.
    """
    rules_path = Path(rules_dir)
    if not rules_path.is_dir():
        return []

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("PyYAML not installed — skipping YAML rules from %s", rules_dir)
        return []

    rules: list[UnifiedRule] = []
    for yaml_file in sorted(rules_path.glob("*.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data is None:
                continue
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            for i, item in enumerate(items):
                try:
                    rule = _parse_yaml_rule(
                        item, source=source, pack=pack, origin=f"{yaml_file.name}[{i}]",
                    )
                    if rule is not None:
                        rules.append(rule)
                except Exception as exc:
                    logger.warning("Invalid rule in %s at index %d: %s", yaml_file.name, i, exc)
        except Exception as exc:
            logger.warning("Failed to load rules from %s: %s", yaml_file, exc)

    if rules:
        logger.info("Loaded %d YAML rules from %s", len(rules), rules_dir)
    return rules


def _parse_yaml_rule(
    data: dict,
    *,
    source: RuleSource = RuleSource.USER,
    pack: str = "",
    origin: str = "",
) -> UnifiedRule | None:
    """Parse a single YAML rule dict into a UnifiedRule."""
    # ``pattern`` is required unless one of: ``patterns``/``pattern-either``
    # provides a composite, OR ``structural_pattern`` provides a Tier-2
    # ast-grep matcher (message-only structural rules are valid).
    has_composite = "patterns" in data or "pattern-either" in data
    has_structural = bool(data.get("structural_pattern"))
    # Allow ``description`` as a synonym for ``message`` so structural-only
    # rules don't have to repeat themselves.
    if "message" not in data and "description" in data:
        data = {**data, "message": data["description"]}
    required = ["id", "message", "severity"]
    if not (has_composite or has_structural):
        required.append("pattern")
    missing = [f for f in required if f not in data]
    if missing:
        logger.warning("Rule %s missing required fields: %s", origin, ", ".join(missing))
        return None

    sev_str = str(data["severity"]).lower()
    if sev_str not in _VALID_SEVERITIES:
        logger.warning("Rule %s has invalid severity '%s'", origin, data["severity"])
        return None

    # Category (default to security for backward compat)
    cat_str = str(data.get("category", "security")).lower()
    category = _YAML_CATEGORY_MAP.get(cat_str, RuleCategory.SECURITY)

    # Build composite pattern if "patterns" or "pattern-either" is present
    composite_pattern = None
    if has_composite:
        from attocode.code_intel.rules.combinators import build_composite_from_yaml
        if "patterns" in data:
            composite_src = data["patterns"]  # list of dicts
        else:
            # Top-level pattern-either: wrap as dict for build_composite_from_yaml
            composite_src = {"pattern-either": data["pattern-either"]}
        composite_pattern = build_composite_from_yaml(composite_src)
        if composite_pattern is None:
            logger.warning("Rule %s has invalid composite patterns", origin)
            return None

    # Compile primary pattern (may be absent for composite-only rules)
    compiled: re.Pattern[str] | None = None
    metavar_names: list[str] = []
    if "pattern" in data:
        pattern_str = str(data["pattern"])
        try:
            if has_metavars(pattern_str):
                compiled, metavar_names = compile_metavar_pattern(pattern_str)
            else:
                compiled = re.compile(pattern_str)
        except re.error as exc:
            logger.warning("Rule %s has invalid regex: %s", origin, exc)
            return None

    tier = RuleTier.STRUCTURAL if data.get("structural_pattern") else RuleTier.REGEX

    # ast-grep's inline-rule YAML accepts a ``pattern`` object with either
    # a bare string OR ``{context, selector}``. Specifying ``context``
    # without ``selector`` produces an invalid rule that ast-grep rejects
    # at parse time, which silently no-ops the rule. Catch it at load.
    if data.get("structural_context") and not data.get("structural_selector"):
        logger.warning(
            "Rule %s sets structural_context without structural_selector; "
            "ast-grep needs both — skipping this rule",
            origin,
        )
        return None

    # Parse metavariable constraints
    metavar_regex: dict[str, str] = {}
    raw_mv_regex = data.get("metavariable-regex") or data.get("metavariable_regex")
    if isinstance(raw_mv_regex, dict):
        metavar_regex = {str(k): str(v) for k, v in raw_mv_regex.items()}

    metavar_comparison: dict[str, str] = {}
    raw_mv_cmp = data.get("metavariable-comparison") or data.get("metavariable_comparison")
    if isinstance(raw_mv_cmp, dict):
        metavar_comparison = {str(k): str(v) for k, v in raw_mv_cmp.items()}

    fix = None
    fix_data = data.get("fix")
    if isinstance(fix_data, dict) and "search" in fix_data and "replace" in fix_data:
        fix_search = str(fix_data["search"])
        fix_replace = str(fix_data["replace"])
        uses_metavars = has_metavars(fix_search) or has_metavars(fix_replace)
        fix = AutoFix(search=fix_search, replace=fix_replace, uses_metavars=uses_metavars)

    examples: list[FewShotExample] = []
    for ex in data.get("examples", []):
        if isinstance(ex, dict) and "bad" in ex and "good" in ex:
            examples.append(FewShotExample(
                bad_code=str(ex["bad"]),
                good_code=str(ex["good"]),
                explanation=str(ex.get("explanation", "")),
            ))

    # Normalize languages and tags to lists (YAML allows string shorthand)
    raw_langs = data.get("languages", [])
    languages = [raw_langs] if isinstance(raw_langs, str) else list(raw_langs)
    raw_tags = data.get("tags", [])
    tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)

    # External references (CWE links, blog posts, etc.) — preserved on import
    raw_refs = data.get("references", [])
    references = [raw_refs] if isinstance(raw_refs, str) else list(raw_refs)

    return UnifiedRule(
        id=str(data["id"]),
        name=str(data.get("name", data["id"])),
        description=str(data["message"]),
        severity=RuleSeverity(sev_str),
        category=category,
        languages=languages,
        pattern=compiled,
        structural_pattern=str(data.get("structural_pattern", "")),
        structural_context=str(data.get("structural_context", "")),
        structural_selector=str(data.get("structural_selector", "")),
        cwe=str(data.get("cwe", "")),
        tags=tags,
        source=source,
        tier=tier,
        confidence=float(data.get("confidence", 0.8)),
        fix=fix,
        enabled=bool(data.get("enabled", True)),
        pack=pack,
        explanation=str(data.get("explanation", "")),
        examples=examples,
        recommendation=str(data.get("recommendation", "")),
        scan_comments=bool(data.get("scan_comments", False)),
        metavars=metavar_names,
        metavar_regex=metavar_regex,
        metavar_comparison=metavar_comparison,
        composite_pattern=composite_pattern,
        references=references,
    )


def load_user_rules(project_dir: str) -> list[UnifiedRule]:
    """Load user-defined rules from .attocode/rules/*.yaml."""
    return load_yaml_rules(
        Path(project_dir) / ".attocode" / "rules",
        source=RuleSource.USER,
    )
