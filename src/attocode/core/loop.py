"""Execution loop - the main async ReAct loop for the agent.

Includes extracted testable functions:
- check_iteration_budget() — budget pre-flight with recovery actions
- handle_auto_compaction() — trigger compaction at thresholds
- handle_fresh_context_refresh() — refresh context at dumb zone
- apply_context_overflow_guard() — mass tool result truncation
- check_external_cancellation() — subagent cancellation + wrapup
- inject_recitation() — periodic goal reinforcement
- accumulate_failure_evidence() — compact failure summaries
- invalidate_ast_on_edit() — AST cache invalidation after edits

Dataclasses:
- LoopResult — final result of the execution loop
- BudgetPreflightResult — budget pre-flight check result
- CompactionResult — auto-compaction attempt result
- WrapupState — graceful wrapup phase tracking for subagents
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from attocode.core.completion import analyze_completion
from attocode.core.response_handler import call_llm, call_llm_streaming
from attocode.core.tool_executor import build_tool_result_messages, execute_tool_calls
from attocode.errors import BudgetExhaustedError, CancellationError
from attocode.types.agent import AgentCompletionStatus, AgentResult, CompletionReason
from attocode.types.events import EventType
from attocode.types.messages import Message, Role, ToolResult

if TYPE_CHECKING:
    from attocode.agent.context import AgentContext

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


@dataclass(slots=True)
class WrapupState:
    """Tracks graceful wrapup phase for subagents."""

    wrapup_requested: bool = False
    wrapup_start_time: float = 0.0
    wrapup_timeout: float = 30.0  # seconds to complete after wrapup
    force_text_only: bool = False
    wrapup_reason: str = ""
    wrapup_iterations_remaining: int = 3  # max iterations in wrapup

    def request_wrapup(self, reason: str = "timeout") -> None:
        """Request graceful wrapup."""
        if not self.wrapup_requested:
            self.wrapup_requested = True
            self.wrapup_start_time = time.monotonic()
            self.wrapup_reason = reason

    @property
    def wrapup_expired(self) -> bool:
        """Check if wrapup timeout has elapsed."""
        if not self.wrapup_requested:
            return False
        elapsed = time.monotonic() - self.wrapup_start_time
        return elapsed > self.wrapup_timeout or self.wrapup_iterations_remaining <= 0

    def tick(self) -> None:
        """Called each iteration during wrapup."""
        if self.wrapup_requested:
            self.wrapup_iterations_remaining -= 1


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


async def handle_auto_compaction(
    ctx: AgentContext,
    *,
    force: bool = False,
    reason: str = "auto",
) -> CompactionResult:
    """Trigger compaction at thresholds.

    Two-stage protocol:
    1. Check if compaction is needed based on token usage
    2. If needed, ask LLM to summarize then compact messages

    Returns CompactionResult with stats.
    """
    if ctx.compaction_manager is None:
        return CompactionResult(compacted=False)

    check = ctx.compaction_manager.check(ctx.messages)
    context_usage = check.usage_fraction
    budget_usage = 0.0
    if ctx.economics is not None:
        try:
            budget_usage = float(getattr(ctx.economics, "usage_fraction", 0.0))
        except Exception:
            budget_usage = 0.0
    threshold = float(getattr(ctx.compaction_manager, "compaction_threshold", 0.8))
    effective_usage = max(context_usage, budget_usage)

    context_trigger = check.status.value in ("needs_compaction",) or context_usage >= threshold
    budget_trigger = budget_usage >= threshold
    needs_compaction = force or context_trigger or budget_trigger
    if not needs_compaction:
        return CompactionResult(compacted=False)

    messages_before = len(ctx.messages)
    trigger_basis = "both" if context_trigger and budget_trigger else ("context" if context_trigger else ("budget" if budget_trigger else "forced"))

    ctx.emit_simple(
        EventType.COMPACTION_START,
        metadata={
            "usage": effective_usage,
            "context_usage": context_usage,
            "budget_usage": budget_usage,
            "messages": messages_before,
            "trigger_basis": trigger_basis,
            "force": force,
            "reason": reason,
        },
    )

    try:
        use_emergency = force and check.status.value not in ("needs_compaction",)
        if use_emergency:
            compacted = ctx.compaction_manager.emergency_compact(ctx.messages)
            messages_after = len(compacted)
            ctx.messages = compacted
            tokens_after = ctx.compaction_manager.check(ctx.messages).estimated_tokens
            tokens_saved = max(0, check.estimated_tokens - tokens_after)

            if ctx.economics:
                ctx.economics.update_baseline(ctx.metrics.total_tokens)

            if ctx.session_store and ctx.session_id:
                try:
                    await ctx.session_store.log_compaction(
                        ctx.session_id,
                        ctx.iteration,
                        messages_before,
                        messages_after,
                        tokens_saved=tokens_saved,
                        strategy="auto_emergency",
                    )
                except Exception:
                    pass

            ctx.emit_simple(
                EventType.COMPACTION_COMPLETE,
                metadata={
                    "messages_before": messages_before,
                    "messages_after": messages_after,
                    "tokens_saved": tokens_saved,
                    "trigger_basis": trigger_basis,
                    "strategy": "emergency",
                },
            )

            return CompactionResult(
                compacted=True,
                messages_before=messages_before,
                messages_after=messages_after,
                tokens_saved=tokens_saved,
            )

        # Stage 0: Extract references for reversible compaction
        from attocode.tricks.reversible_compaction import (
            ReversibleCompactor,
            extract_references,
        )
        preserved_refs_block = ""
        try:
            compactor = getattr(ctx, "_reversible_compactor", None)
            if compactor is None:
                compactor = ReversibleCompactor()
                ctx._reversible_compactor = compactor  # type: ignore[attr-defined]

            # Extract references from messages being compacted
            all_refs = []
            for i, msg in enumerate(ctx.messages):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content:
                    refs = extract_references(
                        content,
                        ["file", "url", "function", "error"],
                        source_index=i,
                    )
                    all_refs.extend(refs)

            # Deduplicate
            seen: set[str] = set()
            deduped = []
            for ref in all_refs:
                key = f"{ref.type}:{ref.value}"
                if key not in seen:
                    seen.add(key)
                    deduped.append(ref)

            if deduped:
                preserved_refs_block = compactor.format_references_block(deduped[:100])
                # Store references on compactor for potential later retrieval
                compactor._references.extend(deduped[:100])
        except Exception:
            pass

        # Stage 1: Ask LLM for summary (with semantic cache)
        summary_prompt = ctx.compaction_manager.create_summary_prompt()

        # Check semantic cache for a similar summary
        semantic_cache = getattr(ctx, "_semantic_cache", None)
        cached_summary = None
        if semantic_cache is not None:
            try:
                cached_summary = semantic_cache.get(summary_prompt)
            except Exception:
                pass

        if cached_summary and isinstance(cached_summary, str):
            summary_text = cached_summary
        else:
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

            # Cache the summary for future use
            if semantic_cache is not None and summary_text:
                try:
                    semantic_cache.put(summary_prompt, summary_text)
                except Exception:
                    pass

        # Stage 2: Compact messages with the summary
        # Gather extra context (work log, goals) if available
        extra_context: list[str] = []
        if ctx.goal:
            extra_context.append(f"Goal: {ctx.goal}")

        compacted = ctx.compaction_manager.compact(
            ctx.messages, summary_text, extra_context=extra_context or None,
        )

        # Stage 3: Append preserved references block after compaction
        if preserved_refs_block:
            compacted.append(Message(
                role=Role.USER,
                content=f"[System: {preserved_refs_block}]",
            ))

        messages_after = len(compacted)
        ctx.messages = compacted
        tokens_after = ctx.compaction_manager.check(ctx.messages).estimated_tokens
        tokens_saved = max(0, check.estimated_tokens - tokens_after)

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
                    tokens_saved=tokens_saved,
                    strategy="auto",
                )
            except Exception:
                pass

        ctx.emit_simple(
            EventType.COMPACTION_COMPLETE,
            metadata={
                "messages_before": messages_before,
                "messages_after": messages_after,
                "tokens_saved": tokens_saved,
                "trigger_basis": trigger_basis,
                "strategy": "summary",
            },
        )

        return CompactionResult(
            compacted=True,
            messages_before=messages_before,
            messages_after=messages_after,
            tokens_saved=tokens_saved,
        )

    except Exception as e:
        ctx.emit_simple(EventType.COMPACTION_ERROR, error=str(e))
        return CompactionResult(compacted=False, error=str(e))


async def handle_fresh_context_refresh(ctx: AgentContext) -> CompactionResult:
    """Refresh context when in the dumb zone (40-60% fill).

    Preserves the old conversation in a thread fork and replaces
    messages with a structured handoff summary for peak-quality
    continuation.

    Returns CompactionResult with stats.
    """
    if ctx.compaction_manager is None:
        return CompactionResult(compacted=False)

    if not ctx.compaction_manager.should_refresh_context(ctx.messages):
        return CompactionResult(compacted=False)

    messages_before = len(ctx.messages)
    check = ctx.compaction_manager.check(ctx.messages)
    refresh_count = ctx.compaction_manager.fresh_context_count + 1

    ctx.emit_simple(
        EventType.CONTEXT_FRESH_REFRESH,
        metadata={
            "phase": "start",
            "usage_fraction": check.usage_fraction,
            "messages": messages_before,
            "refresh_number": refresh_count,
        },
    )

    try:
        # Ask LLM for structured handoff summary
        handoff_prompt = ctx.compaction_manager.create_handoff_summary_prompt()
        ctx.add_message(Message(role=Role.USER, content=handoff_prompt))

        summary_response = await call_llm(ctx, max_retries=1)
        summary_text = summary_response.content or ""

        if summary_response.usage and ctx.economics:
            ctx.economics.record_llm_usage(
                summary_response.usage.input_tokens,
                summary_response.usage.output_tokens,
                summary_response.usage.cost,
            )

        if not summary_text.strip():
            return CompactionResult(compacted=False, error="Empty handoff summary")

        # Fork old conversation if thread manager is available
        thread_manager = getattr(ctx, "thread_manager", None)
        if thread_manager is not None:
            try:
                thread_manager.create_fork(
                    label=f"Fresh context #{refresh_count}",
                    fork_at=messages_before,
                    messages=list(ctx.messages),
                )
            except Exception:
                pass  # Fork is optional — don't block refresh

        # Build fresh context: system msgs + handoff exchange + recent msgs
        system_msgs = [
            m for m in ctx.messages
            if hasattr(m, "role") and m.role == Role.SYSTEM
        ]
        non_system = [
            m for m in ctx.messages
            if not (hasattr(m, "role") and m.role == Role.SYSTEM)
        ]

        keep_recent = min(ctx.compaction_manager.min_messages_to_keep, len(non_system))
        recent = non_system[-keep_recent:] if keep_recent > 0 else []

        new_messages: list[Message | Any] = list(system_msgs)
        new_messages.append(Message(
            role=Role.USER,
            content=(
                "Context has been refreshed for optimal quality. "
                "Here is a structured handoff summary of the work so far:"
            ),
        ))
        new_messages.append(Message(
            role=Role.ASSISTANT,
            content=summary_text,
        ))

        if ctx.goal:
            new_messages.append(Message(
                role=Role.USER,
                content=f"Current goal: {ctx.goal}\n\nPlease continue.",
            ))

        new_messages.extend(recent)

        messages_after = len(new_messages)
        ctx.messages = new_messages

        tokens_after = ctx.compaction_manager.check(ctx.messages).estimated_tokens
        tokens_saved = max(0, check.estimated_tokens - tokens_after)

        ctx.compaction_manager.record_fresh_context()

        if ctx.economics:
            ctx.economics.update_baseline(ctx.metrics.total_tokens)

        if ctx.session_store and ctx.session_id:
            try:
                await ctx.session_store.log_compaction(
                    ctx.session_id,
                    ctx.iteration,
                    messages_before,
                    messages_after,
                    tokens_saved=tokens_saved,
                    strategy="fresh_context",
                )
            except Exception:
                pass

        ctx.emit_simple(
            EventType.CONTEXT_FRESH_REFRESH,
            metadata={
                "phase": "complete",
                "messages_before": messages_before,
                "messages_after": messages_after,
                "tokens_saved": tokens_saved,
                "refresh_number": refresh_count,
            },
        )

        return CompactionResult(
            compacted=True,
            messages_before=messages_before,
            messages_after=messages_after,
            tokens_saved=tokens_saved,
        )

    except Exception as e:
        ctx.emit_simple(EventType.COMPACTION_ERROR, error=f"fresh_context: {e}")
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


def check_external_cancellation(ctx: AgentContext, wrapup: WrapupState) -> BudgetPreflightResult | None:
    """Check external cancellation token and wrapup state.

    For subagents, the parent can signal cancellation via
    an external cancellation token or wrapup request.

    Returns BudgetPreflightResult if should stop, None if OK.
    """
    # Check external cancellation token
    cancel_token = getattr(ctx, 'external_cancellation_token', None)
    if cancel_token is not None:
        is_cancelled = False
        if callable(getattr(cancel_token, 'is_cancelled', None)):
            is_cancelled = cancel_token.is_cancelled()
        elif hasattr(cancel_token, 'is_set'):
            is_cancelled = cancel_token.is_set()

        if is_cancelled:
            if not wrapup.force_text_only:
                wrapup.request_wrapup("parent_cancellation")
                wrapup.force_text_only = True
                return None  # Allow one more iteration to wrap up
            return BudgetPreflightResult(
                can_continue=False,
                reason=CompletionReason.CANCELLED,
                message="Cancelled by parent agent",
            )

    # Check wrapup expiry
    if wrapup.wrapup_expired:
        return BudgetPreflightResult(
            can_continue=False,
            reason=CompletionReason.BUDGET_LIMIT,
            message=f"Wrapup timeout expired (reason: {wrapup.wrapup_reason})",
        )

    return None


def inject_recitation(ctx: AgentContext, iteration: int) -> str | None:
    """Inject goal recitation if the recitation manager says it's time.

    Returns the recitation content if injected, None otherwise.
    """
    if ctx.recitation_manager is None:
        return None

    try:
        from attocode.tricks.recitation import RecitationState

        # Build recitation state with available context
        failure_count = 0
        if ctx.failure_tracker:
            try:
                failure_count = len(ctx.failure_tracker.get_unresolved_failures())
            except Exception:
                pass

        files_modified = 0
        work_log = getattr(ctx, '_work_log', None)
        if work_log:
            try:
                files_modified = work_log.files_modified_count
            except Exception:
                pass

        rec_state = RecitationState(
            iteration=iteration,
            goal=ctx.goal,
            failure_count=failure_count,
            files_modified=files_modified,
        )

        if ctx.recitation_manager.should_inject(iteration):
            content = ctx.recitation_manager.build_recitation(rec_state)
            if content:
                return content
    except Exception:
        pass

    return None


def accumulate_failure_evidence(ctx: AgentContext) -> str | None:
    """Build failure evidence summary for budget check injection.

    When there are unresolved failures, generates a compact summary
    to inject into the context so the LLM can learn from past mistakes.

    Returns failure summary string or None.
    """
    if ctx.failure_tracker is None:
        return None

    try:
        unresolved = ctx.failure_tracker.get_unresolved_failures()
        if not unresolved:
            return None

        # Build compact summary
        parts = [f"Unresolved failures ({len(unresolved)}):"]
        for i, failure in enumerate(unresolved[:5]):  # Max 5
            action = getattr(failure, 'action', 'unknown')
            error = getattr(failure, 'error', 'unknown')
            # Truncate error to keep context small
            if len(error) > 150:
                error = error[:147] + "..."
            parts.append(f"  {i+1}. {action}: {error}")

        if len(unresolved) > 5:
            parts.append(f"  ... and {len(unresolved) - 5} more")

        return "\n".join(parts)
    except Exception:
        return None


def invalidate_ast_on_edit(ctx: AgentContext, tool_name: str, tool_args: dict) -> None:
    """Invalidate and incrementally update codebase AST cache after file-editing tools.

    When the agent edits a file, marks it dirty in the CodebaseContextManager
    for incremental re-parsing.  Also invalidates the CodeAnalyzer cache entry
    so the next analyze_file() call re-reads from disk.
    """
    FILE_EDIT_TOOLS = {"write_file", "edit_file", "create_file", "patch_file", "replace_in_file"}  # noqa: N806

    if tool_name not in FILE_EDIT_TOOLS:
        return

    # Extract file path from tool arguments
    file_path = tool_args.get("path") or tool_args.get("file_path") or tool_args.get("target")
    if not file_path:
        return

    # Mark dirty in CodebaseContextManager for incremental update
    codebase_context = getattr(ctx, 'codebase_context', None)
    if codebase_context is not None and hasattr(codebase_context, 'mark_file_dirty'):
        try:
            codebase_context.mark_file_dirty(file_path)
            codebase_context.invalidate_file(file_path)
            # Trigger incremental re-parse
            codebase_context.update_dirty_files()
        except Exception:
            pass


async def collect_lsp_diagnostics(
    ctx: AgentContext,
    tool_name: str,
    tool_args: dict,
) -> str | None:
    """Collect LSP diagnostics after file-editing tool calls.

    Notifies the LSP server of the file change, waits briefly for
    diagnostics, and returns a formatted string of errors/warnings
    to inject into context. Returns None if no diagnostics or LSP
    is not available.
    """
    FILE_EDIT_TOOLS = {"write_file", "edit_file", "create_file", "patch_file", "replace_in_file"}  # noqa: N806

    if tool_name not in FILE_EDIT_TOOLS:
        return None

    lsp_manager = getattr(ctx, "_lsp_manager", None)
    if lsp_manager is None:
        return None

    file_path = tool_args.get("path") or tool_args.get("file_path") or tool_args.get("target")
    if not file_path:
        return None

    try:
        import os
        abs_path = os.path.abspath(file_path)

        # Read updated file content and notify LSP
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return None

        lsp_manager.notify_file_changed(abs_path, content)

        # Brief wait for the LSP server to publish diagnostics
        await asyncio.sleep(0.3)

        diagnostics = lsp_manager.get_diagnostics(abs_path)
        if not diagnostics:
            return None

        # Filter to errors and warnings only
        important = [d for d in diagnostics if d.severity in ("error", "warning")]
        if not important:
            return None

        # Format diagnostics for injection
        parts = [f"LSP diagnostics for {os.path.basename(abs_path)} ({len(important)} issue{'s' if len(important) != 1 else ''}):"]
        for d in important[:10]:  # Cap at 10
            line = d.range.start.line + 1  # 0-indexed to 1-indexed
            parts.append(f"  L{line} [{d.severity}]: {d.message}")
            if d.source:
                parts[-1] += f" ({d.source})"

        if len(important) > 10:
            parts.append(f"  ... and {len(important) - 10} more issues")

        return "\n".join(parts)
    except Exception:
        return None


def format_wrapup_nudge(wrapup: WrapupState) -> str:
    """Build the wrapup nudge message based on remaining iterations.

    Adjusts urgency based on how many wrapup iterations remain:
    - 3+ remaining: gentle reminder
    - 2 remaining: moderate urgency
    - 1 remaining: final chance
    - 0 remaining: should not reach here (wrapup_expired catches it)
    """
    remaining = wrapup.wrapup_iterations_remaining
    reason = wrapup.wrapup_reason

    if remaining >= 3:
        return (
            f"Wrapping up (reason: {reason}). "
            "Please complete your current task and provide a final summary. "
            f"You have {remaining} iterations remaining."
        )
    elif remaining == 2:
        return (
            f"Wrapup in progress (reason: {reason}). "
            "Finish what you are doing now and summarize your work. "
            "2 iterations remaining."
        )
    elif remaining == 1:
        return (
            f"FINAL iteration (reason: {reason}). "
            "You MUST provide your final summary NOW. "
            "This is your last chance to respond."
        )
    else:
        return (
            f"Wrapup expired (reason: {reason}). "
            "Provide your final summary immediately."
        )


def _extract_keywords(args: dict[str, Any]) -> list[str]:
    """Extract meaningful keywords from tool arguments for recommendation tracking."""
    keywords: list[str] = []
    for key in ("path", "file_path", "pattern", "query", "glob"):
        val = args.get(key)
        if isinstance(val, str) and val and not val.startswith("*"):
            parts = val.replace("\\", "/").split("/")
            kw = parts[-1] if parts else val
            if len(kw) >= 3:
                keywords.append(kw)
    # Extract base command (e.g. "npm" from "npm test")
    cmd = args.get("command")
    if isinstance(cmd, str) and cmd:
        base = cmd.strip().split()[0]
        if base:
            keywords.append(base)
    return list(dict.fromkeys(keywords))  # deduplicate preserving order


def emit_loop_summary(ctx: AgentContext, start_time: float) -> None:
    """Emit a summary event with loop statistics at the end of the loop."""
    duration = time.monotonic() - start_time
    ctx.emit_simple(
        EventType.COMPLETE,
        metadata={
            "total_iterations": ctx.iteration,
            "total_tokens": ctx.metrics.total_tokens,
            "duration_s": round(duration, 2),
            "estimated_cost": ctx.metrics.estimated_cost,
        },
    )


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
    0. Recitation injection (periodic goal reinforcement via inject_recitation)
    1. Budget pre-flight (iteration + token + economics + recovery)
    1b. External cancellation / wrapup check (subagent lifecycle)
    2. Context overflow guard (truncate large tool results)
    3. Auto-compaction (summarize + compact at threshold)
    4. Call LLM (streaming when provider supports it)
    5. Record usage in economics and set baseline after first call
    6. Add assistant message to history
    7. Analyze response for completion (learning store + self-improvement)
    8. If tool calls present:
       a. Execute all tool calls in batch
       b. Record in economics (loop detection + phase tracking)
       c. Record failures in failure tracker
       d. Inject failure context for unresolved failures
       e. Inject accumulated failure evidence (every 5 iterations)
       f. Invalidate AST cache for file-editing tools
       g. Build and add tool result messages
       h. Record in work log and dead letter queue
       i. Auto-checkpoint after tool batch
    9. If no tool calls: return final response

    Wrapup Protocol (subagents):
    When a parent agent signals cancellation via an external token,
    the loop enters wrapup mode. In wrapup:
    - force_text_only is set so the LLM produces text, not tools
    - A nudge is injected asking for a final summary
    - The wrapup has a limited number of iterations (default 3)
    - After wrapup expires, the loop terminates

    Args:
        ctx: Agent context with all dependencies and state.
        max_retries_per_call: Max LLM call retries on retryable errors.

    Returns:
        LoopResult with the final response and completion reason.
    """
    start_time = time.monotonic()
    last_response = ""
    baseline_set = False
    wrapup = WrapupState()
    consecutive_tool_errors = 0
    incomplete_auto_retries = 0
    max_incomplete_auto_retries = 2

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
            recitation_content = inject_recitation(ctx, ctx.iteration)
            if recitation_content:
                ctx.add_message(Message(
                    role=Role.USER,
                    content=f"[Status Recitation]\n{recitation_content}",
                ))

            # 1. Budget pre-flight with recovery
            preflight = check_iteration_budget(ctx)

            if not preflight.can_continue:
                if preflight.reason == CompletionReason.BUDGET_LIMIT:
                    ctx.emit_simple(
                        EventType.BUDGET_EXHAUSTED,
                        metadata={
                            "message": preflight.message,
                            "usage_fraction": ctx.economics.usage_fraction if ctx.economics else 1.0,
                        },
                    )
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=preflight.reason or CompletionReason.ERROR,
                    message=preflight.message,
                )

            # Recovery action: trigger compaction
            if preflight.recovery_action == "compaction":
                await handle_auto_compaction(ctx, force=True, reason="budget_recovery")

            # 1b. External cancellation / wrapup check
            ext_check = check_external_cancellation(ctx, wrapup)
            if ext_check is not None and not ext_check.can_continue:
                return LoopResult(
                    success=False,
                    response=last_response,
                    reason=ext_check.reason or CompletionReason.CANCELLED,
                    message=ext_check.message,
                )

            # Apply wrapup force_text_only
            if wrapup.force_text_only:
                wrapup_nudge = format_wrapup_nudge(wrapup)
                preflight = BudgetPreflightResult(
                    can_continue=True,
                    force_text_only=True,
                    injected_nudge=preflight.injected_nudge or wrapup_nudge,
                )
                ctx.emit_simple(
                    EventType.BUDGET_CHECK,
                    metadata={
                        "wrapup": True,
                        "wrapup_reason": wrapup.wrapup_reason,
                        "iterations_remaining": wrapup.wrapup_iterations_remaining,
                    },
                )
                wrapup.tick()

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

            # 2.5. Fresh context check (before compaction)
            _fresh_result = await handle_fresh_context_refresh(ctx)

            # 3. Auto-compaction check (skip if fresh context already triggered)
            if not _fresh_result.compacted:
                _compaction_result = await handle_auto_compaction(ctx)

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
                # Streaming failed — attempt a non-streaming fallback before
                # giving up entirely.  This catches httpx.StreamError and other
                # mid-stream failures that exhaust streaming retries.
                ctx.emit_simple(
                    EventType.LLM_ERROR,
                    error=f"Streaming failed: {e}; attempting non-streaming fallback",
                    iteration=ctx.iteration,
                )
                try:
                    response = await call_llm(ctx, max_retries=1, retry_base_delay=2.0)
                except (CancellationError, asyncio.CancelledError):
                    raise  # outer handler → CompletionReason.CANCELLED
                except BudgetExhaustedError:
                    raise  # outer handler → CompletionReason.BUDGET_LIMIT
                except Exception as fallback_err:
                    return LoopResult(
                        success=False,
                        response=last_response,
                        reason=CompletionReason.ERROR,
                        message=f"LLM error (streaming and non-streaming): {fallback_err}",
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
                if analysis.reason in (CompletionReason.FUTURE_INTENT, CompletionReason.INCOMPLETE_ACTION):
                    if incomplete_auto_retries < max_incomplete_auto_retries:
                        incomplete_auto_retries += 1
                        ctx.add_message(Message(
                            role=Role.USER,
                            content=(
                                "[System: Your previous response says work remains. "
                                "Do not wrap up yet. Continue implementation by calling the next "
                                "required tools now. If blocked, report the exact blocker with "
                                "the failing command/tool and error output.]"
                            ),
                        ))
                        continue
                    return LoopResult(
                        success=False,
                        response=last_response,
                        reason=analysis.reason,
                        message=analysis.message or "Model repeatedly returned narrative-only incomplete output.",
                    )

                # Record completion in learning store
                if ctx.learning_store is not None:
                    try:
                        ctx.learning_store.record_session_outcome(
                            success=analysis.reason == CompletionReason.COMPLETED,
                            iterations=ctx.iteration,
                            tokens=ctx.metrics.total_tokens,
                        )
                    except Exception:
                        pass

                # Note: self-improvement diagnosis happens per-tool-call
                # in the tool execution section below (SelfImprovementProtocol)

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
                incomplete_auto_retries = 0
                # Pre-filter: hard-block doom loop repeats (>= 5 identical calls)
                calls_to_execute = list(response.tool_calls)
                blocked_results: list[ToolResult] = []
                if ctx.economics is not None:
                    filtered = []
                    for tc in calls_to_execute:
                        detection = ctx.economics.loop_detector.peek(
                            tc.name, tc.arguments or {},
                        )
                        if detection.is_loop and detection.count >= 5:
                            blocked_results.append(ToolResult(
                                call_id=tc.id,
                                error=(
                                    f"Blocked: '{tc.name}' called {detection.count}x "
                                    "with identical args. Use different arguments "
                                    "or a different tool."
                                ),
                            ))
                        else:
                            filtered.append(tc)
                    calls_to_execute = filtered

                tool_results: list[ToolResult] = []
                if calls_to_execute:
                    tool_results = await execute_tool_calls(ctx, calls_to_execute)
                tool_results.extend(blocked_results)

                # Record in economics (loop detection + phase tracking)
                if ctx.economics is not None:
                    for tc, _tr in zip(response.tool_calls, tool_results, strict=False):
                        try:
                            loop_detection, phase_nudge = ctx.economics.record_tool_call(
                                tc.name,
                                arguments=tc.arguments,
                                iteration=ctx.iteration,
                            )
                            # Inject loop detection warning
                            if loop_detection and loop_detection.is_loop:
                                ctx.add_message(Message(
                                    role=Role.USER,
                                    content=(
                                        f"[System: Doom loop detected! '{tc.name}' called "
                                        f"{loop_detection.count} times with same args. "
                                        "Try a DIFFERENT approach.]"
                                    ),
                                ))
                            # Inject phase nudge
                            if phase_nudge:
                                ctx.add_message(Message(
                                    role=Role.USER,
                                    content=f"[System: {phase_nudge}]",
                                ))
                        except Exception:
                            pass

                # Record failures in failure tracker + self-improvement diagnosis
                if ctx.failure_tracker is not None:
                    from attocode.tricks.failure_evidence import FailureInput
                    for tc, tr in zip(response.tool_calls, tool_results, strict=False):
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

                # Self-improvement: diagnose tool failures, record successes
                self_improvement = getattr(ctx, "_self_improvement", None)
                if self_improvement is not None:
                    for tc, tr in zip(response.tool_calls, tool_results, strict=False):
                        try:
                            if tr.is_error and tr.error:
                                enhanced = self_improvement.enhance_error_message(
                                    tc.name,
                                    tr.error,
                                    tc.arguments or {},
                                )
                                # Inject diagnosis as system message if it adds info
                                if enhanced and enhanced != tr.error:
                                    ctx.add_message(Message(
                                        role=Role.USER,
                                        content=f"[System: Self-diagnosis for {tc.name} failure]\n{enhanced}",
                                    ))
                            else:
                                self_improvement.record_success(
                                    tc.name,
                                    tc.arguments or {},
                                    context=f"iteration_{ctx.iteration}",
                                )
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

                # Inject accumulated failure evidence into budget check
                failure_summary = accumulate_failure_evidence(ctx)
                if failure_summary and ctx.iteration % 5 == 0:  # Every 5 iterations
                    ctx.add_message(Message(
                        role=Role.USER,
                        content=f"[System: {failure_summary}]",
                    ))

                # Invalidate AST cache for file edits
                for tc in response.tool_calls:
                    invalidate_ast_on_edit(ctx, tc.name, tc.arguments or {})

                # Collect LSP diagnostics after file edits
                lsp_diagnostics_parts: list[str] = []
                if getattr(ctx, "_lsp_manager", None) is not None:
                    for tc, tr in zip(response.tool_calls, tool_results, strict=False):
                        if not tr.is_error:
                            try:
                                diag_msg = await collect_lsp_diagnostics(
                                    ctx, tc.name, tc.arguments or {},
                                )
                                if diag_msg:
                                    lsp_diagnostics_parts.append(diag_msg)
                            except Exception:
                                pass

                # Build and add tool result messages
                tool_messages = build_tool_result_messages(
                    response.tool_calls,
                    tool_results,
                )
                ctx.add_messages(tool_messages)

                # Inject LSP diagnostics as system feedback
                if lsp_diagnostics_parts:
                    combined = "\n".join(lsp_diagnostics_parts)
                    ctx.add_message(Message(
                        role=Role.USER,
                        content=f"[System: {combined}]",
                    ))

                # Record in work log if available
                work_log = getattr(ctx, "_work_log", None)
                if work_log is not None:
                    try:
                        for tc, tr in zip(response.tool_calls, tool_results, strict=False):
                            work_log.record_tool_call(
                                tc.name,
                                success=not tr.is_error,
                                iteration=ctx.iteration,
                            )
                    except Exception:
                        pass

                # Record in dead letter queue if tool errors
                dlq = getattr(ctx, "_dead_letter_queue", None)
                if dlq is not None:
                    for tc, tr in zip(response.tool_calls, tool_results, strict=False):
                        if tr.is_error:
                            try:
                                dlq.add(tc.name, tr.error or "Unknown error", tc.arguments)
                            except Exception:
                                pass

                # Track consecutive tool error batches (independent of recommender)
                batch_has_error = any(tr.is_error for tr in tool_results)
                if batch_has_error:
                    consecutive_tool_errors += 1
                else:
                    consecutive_tool_errors = 0

                # Tool recommendation: record usage and inject hints on repeated failures
                recommender = getattr(ctx, "_tool_recommender", None)
                if recommender is not None:
                    try:
                        # Determine current phase for task_type
                        phase = "unknown"
                        if ctx.economics is not None:
                            pt = getattr(ctx.economics, "phase_tracker", None)
                            if pt is not None:
                                phase = getattr(pt, "current_phase", "unknown")

                        for tc, tr in zip(response.tool_calls, tool_results, strict=False):
                            recommender.record_usage(
                                tool_name=tc.name,
                                task_type=phase,
                                success=not tr.is_error,
                                context_keywords=_extract_keywords(tc.arguments or {}),
                            )

                        # Inject tool recommendations after 3+ consecutive error batches
                        if consecutive_tool_errors >= 3:
                            recs = recommender.recommend(
                                task_type=phase,
                                context=(ctx.goal or "")[:500],
                                current_tools=[tc.name for tc in response.tool_calls],
                                max_results=3,
                            )
                            if recs:
                                hint = "Suggested tools based on patterns: " + ", ".join(
                                    f"{r.tool_name} ({r.reason})" for r in recs
                                )
                                ctx.add_message(Message(
                                    role=Role.USER,
                                    content=f"[System: {hint}]",
                                ))
                    except Exception:
                        pass

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
