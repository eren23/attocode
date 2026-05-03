"""Rule synthesis from positive / negative code samples.

Two paths:

* **Deterministic regex synthesis** — find the longest common contiguous
  substring across positives, escape + word-boundary it, then validate
  it doesn't match any negative. Cheap, no API needed, surprisingly
  effective for shape-based patterns ("any call to ``eval``", "import
  of a deprecated module", etc.).
* **LLM-assisted synthesis** — when the deterministic path can't find a
  precise enough anchor, fall back to Claude. The prompt feeds samples
  + description + language; the response is parsed as attocode YAML and
  validated against the same samples before being accepted.

Public entry points:

* :func:`synthesize_rule` — top-level dispatch (``mode="auto"|"regex"|"llm"``)
* :func:`synthesize_regex_rule` — deterministic only

Both return a :class:`SynthesisResult` with the candidate rule (or None)
plus diagnostic messages explaining what was tried.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)

logger = logging.getLogger(__name__)


# Length floor for the longest common substring before we accept it as a
# regex anchor. Below this we'd be matching common English/code fragments
# (e.g. "if ", "()") and producing high-FP rules.
DEFAULT_MIN_ANCHOR_LEN = 3


@dataclass(slots=True)
class SynthesisResult:
    """Outcome of a synthesis attempt — None rule means nothing usable."""

    rule: UnifiedRule | None
    method: str  # "regex" | "llm" | "none"
    diagnostics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic regex synthesis
# ---------------------------------------------------------------------------


def _lcs_2way(a: str, b: str) -> str:
    """Longest common contiguous substring of two strings (classic DP)."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return ""
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    end_i = max_len = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                if dp[i][j] > max_len:
                    max_len = dp[i][j]
                    end_i = i
    return a[end_i - max_len:end_i]


def _lcs_across(strings: list[str]) -> str:
    """N-way longest common substring via pairwise reduction."""
    if not strings:
        return ""
    if len(strings) == 1:
        return strings[0]
    base = strings[0]
    for s in strings[1:]:
        base = _lcs_2way(base, s)
        if not base:
            return ""
    return base


def _is_word_char(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch == "_")


def _build_regex_pattern(common: str, positives: list[str] | None = None) -> str:
    """``re.escape`` plus word boundaries when they're safe to add.

    We only attach ``\\b`` at an edge that is a word character AND whose
    actual neighbour in every positive sample is either out-of-string or
    a non-word character. Otherwise ``\\b`` would prevent the pattern
    from matching its own positives (e.g. anchor ``xy_`` followed by
    another word char like ``a`` has no boundary between them).
    """
    pat = re.escape(common)
    add_leading = False
    add_trailing = False

    if _is_word_char(common[:1]):
        if positives:
            add_leading = True
            for p in positives:
                idx = p.find(common)
                if idx > 0 and _is_word_char(p[idx - 1]):
                    add_leading = False
                    break
        else:
            add_leading = True

    if _is_word_char(common[-1:]):
        if positives:
            add_trailing = True
            for p in positives:
                idx = p.find(common)
                end = idx + len(common)
                if end < len(p) and _is_word_char(p[end]):
                    add_trailing = False
                    break
        else:
            add_trailing = True

    if add_leading:
        pat = r"\b" + pat
    if add_trailing:
        pat = pat + r"\b"
    return pat


def synthesize_regex_rule(
    positives: list[str],
    negatives: list[str],
    *,
    rule_id: str,
    language: str,
    description: str = "",
    min_anchor_len: int = DEFAULT_MIN_ANCHOR_LEN,
) -> tuple[UnifiedRule | None, list[str]]:
    """Build a regex rule from common shape across ``positives``.

    Returns ``(rule, diagnostics)``. ``rule`` is ``None`` when no anchor
    that satisfies both positives and negatives can be found.
    """
    diags: list[str] = []
    if not positives:
        diags.append("no positive samples provided")
        return None, diags

    common = _lcs_across(positives)
    if len(common) < min_anchor_len:
        diags.append(
            f"longest common substring ({len(common)} chars) below "
            f"min_anchor_len={min_anchor_len}"
        )
        return None, diags

    pattern_str = _build_regex_pattern(common, positives=positives)
    try:
        compiled = re.compile(pattern_str)
    except re.error as exc:
        diags.append(f"regex compile failed: {exc}")
        return None, diags

    failed_pos = [p for p in positives if not compiled.search(p)]
    if failed_pos:
        diags.append(
            f"synthesised pattern misses {len(failed_pos)}/{len(positives)} "
            "positive(s) — anchor escaped a multi-byte boundary"
        )
        return None, diags

    matched_neg = [n for n in negatives if compiled.search(n)]
    if matched_neg:
        diags.append(
            f"pattern matches {len(matched_neg)}/{len(negatives)} negative "
            "sample(s); common substring too generic for clean separation"
        )
        return None, diags

    rule = UnifiedRule(
        id=rule_id,
        name=rule_id,
        description=description or f"matches pattern {pattern_str}",
        severity=RuleSeverity.MEDIUM,
        category=RuleCategory.SUSPICIOUS,
        languages=[language] if language else [],
        pattern=compiled,
        source=RuleSource.USER,
        tier=RuleTier.REGEX,
        confidence=0.6,
    )
    diags.append(f"synthesised regex pattern: {pattern_str}")
    return rule, diags


# ---------------------------------------------------------------------------
# LLM-assisted synthesis
# ---------------------------------------------------------------------------


_LLM_SYNTH_PROMPT = """\
You generate a single static-analysis rule in attocode's YAML format.

Language: {language}
What this rule should detect: {description}

The rule MUST match every one of these positive samples (each is a single
line of code):
{positives}

The rule MUST NOT match any of these negative samples:
{negatives}

Output ONLY a YAML rule with these fields (no surrounding prose, no
markdown code fences):

- id: kebab-case identifier (use "{suggested_id}")
- message: short human-readable detection message
- severity: critical | high | medium | low | info
- category: correctness | suspicious | complexity | performance | style | security | deprecated
- languages: [{language}]
- pattern: a Python regex string. Use \\b word boundaries to avoid
  over-matching. Keep the pattern minimal — match only the dangerous
  shape, not the full samples literally.
"""


def _strip_code_fences(text: str) -> str:
    """Strip leading/trailing markdown fences if the LLM wrapped the YAML."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    # Drop the first fence line (```yaml or just ```)
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def _validate_llm_yaml(
    yaml_text: str,
    positives: list[str],
    negatives: list[str],
) -> tuple[UnifiedRule | None, list[str]]:
    """Parse + validate an LLM YAML response. Returns (rule, diagnostics).

    A response may contain one or several rules; we accept the first one
    that parses and matches all positives without matching any negative.
    """
    diags: list[str] = []
    try:
        import yaml
    except ImportError:
        return None, ["pyyaml not available — cannot parse LLM YAML"]

    from attocode.code_intel.rules.loader import _parse_yaml_rule

    cleaned = _strip_code_fences(yaml_text)
    try:
        data = yaml.safe_load(cleaned)
    except Exception as exc:
        return None, [f"YAML parse failed: {exc}"]

    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = [d for d in data if isinstance(d, dict)]
    else:
        return None, [f"YAML must be dict or list, got {type(data).__name__}"]

    if not items:
        return None, ["LLM response contained no parseable rules"]

    for i, item in enumerate(items):
        rule = _parse_yaml_rule(item, source=RuleSource.USER, origin=f"llm[{i}]")
        if rule is None:
            diags.append(f"rule[{i}]: loader rejected the YAML")
            continue
        if rule.pattern is None:
            diags.append(f"rule[{i}]: no regex pattern emitted")
            continue
        failed_pos = [p for p in positives if not rule.pattern.search(p)]
        matched_neg = [n for n in negatives if rule.pattern.search(n)]
        if failed_pos or matched_neg:
            diags.append(
                f"rule[{i}] failed validation: "
                f"{len(failed_pos)}/{len(positives)} positive miss, "
                f"{len(matched_neg)}/{len(negatives)} negative match"
            )
            continue
        diags.append(f"rule[{i}] validated against samples")
        return rule, diags

    diags.append("no LLM-generated rule passed validation")
    return None, diags


def _default_llm_caller(prompt: str) -> str:
    """Resolve the project's shared LLM client lazily — keeps the
    optional ``openai``/``anthropic`` import out of the import path for
    callers that only want the deterministic synthesizer.

    The default client lives under the dev-only ``eval/meta_harness/``
    tree, which isn't bundled with the installed wheel. When that path
    is unavailable we surface a clear error so the synthesizer's
    ``except`` arm can attach it as a diagnostic, instead of letting an
    opaque ``ModuleNotFoundError`` bubble out of the MCP tool.
    """
    try:
        from eval.meta_harness._llm_client import call_llm, load_env
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "LLM synthesis requested but no llm_caller was configured "
            "and the dev meta-harness client is not importable from this "
            "process. Pass llm_caller=... explicitly when calling "
            "synthesize_rule(mode='llm' or 'auto') from production."
        ) from exc

    load_env()
    return call_llm(prompt, max_tokens=2048)


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


def synthesize_rule(
    positives: list[str],
    negatives: list[str],
    *,
    language: str,
    rule_id: str = "synth-rule",
    description: str = "",
    mode: str = "auto",
    llm_caller: Callable[[str], str] | None = None,
) -> SynthesisResult:
    """Top-level synthesizer.

    ``mode``:
      * ``"regex"`` — deterministic regex only.
      * ``"llm"`` — call Claude only.
      * ``"auto"`` — try regex first; fall back to LLM if it fails.

    ``llm_caller`` overrides the default LLM client (for testing without
    network or to plug in a non-Claude provider).
    """
    diags: list[str] = []

    if mode not in ("regex", "llm", "auto"):
        return SynthesisResult(
            rule=None,
            method="none",
            diagnostics=[f"unknown mode {mode!r}"],
        )

    if mode in ("regex", "auto"):
        rule, regex_diags = synthesize_regex_rule(
            positives, negatives,
            rule_id=rule_id, language=language, description=description,
        )
        diags.extend(regex_diags)
        if rule is not None:
            return SynthesisResult(rule=rule, method="regex", diagnostics=diags)

    if mode in ("llm", "auto"):
        caller = llm_caller or _default_llm_caller
        prompt = _LLM_SYNTH_PROMPT.format(
            language=language,
            description=description or "(no description)",
            positives="\n".join(f"- {p!r}" for p in positives),
            negatives="\n".join(f"- {n!r}" for n in negatives) or "(none)",
            suggested_id=rule_id,
        )
        try:
            response = caller(prompt)
        except Exception as exc:
            diags.append(f"LLM call failed: {exc}")
            return SynthesisResult(rule=None, method="none", diagnostics=diags)

        rule, llm_diags = _validate_llm_yaml(response, positives, negatives)
        diags.extend(llm_diags)
        if rule is not None:
            return SynthesisResult(rule=rule, method="llm", diagnostics=diags)

    return SynthesisResult(rule=None, method="none", diagnostics=diags)


def render_rule_yaml(rule: UnifiedRule) -> str:
    """Render a synthesised rule as a YAML snippet ready to paste into a
    pack file. Order mirrors the convention used by the example packs."""
    lines = [f"- id: {rule.id}"]
    lines.append(f"  name: {rule.name}")
    if rule.description:
        # Quote the message; rule loader treats ``message`` as the canonical key.
        msg = rule.description.replace('"', '\\"')
        lines.append(f'  message: "{msg}"')
    if rule.pattern is not None:
        pat = rule.pattern.pattern.replace("'", "''")
        lines.append(f"  pattern: '{pat}'")
    if rule.structural_pattern:
        sp = rule.structural_pattern.replace("'", "''")
        lines.append(f"  structural_pattern: '{sp}'")
    lines.append(f"  severity: {rule.severity}")
    lines.append(f"  category: {rule.category}")
    if rule.languages:
        lines.append(f"  languages: [{', '.join(rule.languages)}]")
    lines.append(f"  confidence: {rule.confidence}")
    return "\n".join(lines)
