"""LLM-based false positive classifier for rule findings.

Uses a fast LLM (Haiku) to classify findings as true positive or false
positive based on code context, rule description, and file purpose.
Inspired by the Datadog approach to agentic SAST triage.

Reference: https://www.datadoghq.com/blog/using-llms-to-filter-out-false-positives/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# Default model — Haiku for cost efficiency (~$0.01 per classification)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


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
    api_key: str = "",
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
        model: LLM model to use.
        api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env).

    Returns:
        FPClassification with verdict, confidence, and reasoning.
    """
    import os
    import time

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return FPClassification(
            rule_id=rule_id, file=file, line=line,
            verdict=FPVerdict.UNCERTAIN, confidence=0.0,
            reasoning="No API key available",
        )

    prompt = _CLASSIFICATION_PROMPT.format(
        rule_id=rule_id,
        severity=severity,
        description=description,
        cwe=cwe or "N/A",
        file=file,
        line=line,
        code_context=code_context[:2000],
        matched_line=matched_line[:200],
        explanation=explanation or description,
    )

    start = time.monotonic()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = (time.monotonic() - start) * 1000
        text = response.content[0].text if response.content else ""
        tokens = response.usage.input_tokens + response.usage.output_tokens

        return _parse_response(rule_id, file, line, text, tokens, elapsed)

    except ImportError:
        return FPClassification(
            rule_id=rule_id, file=file, line=line,
            verdict=FPVerdict.UNCERTAIN, confidence=0.0,
            reasoning="anthropic SDK not installed",
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
    api_key: str = "",
) -> list[FPClassification]:
    """Classify multiple findings in batch.

    Args:
        findings_with_context: List of dicts with keys matching
            classify_finding() parameters.
        model: LLM model.
        api_key: API key.

    Returns:
        List of classifications, one per finding.
    """
    results: list[FPClassification] = []
    for f in findings_with_context:
        result = classify_finding(
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
            api_key=api_key,
        )
        results.append(result)
    return results
