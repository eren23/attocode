"""Metavariable support for regex-tier rules.

Translates Semgrep-style ``$VAR`` placeholders in pattern strings into
named capture groups, enabling extraction of matched fragments and
template-based autofix.

Metavariable type inference:
    $FUNC, $NAME, $VAR, $IDENT  ->  identifier (``\\w+``)
    $ARG, $EXPR, $VALUE         ->  expression within parens (``[^,)]+``)
    $STR                        ->  string literal (``["'][^"']*["']``)
    $NUM                        ->  number (``\\d+(?:\\.\\d+)?``)
    $TYPE                       ->  type annotation (``[\\w.\\[\\]]+``)
    $...                        ->  any (non-capturing ``.*?``)
    All others                  ->  identifier (``\\w+``)
"""

from __future__ import annotations

import re

# Pattern that matches $IDENTIFIER tokens in a rule pattern string
_METAVAR_RE = re.compile(r"\$(\.\.\.|[A-Z_][A-Z0-9_]*)")

# Named groups map — root names (no numeric suffix) to regex fragment
_TYPE_FRAGMENTS: dict[str, str] = {
    "FUNC": r"\w+",
    "NAME": r"\w+",
    "VAR": r"\w+",
    "IDENT": r"\w+",
    "ARG": r"[^,)]+",
    "EXPR": r".+?",
    "VALUE": r"[^,)]+",
    "STR": r"""["'][^"']*["']""",
    "NUM": r"\d+(?:\.\d+)?",
    "TYPE": r"[\w.\[\]]+",
}

# Default regex for any $X not in _TYPE_FRAGMENTS
_DEFAULT_FRAGMENT = r"\w+"

# Comparison operators for metavariable-comparison constraints
_CMP_OPS = {
    ">": float.__gt__, ">=": float.__ge__,
    "<": float.__lt__, "<=": float.__le__,
    "==": float.__eq__, "!=": float.__ne__,
}


def _infer_fragment(name: str) -> str:
    """Infer the regex fragment for a metavariable name.

    Strips trailing digits to find the root type hint:
    ``$FUNC2`` -> root ``FUNC`` -> ``\\w+``.
    """
    root = name.rstrip("0123456789")
    return _TYPE_FRAGMENTS.get(root, _DEFAULT_FRAGMENT)


def has_metavars(pattern_str: str) -> bool:
    """Return True if *pattern_str* contains any ``$VAR`` metavariable tokens."""
    return bool(_METAVAR_RE.search(pattern_str))


def compile_metavar_pattern(
    pattern_str: str,
) -> tuple[re.Pattern[str], list[str]]:
    """Compile a pattern string with ``$VAR`` metavariables into a regex.

    Returns:
        (compiled_regex, metavar_names) where *metavar_names* lists the
        metavariable names in order of appearance (``"..."`` for ellipsis).
    """
    metavar_names: list[str] = []
    seen: set[str] = set()
    pos = 0
    parts: list[str] = []

    for m in _METAVAR_RE.finditer(pattern_str):
        # Escape the literal text between the previous match end and this match start
        parts.append(re.escape(pattern_str[pos:m.start()]))
        pos = m.end()

        token = m.group(1)  # e.g. "FUNC", "...", "ARG2"

        if token == "...":
            parts.append(r".*?")
            metavar_names.append("...")
        elif token in seen:
            # Back-reference — must match the same text as the first occurrence
            parts.append(rf"(?P={token})")
            metavar_names.append(token)
        else:
            fragment = _infer_fragment(token)
            parts.append(rf"(?P<{token}>{fragment})")
            metavar_names.append(token)
            seen.add(token)

    # Trailing literal after the last metavar
    parts.append(re.escape(pattern_str[pos:]))

    combined = "".join(parts)
    return re.compile(combined), metavar_names


def interpolate_message(template: str, captures: dict[str, str]) -> str:
    """Substitute ``$VAR`` references in a message template with captured values."""
    def _replace(m: re.Match[str]) -> str:
        token = m.group(1)
        if token == "...":
            return "$..."
        return captures.get(token, m.group(0))

    return _METAVAR_RE.sub(_replace, template)


def apply_metavar_fix(
    search_template: str,
    replace_template: str,
    captures: dict[str, str],
) -> tuple[str, str]:
    """Resolve ``$VAR`` references in autofix search/replace templates.

    Returns:
        (concrete_search, concrete_replace) with metavariables substituted.
    """
    return (
        interpolate_message(search_template, captures),
        interpolate_message(replace_template, captures),
    )


# ---------------------------------------------------------------------------
# Metavariable constraints (post-match filters)
# ---------------------------------------------------------------------------


def check_metavar_constraints(
    captures: dict[str, str],
    metavar_regex: dict[str, str] | None = None,
    metavar_comparison: dict[str, str] | None = None,
) -> bool:
    """Evaluate metavariable constraints against captured values.

    Args:
        captures: Captured metavar values from a regex match.
        metavar_regex: Map of ``$VAR`` name to regex that the captured
            value must match (e.g. ``{"FUNC": "^(query|execute)$"}``).
        metavar_comparison: Map of ``$VAR`` name to comparison expression
            (e.g. ``{"NUM": "> 1000"}``). Only numeric comparisons supported.

    Returns:
        True if all constraints pass (or no constraints given).
    """
    if metavar_regex:
        for var, regex_str in metavar_regex.items():
            name = var.lstrip("$")
            val = captures.get(name, "")
            if not re.search(regex_str, val):
                return False

    if metavar_comparison:
        for var, expr in metavar_comparison.items():
            name = var.lstrip("$")
            val = captures.get(name, "")
            try:
                num = float(val)
            except (ValueError, TypeError):
                return False
            # Parse operator + value from expr like "> 1000" or "<= 5"
            cmp_match = re.match(r"([<>!=]+)\s*(-?\d+(?:\.\d+)?)", expr.strip())
            if not cmp_match:
                return False
            op, threshold_str = cmp_match.group(1), cmp_match.group(2)
            threshold = float(threshold_str)
            op_fn = _CMP_OPS.get(op)
            if op_fn is None:
                return False  # unrecognized operator — fail closed
            if not op_fn(num, threshold):
                return False

    return True
