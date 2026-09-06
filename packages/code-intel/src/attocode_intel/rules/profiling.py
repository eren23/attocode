"""Rule profiling and confidence calibration.

Tracks per-rule execution time, match counts, and true/false positive
feedback to calibrate confidence scores over time.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuleStats:
    """Per-rule profiling statistics."""

    rule_id: str
    total_time_ms: float = 0.0
    match_count: int = 0
    files_scanned: int = 0
    true_positives: int = 0
    false_positives: int = 0

    @property
    def calibrated_confidence(self) -> float | None:
        """Compute calibrated confidence from TP/FP feedback.

        Returns None if insufficient data (<5 samples).
        """
        total = self.true_positives + self.false_positives
        if total < 5:
            return None
        return self.true_positives / total

    @property
    def false_positive_rate(self) -> float | None:
        total = self.true_positives + self.false_positives
        if total == 0:
            return None
        return self.false_positives / total


class RuleProfiler:
    """Thread-safe rule profiler with per-rule timing and feedback tracking."""

    def __init__(self) -> None:
        self._stats: dict[str, RuleStats] = {}
        self._lock = threading.Lock()
        self._timers: dict[tuple[str, int], float] = {}  # (rule_id, thread_id) -> start

    def _ensure(self, rule_id: str) -> RuleStats:
        if rule_id not in self._stats:
            self._stats[rule_id] = RuleStats(rule_id=rule_id)
        return self._stats[rule_id]

    def start(self, rule_id: str) -> None:
        """Start timing a rule execution."""
        key = (rule_id, threading.get_ident())
        with self._lock:
            self._timers[key] = time.monotonic()

    def stop(self, rule_id: str) -> None:
        """Stop timing and record elapsed time."""
        key = (rule_id, threading.get_ident())
        with self._lock:
            start = self._timers.pop(key, None)
        if start is None:
            return
        elapsed_ms = (time.monotonic() - start) * 1000
        with self._lock:
            stats = self._ensure(rule_id)
            stats.total_time_ms += elapsed_ms

    def record_match(self, rule_id: str) -> None:
        """Record a rule match."""
        with self._lock:
            self._ensure(rule_id).match_count += 1

    def record_file_scanned(self, rule_id: str) -> None:
        """Record that a rule was evaluated against a file."""
        with self._lock:
            self._ensure(rule_id).files_scanned += 1

    def record_feedback(self, rule_id: str, *, is_true_positive: bool) -> None:
        """Record TP/FP feedback for confidence calibration."""
        with self._lock:
            stats = self._ensure(rule_id)
            if is_true_positive:
                stats.true_positives += 1
            else:
                stats.false_positives += 1

    def get_stats(self, rule_id: str = "") -> dict[str, RuleStats]:
        """Get stats for a specific rule or all rules."""
        with self._lock:
            if rule_id:
                s = self._stats.get(rule_id)
                return {rule_id: s} if s else {}
            return dict(self._stats)

    def reset(self) -> None:
        """Clear all profiling data."""
        with self._lock:
            self._stats.clear()
            self._timers.clear()


# ---------------------------------------------------------------------------
# Persistent feedback store
# ---------------------------------------------------------------------------


class FeedbackStore:
    """Persistent rule-quality state stored in .attocode/rule_feedback.json.

    Tracks both TP/FP feedback (for confidence calibration) and per-rule
    scan/match counters plus hygiene-applied disable state (consumed by
    ``rules.hygiene``). One JSON file keeps related metadata together so
    auto-prune decisions persist across sessions.
    """

    def __init__(self, project_dir: str) -> None:
        self._path = Path(project_dir) / ".attocode" / "rule_feedback.json"
        self._data: dict[str, dict[str, object]] = {}
        # Single in-process lock guards both the in-memory map and the
        # read-modify-write JSON file. Cross-process safety would need a
        # ``filelock``; in-process MCP/HTTP concurrency is the immediate
        # need here (record_session() fires on every analyze() call).
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load rule feedback: %s", exc)
                self._data = {}

    def _save_locked(self) -> None:
        """Persist to disk. Caller must hold ``self._lock``."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save rule feedback: %s", exc)

    @staticmethod
    def _entry_int(entry: dict[str, object], key: str) -> int:
        value = entry.get(key, 0)
        return int(value) if isinstance(value, (int, float)) else 0

    def _ensure_locked(self, rule_id: str) -> dict[str, object]:
        """Caller must hold ``self._lock``."""
        return self._data.setdefault(rule_id, {"tp": 0, "fp": 0})

    def record(self, rule_id: str, *, is_true_positive: bool) -> None:
        """Record a TP/FP observation and persist."""
        with self._lock:
            entry = self._ensure_locked(rule_id)
            if is_true_positive:
                entry["tp"] = self._entry_int(entry, "tp") + 1
            else:
                entry["fp"] = self._entry_int(entry, "fp") + 1
            total = self._entry_int(entry, "tp") + self._entry_int(entry, "fp")
            if total >= 5:
                tp = self._entry_int(entry, "tp")
                entry["calibrated"] = round(tp / total, 3)
            self._save_locked()

    def record_session(
        self,
        rule_ids: list[str],
        matches: dict[str, int],
        *,
        files_scanned: int = 0,
    ) -> None:
        """Record one analyze-session's scan + match counters across rules.

        Each rule that was applied in the session has its ``scans`` counter
        incremented by 1 (one session = one scan, irrespective of file count
        — matching the roadmap's "0 matches across 10+ scanned repos"
        framing). Matches are added cumulatively. ``files_scanned`` is
        recorded as a rolling total per-rule for diagnostics only.
        """
        if not rule_ids:
            return
        with self._lock:
            for qid in rule_ids:
                entry = self._ensure_locked(qid)
                entry["scans"] = self._entry_int(entry, "scans") + 1
                if files_scanned:
                    entry["files_scanned"] = (
                        self._entry_int(entry, "files_scanned") + files_scanned
                    )
                entry["matches"] = (
                    self._entry_int(entry, "matches") + int(matches.get(qid, 0))
                )
            self._save_locked()

    def set_disabled(self, rule_id: str, reason: str) -> None:
        """Mark a rule disabled with a reason (e.g. 'dead', 'noisy')."""
        with self._lock:
            entry = self._ensure_locked(rule_id)
            entry["disabled"] = True
            entry["disabled_reason"] = reason
            self._save_locked()

    def clear_disabled(self, rule_id: str) -> None:
        """Re-enable a previously hygiene-disabled rule."""
        with self._lock:
            entry = self._data.get(rule_id)
            if entry is None:
                return
            entry["disabled"] = False
            entry["disabled_reason"] = ""
            self._save_locked()

    def is_disabled(self, rule_id: str) -> bool:
        with self._lock:
            entry = self._data.get(rule_id, {})
            return bool(entry.get("disabled", False))

    def get_disabled_reason(self, rule_id: str) -> str:
        with self._lock:
            entry = self._data.get(rule_id, {})
            value = entry.get("disabled_reason", "")
            return value if isinstance(value, str) else ""

    def get_scan_count(self, rule_id: str) -> int:
        with self._lock:
            return self._entry_int(self._data.get(rule_id, {}), "scans")

    def get_match_count(self, rule_id: str) -> int:
        with self._lock:
            return self._entry_int(self._data.get(rule_id, {}), "matches")

    def get_calibrated_confidence(self, rule_id: str) -> float | None:
        """Get calibrated confidence for a rule, or None if insufficient data."""
        with self._lock:
            entry = self._data.get(rule_id, {})
            value = entry.get("calibrated")
            return float(value) if isinstance(value, (int, float)) else None

    def get_feedback(self, rule_id: str) -> dict[str, int]:
        """Get raw TP/FP counts for a rule."""
        with self._lock:
            entry = self._data.get(rule_id, {})
            return {
                "tp": self._entry_int(entry, "tp"),
                "fp": self._entry_int(entry, "fp"),
            }

    def all_feedback(self) -> dict[str, dict[str, object]]:
        """Get all stored data (TP/FP + scan/match + disabled state)."""
        with self._lock:
            return dict(self._data)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_rule_stats(
    stats: dict[str, RuleStats],
    feedback: dict[str, dict[str, object]] | None = None,
) -> str:
    """Format profiling stats as markdown."""
    if not stats:
        return "No profiling data available."

    lines = ["# Rule Profiling Stats\n"]

    # Sort by total time descending
    sorted_stats = sorted(stats.values(), key=lambda s: s.total_time_ms, reverse=True)

    lines.append("| Rule | Time (ms) | Matches | Files | TP | FP | Calibrated |")
    lines.append("|------|-----------|---------|-------|----|----|------------|")

    for s in sorted_stats:
        fb = (feedback or {}).get(s.rule_id, {})
        tp_raw = fb.get("tp", s.true_positives)
        fp_raw = fb.get("fp", s.false_positives)
        tp = int(tp_raw) if isinstance(tp_raw, (int, float)) else s.true_positives
        fp = int(fp_raw) if isinstance(fp_raw, (int, float)) else s.false_positives
        cal_raw = fb.get("calibrated", s.calibrated_confidence)
        cal: float | None
        if isinstance(cal_raw, (int, float)):
            cal = float(cal_raw)
        elif cal_raw is None:
            cal = s.calibrated_confidence
        else:
            cal = None
        cal_str = f"{cal:.2f}" if cal is not None else "—"
        lines.append(
            f"| `{s.rule_id}` | {s.total_time_ms:.1f} | {s.match_count} | "
            f"{s.files_scanned} | {tp} | {fp} | {cal_str} |"
        )

    # Summary
    total_time = sum(s.total_time_ms for s in sorted_stats)
    total_matches = sum(s.match_count for s in sorted_stats)
    lines.append(f"\n**Total**: {total_time:.1f}ms across {len(sorted_stats)} rules, {total_matches} matches")

    # Top 5 slowest
    if len(sorted_stats) > 5:
        lines.append("\n## Slowest Rules")
        for s in sorted_stats[:5]:
            lines.append(f"- `{s.rule_id}`: {s.total_time_ms:.1f}ms")

    # Highest FP rate
    fp_rules = [
        s for s in sorted_stats
        if s.false_positive_rate is not None and s.false_positive_rate > 0
    ]
    if fp_rules:
        fp_rules.sort(key=lambda s: s.false_positive_rate or 0, reverse=True)  # type: ignore[arg-type]
        lines.append("\n## Highest False Positive Rates")
        for s in fp_rules[:5]:
            lines.append(f"- `{s.rule_id}`: {s.false_positive_rate:.0%}")

    return "\n".join(lines)
