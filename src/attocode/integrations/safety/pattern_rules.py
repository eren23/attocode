"""Pattern-based tool permission rules — the CC-style permission system.

Extends the base PolicyEngine with fnmatch-style pattern matching on
both tool names AND input arguments. This replaces the simple regex
matching in the base engine.

Rule format:
    tool_pattern[?arg_pattern]  decision  [danger_level]

Examples:
    git *                       allow   safe
    bash(npm *)                 allow   low
    bash(rm -rf *)              deny    critical
    bash(curl *)                prompt  medium
    write_file(path:src/**)    allow   low
    edit_file(path:tests/**)   prompt  low

The argument pattern is optional and checked against the JSON representation
of tool arguments when present.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Any

from attocode.types.messages import DangerLevel

from .policy_engine import PolicyDecision, PolicyResult


@dataclass(slots=True)
class PatternRule:
    """A permission rule with fnmatch-style tool pattern and optional arg pattern.

    Format: ``tool_pattern[?arg_pattern]``

    The tool_pattern uses fnmatch (glob) syntax. The optional arg_pattern
    is checked against the JSON-serialized arguments.

    Examples:
        "bash"                     → all bash calls
        "bash?command=rm *"        → bash where command matches "rm *"
        "write_file?path=src/**"  → writes to files under src/
        "bash?command=sudo *"     → sudo commands (always high risk)
    """

    tool_pattern: str  # fnmatch pattern for tool name
    decision: PolicyDecision
    danger_level: DangerLevel = DangerLevel.SAFE
    arg_pattern: str = ""  # Optional fnmatch pattern for JSON args
    description: str = ""  # Human-readable description
    source: str = "default"  # Where this rule came from: default, user, project

    # Compiled patterns for performance (set after __post_init__)
    _tool_re: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _arg_re: re.Pattern[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Parse tool?arg pattern — extract tool name and arg pattern
        # If arg_pattern is not already set, extract it from tool_pattern
        tool_raw = self.tool_pattern
        arg_raw = self.arg_pattern
        if "?" in tool_raw and not arg_raw:
            # "bash?command:rm *" → tool="bash", arg="command:rm *"
            idx = tool_raw.index("?")
            tool_raw, arg_raw = tool_raw[:idx], tool_raw[idx + 1:]
            self.arg_pattern = arg_raw  # persist extracted arg pattern

        # Convert fnmatch to regex for tool pattern
        tool_regex = "^" + fnmatch.translate(tool_raw) + "$"
        try:
            self._tool_re = re.compile(tool_regex, re.IGNORECASE)
        except re.error:
            self._tool_re = re.compile(re.escape(tool_raw), re.IGNORECASE)

        if arg_raw:
            # For argument patterns, we use fnmatch on the serialized JSON
            # The pattern should match against the JSON string representation
            arg_regex = "^" + fnmatch.translate(arg_raw) + "$"
            try:
                self._arg_re = re.compile(arg_regex, re.IGNORECASE)
            except re.error:
                self._arg_re = re.compile(re.escape(arg_raw), re.IGNORECASE)

    @property
    def _arg_field_name(self) -> str | None:
        """Return the field name if arg_pattern uses field:value syntax."""
        if self.arg_pattern and ":" in self.arg_pattern:
            return self.arg_pattern.split(":", 1)[0]
        return None

    def matches_tool(self, tool_name: str) -> bool:
        """Check if this rule's tool pattern matches tool_name."""
        if self._tool_re is None:
            return False
        return bool(self._tool_re.match(tool_name))

    def matches_args(self, arguments: dict[str, Any] | None) -> bool:
        """Check if this rule's arg pattern matches the given arguments.

        Supports two formats:
        1. Raw fnmatch pattern against JSON-serialized args (no colon)
        2. field:value syntax: extracts field from args and fnmatch the value

        Examples:
            "command:rm *"      → matches args["command"] matching "rm *"
            "path:src/**"       → matches args["path"] matching "src/**"
            "*.py"              → matches JSON string containing ".py"
        """
        if not self.arg_pattern:
            return True  # No arg constraint → matches all
        if arguments is None:
            return False

        # Field:value syntax: extract field from args
        if self._arg_field_name:
            field_name = self._arg_field_name
            _, value_pattern = self.arg_pattern.split(":", 1)
            field_value = arguments.get(field_name)
            if field_value is None:
                return False
            # Normalize: trailing space in pattern → "followed by args" (append *)
            if value_pattern.endswith(" ") and not value_pattern.endswith(" *"):
                value_pattern += "*"
            value_str = str(field_value)
            return fnmatch.fnmatch(value_str, value_pattern)

        # Raw fnmatch against JSON-serialized args
        if self._arg_re is None:
            return False
        try:
            serialized = json.dumps(arguments, sort_keys=True, default=str)
            return bool(self._arg_re.search(serialized))
        except (TypeError, ValueError):
            return False
            return bool(self._arg_re.search(serialized))
        except (TypeError, ValueError):
            return False

    def matches(self, tool_name: str, arguments: dict[str, Any] | None) -> bool:
        """Full match: tool pattern AND (if present) argument pattern."""
        return self.matches_tool(tool_name) and self.matches_args(arguments)


# =============================================================================
# Rule compilation utilities
# =============================================================================


def compile_pattern_rule(line: str, source: str = "user") -> PatternRule | None:
    """Compile a single rule line into a PatternRule.

    Format: ``tool_pattern[?arg_pattern]  decision  [danger_level] [# description]``

    Examples:
        git *                       allow   safe
        bash(npm *)                 allow   low
        bash(rm -rf /)              deny    critical
        bash(sudo *)                prompt  medium
        write_file(path:src/**/*.py) allow low

    The arg_pattern uses field:value syntax for readability.
    E.g., ``bash(command:curl *)`` matches bash commands starting with "curl ".
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Strip inline comments
    if "# " in line and not line.startswith("#"):
        line = line.split("# ")[0].strip()

    # Parse: tool_pattern decision [danger_level]
    # The tool_pattern can contain spaces (e.g. bash commands like "rm -rf /").
    # Strategy: find the decision keyword as a word-bounded token, everything
    # before it is the tool pattern, the word after is the danger level (optional).
    import re as _re

    # Find decision keyword bounded by whitespace or string start/end
    m = _re.search(r"(?<![^\s])(\ballow\b|\bdeny\b|\bprompt\b)(?![^\s])", line)
    if not m:
        return None
    decision_str = m.group(1)
    decision_pos = m.start()

    tool_pattern = line[:decision_pos].strip()

    # After the decision, the next word is the danger level (if valid)
    danger_str = "medium"
    after_decision = line[m.end():].strip()
    if after_decision:
        first_after = after_decision.split()[0].lower()
        if first_after in ("safe", "low", "medium", "high", "critical"):
            danger_str = first_after

    # Parse arg pattern from tool_pattern if present
    arg_pattern = ""
    if "?" in tool_pattern:
        idx = tool_pattern.index("?")
        tool_part, arg_part = tool_pattern[:idx], tool_pattern[idx + 1:]
        tool_pattern = tool_part
        # Parse field:value format — kept as-is for matches_args to handle
        if ":" in arg_part:
            arg_pattern = arg_part  # "command:rm -rf /" stored directly
        else:
            arg_pattern = arg_part

    # Validate decision
    decision_map = {
        "allow": PolicyDecision.ALLOW,
        "deny": PolicyDecision.DENY,
        "prompt": PolicyDecision.PROMPT,
    }
    danger_map = {
        "safe": DangerLevel.SAFE,
        "low": DangerLevel.LOW,
        "medium": DangerLevel.MEDIUM,
        "high": DangerLevel.HIGH,
        "critical": DangerLevel.CRITICAL,
    }

    return PatternRule(
        tool_pattern=tool_pattern,
        decision=decision_map[decision_str],
        danger_level=danger_map[danger_str],
        arg_pattern=arg_pattern,
        source=source,
    )


# =============================================================================
# Default rules (CC-style tool allowlists)
# =============================================================================

DEFAULT_PATTERN_RULES: list[PatternRule] = [
    # Read-only tools — always safe
    PatternRule("read_file", PolicyDecision.ALLOW, DangerLevel.SAFE,
                 description="File reads are always allowed"),
    PatternRule("glob*", PolicyDecision.ALLOW, DangerLevel.SAFE,
                 description="Glob search is always allowed"),
    PatternRule("grep", PolicyDecision.ALLOW, DangerLevel.SAFE,
                 description="Grep is always allowed"),
    PatternRule("list_files", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("lsp_definition", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("lsp_references", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("lsp_hover", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("lsp_diagnostics", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("lsp_call_hierarchy", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("semantic_search", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("codebase_overview", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("get_repo_map", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("explore_codebase", PolicyDecision.ALLOW, DangerLevel.SAFE),

    # Write tools — always allowed (with workspace boundary enforcement elsewhere)
    PatternRule("write_file", PolicyDecision.ALLOW, DangerLevel.LOW),
    PatternRule("edit_file", PolicyDecision.ALLOW, DangerLevel.LOW),
    PatternRule("create_file", PolicyDecision.ALLOW, DangerLevel.LOW),
    PatternRule("patch_file", PolicyDecision.ALLOW, DangerLevel.LOW),

    # Bash — categorized by command pattern
    # ORDER MATTERS: deny > prompt > allow (first match wins).
    # Destructive bash — always denied
    PatternRule("bash?command:rm -rf /", PolicyDecision.DENY, DangerLevel.CRITICAL,
                 description="Root deletion is always blocked"),
    PatternRule("bash?command:rm -rf /*", PolicyDecision.DENY, DangerLevel.CRITICAL),
    PatternRule("bash?command:dd if=*of=/dev/", PolicyDecision.DENY, DangerLevel.CRITICAL,
                 description="Direct disk writes are blocked"),
    PatternRule("bash?command:mkfs", PolicyDecision.DENY, DangerLevel.CRITICAL),
    PatternRule("bash?command:sudo su", PolicyDecision.DENY, DangerLevel.CRITICAL,
                 description="Privilege escalation blocked"),
    PatternRule("bash?command:>:", PolicyDecision.DENY, DangerLevel.CRITICAL,
                 description="/dev/null overwrite is blocked"),

    # Medium/high-risk bash — prompt
    PatternRule("bash?command:curl *|sh", PolicyDecision.PROMPT, DangerLevel.HIGH,
                 description="Pipe to shell is blocked"),
    PatternRule("bash?command:wget *|sh", PolicyDecision.PROMPT, DangerLevel.HIGH),
    PatternRule("bash?command:sudo ", PolicyDecision.PROMPT, DangerLevel.MEDIUM,
                 description="sudo requires confirmation"),
    PatternRule("bash?command:chmod 777", PolicyDecision.PROMPT, DangerLevel.HIGH,
                 description="World-writable permissions are risky"),
    PatternRule("bash?command:git reset --hard", PolicyDecision.PROMPT, DangerLevel.HIGH,
                 description="Hard reset is destructive"),

    # Safe commands — allow
    PatternRule("bash?command:git ", PolicyDecision.ALLOW, DangerLevel.SAFE,
                 description="git commands are safe"),
    PatternRule("bash?command:npm test", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:npm run ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:pytest ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:python -m ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:make ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:cargo ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:go run ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:ls ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:pwd", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:cat ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:head ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:tail ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:grep ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:find ", PolicyDecision.ALLOW, DangerLevel.SAFE),
    PatternRule("bash?command:curl ", PolicyDecision.ALLOW, DangerLevel.LOW,
                 description="curl is low risk for GET requests"),
    PatternRule("bash?command:wget ", PolicyDecision.ALLOW, DangerLevel.LOW),

    # MCP tools — need approval
    PatternRule("mcp_*", PolicyDecision.PROMPT, DangerLevel.MEDIUM,
                 description="MCP tools require approval (external services)"),
]


# =============================================================================
# PatternRuleEngine
# =============================================================================


class PatternRuleEngine:
    """Permission engine using fnmatch pattern rules.

    Extends the base PolicyEngine with pattern matching. Rules are evaluated
    in order (first match wins). User rules override default rules.
    """

    def __init__(
        self,
        user_rules: list[PatternRule] | None = None,
        default_rules: list[PatternRule] | None = None,
    ) -> None:
        self._rules: list[PatternRule] = list(default_rules or DEFAULT_PATTERN_RULES)
        self._user_rules: list[PatternRule] = list(user_rules or [])
        self._approved: dict[str, set[str]] = {}  # tool → set of approved arg sigs

    def add_user_rule(self, rule: PatternRule) -> None:
        """Add a user rule (takes precedence over defaults)."""
        self._user_rules.append(rule)

    def add_rules_from_lines(self, lines: str, source: str = "project") -> int:
        """Parse rule lines and add them as user rules. Returns count added."""
        count = 0
        for line in lines.splitlines():
            rule = compile_pattern_rule(line, source=source)
            if rule:
                self._user_rules.append(rule)
                count += 1
        return count

    def load_from_file(self, path: str) -> int:
        """Load rules from a file. Returns count added."""
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            return self.add_rules_from_lines(content, source="project")
        except OSError:
            return 0

    def approve(self, tool_name: str, arg_sig: str = "*") -> None:
        """Mark a tool+args as pre-approved."""
        if tool_name not in self._approved:
            self._approved[tool_name] = set()
        self._approved[tool_name].add(arg_sig)

    def is_approved(self, tool_name: str, arg_sig: str = "*") -> bool:
        """Check if tool+args is pre-approved."""
        sigs = self._approved.get(tool_name, set())
        return "*" in sigs or arg_sig in sigs

    def _serialize_args(self, args: dict[str, Any] | None) -> str:
        """Serialize args for signature matching."""
        if args is None:
            return "{}"
        try:
            return json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(args)

    def evaluate(self, tool_name: str, args: dict[str, Any] | None) -> PolicyResult:
        """Evaluate a tool call against pattern rules.

        Checks in order:
        1. Pre-approved commands (from "Always Allow" grants)
        2. User rules (loaded from files/env)
        3. Default rules
        4. Fallback: prompt for unknown tools
        """
        # 1. Check pre-approved
        if self.is_approved(tool_name, self._serialize_args(args)):
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                danger_level=DangerLevel.SAFE,
                reason="Pre-approved command",
                tool_name=tool_name,
            )

        # 2. User rules
        for rule in self._user_rules:
            if rule.matches(tool_name, args):
                return PolicyResult(
                    decision=rule.decision,
                    danger_level=rule.danger_level,
                    reason=rule.description or f"Matched rule: {rule.tool_pattern}",
                    tool_name=tool_name,
                )

        # 3. Default rules
        for rule in self._rules:
            if rule.matches(tool_name, args):
                return PolicyResult(
                    decision=rule.decision,
                    danger_level=rule.danger_level,
                    reason=rule.description or f"Default rule: {rule.tool_pattern}",
                    tool_name=tool_name,
                )

        # 4. Fallback
        return PolicyResult(
            decision=PolicyDecision.PROMPT,
            danger_level=DangerLevel.MEDIUM,
            reason=f"Unknown tool '{tool_name}' requires approval",
            tool_name=tool_name,
        )

    @property
    def all_rules(self) -> list[PatternRule]:
        """All rules (user + default) for inspection."""
        return self._user_rules + self._rules
