"""Rule executor — runs rules against source files to produce findings."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
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

# Per-rule subprocess timeout for ast-grep (seconds). Structural patterns
# can be expensive on huge files; cap to keep ``analyze`` responsive.
_AST_GREP_TIMEOUT = 30.0

# Languages where ast-grep ships a tree-sitter grammar. When a structural
# rule targets a language outside this set we either skip the rule (no
# fallback regex) or fall back to ``rule.pattern`` if the YAML defined one.
_AST_GREP_LANGS = frozenset({
    "bash", "c", "cpp", "csharp", "css", "elixir", "go", "html", "java",
    "javascript", "json", "kotlin", "lua", "php", "python", "ruby", "rust",
    "scala", "shell", "swift", "tsx", "typescript", "yaml",
})

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


def _ast_grep_available() -> bool:
    """Return True when an ``sg`` or ``ast-grep`` binary is on PATH."""
    return shutil.which("sg") is not None or shutil.which("ast-grep") is not None


def _ast_grep_binary() -> str:
    """Resolve the ast-grep binary, preferring the short ``sg`` alias."""
    return shutil.which("sg") or shutil.which("ast-grep") or "sg"


# ast-grep's ``language`` field uses TitleCase ("Go", "Python") whereas
# our internal language tags are lowercase. Mapping covers the cases that
# differ from a naive ``.title()``.
_AST_GREP_LANG_NAMES: dict[str, str] = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "tsx": "Tsx",
    "csharp": "CSharp",
    "cpp": "Cpp",
    "html": "Html",
    "css": "Css",
    "json": "Json",
    "yaml": "Yaml",
}


def _ast_grep_lang_name(lang: str) -> str:
    return _AST_GREP_LANG_NAMES.get(lang, lang.title())


def _yaml_quote(value: str) -> str:
    """Render ``value`` as a YAML single-quoted scalar, escaping quotes."""
    return "'" + value.replace("'", "''") + "'"


def _build_inline_rule_yaml(rule: UnifiedRule, lang: str) -> str:
    """Build the minimal ast-grep YAML rule for ``sg scan --inline-rules``.

    Used when the rule provides ``structural_context`` and/or
    ``structural_selector`` to disambiguate the parse.

    ast-grep accepts two pattern shapes under ``rule.pattern``:

    * a bare string — the simple pattern, no disambiguation
    * an object with ``context`` (the full snippet that parses correctly)
      and ``selector`` (the AST kind to extract from inside it). The plain
      ``pattern`` field on the object is *not* used when context drives
      matching; including it makes the YAML invalid.
    """
    parts: list[str] = [
        f"id: {rule.id or 'inline'}",
        f"language: {_ast_grep_lang_name(lang)}",
        "rule:",
    ]
    if rule.structural_context:
        parts.append("  pattern:")
        parts.append(f"    context: {_yaml_quote(rule.structural_context)}")
        if rule.structural_selector:
            parts.append(f"    selector: {rule.structural_selector}")
    elif rule.structural_selector:
        # Selector without context: pair it with the pattern as object.
        parts.append("  pattern:")
        parts.append(f"    pattern: {_yaml_quote(rule.structural_pattern)}")
        parts.append(f"    selector: {rule.structural_selector}")
    else:
        parts.append(f"  pattern: {_yaml_quote(rule.structural_pattern)}")
    return "\n".join(parts) + "\n"


def _execute_structural_rule(
    rule: UnifiedRule,
    files_by_lang: dict[str, list[str]],
    *,
    project_dir: str = "",
) -> list[EnrichedFinding]:
    """Run a single structural rule across applicable files via ast-grep.

    Per language: shells out to ``sg run --pattern <pat> --lang <lang>
    --json=stream <files...>`` and parses one match per JSON line. Files
    in languages without an ast-grep grammar are silently skipped — the
    caller is responsible for supplying ``rule.pattern`` if they want a
    Tier-1 fallback for those languages.

    Returns the list of (partially populated) ``EnrichedFinding`` objects.
    """
    if not rule.structural_pattern:
        return []

    # Determine which languages this rule applies to. An empty
    # ``rule.languages`` means "all languages we have files for".
    target_langs: list[str]
    if rule.languages:
        target_langs = [lang for lang in rule.languages if lang in files_by_lang]
    else:
        target_langs = list(files_by_lang.keys())

    binary = _ast_grep_binary()
    findings: list[EnrichedFinding] = []

    for lang in target_langs:
        if lang not in _AST_GREP_LANGS:
            continue
        files = files_by_lang.get(lang, [])
        if not files:
            continue

        # When the rule needs context/selector to disambiguate parsing
        # (e.g. ``fmt.Println($X)`` in Go), shell out to ``sg scan
        # --inline-rules`` with a YAML rule body. Otherwise the simpler
        # ``sg run --pattern`` path is faster.
        if rule.structural_context or rule.structural_selector:
            inline_yaml = _build_inline_rule_yaml(rule, lang)
            cmd = [
                binary, "scan",
                "--inline-rules", inline_yaml,
                "--json=stream",
                *files,
            ]
        else:
            cmd = [
                binary, "run",
                "--pattern", rule.structural_pattern,
                "--lang", lang,
                "--json=stream",
                *files,
            ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_AST_GREP_TIMEOUT,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning(
                "ast-grep failed for rule %s lang=%s: %s",
                rule.qualified_id, lang, exc,
            )
            continue

        # ast-grep returns non-zero when *no* matches are found. Only treat
        # stderr-with-actual-content as an error signal.
        if result.returncode not in (0, 1) and result.stderr.strip():
            logger.warning(
                "ast-grep error for rule %s lang=%s: %s",
                rule.qualified_id, lang, result.stderr.strip()[:200],
            )
            continue

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                match = json.loads(line)
            except json.JSONDecodeError:
                continue

            file_path = match.get("file", "")
            start = match.get("range", {}).get("start", {})
            line_no = int(start.get("line", 0)) + 1  # ast-grep is 0-based
            snippet = (match.get("lines") or "").rstrip()[:200]

            captures: dict[str, str] = {}
            metavars = match.get("metaVariables") or match.get("metavariables") or {}
            singles = metavars.get("single") or {}
            for var_name, info in singles.items():
                text = info.get("text") if isinstance(info, dict) else None
                if isinstance(text, str):
                    captures[var_name] = text
            # ast-grep emits ``$$$X`` (variadic) bindings under ``multi``.
            # Concatenate the segment texts so description templates that
            # reference ``$X`` still resolve to something readable.
            multis = metavars.get("multi") or {}
            for var_name, segments in multis.items():
                if var_name in captures or not isinstance(segments, list):
                    continue
                parts = [
                    s.get("text", "") for s in segments
                    if isinstance(s, dict) and isinstance(s.get("text"), str)
                ]
                if parts:
                    captures[var_name] = "".join(parts)

            description = rule.description
            if captures:
                description = interpolate_message(description, captures)

            suggested_fix = ""
            if rule.fix:
                if rule.fix.uses_metavars and captures:
                    sf_search, sf_replace = apply_metavar_fix(
                        rule.fix.search, rule.fix.replace, captures,
                    )
                    suggested_fix = f"{sf_search} → {sf_replace}"
                else:
                    suggested_fix = f"{rule.fix.search} → {rule.fix.replace}"

            rel_path = file_path
            if project_dir:
                try:
                    rel_path = os.path.relpath(file_path, project_dir)
                except ValueError:
                    pass

            findings.append(EnrichedFinding(
                rule_id=rule.qualified_id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                confidence=rule.confidence,
                file=rel_path,
                line=line_no,
                code_snippet=snippet,
                description=description,
                explanation=rule.explanation,
                recommendation=rule.recommendation,
                examples=list(rule.examples),
                suggested_fix=suggested_fix,
                captures=captures,
                cwe=rule.cwe,
                pack=rule.pack,
                tags=list(rule.tags),
            ))
    return findings


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

    # ----- Tier 2: structural rules via ast-grep --------------------------
    structural_rules = [
        r for r in rules
        if r.tier == RuleTier.STRUCTURAL and r.structural_pattern
    ]
    if structural_rules:
        if _ast_grep_available():
            files_by_lang: dict[str, list[str]] = {}
            for fp in files:
                lang = detect_language(fp)
                if lang:
                    files_by_lang.setdefault(lang, []).append(fp)
            for rule in structural_rules:
                findings.extend(_execute_structural_rule(
                    rule, files_by_lang, project_dir=project_dir,
                ))
        else:
            logger.info(
                "ast-grep not on PATH; skipping %d structural rule(s). "
                "Install with: cargo install ast-grep || brew install ast-grep",
                len(structural_rules),
            )

    # Pre-group rules by language for fast lookup. Tier-1 rules always run
    # here; Tier-2 (structural) rules also run here as a regex fallback
    # for languages where ast-grep can't help — either because the language
    # has no ast-grep grammar, or because the binary is missing entirely.
    # Roadmap Phase 1: "Fallback to regex Tier 1 for languages without
    # ast-grep grammars".
    ast_grep_ok = _ast_grep_available()
    lang_rules: dict[str, list[UnifiedRule]] = {}
    universal_rules: list[UnifiedRule] = []

    for rule in rules:
        if rule.pattern is None and rule.composite_pattern is None:
            continue  # no executable pattern

        regex_langs: list[str]
        if rule.tier == RuleTier.REGEX:
            regex_langs = list(rule.languages)
            regex_universal = not rule.languages
        elif rule.tier == RuleTier.STRUCTURAL:
            # Only run the regex fallback when ast-grep can't cover the rule.
            if ast_grep_ok:
                if not rule.languages:
                    continue  # universal structural — ast-grep handled it
                regex_langs = [
                    lang for lang in rule.languages
                    if lang not in _AST_GREP_LANGS
                ]
                regex_universal = False
                if not regex_langs:
                    continue
            else:
                # ast-grep missing — fall back to regex everywhere the rule
                # was meant to apply.
                regex_langs = list(rule.languages)
                regex_universal = not rule.languages
        else:
            continue  # plugin tier

        if regex_universal:
            universal_rules.append(rule)
        else:
            for lang in regex_langs:
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
