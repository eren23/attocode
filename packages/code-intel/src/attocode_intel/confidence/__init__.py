"""Where a finding's confidence comes from.

Most confidences in this package are literals somebody picked: the eight in
``bug_finder._PATTERNS``, the ``0.6`` on synthesized rules, the ``0.7``/``0.8``
in ``dead_code_tools``. Measured against ``eval/rule_accuracy``, those constants
are badly calibrated — ECE 0.21 against a 0.10 target, with the 0.8–0.9 bin
holding 38 of 82 findings and delivering 63%.

Two scorers can replace them, chosen with ``ATTOCODE_FLAG_CONFIDENCE``:

=========  =====  =====  ====  ======================================
scorer         P      R   ECE  character
=========  =====  =====  ====  ======================================
constants   0.89   0.72  0.21  free, no network, badly calibrated
jev         0.89   0.86  0.13  best F1 and calibration
llm         0.96   0.74  0.28  most precise, worst calibrated
=========  =====  =====  ====  ======================================

``ATTOCODE_FLAG_CONFIDENCE_MODE`` picks what happens with the estimate:
``shadow`` logs it beside the constant and changes nothing, ``live`` uses it.
Both default to off/shadow, so nothing here runs unless asked.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from attocode_intel._internal.integrations.feature_flags import registry
from attocode_intel.confidence import jev as jev_scorer
from attocode_intel.confidence import llm as llm_scorer
from attocode_intel.confidence.redact import redact

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

__all__ = ["MAX_CALLS", "last_run", "mode", "redact", "score", "scorer_name"]

# ponytail: per-call cap. A corpus file yields a handful of findings; a wide
# diff can yield hundreds, and each one is a network round trip.
MAX_CALLS = 25

_SCORERS = {"jev": jev_scorer, "llm": llm_scorer}

# Counts from the most recent score() call. Diagnostic only, last write wins:
# score() runs deep inside run_pipeline, so a caller that wants to know whether
# the scorer actually committed to anything cannot read the return value.
_last: tuple[int, int] = (0, 0)


def last_run() -> tuple[int, int]:
    """(estimated, considered) from the most recent score() call."""
    return _last


def scorer_name() -> str:
    """Which scorer is selected: "off", "jev" or "llm"."""
    name = registry.get_str("CONFIDENCE", "off")
    if name == "jev" and not jev_scorer.available():
        return "off"
    return name if name in _SCORERS else "off"


def mode() -> str:
    """What to do with an estimate: "shadow" (log only) or "live" (use it)."""
    value = registry.get_str("CONFIDENCE_MODE", "shadow")
    return "live" if value == "live" else "shadow"


def score(findings: Sequence[Any], *, min_confidence: float) -> tuple[int, int]:
    """Estimate p(true positive) per finding and log it beside the constant.

    In ``live`` mode the estimate replaces ``finding.confidence``. Findings the
    scorer has no opinion on keep their constant. Never raises: a scorer outage
    must not cost a caller its findings.

    Returns (estimated, considered) so a caller can tell a real score from a
    scorer that ran but never committed to anything.
    """
    global _last

    name = scorer_name()
    if name == "off" or not findings:
        _last = (0, 0)
        return _last

    batch = list(findings)[:MAX_CALLS]
    if len(findings) > MAX_CALLS:
        logger.debug("confidence: scoring %d of %d findings", MAX_CALLS, len(findings))

    try:
        estimates = _SCORERS[name].estimate(batch, min_confidence=min_confidence)
    except Exception:
        logger.warning("confidence: %s scorer failed, keeping constants", name)
        _last = (0, len(batch))
        return _last

    live = mode() == "live"
    estimated = 0
    for finding, estimate in zip(batch, estimates, strict=False):
        if estimate is None:
            continue
        estimated += 1
        logger.info(
            "confidence[%s] %s:%s constant=%.2f p=%.2f",
            name, finding.file, finding.line, finding.confidence, estimate,
        )
        if live:
            finding.confidence = estimate

    if estimated < len(batch):
        logger.info(
            "confidence[%s]: no opinion on %d of %d findings; constants stand",
            name, len(batch) - estimated, len(batch),
        )
    _last = (estimated, len(batch))
    return _last
