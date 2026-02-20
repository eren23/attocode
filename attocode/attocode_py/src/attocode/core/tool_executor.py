"""Tool executor - handles parallel tool execution with error isolation.

Features:
- Parallel execution via asyncio.gather()
- Per-tool timeout handling
- Tool result size capping
- Permission checks before execution
- Economics integration (loop detection, phase tracking)
- Batched execution with configurable concurrency
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from attocode.types.events import EventType
from attocode.types.messages import Message, Role, ToolCall, ToolResult


if __name__ != "__main__":
    from attocode.agent.context import AgentContext


# Defaults
DEFAULT_TOOL_TIMEOUT = 120.0  # 2 minutes per tool
MAX_RESULT_CHARS = 100_000  # Cap individual tool results
MAX_CONCURRENT_TOOLS = 10  # Max parallel tool executions


@dataclass(slots=True)
class ToolExecutionStats:
    """Statistics from a batch of tool executions."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    denied: int = 0
    total_duration_ms: float = 0.0
    truncated: int = 0


async def _check_permission(ctx: AgentContext, tc: ToolCall) -> str | None:
    """Check tool permission via policy engine. Returns error string if denied, None if allowed."""
    if ctx.policy_engine is None:
        return None

    from attocode.integrations.safety.policy_engine import PolicyDecision

    result = ctx.policy_engine.evaluate(tc.name, tc.arguments)

    if result.decision == PolicyDecision.ALLOW:
        return None

    if result.decision == PolicyDecision.DENY:
        return f"Tool '{tc.name}' is denied by policy: {result.reason}"

    # PROMPT — need user approval
    if ctx.approval_callback is not None:
        try:
            approval = await ctx.approval_callback(
                tc.name,
                tc.arguments,
                result.danger_level,
                result.reason,
            )
            if hasattr(approval, "approved") and approval.approved:
                return None
            return f"Tool '{tc.name}' was denied by user"
        except Exception:
            return f"Tool '{tc.name}' approval timed out or failed"

    # No approval callback but policy says PROMPT — auto-allow in non-interactive mode
    return None


def _cap_result(content: str, max_chars: int = MAX_RESULT_CHARS) -> tuple[str, bool]:
    """Cap a tool result string to max_chars. Returns (content, was_truncated)."""
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars] + (
        f"\n\n[... output truncated ({len(content)} chars → {max_chars} chars)]"
    )
    return truncated, True


async def execute_single_tool(
    ctx: AgentContext,
    tc: ToolCall,
    *,
    timeout: float | None = None,
    max_result_chars: int = MAX_RESULT_CHARS,
) -> tuple[ToolResult, bool]:
    """Execute a single tool call with permission check, timeout, and result capping.

    Returns:
        Tuple of (ToolResult, was_truncated).
    """
    # Permission check
    denial = await _check_permission(ctx, tc)
    if denial:
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=denial,
        )
        return ToolResult(call_id=tc.id, error=denial), False

    ctx.emit_simple(EventType.TOOL_START, tool=tc.name, args=tc.arguments)
    start = time.monotonic()

    # Record tool call in economics if available
    if ctx.economics is not None:
        loop_detection, phase_nudge = ctx.economics.record_tool_call(
            tc.name, tc.arguments, ctx.iteration,
        )
        if loop_detection.is_loop:
            ctx.emit_simple(
                EventType.BUDGET_WARNING,
                metadata={"doom_loop": True, "tool": tc.name, "count": loop_detection.count},
            )
        if phase_nudge:
            ctx.add_message(Message(
                role=Role.USER,
                content=f"[System: {phase_nudge}]",
            ))

    effective_timeout = timeout or DEFAULT_TOOL_TIMEOUT
    was_truncated = False

    try:
        # Capture before-content for undo tracking on write/edit tools
        _before_content: str | None = None
        _track_path: str | None = None
        if ctx.file_change_tracker and tc.name in ("write_file", "edit_file"):
            _track_path = (tc.arguments or {}).get("path")
            if _track_path:
                try:
                    from pathlib import Path as _P
                    _p = _P(_track_path)
                    if not _p.is_absolute() and ctx.working_dir:
                        _p = _P(ctx.working_dir) / _p
                    _p = _p.resolve()
                    _track_path = str(_p)
                    _before_content = _p.read_text(encoding="utf-8") if _p.exists() else None
                except Exception:
                    _track_path = None

        result = await asyncio.wait_for(
            ctx.registry.execute(tc.name, tc.arguments, timeout=timeout),
            timeout=effective_timeout,
        )
        duration = time.monotonic() - start
        ctx.metrics.tool_calls += 1

        # Record file change for undo/diff tracking
        if _track_path and not result.is_error and ctx.file_change_tracker:
            try:
                from pathlib import Path as _P
                _after = _P(_track_path).read_text(encoding="utf-8") if _P(_track_path).exists() else None
                ctx.file_change_tracker.track_change(
                    _track_path, _before_content, _after, tc.name,
                )
            except Exception:
                pass

        # Cap result size
        result_content = result.result or ""
        if result_content and len(result_content) > max_result_chars:
            result_content, was_truncated = _cap_result(result_content, max_result_chars)

        if result.is_error:
            ctx.emit_simple(
                EventType.TOOL_ERROR,
                tool=tc.name,
                error=result.error,
                metadata={"duration_ms": duration * 1000},
            )
        else:
            ctx.emit_simple(
                EventType.TOOL_COMPLETE,
                tool=tc.name,
                result=_truncate(result_content, 500),
                metadata={"duration_ms": duration * 1000, "truncated": was_truncated},
            )

        return ToolResult(
            call_id=tc.id,
            result=result_content if not result.is_error else result.result,
            error=result.error,
        ), was_truncated

    except asyncio.TimeoutError:
        duration = time.monotonic() - start
        error_msg = f"Tool '{tc.name}' timed out after {effective_timeout}s"
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            metadata={"duration_ms": duration * 1000, "timed_out": True},
        )
        return ToolResult(call_id=tc.id, error=error_msg), False

    except Exception as e:
        duration = time.monotonic() - start
        error_msg = f"{type(e).__name__}: {e}"
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            metadata={"duration_ms": duration * 1000},
        )
        return ToolResult(call_id=tc.id, error=error_msg), False


async def execute_tool_calls(
    ctx: AgentContext,
    tool_calls: list[ToolCall],
    *,
    timeout: float | None = None,
    max_concurrent: int = MAX_CONCURRENT_TOOLS,
    max_result_chars: int = MAX_RESULT_CHARS,
) -> list[ToolResult]:
    """Execute tool calls in parallel with concurrency control.

    Each tool call is isolated — failures in one do not affect others.
    Events are emitted for each tool start/complete/error.
    Permission checks run before execution.

    Args:
        ctx: Agent context.
        tool_calls: List of tool calls to execute.
        timeout: Per-tool timeout in seconds.
        max_concurrent: Maximum concurrent tool executions.
        max_result_chars: Maximum characters per tool result.

    Returns:
        List of ToolResults in the same order as tool_calls.
    """
    if not tool_calls:
        return []

    # Use semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_with_semaphore(tc: ToolCall) -> ToolResult:
        async with semaphore:
            result, _ = await execute_single_tool(
                ctx, tc,
                timeout=timeout,
                max_result_chars=max_result_chars,
            )
            return result

    # Run all tool calls concurrently (bounded by semaphore)
    results = await asyncio.gather(
        *[_run_with_semaphore(tc) for tc in tool_calls],
    )
    return list(results)


async def execute_tool_calls_batched(
    ctx: AgentContext,
    tool_calls: list[ToolCall],
    *,
    batch_size: int = 5,
    timeout: float | None = None,
) -> tuple[list[ToolResult], ToolExecutionStats]:
    """Execute tool calls in batches, collecting statistics.

    Useful for large batches where you want progress reporting
    between batches.

    Returns:
        Tuple of (results, stats).
    """
    stats = ToolExecutionStats(total=len(tool_calls))
    all_results: list[ToolResult] = []

    for i in range(0, len(tool_calls), batch_size):
        batch = tool_calls[i:i + batch_size]

        batch_results: list[ToolResult] = []
        for tc in batch:
            result, was_truncated = await execute_single_tool(ctx, tc, timeout=timeout)
            batch_results.append(result)

            if result.is_error:
                if "timed out" in (result.error or ""):
                    stats.timed_out += 1
                elif "denied" in (result.error or ""):
                    stats.denied += 1
                else:
                    stats.failed += 1
            else:
                stats.succeeded += 1

            if was_truncated:
                stats.truncated += 1

        all_results.extend(batch_results)

    return all_results, stats


def build_tool_result_messages(
    tool_calls: list[ToolCall],
    results: list[ToolResult],
) -> list[Message]:
    """Build tool result messages from tool calls and their results.

    Returns a list of Message objects with role=TOOL, one per result.
    """
    messages: list[Message] = []
    for tc, result in zip(tool_calls, results):
        content = result.error if result.is_error else (result.result or "")
        messages.append(Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=tc.id,
        ))
    return messages


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string for event display."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"... ({len(s)} total chars)"
