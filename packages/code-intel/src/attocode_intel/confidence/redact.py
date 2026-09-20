"""Strip credentials out of code before it leaves the machine.

Every scorer in this package sends source context to a third-party API. Repo
code is exactly where hardcoded keys live, so redaction happens on the way out,
once, rather than in each scorer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attocode_intel._internal.integrations.security.patterns import SECRET_PATTERNS

if TYPE_CHECKING:
    import re

def _placeholder(secret: str) -> str:
    """Describe the secret without disclosing it.

    A scorer judging a hardcoded-credential finding still needs to know that a
    literal of credential shape is present. Length alone carries that, and the
    surrounding assignment survives, so the evidence is intact and the value
    never leaves the machine.
    """
    return f"[REDACTED:{len(secret)} chars]"


def _blank(match: re.Match[str]) -> str:
    """Replace the secret itself, keeping the surrounding code readable."""
    whole = match.group(0)
    if match.lastindex:  # the pattern captures just the value
        start = match.start(1) - match.start(0)
        end = match.end(1) - match.start(0)
        return whole[:start] + _placeholder(match.group(1)) + whole[end:]
    return _placeholder(whole)


def redact(text: str) -> str:
    """Return text with anything matching a known secret pattern blanked out."""
    if not text:
        return text
    for pattern in SECRET_PATTERNS:
        text = pattern.pattern.sub(_blank, text)
    return text
