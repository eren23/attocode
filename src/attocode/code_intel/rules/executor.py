"""Rule executor — runs rules against source files to produce findings."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from attocode.code_intel.rules.combinators import MatchContext
from attocode.code_intel.rules.metavar import (
    apply_metavar_fix,
    check_metavar_constraints,
    interpolate_message,
)
from attocode.code_intel.rules.model import (
    EnrichedFinding,
    RuleTier,
    UnifiedRule,
)

logger = logging.getLogger(__name__)

# Extension to language mapping
_EXT_LANG: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".cs": "csharp",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".scala": "scala",
    ".ex": "elixir", ".exs": "elixir",
}

# Comment prefix detection per language
_COMMENT_PREFIX: dict[str, list[str]] = {
    "python": ["#"],
    "javascript": ["//"],
    "typescript": ["//"],
    "go": ["//"],
    "rust": ["//"],
    "java": ["//"],
    "kotlin": ["//"],
    "ruby": ["#"],
    "php": ["//", "#"],
    "swift": ["//"],
    "csharp": ["//"],
    "c": ["//"],
    "cpp": ["//"],
    "lua": ["--"],
    "shell": ["#"],
    "scala": ["//"],
    "elixir": ["#"],
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return _EXT_LANG.get(ext, "")


def _is_comment_line(line: str, language: str) -> bool:
    stripped = line.lstrip()
    for prefix in _COMMENT_PREFIX.get(language, []):
        if stripped.startswith(prefix):
            return True
    return False


def execute_rules(
    files: list[str],
    rules: list[UnifiedRule],
    *,
    project_dir: str = "",
) -> list[EnrichedFinding]:
    """Execute rules against a list of files.

    Args:
        files: Absolute file paths to scan.
        rules: Rules to execute (should be pre-filtered to enabled only).
        project_dir: Project root for relative path computation.

    Returns:
        List of EnrichedFinding (partially populated — use enricher for full context).
    """
    findings: list[EnrichedFinding] = []

    # Pre-group rules by language for fast lookup
    lang_rules: dict[str, list[UnifiedRule]] = {}
    universal_rules: list[UnifiedRule] = []

    for rule in rules:
        if rule.tier != RuleTier.REGEX:
            continue  # structural/plugin tiers handled elsewhere
        if rule.pattern is None and rule.composite_pattern is None:
            continue  # no executable pattern
        if not rule.languages:
            universal_rules.append(rule)
        else:
            for lang in rule.languages:
                lang_rules.setdefault(lang, []).append(rule)

    for file_path in files:
        lang = detect_language(file_path)
        applicable = list(universal_rules)
        if lang:
            applicable.extend(lang_rules.get(lang, []))
        if not applicable:
            continue

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = content.splitlines()
        rel_path = file_path
        if project_dir:
            try:
                rel_path = os.path.relpath(file_path, project_dir)
            except ValueError:
                pass

        for i, line in enumerate(lines):
            line_no = i + 1
            is_comment = _is_comment_line(line, lang)

            for rule in applicable:
                if is_comment and not rule.scan_comments:
                    continue

                captures: dict[str, str] = {}

                # --- Composite pattern path ---
                if rule.composite_pattern is not None:
                    ctx = MatchContext(
                        line=line, line_no=line_no, all_lines=lines,
                    )
                    if not rule.composite_pattern.evaluate(ctx):
                        continue
                    captures = ctx.captures

                # --- Simple pattern path ---
                elif rule.pattern is not None:
                    match = rule.pattern.search(line)
                    if not match:
                        continue
                    if rule.metavars:
                        captures = {
                            k: v for k, v in match.groupdict().items()
                            if v is not None
                        }
                        if not check_metavar_constraints(
                            captures, rule.metavar_regex, rule.metavar_comparison,
                        ):
                            continue
                else:
                    continue

                # Build description with metavar interpolation
                description = rule.description
                if captures:
                    description = interpolate_message(description, captures)

                # Build suggested fix
                suggested_fix = ""
                if rule.fix:
                    if rule.fix.uses_metavars and captures:
                        sf_search, sf_replace = apply_metavar_fix(
                            rule.fix.search, rule.fix.replace, captures,
                        )
                        suggested_fix = f"{sf_search} \u2192 {sf_replace}"
                    else:
                        suggested_fix = f"{rule.fix.search} \u2192 {rule.fix.replace}"

                findings.append(EnrichedFinding(
                    rule_id=rule.qualified_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    category=rule.category,
                    confidence=rule.confidence,
                    file=rel_path,
                    line=line_no,
                    code_snippet=line.rstrip()[:200],
                    description=description,
                    explanation=rule.explanation,
                    recommendation=rule.recommendation,
                    examples=list(rule.examples),
                    suggested_fix=suggested_fix,
                    captures=dict(captures),
                    cwe=rule.cwe,
                    pack=rule.pack,
                    tags=list(rule.tags),
                ))

    # Sort: severity first, then file, then line
    _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (_sev_order.get(f.severity, 9), f.file, f.line))
    return findings
