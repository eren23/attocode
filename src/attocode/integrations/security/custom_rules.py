"""Load user-defined security rules from .attocode/rules/*.yaml files.

Custom rules use the same SecurityPattern dataclass as built-in patterns,
allowing them to be seamlessly merged into the scanning pipeline.

Rule format (YAML):
    id: my_rule_name
    pattern: "regex_pattern_here"
    message: "What was detected"
    severity: high           # critical | high | medium | low | info
    cwe: CWE-79             # optional
    recommendation: "How to fix"
    languages:               # optional, empty = all languages
      - python
      - javascript
    scan_comments: false     # optional, default false
    fix:                     # optional autofix
      search: "old_code("
      replace: "new_code("
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from attocode.integrations.security.patterns import (
    Category,
    SecurityPattern,
    Severity,
)

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = frozenset(s.value for s in Severity)


def load_custom_rules(project_dir: str) -> list[SecurityPattern]:
    """Load custom security rules from .attocode/rules/*.yaml files.

    Args:
        project_dir: Project root directory.

    Returns:
        List of SecurityPattern instances from user-defined rules.
        Invalid rules are logged and skipped.
    """
    rules_dir = Path(project_dir) / ".attocode" / "rules"
    if not rules_dir.is_dir():
        return []

    patterns: list[SecurityPattern] = []
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        try:
            file_patterns = _load_rules_file(yaml_file)
            patterns.extend(file_patterns)
        except Exception as exc:
            logger.warning("Failed to load custom rules from %s: %s", yaml_file, exc)

    if patterns:
        logger.info("Loaded %d custom security rule(s) from %s", len(patterns), rules_dir)

    return patterns


def _load_rules_file(path: Path) -> list[SecurityPattern]:
    """Parse a single YAML rules file into SecurityPattern instances."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("PyYAML not installed — skipping custom rules file %s", path)
        return []

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    if data is None:
        return []

    # Support both single-rule and multi-rule files
    if isinstance(data, dict):
        rules_list = [data]
    elif isinstance(data, list):
        rules_list = data
    else:
        logger.warning("Invalid rules file %s: expected dict or list", path)
        return []

    patterns: list[SecurityPattern] = []
    for i, rule in enumerate(rules_list):
        try:
            pattern = _parse_rule(rule, source=f"{path.name}[{i}]")
            if pattern is not None:
                patterns.append(pattern)
        except Exception as exc:
            logger.warning("Invalid rule in %s at index %d: %s", path.name, i, exc)

    return patterns


def _parse_rule(rule: dict, source: str = "") -> SecurityPattern | None:
    """Parse a single rule dict into a SecurityPattern.

    Required fields: id, pattern, message, severity, recommendation.
    Optional fields: cwe, languages, scan_comments, fix.
    """
    # Validate required fields
    missing = [f for f in ("id", "pattern", "message", "severity", "recommendation") if f not in rule]
    if missing:
        logger.warning("Rule %s missing required fields: %s", source, ", ".join(missing))
        return None

    # Validate severity
    severity_str = str(rule["severity"]).lower()
    if severity_str not in _VALID_SEVERITIES:
        logger.warning(
            "Rule %s has invalid severity '%s' (must be one of: %s)",
            source, rule["severity"], ", ".join(sorted(_VALID_SEVERITIES)),
        )
        return None

    # Compile regex
    try:
        compiled = re.compile(rule["pattern"])
    except re.error as exc:
        logger.warning("Rule %s has invalid regex '%s': %s", source, rule["pattern"], exc)
        return None

    return SecurityPattern(
        name=str(rule["id"]),
        pattern=compiled,
        severity=Severity(severity_str),
        category=Category.ANTI_PATTERN,
        cwe_id=str(rule.get("cwe", "")),
        message=str(rule["message"]),
        recommendation=str(rule["recommendation"]),
        languages=rule.get("languages", []),
        scan_comments=bool(rule.get("scan_comments", False)),
    )


def get_autofix_from_rules(
    project_dir: str,
) -> dict[str, tuple[str, str]]:
    """Extract autofix templates from custom rules that define a 'fix' field.

    Returns:
        Dict mapping rule id -> (search, replace) for rules with fix defined.
    """
    rules_dir = Path(project_dir) / ".attocode" / "rules"
    if not rules_dir.is_dir():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {}

    fixes: dict[str, tuple[str, str]] = {}
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data is None:
                continue
            rules_list = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            for rule in rules_list:
                if isinstance(rule, dict) and "fix" in rule and "id" in rule:
                    fix = rule["fix"]
                    if isinstance(fix, dict) and "search" in fix and "replace" in fix:
                        fixes[str(rule["id"])] = (str(fix["search"]), str(fix["replace"]))
        except Exception:
            continue

    return fixes
