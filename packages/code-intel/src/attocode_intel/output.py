"""A single output budget, including all composed sections."""

from __future__ import annotations

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens


def bounded_text(text: str, max_tokens: int) -> tuple[str, bool]:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if count_tokens(text) <= max_tokens:
        return text, False
    suffix = "\n[Truncated; narrow the query or increase max_tokens.]"
    if count_tokens(suffix) >= max_tokens:
        suffix = ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid] + suffix) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + suffix, True
