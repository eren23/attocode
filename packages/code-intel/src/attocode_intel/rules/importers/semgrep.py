"""Semgrep rule importer — converts Semgrep YAML rules to attocode format.

Handles Semgrep's rule format including:
- ``pattern``, ``patterns``, ``pattern-either``, ``pattern-not``
- ``metavariable-regex`` and ``metavariable-comparison``
- ``fix`` (autofix)
- ``metadata`` (CWE, confidence, OWASP)

Limitations:
- Semgrep patterns that use ``$X`` metavariables in AST-aware mode
  cannot be directly converted to regex. These are flagged as needing
  the structural tier (ast-grep).
- ``pattern-inside`` with full AST scope is approximated as line-based.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Semgrep severity -> attocode severity
_SEVERITY_MAP = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "INVENTORY": "info",
}

# Semgrep category hints -> attocode category
_CATEGORY_MAP = {
    "security": "security",
    "correctness": "correctness",
    "best-practice": "style",
    "performance": "performance",
    "maintainability": "complexity",
}


def _has_ast_metavars(pattern: str) -> bool:
    """Check if a Semgrep pattern uses AST-aware metavariables.

    Semgrep metavars like ``$X`` in AST patterns work differently from
    regex patterns — they match entire AST nodes. We can only convert
    simple patterns where ``$X`` maps to ``\\w+`` or similar.
    """
    # Patterns with ellipsis operators (... in Semgrep) are AST-aware
    if "..." in pattern and "$" in pattern:
        return True
    # Patterns with type constraints or deep patterns
    if "<..." in pattern or "...>" in pattern:
        return True
    return False


def _extract_cwe(metadata: dict) -> str:
    """Extract CWE ID from Semgrep metadata."""
    # Semgrep stores CWE in various places
    cwe = metadata.get("cwe", "")
    if isinstance(cwe, list):
        cwe = cwe[0] if cwe else ""
    cwe = str(cwe)

    # Normalize to "CWE-NNN" format
    m = re.search(r"CWE-?(\d+)", cwe, re.IGNORECASE)
    if m:
        return f"CWE-{m.group(1)}"
    return ""


def _extract_confidence(metadata: dict) -> float:
    """Extract confidence from Semgrep metadata."""
    conf = metadata.get("confidence", "")
    if isinstance(conf, (int, float)):
        return float(conf) if 0 <= conf <= 1 else conf / 100
    conf_str = str(conf).lower()
    if conf_str == "high":
        return 0.9
    elif conf_str == "medium":
        return 0.7
    elif conf_str == "low":
        return 0.5
    return 0.8


def convert_semgrep_rule(rule: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a single Semgrep rule to attocode YAML format.

    Args:
        rule: A single rule dict from Semgrep YAML.

    Returns:
        Attocode-format rule dict, or None if unconvertible.
    """
    rule_id = rule.get("id", "")
    if not rule_id:
        return None

    metadata = rule.get("metadata", {})
    severity = _SEVERITY_MAP.get(rule.get("severity", "WARNING"), "medium")

    # Determine category
    category = "security"  # default for Semgrep rules
    for tag in metadata.get("category", []) if isinstance(metadata.get("category"), list) else [str(metadata.get("category", ""))]:
        tag_lower = tag.lower()
        if tag_lower in _CATEGORY_MAP:
            category = _CATEGORY_MAP[tag_lower]
            break

    # Extract pattern(s)
    attocode_rule: dict[str, Any] = {
        "id": rule_id,
        "name": rule_id.replace("-", " ").replace("_", " ").title()[:60],
        "message": rule.get("message", ""),
        "severity": severity,
        "category": category,
        "confidence": _extract_confidence(metadata),
    }

    # CWE
    cwe = _extract_cwe(metadata)
    if cwe:
        attocode_rule["cwe"] = cwe

    # Languages
    languages = rule.get("languages", [])
    if languages:
        attocode_rule["languages"] = languages

    # Tags
    tags = metadata.get("tags", [])
    if isinstance(tags, list):
        attocode_rule["tags"] = tags

    # Handle pattern types
    needs_structural = False

    if "pattern" in rule:
        pattern = str(rule["pattern"])
        if _has_ast_metavars(pattern):
            needs_structural = True
            attocode_rule["structural_pattern"] = pattern
            # Still provide regex approximation
            regex_approx = _semgrep_to_regex(pattern)
            if regex_approx:
                attocode_rule["pattern"] = regex_approx
        else:
            regex = _semgrep_to_regex(pattern)
            if regex:
                attocode_rule["pattern"] = regex
            else:
                return None  # can't convert

    elif "patterns" in rule:
        # Semgrep composite patterns -> attocode patterns list
        patterns_list = _convert_patterns(rule["patterns"])
        if patterns_list:
            attocode_rule["patterns"] = patterns_list
        else:
            return None

    elif "pattern-either" in rule:
        either = rule["pattern-either"]
        converted = []
        for p in either:
            if isinstance(p, str):
                regex = _semgrep_to_regex(p)
                if regex:
                    converted.append(regex)
            elif isinstance(p, dict) and "pattern" in p:
                regex = _semgrep_to_regex(str(p["pattern"]))
                if regex:
                    converted.append(regex)
        if converted:
            attocode_rule["pattern-either"] = converted
        else:
            return None

    else:
        return None  # no pattern to convert

    # Metavariable constraints — convert Semgrep format to attocode format
    # Semgrep: {"metavariable": "$VAR", "regex": "..."} or {"metavariable": "$VAR", "comparison": "..."}
    # Attocode: {"VAR": "..."} (key is var name without $)
    for item in rule.get("patterns", []):
        if isinstance(item, dict):
            if "metavariable-regex" in item:
                mv = item["metavariable-regex"]
                if isinstance(mv, dict) and "metavariable" in mv and "regex" in mv:
                    var = str(mv["metavariable"]).lstrip("$")
                    attocode_rule.setdefault("metavariable-regex", {})[var] = str(mv["regex"])
                elif isinstance(mv, dict):
                    # Already in attocode format (key: regex pairs)
                    attocode_rule["metavariable-regex"] = mv
            if "metavariable-comparison" in item:
                mv = item["metavariable-comparison"]
                if isinstance(mv, dict) and "metavariable" in mv and "comparison" in mv:
                    var = str(mv["metavariable"]).lstrip("$")
                    attocode_rule.setdefault("metavariable-comparison", {})[var] = str(mv["comparison"])
                elif isinstance(mv, dict):
                    attocode_rule["metavariable-comparison"] = mv

    # Fix
    fix = rule.get("fix", "")
    if fix:
        attocode_rule["fix"] = {
            "search": rule.get("pattern", ""),
            "replace": fix,
        }

    # Generate explanation stub from message
    message = rule.get("message", "")
    if message and "explanation" not in attocode_rule:
        attocode_rule["explanation"] = message
    if message and "recommendation" not in attocode_rule:
        attocode_rule["recommendation"] = f"Address: {message[:100]}"

    # Mark as needing structural tier
    if needs_structural:
        attocode_rule.setdefault("tags", []).append("needs-structural-tier")

    return attocode_rule


def _semgrep_to_regex(pattern: str) -> str | None:
    """Convert a Semgrep pattern to a regex pattern.

    Simple Semgrep patterns (without deep AST matching) can often
    be converted to regex with metavariable support.
    """
    if not pattern.strip():
        return None

    # Remove leading/trailing whitespace and ellipsis
    p = pattern.strip()

    # Replace Semgrep ellipsis with regex wildcard
    p = p.replace("...", ".*?")

    # Escape regex special chars EXCEPT those in metavar patterns
    # We do a targeted escape: escape chars that are regex-special
    # but preserve $VAR metavariables
    result = []
    i = 0
    while i < len(p):
        if p[i] == "$" and i + 1 < len(p) and (p[i + 1].isalpha() or p[i + 1] == "_"):
            # Keep $VAR as-is (metavar)
            j = i + 1
            while j < len(p) and (p[j].isalnum() or p[j] == "_"):
                j += 1
            result.append(p[i:j])
            i = j
        elif p[i] in r"\.+*?[]{}()^|":
            # Escape regex special chars
            if p[i] == "." and i + 2 < len(p) and p[i:i+3] == ".*?":
                result.append(".*?")
                i += 3
            else:
                result.append("\\" + p[i])
                i += 1
        else:
            result.append(p[i])
            i += 1

    regex = "".join(result)

    # Verify it compiles
    try:
        re.compile(regex)
        return regex
    except re.error:
        return None


def _convert_patterns(patterns: list) -> list[dict[str, str]] | None:
    """Convert Semgrep patterns list to attocode patterns list."""
    result: list[dict[str, str]] = []

    for item in patterns:
        if not isinstance(item, dict):
            continue

        if "pattern" in item:
            regex = _semgrep_to_regex(str(item["pattern"]))
            if regex:
                result.append({"pattern": regex})

        elif "pattern-not" in item:
            regex = _semgrep_to_regex(str(item["pattern-not"]))
            if regex:
                result.append({"pattern-not": regex})

        elif "pattern-inside" in item:
            regex = _semgrep_to_regex(str(item["pattern-inside"]))
            if regex:
                result.append({"pattern-inside": regex})

        elif "pattern-not-inside" in item:
            regex = _semgrep_to_regex(str(item["pattern-not-inside"]))
            if regex:
                result.append({"pattern-not-inside": regex})

        elif "pattern-either" in item:
            either_list = item["pattern-either"]
            converted = []
            for p in either_list:
                if isinstance(p, str):
                    regex = _semgrep_to_regex(p)
                    if regex:
                        converted.append(regex)
                elif isinstance(p, dict) and "pattern" in p:
                    regex = _semgrep_to_regex(str(p["pattern"]))
                    if regex:
                        converted.append(regex)
            if converted:
                result.append({"pattern-either": converted})

    return result if result else None


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------


def convert_semgrep_file(yaml_content: str) -> tuple[list[dict], list[str]]:
    """Convert a Semgrep YAML file (possibly with multiple rules) to attocode format.

    Args:
        yaml_content: Raw YAML content from a Semgrep rule file.

    Returns:
        (converted_rules, errors) — list of attocode rule dicts and error messages.
    """
    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(yaml_content)
    except Exception as exc:
        return [], [f"Failed to parse YAML: {exc}"]

    if not isinstance(data, dict) or "rules" not in data:
        return [], ["Expected Semgrep format with top-level 'rules' key"]

    converted: list[dict] = []
    errors: list[str] = []

    for i, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict):
            errors.append(f"Rule at index {i}: expected dict")
            continue
        result = convert_semgrep_rule(rule)
        if result:
            converted.append(result)
        else:
            errors.append(f"Rule '{rule.get('id', f'index-{i}')}': could not convert")

    return converted, errors


def convert_semgrep_to_yaml(yaml_content: str) -> str:
    """Convert Semgrep YAML to attocode YAML string.

    Convenience function for the MCP tool.
    """
    converted, errors = convert_semgrep_file(yaml_content)

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return "Error: PyYAML not installed"

    parts: list[str] = []
    if converted:
        parts.append(yaml.dump(converted, default_flow_style=False, sort_keys=False))
    if errors:
        parts.append("\n# Conversion errors:")
        for e in errors:
            parts.append(f"#   {e}")

    return "\n".join(parts) if parts else "No rules converted."
