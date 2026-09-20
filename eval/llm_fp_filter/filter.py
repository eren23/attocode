"""LLM-based false positive classifier — moved into the shipped package.

The implementation now lives in :mod:`attocode_intel.confidence.llm`, where it
sits beside the other confidence scorers and is reachable from the rules
pipeline. This module stays as a re-export so the benchmark and existing
imports keep working.
"""

from __future__ import annotations

from attocode_intel.confidence.llm import (
    DEFAULT_MODEL,
    FPClassification,
    FPVerdict,
    _parse_response,
    classify_finding,
    classify_findings_batch,
)

__all__ = [
    "DEFAULT_MODEL",
    "FPClassification",
    "FPVerdict",
    "_parse_response",
    "classify_finding",
    "classify_findings_batch",
]
