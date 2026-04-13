"""Boolean pattern combinators for composite rule matching.

Enables Semgrep-style ``pattern-either``, ``pattern-not``, and
``pattern-inside`` composition without requiring AST parsing.

All combinators operate on a ``MatchContext`` that provides the
current line, surrounding lines, and file content for scope analysis.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from attocode.code_intel.rules.metavar import compile_metavar_pattern, has_metavars


# ---------------------------------------------------------------------------
# Match context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MatchContext:
    """Context passed to pattern nodes during evaluation."""

    line: str  # current line being evaluated
    line_no: int  # 1-based line number
    all_lines: list[str]  # full file content (0-indexed)
    captures: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pattern node hierarchy
# ---------------------------------------------------------------------------


class PatternNode(ABC):
    """Abstract base for all pattern nodes in a composite rule."""

    @abstractmethod
    def evaluate(self, ctx: MatchContext) -> bool:
        """Return True if this pattern matches in the given context."""


@dataclass(slots=True)
class RegexNode(PatternNode):
    """Matches a single line against a compiled regex."""

    pattern: re.Pattern[str]
    metavar_names: list[str] = field(default_factory=list)

    def evaluate(self, ctx: MatchContext) -> bool:
        m = self.pattern.search(ctx.line)
        if m and self.metavar_names:
            ctx.captures.update(
                {k: v for k, v in m.groupdict().items() if v is not None}
            )
        return bool(m)


@dataclass(slots=True)
class EitherNode(PatternNode):
    """OR combinator — matches if ANY child matches."""

    children: list[PatternNode]

    def evaluate(self, ctx: MatchContext) -> bool:
        return any(child.evaluate(ctx) for child in self.children)


@dataclass(slots=True)
class AllNode(PatternNode):
    """AND combinator — matches if ALL children match the same line."""

    children: list[PatternNode]

    def evaluate(self, ctx: MatchContext) -> bool:
        return all(child.evaluate(ctx) for child in self.children)


@dataclass(slots=True)
class NotNode(PatternNode):
    """Negation — matches if the child does NOT match the current line."""

    child: PatternNode

    def evaluate(self, ctx: MatchContext) -> bool:
        return not self.child.evaluate(ctx)


# Function definition patterns — used as scope boundaries
_FUNC_DEF_RE = re.compile(
    r"^(?:def |func |function |fn |"
    r"(?:public|private|protected|internal)\s+(?:static\s+)?\w+\s+\w+\(|"
    r"(?:export\s+)?(?:async\s+)?function\s)"
)


def _indent_level(line: str) -> int:
    """Return the number of leading whitespace characters."""
    return len(line) - len(line.lstrip())


@dataclass(slots=True)
class InsideNode(PatternNode):
    """Scope constraint — matches only if a scope pattern is found above.

    Scans backward from the current line looking for a line that matches
    the scope pattern within ``max_distance`` lines. Uses two heuristics
    to avoid cross-scope false positives:

    1. The scope line must have *less* indentation than the current line
       (the current line is "inside" the scope block).
    2. Scanning stops at function definition boundaries to prevent
       matching scope patterns from preceding functions.
    """

    scope_pattern: re.Pattern[str]
    max_distance: int = 50

    def evaluate(self, ctx: MatchContext) -> bool:
        cur_indent = _indent_level(ctx.line)
        start = max(0, ctx.line_no - 1 - self.max_distance)
        end = ctx.line_no - 1  # exclude current line (0-indexed)
        for i in range(end - 1, start - 1, -1):
            scan_line = ctx.all_lines[i]
            stripped = scan_line.strip()
            if not stripped:
                continue

            # Check scope pattern BEFORE function boundary
            # (the func def line itself may be the scope pattern)
            if self.scope_pattern.search(scan_line):
                if _indent_level(scan_line) < cur_indent:
                    return True

            # Stop at function boundaries (different scope)
            if _FUNC_DEF_RE.match(stripped):
                return False
        return False


@dataclass(slots=True)
class NotInsideNode(PatternNode):
    """Inverse scope — matches only if the scope pattern is NOT found above."""

    scope_pattern: re.Pattern[str]
    max_distance: int = 50

    def evaluate(self, ctx: MatchContext) -> bool:
        cur_indent = _indent_level(ctx.line)
        start = max(0, ctx.line_no - 1 - self.max_distance)
        end = ctx.line_no - 1
        for i in range(end - 1, start - 1, -1):
            scan_line = ctx.all_lines[i]
            stripped = scan_line.strip()
            if not stripped:
                continue
            # Check scope pattern BEFORE function boundary
            # (the func def line itself may be the scope pattern)
            if self.scope_pattern.search(scan_line):
                if _indent_level(scan_line) < cur_indent:
                    return False
            if _FUNC_DEF_RE.match(stripped):
                return True  # hit function boundary — not inside
        return True


# ---------------------------------------------------------------------------
# Composite pattern (wraps primary + constraints)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CompositePattern:
    """A primary pattern with boolean constraints.

    The primary pattern must match the current line. Then all constraints
    (pattern-not, pattern-inside, pattern-not-inside) are evaluated.
    All constraints must pass for the composite to match.
    """

    primary: PatternNode
    constraints: list[PatternNode] = field(default_factory=list)

    def evaluate(self, ctx: MatchContext) -> bool:
        if not self.primary.evaluate(ctx):
            return False
        return all(c.evaluate(ctx) for c in self.constraints)


# ---------------------------------------------------------------------------
# Builder — parses YAML structure into pattern tree
# ---------------------------------------------------------------------------


def _compile_pattern(pattern_str: str) -> tuple[re.Pattern[str], list[str]]:
    """Compile a pattern string, handling metavariables if present."""
    if has_metavars(pattern_str):
        return compile_metavar_pattern(pattern_str)
    return re.compile(pattern_str), []


def build_composite_from_yaml(data: list[dict] | dict) -> CompositePattern | None:
    """Build a CompositePattern from YAML ``patterns`` structure.

    Supported YAML keys within the patterns list:
        - ``pattern``: primary regex (first one found becomes primary)
        - ``pattern-either``: list of alternative patterns (becomes primary)
        - ``pattern-not``: line must NOT match this regex
        - ``pattern-inside``: a scope pattern must exist above the current line
        - ``pattern-not-inside``: a scope pattern must NOT exist above

    Example YAML:
        patterns:
          - pattern: 'fmt\\.Sprintf\\s*\\('
          - pattern-inside: 'for\\s.*\\{'
          - pattern-not: '// nolint'
    """
    if isinstance(data, dict):
        # Single pattern-either at top level
        if "pattern-either" in data:
            either_pats = data["pattern-either"]
            if not isinstance(either_pats, list):
                return None
            children = []
            all_metavars: list[str] = []
            for p in either_pats:
                pat_str = str(p)
                compiled, mvars = _compile_pattern(pat_str)
                children.append(RegexNode(pattern=compiled, metavar_names=mvars))
                all_metavars.extend(mvars)
            return CompositePattern(primary=EitherNode(children=children))
        return None

    if not isinstance(data, list):
        return None

    primary: PatternNode | None = None
    constraints: list[PatternNode] = []
    all_metavars: list[str] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        if "pattern" in item:
            pat_str = str(item["pattern"])
            compiled, mvars = _compile_pattern(pat_str)
            if primary is None:
                primary = RegexNode(pattern=compiled, metavar_names=mvars)
                all_metavars.extend(mvars)
            else:
                # Additional patterns act as AND constraints
                constraints.append(RegexNode(pattern=compiled, metavar_names=mvars))

        elif "pattern-either" in item:
            either_pats = item["pattern-either"]
            if isinstance(either_pats, list):
                children = []
                for p in either_pats:
                    c, mv = _compile_pattern(str(p))
                    children.append(RegexNode(pattern=c, metavar_names=mv))
                    all_metavars.extend(mv)
                node = EitherNode(children=children)
                if primary is None:
                    primary = node
                else:
                    constraints.append(node)

        elif "pattern-not" in item:
            pat_str = str(item["pattern-not"])
            compiled, mvars = _compile_pattern(pat_str)
            constraints.append(NotNode(child=RegexNode(pattern=compiled, metavar_names=mvars)))

        elif "pattern-inside" in item:
            pat_str = str(item["pattern-inside"])
            compiled, _ = _compile_pattern(pat_str)
            max_dist = int(item.get("max-distance", 50))
            constraints.append(InsideNode(scope_pattern=compiled, max_distance=max_dist))

        elif "pattern-not-inside" in item:
            pat_str = str(item["pattern-not-inside"])
            compiled, _ = _compile_pattern(pat_str)
            max_dist = int(item.get("max-distance", 50))
            constraints.append(NotInsideNode(scope_pattern=compiled, max_distance=max_dist))

    if primary is None:
        return None

    return CompositePattern(primary=primary, constraints=constraints)
