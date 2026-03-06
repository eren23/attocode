"""Session-level trace analysis.

Computes summary metrics, timeline views, hierarchical tree views, and
token flow data from a :class:`~attocode.tracing.types.TraceSession`.
"""

from __future__ import annotations

from typing import Any

from attocode.tracing.analysis.token_analyzer import TokenAnalyzer
from attocode.tracing.analysis.views import (
    SessionSummaryView,
    TimelineEntry,
    TokenFlowPoint,
    TreeNode,
)
from attocode.tracing.types import TraceEvent, TraceEventKind, TraceSession


class SessionAnalyzer:
    """Computes metrics and efficiency scores from a TraceSession.

    All computation is lazy -- nothing is calculated until the corresponding
    method is called.
    """

    def __init__(self, session: TraceSession) -> None:
        self._session = session
        self._token_analyzer = TokenAnalyzer(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summary(self) -> SessionSummaryView:
        """Compute the full session summary including efficiency score."""
        s = self._session
        iterations = self._count_kind(TraceEventKind.ITERATION_START)
        tool_calls = self._count_tool_calls()
        llm_calls = self._count_kind(TraceEventKind.LLM_RESPONSE)
        errors = self._count_errors()
        compactions = self._count_compactions()
        total_tokens = self._sum_tokens()
        total_cost = self._token_analyzer.total_cost()

        cache_hit_rate = self._compute_cache_hit_rate()
        efficiency = self._compute_efficiency_score(
            cache_hit_rate=cache_hit_rate,
            errors=errors,
            tool_calls=tool_calls,
            compactions=compactions,
            iterations=iterations,
        )

        avg_tok = total_tokens / iterations if iterations > 0 else 0.0
        avg_cost = total_cost / iterations if iterations > 0 else 0.0

        return SessionSummaryView(
            session_id=s.session_id,
            goal=s.goal,
            model=s.model,
            duration_seconds=s.duration_seconds,
            total_tokens=total_tokens,
            total_cost=total_cost,
            iterations=iterations,
            tool_calls=tool_calls,
            llm_calls=llm_calls,
            errors=errors,
            compactions=compactions,
            efficiency_score=round(efficiency, 1),
            cache_hit_rate=round(cache_hit_rate, 4),
            avg_tokens_per_iteration=round(avg_tok, 1),
            avg_cost_per_iteration=round(avg_cost, 6),
        )

    def timeline(self) -> list[TimelineEntry]:
        """Build a chronologically sorted timeline of all events."""
        entries: list[TimelineEntry] = []
        for event in self._session.events:
            summary_text = _event_summary(event)
            entries.append(
                TimelineEntry(
                    timestamp=event.timestamp,
                    event_kind=str(event.kind),
                    iteration=event.iteration,
                    summary=summary_text,
                    duration_ms=event.duration_ms or event.data.get("duration_ms"),
                    data=event.data,
                )
            )
        entries.sort(key=lambda e: e.timestamp)
        return entries

    def tree(self) -> list[TreeNode]:
        """Build a hierarchical tree grouped by iteration.

        Each top-level node represents an iteration.  Its children are the
        events that occurred within that iteration.  Events without an
        iteration are grouped under a synthetic "ungrouped" root.
        """
        iteration_buckets: dict[int, list[TraceEvent]] = {}
        ungrouped: list[TraceEvent] = []

        for event in self._session.events:
            if event.iteration is not None:
                iteration_buckets.setdefault(event.iteration, []).append(event)
            else:
                ungrouped.append(event)

        roots: list[TreeNode] = []

        # Build iteration subtrees in order.
        for iteration_num in sorted(iteration_buckets):
            events = iteration_buckets[iteration_num]
            # Compute iteration duration from iteration_start/end if available.
            iter_duration = _iteration_duration(events)
            children = [
                TreeNode(
                    event_id=e.event_id,
                    kind=str(e.kind),
                    label=_event_summary(e),
                    duration_ms=e.duration_ms or e.data.get("duration_ms"),
                    data=e.data,
                )
                for e in events
            ]
            roots.append(
                TreeNode(
                    event_id=f"iteration-{iteration_num}",
                    kind="iteration",
                    label=f"Iteration {iteration_num}",
                    duration_ms=iter_duration,
                    children=children,
                )
            )

        # Ungrouped events as a flat list at the top level.
        if ungrouped:
            for event in ungrouped:
                roots.append(
                    TreeNode(
                        event_id=event.event_id,
                        kind=str(event.kind),
                        label=_event_summary(event),
                        duration_ms=event.duration_ms or event.data.get("duration_ms"),
                        data=event.data,
                    )
                )

        return roots

    def token_flow(self) -> list[TokenFlowPoint]:
        """Delegate to :class:`TokenAnalyzer` for per-iteration token flow."""
        return self._token_analyzer.token_flow()

    # ------------------------------------------------------------------
    # Efficiency scoring
    # ------------------------------------------------------------------

    def _compute_efficiency_score(
        self,
        *,
        cache_hit_rate: float,
        errors: int,
        tool_calls: int,
        compactions: int,
        iterations: int,
    ) -> float:
        """Score 0-100 based on five weighted components.

        Weights:
        - Cache hit rate:       30 pts  (cache_read / (input + cache_read))
        - Error rate:           25 pts  (1 - errors / tool_calls)
        - Compaction frequency: 15 pts  (1 - compactions / iterations, min 0)
        - Tool success rate:    20 pts  (successful_tools / total_tools)
        - Token efficiency:     10 pts  (output / input ratio, capped at 1.0)
        """
        # 1. Cache hit rate (0-30)
        cache_score = cache_hit_rate * 30.0

        # 2. Error rate (0-25) -- lower errors = higher score
        if tool_calls > 0:
            error_rate = min(errors / tool_calls, 1.0)
            error_score = (1.0 - error_rate) * 25.0
        else:
            error_score = 25.0  # No tool calls = no errors

        # 3. Compaction frequency (0-15) -- fewer compactions = higher score
        if iterations > 0:
            compaction_ratio = min(compactions / iterations, 1.0)
            compaction_score = max(0.0, (1.0 - compaction_ratio)) * 15.0
        else:
            compaction_score = 15.0

        # 4. Tool success rate (0-20)
        tool_errors = self._count_kind(TraceEventKind.TOOL_ERROR)
        if tool_calls > 0:
            success_rate = max(0.0, 1.0 - tool_errors / tool_calls)
            tool_score = success_rate * 20.0
        else:
            tool_score = 20.0

        # 5. Token efficiency (0-10) -- output/input ratio, capped
        breakdown = self._token_analyzer.token_breakdown()
        total_input = breakdown["input"] + breakdown["cache_read"]
        total_output = breakdown["output"]
        if total_input > 0:
            ratio = min(total_output / total_input, 1.0)
            token_score = ratio * 10.0
        else:
            token_score = 5.0  # Neutral when no data

        return cache_score + error_score + compaction_score + tool_score + token_score

    def _compute_cache_hit_rate(self) -> float:
        """Compute cache hit rate: cache_read / (input + cache_read)."""
        return self._token_analyzer.cache_efficiency()

    # ------------------------------------------------------------------
    # Internal counters
    # ------------------------------------------------------------------

    def _count_kind(self, kind: TraceEventKind) -> int:
        """Count events of a specific kind."""
        return sum(1 for e in self._session.events if e.kind == kind)

    def _count_tool_calls(self) -> int:
        """Count tool invocations (tool_end + tool_error)."""
        return sum(
            1
            for e in self._session.events
            if e.kind in (TraceEventKind.TOOL_END, TraceEventKind.TOOL_ERROR)
        )

    def _count_errors(self) -> int:
        """Count all error events (tool_error + error + llm_error)."""
        error_kinds = {
            TraceEventKind.TOOL_ERROR,
            TraceEventKind.ERROR,
            TraceEventKind.LLM_ERROR,
        }
        return sum(1 for e in self._session.events if e.kind in error_kinds)

    def _count_compactions(self) -> int:
        """Count compaction events (compaction_end)."""
        return self._count_kind(TraceEventKind.COMPACTION_END)

    def _sum_tokens(self) -> int:
        """Sum total tokens from all LLM response events."""
        total = 0
        for e in self._session.events:
            if e.kind == TraceEventKind.LLM_RESPONSE:
                tok = e.data.get("tokens")
                if tok is not None:
                    try:
                        total += int(tok)
                    except (TypeError, ValueError):
                        pass
        return total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_summary(event: TraceEvent) -> str:
    """Generate a human-readable one-line summary for a trace event."""
    kind = event.kind
    d = event.data

    if kind == TraceEventKind.SESSION_START:
        goal = d.get("goal", "")
        model = d.get("model", "")
        return f"Session started: {goal}" if goal else f"Session started (model={model})"

    if kind == TraceEventKind.SESSION_END:
        status = d.get("status", "unknown")
        return f"Session ended: {status}"

    if kind == TraceEventKind.ITERATION_START:
        return f"Iteration {event.iteration} started"

    if kind == TraceEventKind.ITERATION_END:
        dur = d.get("duration_ms")
        dur_str = f" ({dur:.0f}ms)" if dur is not None else ""
        return f"Iteration {event.iteration} ended{dur_str}"

    if kind == TraceEventKind.LLM_REQUEST:
        model = d.get("model", "?")
        count = d.get("messages_count", "?")
        return f"LLM request: {count} messages -> {model}"

    if kind == TraceEventKind.LLM_RESPONSE:
        tokens = d.get("tokens", 0)
        cost = d.get("cost", 0.0)
        return f"LLM response: {tokens} tokens (${cost:.4f})"

    if kind == TraceEventKind.LLM_ERROR:
        error = d.get("error", "unknown error")
        return f"LLM error: {error}"

    if kind == TraceEventKind.LLM_RETRY:
        attempt = d.get("attempt", "?")
        return f"LLM retry (attempt {attempt})"

    if kind == TraceEventKind.TOOL_START:
        tool = d.get("tool", "unknown")
        return f"Tool started: {tool}"

    if kind == TraceEventKind.TOOL_END:
        tool = d.get("tool", "unknown")
        dur = d.get("duration_ms")
        dur_str = f" ({dur:.0f}ms)" if dur is not None else ""
        return f"Tool completed: {tool}{dur_str}"

    if kind == TraceEventKind.TOOL_ERROR:
        tool = d.get("tool", "unknown")
        error = d.get("error", "unknown")
        return f"Tool error: {tool} -- {error}"

    if kind == TraceEventKind.TOOL_APPROVAL:
        tool = d.get("tool", "unknown")
        return f"Tool approval: {tool}"

    if kind == TraceEventKind.BUDGET_CHECK:
        usage = d.get("usage_fraction", 0)
        return f"Budget check: {usage:.0%} used"

    if kind == TraceEventKind.BUDGET_WARNING:
        msg = d.get("message", "approaching limit")
        return f"Budget warning: {msg}"

    if kind == TraceEventKind.BUDGET_EXHAUSTED:
        return "Budget exhausted"

    if kind == TraceEventKind.COMPACTION_START:
        return "Compaction started"

    if kind == TraceEventKind.COMPACTION_END:
        saved = d.get("tokens_saved", 0)
        return f"Compaction completed: {saved} tokens saved"

    if kind == TraceEventKind.CONTEXT_OVERFLOW:
        return "Context overflow detected"

    if kind == TraceEventKind.SUBAGENT_SPAWN:
        agent_id = d.get("agent_id", "unknown")
        return f"Subagent spawned: {agent_id}"

    if kind == TraceEventKind.SUBAGENT_COMPLETE:
        agent_id = d.get("agent_id", "unknown")
        return f"Subagent completed: {agent_id}"

    if kind == TraceEventKind.SUBAGENT_ERROR:
        agent_id = d.get("agent_id", "unknown")
        return f"Subagent error: {agent_id}"

    if kind == TraceEventKind.SUBAGENT_TIMEOUT:
        agent_id = d.get("agent_id", "unknown")
        return f"Subagent timeout: {agent_id}"

    if kind == TraceEventKind.ERROR:
        error = d.get("error", "unknown error")
        return f"Error: {error}"

    if kind == TraceEventKind.RECOVERY:
        return "Recovery initiated"

    # Generic fallback for less common event kinds.
    return str(kind.value).replace("_", " ").capitalize()


def _iteration_duration(events: list[TraceEvent]) -> float | None:
    """Extract iteration wall-clock duration from start/end events."""
    start_ts: float | None = None
    end_ts: float | None = None
    for e in events:
        if e.kind == TraceEventKind.ITERATION_START:
            start_ts = e.timestamp
        elif e.kind == TraceEventKind.ITERATION_END:
            end_ts = e.timestamp
            # Also check data.duration_ms which is more precise.
            dur = e.data.get("duration_ms")
            if dur is not None:
                try:
                    return float(dur)
                except (TypeError, ValueError):
                    pass

    if start_ts is not None and end_ts is not None:
        return (end_ts - start_ts) * 1000.0
    return None
