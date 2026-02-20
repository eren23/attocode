"""Execution loop - the main async ReAct loop for the agent.

Includes extracted testable functions:
- check_iteration_budget() — budget pre-flight with recovery actions
- handle_auto_compaction() — trigger compaction at thresholds
- apply_context_overflow_guard() — mass tool result truncation
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.errors import BudgetExhaustedError, CancellationError
from attocode.types.agent import AgentCompletionStatus, AgentResult, CompletionReason
from attocode.types.events import EventType
from attocode.types.messages import Message, Role

from attocode.agent.context import AgentContext
from attocode.core.completion import CompletionAnalysis, analyze_completion
from attocode.core.response_handler import call_llm, call_llm_streaming
from attocode.core.tool_executor import build_tool_result_messages, execute_tool_calls


# Context overflow guard constants
MAX_SINGLE_TOOL_RESULT_TOKENS = 50_000
MAX_TOTAL_TOOL_RESULTS_TOKENS = 100_000
TRUNCATION_SUFFIX = "\n\n[... output truncated ({original} chars → {truncated} chars)]"


@dataclass(slots=True)
class LoopResult:
    """Result of the execution loop."""

    success: bool
    response: str
    reason: CompletionReason
    message: str = ""


@dataclass(slots=True)
class BudgetPreflightResult:
    """Result of budget pre-flight check."""

    can_continue: bool
    reason: CompletionReason | None = None
    message: str = ""
    recovery_action: str | None = None
    force_text_only: bool = False
    injected_nudge: str = ""


@dataclass(slots=True)
class CompactionResult:
    """Result of auto-compaction attempt."""

    compacted: bool
    messages_before: int = 0
    messages_after: int = 0
    tokens_saved: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Extracted testable functions
# ---------------------------------------------------------------------------


def check_iteration_budget(ctx: AgentContext) -> BudgetPreflightResult:
    """Budget pre-flight check with recovery actions.

    Checks iteration budget, token budget, economics budget, and
    duration budget. Returns recovery actions when possible instead
    of immediately stopping.
    """
    # 1. Cancellation
    if ctx.is_cancelled:
        return BudgetPreflightResult(
            can_continue=False,
            reason=CompletionReason.CANCELLED,
            message="Cancelled by user",
        )

    # 2. Iteration limit
    if not ctx.check_iteration_budget():
        return BudgetPreflightResult(
            can_continue=False,
            reason=CompletionReason.MAX_ITERATIONS,
            message=f"Reached iteration limit ({ctx.iteration})",
        )

    # 3. Token budget
    if not ctx.check_token_budget():
        # Try recovery: if economics allows and not already attempted
        if ctx.economics and not ctx.economics.recovery_attempted:
            ctx.economics.recovery_attempted = True
            return BudgetPreflightResult(
                can_continue=True,
                recovery_action="compaction",
                message="Token budget near limit — attempting compaction recovery",
                force_text_only=True,
            )
        return BudgetPreflightResult(
            can_continue=False,
            reason=CompletionReason.BUDGET_LIMIT,
            message="Token budget exhausted",
        )

    # 4. Economics check (richer, includes soft limits + nudges)
    if ctx.economics is not None:
        budget_check = ctx.economics.check_budget()

        ctx.emit_simple(
            EventType.BUDGET_CHECK,
            metadata={
                "status": budget_check.status,
                "usage_fraction": budget_check.usage_fraction,
                "force_text_only": budget_check.force_text_only,
            },
        )

        if not budget_check.can_continue:
            return BudgetPreflightResult(
                can_continue=False,
                reason=CompletionReason.BUDGET_LIMIT,
                message=budget_check.message,
            )

        nudge = ""
        if budget_check.injected_prompt:
            nudge = budget_check.injected_prompt

        return BudgetPreflightResult(
            can_continue=True,
            force_text_only=budget_check.force_text_only,
            injected_nudge=nudge,
        )

    # No economics — all clear
    return BudgetPreflightResult(can_continue=True)


async def handle_auto_compaction(ctx: AgentContext) -> CompactionResult:
    """Trigger compaction at thresholds.

    Two-stage protocol:
    1. Check if compaction is needed based on token usage
    2. If needed, ask LLM to summarize then compact messages

    Returns CompactionResult with stats.
    """
    if ctx.compaction_manager is None:
        return CompactionResult(compacted=False)

    check = ctx.compaction_manager.check(ctx.messages)

    if check.status.value not in ("needs_compaction",):
        return CompactionResult(compacted=False)

    messages_before = len(ctx.messages)

    ctx.emit_simple(
        EventType.COMPACTION_START,
        metadata={"usage": check.usage_fraction, "messages": messages_before},
    )

    try:
        # Stage 1: Ask LLM for summary
        summary_prompt = ctx.compaction_manager.create_summary_prompt()
        ctx.add_message(Message(role=Role.USER, content=summary_prompt))

        summary_response = await call_llm(ctx, max_retries=1)
        summary_text = summary_response.content or ""

        # Record summary LLM usage
        if summary_response.usage and ctx.economics:
            ctx.economics.record_llm_usage(
                summary_response.usage.input_tokens,
                summary_response.usage.output_tokens,
                summary_response.usage.cost,
            )

        # Stage 2: Compact messages with the summary
        # Gather extra context (work log, goals) if available
        extra_context: list[str] = []
        if ctx.goal:
            extra_context.append(f"Goal: {ctx.goal}")

        compacted = ctx.compaction_manager.compact(
            ctx.messages, summary_text, extra_context=extra_context or None,
        )
        messages_after = len(compacted)
        ctx.messages = compacted

        # Update economics baseline after compaction
        if ctx.economics:
            ctx.economics.update_baseline(ctx.metrics.total_tokens)

        # Log compaction in session store
        if ctx.session_store and ctx.session_id:
            try:
                await ctx.session_store.log_compaction(
                    ctx.session_id,
                    ctx.iteration,
                    messages_before,
                    messages_after,
                    tokens_saved=0,  # estimate later
                    strategy="auto",
                )
            except Exception:
                pass

        ctx.emit_simple(
            EventType.COMPACTION_COMPLETE,
            metadata={
                "messages_before": messages_before,
                "messages_after": messages_after,
            },
        )

        return CompactionResult(
            compacted=True,
            messages_before=messages_before,
            messages_after=messages_after,
        )

    except Exception as e:
        ctx.emit_simple(EventType.COMPACTION_ERROR, error=str(e))
        return CompactionResult(compacted=False, error=str(e))


def apply_context_overflow_guard(
    messages: list[Message | Any],
    *,
    max_single_result: int = MAX_SINGLE_TOOL_RESULT_TOKENS,
    max_total_results: int = MAX_TOTAL_TOOL_RESULTS_TOKENS,
    chars_per_token: float = 3.5,
) -> tuple[list[Message | Any], int]:
    """Mass tool result truncation to prevent context overflow.

    Scans recent tool result messages and truncates any that are
    excessively large. Works on character counts using chars_per_token
    conversion.

    Returns:
        Tuple of (possibly-modified messages, number of truncations).
    """
    max_single_chars = int(max_single_result * chars_per_token)
    max_total_chars = int(max_total_results * chars_per_token)
    truncations = 0
    total_tool_chars = 0

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = getattr(msg, "role", None)
        if role != Role.TOOL:
            continue

        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue

        content_len = len(content)
        total_tool_chars += content_len

        # Check single result limit
        if content_len > max_single_chars:
            truncated = content[:max_single_chars] + TRUNCATION_SUFFIX.format(
                original=content_len, truncated=max_single_chars,
            )
            messages[i] = Message(
                role=Role.TOOL,
                content=truncated,
                tool_call_id=getattr(msg, "tool_call_id", None),
            )
            truncations += 1

        # Check total results limit (truncate oldest first)
        if total_tool_chars > max_total_chars:
            # Aggressively truncate this (older) result
            keep_chars = max(500, max_single_chars // 4)
            if content_len > keep_chars:
                truncated = content[:keep_chars] + TRUNCATION_SUFFIX.format(
                    original=content_len, truncated=keep_chars,
                )
                messages[i] = Message(
                    role=Role.TOOL,
                    content=truncated,
                    tool_call_id=getattr(msg, "tool_call_id", None),
                )
                truncations += 1

    return messages, truncations


# ---------------------------------------------------------------------------
# Main execution loop
# ---------------------------------------------------------------------------


async def run_execution_loop(
    ctx: AgentContext,
    *,
    max_retries_per_call: int = 3,
) -> LoopResult:
    """Run the main ReAct execution loop.

    Flow per iteration:
    1. Recitation injection (periodic goal reinforcement)
    2. Budget pre-flight (iteration + token + economics + recovery)
    3. Context overflow guard (truncate large tool results)
    4. Auto-compaction (summarize + compact at threshold)
    5. Call LLM
    6. Set economics baseline after first LLM call
    7. Analyze response for completion
    8. If tool calls: execute tools, add results to messages, loop
    9. If no tool calls: return final response

    Args:
        ctx: Agent context with all dependencies and state.
        max_retries_per_call: Max LLM call retries on retryable errors.

    Returns:
        LoopResult with the final response and completion reason.
    """
    start_time = time.monotonic()
    last_response = ""
    baseline_set = False

    ctx.emit_simple(EventType.START, task="execution_loop")

    try:
        while True:
            ctx.iteration += 1

            ctx.emit_simple(
                EventType.ITERATION,
                iteration=ctx.iteration,
                tokens=ctx.metrics.total_tokens,
                cost=ctx.metrics.estimated_cost,
            )

            # 0. Recitation injection (periodic goal reinforcement)
            if ctx.recitation_manager is not None:
                try:
                    from attocode.tricks.recitation import RecitationState
                    rec_state = RecitationState(
                        iteration=ctx.iteration,
                        goal=ctx.goal,
                    )
                    if ctx.recitation_manager.should_inject(ctx.iteration):
                        content = ctx.recitation_manager.build_recitation(rec_state)
                        if content:
                            ctx.add_message(Message(
                                role=Role.USER,
                                content=f"[Status Recitation]\n{content}",
                            ))
                except Exception:
                    pass  # Recitation failure is non-fatal

            # 1. Budget pre-flight with recovery
            preflight = check_iteration_budget(ctx)

            if not preflight.can_continue:
                if preflight.reason == CompletionReason.BUDGET_LIMIT:
                    ctx.emit_simple(
                        EventType.BUDGET_EXHAUSTED,
                        metadata={"message": preflight.message},
                    )
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=preflight.reason or CompletionReason.ERROR,
                    message=preflight.message,
                )

            # Recovery action: trigger compaction
            if preflight.recovery_action == "compaction":
                await handle_auto_compaction(ctx)

            # Inject budget nudge if present
            if preflight.injected_nudge:
                ctx.add_message(Message(
                    role=Role.USER,
                    content=f"[System: {preflight.injected_nudge}]",
                ))

            # 2. Context overflow guard
            ctx.messages, truncation_count = apply_context_overflow_guard(ctx.messages)
            if truncation_count > 0:
                ctx.emit_simple(
                    EventType.CONTEXT_OVERFLOW,
                    metadata={"truncations": truncation_count},
                )

            # 3. Auto-compaction check
            compaction_result = await handle_auto_compaction(ctx)

            # 4. Call LLM (streaming when provider supports it)
            try:
                response = await call_llm_streaming(
                    ctx,
                    max_retries=max_retries_per_call,
                )
            except CancellationError:
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=CompletionReason.CANCELLED,
                )
            except asyncio.CancelledError:
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=CompletionReason.CANCELLED,
                )
            except BudgetExhaustedError:
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=CompletionReason.BUDGET_LIMIT,
                    message="Budget exhausted during LLM call",
                )
            except Exception as e:
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=CompletionReason.ERROR,
                    message=f"LLM error: {e}",
                )

            # 5. Record usage in economics and set baseline
            if response.usage and ctx.economics:
                ctx.economics.record_llm_usage(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    response.usage.cost,
                    cache_read_tokens=response.usage.cache_read_tokens,
                )
                if not baseline_set:
                    ctx.economics.set_baseline()
                    baseline_set = True

            # Track the latest response text
            if response.content:
                last_response = response.content

            # 6. Add assistant message to history
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content or "",
                tool_calls=response.tool_calls,
            )
            ctx.add_message(assistant_msg)

            # 7. Analyze completion
            analysis = analyze_completion(response)

            if analysis.should_stop and not response.has_tool_calls:
                # Agent is done
                ctx.emit_simple(
                    EventType.COMPLETE,
                    result=analysis.reason,
                    metadata={"iterations": ctx.iteration},
                )
                return LoopResult(
                    success=analysis.reason == CompletionReason.COMPLETED,
                    response=last_response,
                    reason=analysis.reason,
                    message=analysis.message,
                )

            # 8. Execute tool calls if present
            if response.has_tool_calls:
                tool_results = await execute_tool_calls(
                    ctx,
                    response.tool_calls,
                )

                # Record failures in failure tracker
                if ctx.failure_tracker is not None:
                    from attocode.tricks.failure_evidence import FailureInput
                    for tc, tr in zip(response.tool_calls, tool_results):
                        if tr.is_error and tr.error:
                            try:
                                ctx.failure_tracker.record_failure(FailureInput(
                                    action=tc.name,
                                    error=tr.error,
                                    args=tc.arguments,
                                    iteration=ctx.iteration,
                                ))
                            except Exception:
                                pass

                # Inject failure context if there are unresolved failures
                if ctx.failure_tracker is not None:
                    try:
                        failure_ctx = ctx.failure_tracker.get_failure_context(max_failures=3)
                        if failure_ctx:
                            ctx.add_message(Message(
                                role=Role.USER,
                                content=f"[System: {failure_ctx}]",
                            ))
                    except Exception:
                        pass

                # Build and add tool result messages
                tool_messages = build_tool_result_messages(
                    response.tool_calls,
                    tool_results,
                )
                ctx.add_messages(tool_messages)

                # Auto-checkpoint after tool batch
                if ctx.auto_checkpoint is not None:
                    try:
                        ctx.auto_checkpoint.check_and_save(
                            ctx.iteration,
                            f"After {len(tool_results)} tool calls",
                        )
                    except Exception:
                        pass

            # Loop continues for next iteration

    except asyncio.CancelledError:
        return LoopResult(
            success=False,
            response=last_response,
            reason=CompletionReason.CANCELLED,
        )
    except Exception as e:
        ctx.emit_simple(EventType.ERROR, error=str(e))
        return LoopResult(
            success=False,
            response=last_response,
            reason=CompletionReason.ERROR,
            message=str(e),
        )
    finally:
        duration = time.monotonic() - start_time
        ctx.metrics.duration_ms = duration * 1000


def loop_result_to_agent_result(result: LoopResult, ctx: AgentContext) -> AgentResult:
    """Convert a LoopResult to an AgentResult."""
    return AgentResult(
        success=result.success,
        response=result.response,
        completion=AgentCompletionStatus(
            success=result.success,
            reason=result.reason,
            details=result.message or None,
        ),
        metrics=ctx.metrics,
        error=result.message if not result.success else None,
    )
