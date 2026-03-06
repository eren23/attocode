"""Token usage analysis for trace sessions.

Provides detailed breakdowns of token consumption, cost tracking per
iteration, cache efficiency metrics, and cumulative flow data suitable
for charting.
"""

from __future__ import annotations

from typing import Any

from attocode.tracing.analysis.views import TokenFlowPoint
from attocode.tracing.types import TraceEvent, TraceEventKind, TraceSession


class TokenAnalyzer:
    """Analyzes token usage patterns across a session.

    All metrics are derived from ``llm_response`` events in
    ``session.events``.  Each such event is expected to carry the following
    data keys (all optional, defaulting to 0):

    - ``tokens`` -- total tokens for the call
    - ``cost`` -- monetary cost
    - ``input_tokens``, ``output_tokens``
    - ``cache_read_tokens``, ``cache_write_tokens``
    """

    def __init__(self, session: TraceSession) -> None:
        self._session = session
        self._llm_responses: list[TraceEvent] = [
            e
            for e in session.events
            if e.kind == TraceEventKind.LLM_RESPONSE
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def token_flow(self) -> list[TokenFlowPoint]:
        """Build per-iteration token flow points.

        Events without an ``iteration`` field are grouped under iteration 0.
        Points are sorted by iteration number and include cumulative cost.
        """
        buckets: dict[int, TokenFlowPoint] = {}
        cumulative_cost = 0.0

        for event in self._llm_responses:
            iteration = event.iteration if event.iteration is not None else 0
            d = event.data

            input_tok = _int(d, "input_tokens")
            output_tok = _int(d, "output_tokens")
            cache_read = _int(d, "cache_read_tokens")
            cache_write = _int(d, "cache_write_tokens")
            total = _int(d, "tokens") or (input_tok + output_tok + cache_read + cache_write)
            cost = _float(d, "cost")
            cumulative_cost += cost

            if iteration not in buckets:
                buckets[iteration] = TokenFlowPoint(
                    iteration=iteration,
                    cumulative_cost=cumulative_cost,
                )

            pt = buckets[iteration]
            pt.input_tokens += input_tok
            pt.output_tokens += output_tok
            pt.cache_read_tokens += cache_read
            pt.cache_write_tokens += cache_write
            pt.total_tokens += total
            pt.cumulative_cost = cumulative_cost

        return sorted(buckets.values(), key=lambda p: p.iteration)

    def total_cost(self) -> float:
        """Sum of ``cost`` across all LLM response events."""
        return sum(_float(e.data, "cost") for e in self._llm_responses)

    def cost_by_iteration(self) -> dict[int, float]:
        """Map from iteration number to total cost within that iteration."""
        result: dict[int, float] = {}
        for event in self._llm_responses:
            iteration = event.iteration if event.iteration is not None else 0
            result[iteration] = result.get(iteration, 0.0) + _float(event.data, "cost")
        return result

    def cache_efficiency(self) -> float:
        """Fraction of input tokens served from cache.

        Returns ``cache_read / (input + cache_read)`` across the whole
        session, or 0.0 if no input tokens were recorded.
        """
        total_input = 0
        total_cache_read = 0
        for event in self._llm_responses:
            total_input += _int(event.data, "input_tokens")
            total_cache_read += _int(event.data, "cache_read_tokens")

        denominator = total_input + total_cache_read
        if denominator == 0:
            return 0.0
        return total_cache_read / denominator

    def token_breakdown(self) -> dict[str, int]:
        """Aggregate token counts by category.

        Returns:
            Dict with keys ``input``, ``output``, ``cache_read``,
            ``cache_write``.
        """
        totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for event in self._llm_responses:
            d = event.data
            totals["input"] += _int(d, "input_tokens")
            totals["output"] += _int(d, "output_tokens")
            totals["cache_read"] += _int(d, "cache_read_tokens")
            totals["cache_write"] += _int(d, "cache_write_tokens")
        return totals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int(d: dict[str, Any], key: str) -> int:
    """Safely extract an integer from a data dict."""
    v = d.get(key)
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _float(d: dict[str, Any], key: str) -> float:
    """Safely extract a float from a data dict."""
    v = d.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
