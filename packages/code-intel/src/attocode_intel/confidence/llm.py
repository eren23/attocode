"""LLM-based false positive classifier for rule findings.

Uses a fast LLM (Haiku) to classify findings as true positive or false
positive based on code context, rule description, and file purpose.
Inspired by the Datadog approach to agentic SAST triage.

Measured against the rule corpus this is the most precise scorer available
(P=0.96) and the worst calibrated (ECE=0.28) — a good gate, a poor probability.

Reference: https://www.datadoghq.com/blog/using-llms-to-filter-out-false-positives/
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from attocode_intel.confidence.redact import redact

# (prompt, model, max_tokens) -> completion text
LLMCaller = Callable[[str, str, int], str]

logger = logging.getLogger(__name__)

# Haiku for cost efficiency (~$0.01 per classification). The id differs by
# route, so "" means "let _cheap_model() pick for whichever key is present".
DEFAULT_MODEL = ""
_OPENROUTER_MODEL = "anthropic/claude-haiku-4.5"
_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
# Measured: still scaling at 32 (16.9x) — per-call latency is ~1.6s, so there
# is far more of it to hide than the noul head has.
_WORKERS = 32


def _default_llm_caller() -> LLMCaller:
    """The project's shared client. Only importable inside this repo."""
    try:
        from eval.meta_harness._llm_client import call_llm
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on checkout
        raise RuntimeError(
            "No LLM caller available. Pass llm_caller=..., or run inside the "
            "attocode repo where eval.meta_harness is importable."
        ) from exc

    def call(prompt: str, model: str, max_tokens: int) -> str:
        return call_llm(prompt, model=model, max_tokens=max_tokens)

    return call


def _load_env() -> None:
    """Populate keys from the project .env when running inside the repo."""
    try:
        from eval.meta_harness._llm_client import load_env
    except ModuleNotFoundError:  # pragma: no cover - depends on checkout
        return
    load_env()


def _cheap_model() -> str:
    """The Haiku id for whichever provider call_llm() will route to."""
    import os

    return _OPENROUTER_MODEL if os.environ.get("OPENROUTER_API_KEY") else _ANTHROPIC_MODEL


class FPVerdict(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    UNCERTAIN = "uncertain"


@dataclass(slots=True)
class FPClassification:
    """Result of LLM-based TP/FP classification."""

    rule_id: str
    file: str
    line: int
    verdict: FPVerdict
    confidence: float  # 0.0-1.0
    reasoning: str
    tokens_used: int = 0
    latency_ms: float = 0.0


_CLASSIFICATION_PROMPT = """\
You are a security code reviewer. Analyze whether the following static analysis finding is a TRUE POSITIVE (real security issue) or FALSE POSITIVE (benign code incorrectly flagged).

## Finding
- **Rule**: {rule_id}
- **Severity**: {severity}
- **Description**: {description}
- **CWE**: {cwe}
- **File**: {file}:{line}

## Code Context
```
{code_context}
```

## Matched Line
```
{matched_line}
```

## Rule Explanation
{explanation}

## Instructions
Determine if this is a true positive or false positive. Consider:
1. Is the flagged pattern actually exploitable in this context?
2. Is there input validation, sanitization, or other mitigation nearby?
3. Is this test code, example code, or documentation?
4. Could the value be controlled by an attacker?

Respond with EXACTLY this format (no other text):
VERDICT: TRUE_POSITIVE or FALSE_POSITIVE or UNCERTAIN
CONFIDENCE: 0.0 to 1.0
REASONING: one sentence explanation
"""


def classify_finding(
    rule_id: str,
    severity: str,
    description: str,
    cwe: str,
    file: str,
    line: int,
    matched_line: str,
    code_context: str,
    explanation: str = "",
    *,
    model: str = DEFAULT_MODEL,
    llm_caller: LLMCaller | None = None,
) -> FPClassification:
    """Classify a single finding as TP/FP using an LLM.

    Args:
        rule_id: The rule that produced the finding.
        severity: Finding severity.
        description: What was found.
        cwe: CWE identifier.
        file: Source file path.
        line: Line number.
        matched_line: The matched source line.
        code_context: ~30 lines of surrounding code.
        explanation: Rule explanation (why it matters).
        model: LLM model to use. Defaults to Haiku on whichever route is keyed.
        llm_caller: Override the provider call. Defaults to the project's
            shared client, which is only importable inside this repo.

    Returns:
        FPClassification with verdict, confidence, and reasoning.
    """
    import os
    import time

    _load_env()
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return FPClassification(
            rule_id=rule_id, file=file, line=line,
            verdict=FPVerdict.UNCERTAIN, confidence=0.0,
            reasoning="No API key available",
        )

    prompt = _CLASSIFICATION_PROMPT.format(
        rule_id=redact(rule_id),
        severity=redact(severity),
        description=redact(description)[:1000],
        cwe=redact(cwe or "N/A"),
        file=redact(file),
        line=line,
        code_context=redact(code_context)[:2000],
        matched_line=redact(matched_line)[:200],
        explanation=redact(explanation or description)[:2000],
    )

    start = time.monotonic()
    try:
        text = (llm_caller or _default_llm_caller())(
            prompt, model or _cheap_model(), 200,
        )
        elapsed = (time.monotonic() - start) * 1000
        # call_llm returns text only; token counts are not available on this path.
        return _parse_response(rule_id, file, line, text, 0, elapsed)

    except ImportError:
        return FPClassification(
            rule_id=rule_id, file=file, line=line,
            verdict=FPVerdict.UNCERTAIN, confidence=0.0,
            reasoning="LLM SDK not installed (need openai for OpenRouter)",
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return FPClassification(
            rule_id=rule_id, file=file, line=line,
            verdict=FPVerdict.UNCERTAIN, confidence=0.0,
            reasoning=f"API error: {exc}",
            latency_ms=elapsed,
        )


def _parse_response(
    rule_id: str, file: str, line: int,
    text: str, tokens: int, latency_ms: float,
) -> FPClassification:
    """Parse the LLM response into a classification."""
    verdict = FPVerdict.UNCERTAIN
    confidence = 0.5
    reasoning = text.strip()

    for resp_line in text.strip().splitlines():
        resp_line = resp_line.strip()
        if resp_line.startswith("VERDICT:"):
            v = resp_line.split(":", 1)[1].strip().upper()
            if "TRUE_POSITIVE" in v:
                verdict = FPVerdict.TRUE_POSITIVE
            elif "FALSE_POSITIVE" in v:
                verdict = FPVerdict.FALSE_POSITIVE
        elif resp_line.startswith("CONFIDENCE:"):
            try:
                confidence = float(resp_line.split(":", 1)[1].strip())
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                pass
        elif resp_line.startswith("REASONING:"):
            reasoning = resp_line.split(":", 1)[1].strip()

    return FPClassification(
        rule_id=rule_id,
        file=file,
        line=line,
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        tokens_used=tokens,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Batch classification for benchmark evaluation
# ---------------------------------------------------------------------------


def classify_findings_batch(
    findings_with_context: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    llm_caller: LLMCaller | None = None,
) -> list[FPClassification]:
    """Classify multiple findings in batch.

    Args:
        findings_with_context: List of dicts with keys matching
            classify_finding() parameters.
        model: LLM model.

    Returns:
        List of classifications, one per finding.
    """
    def one(f: dict[str, Any]) -> FPClassification:
        return classify_finding(
            rule_id=f.get("rule_id", ""),
            severity=f.get("severity", ""),
            description=f.get("description", ""),
            cwe=f.get("cwe", ""),
            file=f.get("file", ""),
            line=f.get("line", 0),
            matched_line=f.get("matched_line", ""),
            code_context=f.get("code_context", ""),
            explanation=f.get("explanation", ""),
            model=model,
            llm_caller=llm_caller,
        )

    # Concurrent so a wall-clock comparison against other scorers measures the
    # model, not this loop. map() preserves input order.
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return list(pool.map(one, findings_with_context))


# ---------------------------------------------------------------------------
# Scorer interface
# ---------------------------------------------------------------------------


def estimate(findings: list[Any], *, min_confidence: float) -> list[float | None]:
    """Return p(true positive) per finding, or None where the model had none.

    ``min_confidence`` is unused here: the classifier does not see the
    incumbent constant, unlike the jev scorer which records it for comparison.
    """
    if not findings:
        return []

    payload = [
        {
            "rule_id": getattr(f, "rule_id", ""),
            "severity": str(getattr(f, "severity", "")),
            "description": getattr(f, "description", ""),
            "cwe": getattr(f, "cwe", ""),
            "file": f.file,
            "line": f.line,
            "matched_line": getattr(f, "code_snippet", ""),
            "code_context": "\n".join([
                *getattr(f, "context_before", []),
                getattr(f, "code_snippet", ""),
                *getattr(f, "context_after", []),
            ]),
            "explanation": getattr(f, "explanation", ""),
        }
        for f in findings
    ]

    out: list[float | None] = []
    for c in classify_findings_batch(payload):
        if c.verdict == FPVerdict.TRUE_POSITIVE:
            out.append(c.confidence)
        elif c.verdict == FPVerdict.FALSE_POSITIVE:
            out.append(1.0 - c.confidence)
        else:
            out.append(None)  # no opinion; the constant stands
    return out
