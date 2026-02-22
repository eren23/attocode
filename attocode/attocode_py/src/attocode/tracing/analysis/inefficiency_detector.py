"""Inefficiency detection for trace sessions.

Scans a :class:`~attocode.tracing.types.TraceSession` for 11 categories of
performance problems, anti-patterns, and anomalies.  Each detector returns
zero or more :class:`DetectedIssue` instances with severity, description,
and actionable suggestions.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from attocode.tracing.analysis.views import DetectedIssue
from attocode.tracing.types import TraceEvent, TraceEventKind, TraceSession


class InefficiencyDetector:
    """Detects 11 types of inefficiencies in trace sessions.

    Instantiate with a session and call :meth:`detect_all` to run every
    detector.
    """

    def __init__(self, session: TraceSession) -> None:
        self._session = session

    def detect_all(self) -> list[DetectedIssue]:
        """Run all 11 detectors and return the aggregated issue list."""
        issues: list[DetectedIssue] = []
        issues.extend(self._detect_excessive_iterations())
        issues.extend(self._detect_repeated_tool_calls())
        issues.extend(self._detect_cache_drops())
        issues.extend(self._detect_token_spikes())
        issues.extend(self._detect_compaction_frequency())
        issues.extend(self._detect_empty_responses())
        issues.extend(self._detect_tool_error_rate())
        issues.extend(self._detect_long_tool_execution())
        issues.extend(self._detect_context_overflow())
        issues.extend(self._detect_budget_warnings_without_action())
        issues.extend(self._detect_subagent_timeouts())
        return issues

    # ------------------------------------------------------------------
    # 1. Excessive iterations without tool calls (spinning)
    # ------------------------------------------------------------------

    def _detect_excessive_iterations(self) -> list[DetectedIssue]:
        """Detect runs of >15 iterations without any tool calls."""
        issues: list[DetectedIssue] = []

        # Build a set of iterations that contain at least one tool call.
        iterations_with_tools: set[int] = set()
        max_iteration = 0
        for event in self._session.events:
            if event.iteration is not None:
                max_iteration = max(max_iteration, event.iteration)
            if event.kind in (TraceEventKind.TOOL_END, TraceEventKind.TOOL_ERROR):
                if event.iteration is not None:
                    iterations_with_tools.add(event.iteration)

        # Scan for consecutive runs without tools.
        run_start: int | None = None
        run_length = 0
        for i in range(1, max_iteration + 1):
            if i not in iterations_with_tools:
                if run_start is None:
                    run_start = i
                run_length += 1
            else:
                if run_length > 15 and run_start is not None:
                    issues.append(
                        DetectedIssue(
                            severity="high",
                            category="spinning",
                            title="Excessive iterations without tool calls",
                            description=(
                                f"{run_length} consecutive iterations "
                                f"({run_start}-{run_start + run_length - 1}) "
                                f"without any tool invocations. The agent may "
                                f"be spinning."
                            ),
                            iteration=run_start,
                            suggestion=(
                                "Check if the agent is stuck in a reasoning "
                                "loop. Consider adding a nudge or reducing "
                                "the iteration budget."
                            ),
                        )
                    )
                run_start = None
                run_length = 0

        # Check trailing run.
        if run_length > 15 and run_start is not None:
            issues.append(
                DetectedIssue(
                    severity="high",
                    category="spinning",
                    title="Excessive iterations without tool calls",
                    description=(
                        f"{run_length} consecutive iterations "
                        f"({run_start}-{run_start + run_length - 1}) "
                        f"without any tool invocations at end of session."
                    ),
                    iteration=run_start,
                    suggestion=(
                        "The agent may have been spinning at session end. "
                        "Review the iteration budget and loop detection."
                    ),
                )
            )

        return issues

    # ------------------------------------------------------------------
    # 2. Repeated tool calls (identical tool + args 3+ times)
    # ------------------------------------------------------------------

    def _detect_repeated_tool_calls(self) -> list[DetectedIssue]:
        """Detect identical tool invocations repeated 3 or more times."""
        issues: list[DetectedIssue] = []

        # Build fingerprints: (tool_name, stable_args_json) -> count + first iteration
        call_counts: Counter[str] = Counter()
        first_iteration: dict[str, int | None] = {}

        for event in self._session.events:
            if event.kind not in (TraceEventKind.TOOL_END, TraceEventKind.TOOL_ERROR):
                continue
            tool = event.data.get("tool", "")
            args = event.data.get("args")
            fingerprint = _tool_fingerprint(tool, args)
            call_counts[fingerprint] += 1
            if fingerprint not in first_iteration:
                first_iteration[fingerprint] = event.iteration

        for fingerprint, count in call_counts.items():
            if count >= 3:
                # Extract tool name from fingerprint (before the first colon).
                tool_name = fingerprint.split(":", 1)[0] if ":" in fingerprint else fingerprint
                issues.append(
                    DetectedIssue(
                        severity="high",
                        category="doom_loop",
                        title=f"Repeated tool call: {tool_name}",
                        description=(
                            f"Tool '{tool_name}' called {count} times with "
                            f"identical arguments. This is a doom loop indicator."
                        ),
                        iteration=first_iteration.get(fingerprint),
                        suggestion=(
                            "The agent is calling the same tool repeatedly. "
                            "The loop detector should break this pattern. "
                            "Consider reviewing doom loop thresholds."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 3. Cache drop detection (>50% drop between LLM calls)
    # ------------------------------------------------------------------

    def _detect_cache_drops(self) -> list[DetectedIssue]:
        """Detect cache hit rate drops exceeding 50% between LLM calls."""
        issues: list[DetectedIssue] = []

        llm_responses = [
            e for e in self._session.events if e.kind == TraceEventKind.LLM_RESPONSE
        ]

        prev_rate: float | None = None
        for event in llm_responses:
            input_tok = _int(event.data, "input_tokens")
            cache_read = _int(event.data, "cache_read_tokens")
            denominator = input_tok + cache_read
            if denominator == 0:
                prev_rate = None
                continue

            current_rate = cache_read / denominator

            if prev_rate is not None and prev_rate > 0:
                drop = prev_rate - current_rate
                if drop > 0.5:
                    issues.append(
                        DetectedIssue(
                            severity="medium",
                            category="cache_drop",
                            title="Cache hit rate dropped significantly",
                            description=(
                                f"Cache hit rate dropped from {prev_rate:.0%} "
                                f"to {current_rate:.0%} (a {drop:.0%} decrease). "
                                f"This may indicate context restructuring or "
                                f"compaction invalidating the KV cache."
                            ),
                            iteration=event.iteration,
                            suggestion=(
                                "Review context management around this iteration. "
                                "Compactions and message reordering can invalidate "
                                "KV cache prefixes."
                            ),
                        )
                    )

            prev_rate = current_rate

        return issues

    # ------------------------------------------------------------------
    # 4. Token spike (>2x average)
    # ------------------------------------------------------------------

    def _detect_token_spikes(self) -> list[DetectedIssue]:
        """Detect LLM calls using more than 2x the average tokens."""
        issues: list[DetectedIssue] = []

        llm_responses = [
            e for e in self._session.events if e.kind == TraceEventKind.LLM_RESPONSE
        ]
        if len(llm_responses) < 3:
            return issues  # Not enough data points.

        token_counts = [_int(e.data, "tokens") for e in llm_responses]
        avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0
        if avg_tokens == 0:
            return issues

        threshold = avg_tokens * 2.0
        for event, tokens in zip(llm_responses, token_counts):
            if tokens > threshold:
                issues.append(
                    DetectedIssue(
                        severity="medium",
                        category="token_spike",
                        title="Token usage spike",
                        description=(
                            f"LLM call used {tokens:,} tokens, "
                            f"which is {tokens / avg_tokens:.1f}x the average "
                            f"({avg_tokens:,.0f}). This may indicate context "
                            f"bloat or an oversized tool result."
                        ),
                        iteration=event.iteration,
                        suggestion=(
                            "Check if a large tool result was injected "
                            "before this call. Consider truncating tool "
                            "outputs or using context overflow guards."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 5. Compaction frequency (>3 in 20 iterations)
    # ------------------------------------------------------------------

    def _detect_compaction_frequency(self) -> list[DetectedIssue]:
        """Detect excessive compaction frequency (>3 per 20 iterations)."""
        issues: list[DetectedIssue] = []

        compaction_iterations: list[int] = []
        for event in self._session.events:
            if event.kind == TraceEventKind.COMPACTION_END and event.iteration is not None:
                compaction_iterations.append(event.iteration)

        if len(compaction_iterations) < 4:
            return issues  # Threshold is >3.

        compaction_iterations.sort()

        # Sliding window of 20 iterations.
        for i, start_iter in enumerate(compaction_iterations):
            window_end = start_iter + 20
            count_in_window = sum(
                1 for ci in compaction_iterations[i:] if ci <= window_end
            )
            if count_in_window > 3:
                issues.append(
                    DetectedIssue(
                        severity="medium",
                        category="compaction_frequency",
                        title="Excessive compaction frequency",
                        description=(
                            f"{count_in_window} compactions within 20 iterations "
                            f"(starting at iteration {start_iter}). Frequent "
                            f"compaction degrades cache efficiency and increases "
                            f"latency."
                        ),
                        iteration=start_iter,
                        suggestion=(
                            "The context window is filling too quickly. "
                            "Consider more aggressive tool output truncation "
                            "or raising the compaction threshold."
                        ),
                    )
                )
                break  # Report only the first window hit.

        return issues

    # ------------------------------------------------------------------
    # 6. Empty LLM responses (0 output tokens)
    # ------------------------------------------------------------------

    def _detect_empty_responses(self) -> list[DetectedIssue]:
        """Detect LLM responses with 0 output tokens."""
        issues: list[DetectedIssue] = []

        for event in self._session.events:
            if event.kind != TraceEventKind.LLM_RESPONSE:
                continue
            output_tokens = _int(event.data, "output_tokens")
            if output_tokens == 0:
                issues.append(
                    DetectedIssue(
                        severity="low",
                        category="empty_response",
                        title="Empty LLM response",
                        description=(
                            "An LLM call returned 0 output tokens. This may "
                            "indicate a malformed request, context overflow, "
                            "or a provider-side issue."
                        ),
                        iteration=event.iteration,
                        suggestion=(
                            "Check the request that preceded this response. "
                            "Verify the context window was not exceeded."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 7. Tool error rate (>30%)
    # ------------------------------------------------------------------

    def _detect_tool_error_rate(self) -> list[DetectedIssue]:
        """Detect sessions with >30% tool call failure rate."""
        issues: list[DetectedIssue] = []

        total_tools = 0
        total_errors = 0
        for event in self._session.events:
            if event.kind == TraceEventKind.TOOL_END:
                total_tools += 1
            elif event.kind == TraceEventKind.TOOL_ERROR:
                total_tools += 1
                total_errors += 1

        if total_tools < 3:
            return issues  # Not enough data.

        error_rate = total_errors / total_tools
        if error_rate > 0.3:
            issues.append(
                DetectedIssue(
                    severity="high",
                    category="tool_error_rate",
                    title="High tool error rate",
                    description=(
                        f"{total_errors}/{total_tools} tool calls failed "
                        f"({error_rate:.0%} error rate). This exceeds the "
                        f"30% threshold."
                    ),
                    suggestion=(
                        "Review the failing tools and their inputs. "
                        "Common causes: incorrect file paths, permission "
                        "denials, or sandbox restrictions."
                    ),
                )
            )

        return issues

    # ------------------------------------------------------------------
    # 8. Long tool execution (>30 seconds)
    # ------------------------------------------------------------------

    def _detect_long_tool_execution(self) -> list[DetectedIssue]:
        """Detect tool calls taking longer than 30 seconds."""
        issues: list[DetectedIssue] = []
        threshold_ms = 30_000.0

        for event in self._session.events:
            if event.kind not in (TraceEventKind.TOOL_END, TraceEventKind.TOOL_ERROR):
                continue
            duration = event.duration_ms or event.data.get("duration_ms")
            if duration is None:
                continue
            try:
                dur_ms = float(duration)
            except (TypeError, ValueError):
                continue

            if dur_ms > threshold_ms:
                tool = event.data.get("tool", "unknown")
                issues.append(
                    DetectedIssue(
                        severity="medium",
                        category="long_tool",
                        title=f"Long tool execution: {tool}",
                        description=(
                            f"Tool '{tool}' took {dur_ms / 1000:.1f}s to "
                            f"execute, exceeding the 30s threshold."
                        ),
                        iteration=event.iteration,
                        suggestion=(
                            "Consider adding a timeout to this tool or "
                            "breaking the operation into smaller steps."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 9. Context overflow events
    # ------------------------------------------------------------------

    def _detect_context_overflow(self) -> list[DetectedIssue]:
        """Detect any context_overflow events."""
        issues: list[DetectedIssue] = []

        for event in self._session.events:
            if event.kind == TraceEventKind.CONTEXT_OVERFLOW:
                issues.append(
                    DetectedIssue(
                        severity="critical",
                        category="context_overflow",
                        title="Context overflow detected",
                        description=(
                            "A context overflow event was recorded. The agent's "
                            "context window was exceeded, requiring emergency "
                            "truncation of tool results or messages."
                        ),
                        iteration=event.iteration,
                        suggestion=(
                            "Review the context overflow guard configuration. "
                            "Consider lowering compaction thresholds or "
                            "truncating large tool outputs earlier."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 10. Budget warnings without behavior change
    # ------------------------------------------------------------------

    def _detect_budget_warnings_without_action(self) -> list[DetectedIssue]:
        """Detect budget_warning events not followed by behavioral change.

        A "behavioral change" is defined as a reduction in tool calls per
        iteration or a transition to text-only mode within the next 3
        iterations after the warning.
        """
        issues: list[DetectedIssue] = []

        # Collect budget warning iterations.
        warning_iterations: list[int] = []
        for event in self._session.events:
            if event.kind == TraceEventKind.BUDGET_WARNING and event.iteration is not None:
                warning_iterations.append(event.iteration)

        if not warning_iterations:
            return issues

        # Count tool calls per iteration.
        tools_per_iteration: Counter[int] = Counter()
        for event in self._session.events:
            if event.kind in (TraceEventKind.TOOL_END, TraceEventKind.TOOL_ERROR):
                if event.iteration is not None:
                    tools_per_iteration[event.iteration] += 1

        # Check for mode changes.
        mode_change_iterations: set[int] = set()
        for event in self._session.events:
            if event.kind == TraceEventKind.MODE_CHANGE and event.iteration is not None:
                mode_change_iterations.add(event.iteration)

        for warn_iter in warning_iterations:
            # Look at the 3 iterations after the warning.
            pre_tools = tools_per_iteration.get(warn_iter, 0)
            behavioral_change = False

            for offset in range(1, 4):
                check_iter = warn_iter + offset
                if check_iter in mode_change_iterations:
                    behavioral_change = True
                    break
                post_tools = tools_per_iteration.get(check_iter, 0)
                # A reduction of >= 50% counts as a change.
                if pre_tools > 0 and post_tools < pre_tools * 0.5:
                    behavioral_change = True
                    break

            if not behavioral_change:
                issues.append(
                    DetectedIssue(
                        severity="medium",
                        category="budget_warning_ignored",
                        title="Budget warning without behavior change",
                        description=(
                            f"A budget warning at iteration {warn_iter} was "
                            f"not followed by reduced tool usage or a mode "
                            f"change within 3 iterations."
                        ),
                        iteration=warn_iter,
                        suggestion=(
                            "The agent should reduce tool calls or switch to "
                            "text-only mode after a budget warning. Review "
                            "the budget enforcement configuration."
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 11. Subagent timeout patterns
    # ------------------------------------------------------------------

    def _detect_subagent_timeouts(self) -> list[DetectedIssue]:
        """Detect subagent_timeout events."""
        issues: list[DetectedIssue] = []

        for event in self._session.events:
            if event.kind == TraceEventKind.SUBAGENT_TIMEOUT:
                agent_id = event.data.get("agent_id", "unknown")
                issues.append(
                    DetectedIssue(
                        severity="high",
                        category="subagent_timeout",
                        title=f"Subagent timeout: {agent_id}",
                        description=(
                            f"Subagent '{agent_id}' timed out. This wastes "
                            f"tokens and delays the parent agent."
                        ),
                        iteration=event.iteration,
                        suggestion=(
                            "Consider increasing the subagent timeout, "
                            "reducing the delegated task scope, or using a "
                            "faster model for subagent work."
                        ),
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_fingerprint(tool: str, args: Any) -> str:
    """Create a stable string fingerprint for a tool invocation."""
    if args is None:
        return f"{tool}:"
    try:
        args_str = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_str = str(args)
    return f"{tool}:{args_str}"


def _int(d: dict[str, Any], key: str) -> int:
    """Safely extract an integer from a data dict."""
    v = d.get(key)
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
