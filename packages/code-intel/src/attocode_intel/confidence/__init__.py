"""Where a finding's confidence comes from.

Most confidences in this package are literals somebody picked: the eight in
``bug_finder._PATTERNS``, the ``0.6`` on synthesized rules, the ``0.7``/``0.8``
in ``dead_code_tools``. Two scorers can replace them, chosen with
``ATTOCODE_FLAG_CONFIDENCE``: jev and llm. Historical experiments and their
limitations live in ``eval/rule_accuracy/demo``; their results are not
general accuracy guarantees.

``ATTOCODE_FLAG_CONFIDENCE_MODE`` picks what happens with the estimate:
``shadow`` logs it beside the constant and changes nothing, ``live`` uses it.
Both default to off/shadow, so nothing here runs unless asked.
"""

from __future__ import annotations

import hashlib
import logging
import math
from contextvars import ContextVar
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from attocode_intel.confidence import jev as jev_scorer
from attocode_intel.confidence import llm as llm_scorer
from attocode_intel.confidence import settings
from attocode_intel.confidence.redact import redact

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

__all__ = ["MAX_CALLS", "last_report", "last_run", "mode", "redact", "rule_threshold", "score", "scorer_name", "summary"]

# ponytail: per-call cap. A corpus file yields a handful of findings; a wide
# diff can yield hundreds, and each one is a network round trip.
MAX_CALLS = 25

_SCORERS = {"jev": jev_scorer, "llm": llm_scorer}

_last: ContextVar[tuple[int, int]] = ContextVar("confidence_counts", default=(0, 0))
_report: ContextVar[dict | None] = ContextVar("confidence_report", default=None)


def last_run() -> tuple[int, int]:
    """(estimated, considered) from the most recent score() call."""
    return _last.get()


def last_report() -> dict:
    """A detached request-local audit, including suppressed and unscored candidates."""
    return deepcopy(_report.get() or {})


def summary() -> str:
    report = _report.get() or {}
    if not report or report["scorer"] == "off":
        return ""
    return (
        f"Confidence: {report['scorer']} ({report['mode']}); "
        f"{report['estimated']}/{report['total']} scored, "
        f"{report['fallback']} fallback, {report['skipped']} skipped by cap. "
        "Fallback and skipped findings retain their baseline confidence."
    )


def rule_threshold(min_confidence: float) -> float:
    """Live estimates can promote rules below their old constant threshold."""
    return 0.0 if settings.selected() != "off" and mode() == "live" else min_confidence


def scorer_name() -> str:
    """Which scorer is selected: "off", "jev" or "llm"."""
    name = settings.selected()
    if name == "jev":
        try:
            if not jev_scorer.available():
                return "off"
        except (ValueError, OSError):
            return "off"
    return name if name in _SCORERS else "off"


def mode() -> str:
    """What to do with an estimate: "shadow" (log only) or "live" (use it)."""
    value = settings.mode()
    return "live" if value == "live" else "shadow"


def score(findings: Sequence[Any], *, min_confidence: float) -> tuple[int, int]:
    """Estimate p(true positive) per finding and log it beside the constant.

    In ``live`` mode the estimate replaces ``finding.confidence``. Findings the
    scorer has no opinion on keep their constant. Never raises: a scorer outage
    must not cost a caller its findings.

    Returns (estimated, considered) so a caller can tell a real score from a
    scorer that ran but never committed to anything.
    """
    requested = settings.selected()
    name = scorer_name()
    items = list(findings)
    batch = items[:MAX_CALLS] if name != "off" else []
    estimates: list = []
    if batch:
        try:
            estimates = list(_SCORERS[name].estimate(batch, min_confidence=min_confidence))
        except Exception:
            logger.warning("confidence: %s scorer failed, keeping constants", name)
    live = mode() == "live"
    estimated = 0
    rows = []
    for index, finding in enumerate(items):
        baseline = finding.confidence
        estimate = estimates[index] if index < len(batch) and index < len(estimates) else None
        if isinstance(estimate, bool) or not isinstance(estimate, int | float) or not 0 <= estimate <= 1 or not math.isfinite(estimate):
            estimate = None
        if estimate is not None:
            estimated += 1
            if live:
                finding.confidence = estimate
        status = ("off" if requested == "off" else "unavailable" if name == "off"
                  else "skipped_cap" if index >= len(batch)
                  else "estimated" if estimate is not None else "fallback")
        identity = f"{finding.file}:{finding.line}:{getattr(finding, 'rule_id', '')}"
        rows.append({
            "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
            "file": finding.file, "line": finding.line,
            "rule": getattr(finding, "rule_id", ""),
            "baseline": baseline, "estimate": estimate, "effective": finding.confidence,
            "status": status, "kept": finding.confidence >= min_confidence,
        })
    report = {
        "scorer": requested, "mode": mode(), "total": len(items), "estimated": estimated,
        "considered": len(batch), "skipped": sum(r["status"] == "skipped_cap" for r in rows),
        "fallback": sum(r["status"] in {"fallback", "unavailable"} for r in rows),
        "findings": rows,
    }
    _report.set(report)
    _last.set((estimated, len(batch)))
    if requested != "off":
        logger.info("%s", summary())
    return last_run()
