"""Tool executor - handles parallel tool execution with error isolation.

Features:
- Parallel execution via asyncio.gather()
- Per-tool timeout handling
- Tool result size capping
- Permission checks before execution
- Economics integration (loop detection, phase tracking)
- Batched execution with configurable concurrency
- Argument normalization for non-Anthropic LLMs (alias mapping + fuzzy match)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attocode.types.events import EventType
from attocode.types.messages import Message, Role, ToolCall, ToolResult

if TYPE_CHECKING:
    from attocode.agent.context import AgentContext

if __name__ != "__main__":
    pass

import logging
logger = logging.getLogger(__name__)

# Defaults
DEFAULT_TOOL_TIMEOUT = 120.0  # 2 minutes per tool
MAX_RESULT_CHARS = 100_000  # Cap individual tool results
MAX_CONCURRENT_TOOLS = 10  # Max parallel tool executions

# ---------------------------------------------------------------------------
# Argument normalization — alias maps for built-in tools
# ---------------------------------------------------------------------------
# Non-Anthropic LLMs (e.g. GLM-5) frequently guess wrong parameter names.
# These maps translate common wrong names to the canonical parameter names.

_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "write_file": {
        "file_path": "path", "filepath": "path", "filename": "path",
        "file": "path", "file_name": "path",
        "text": "content", "body": "content", "data": "content",
        "file_content": "content", "code": "content", "source": "content",
    },
    "edit_file": {
        "file_path": "path", "filepath": "path", "filename": "path",
        "file": "path", "file_name": "path",
        "old_text": "old_string", "original": "old_string",
        "search": "old_string", "find": "old_string",
        "old_content": "old_string", "old": "old_string",
        "before": "old_string", "target": "old_string",
        "new_text": "new_string", "replacement": "new_string",
        "replace": "new_string", "new_content": "new_string",
        "new": "new_string", "after": "new_string",
    },
    "read_file": {
        "file_path": "path", "filepath": "path", "filename": "path",
        "file": "path", "file_name": "path",
    },
    "bash": {
        "cmd": "command", "shell_command": "command",
        "script": "command", "shell": "command",
        "bash_command": "command", "exec": "command",
    },
    "grep": {
        "query": "pattern", "search_pattern": "pattern",
        "regex": "pattern", "term": "pattern",
    },
    "glob_files": {
        "glob": "pattern", "file_pattern": "pattern",
        "glob_pattern": "pattern",
    },
}


def _normalize_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Normalize tool arguments so non-Anthropic LLMs can use tools correctly.

    Three phases:
      1. Known alias mapping — rename well-known wrong param names for built-in tools.
      2. Generic fuzzy match — for any remaining missing required params, check if an
         unrecognized argument name contains (or is contained by) the missing param name.
      3. Type coercion — delegate to ``coerce_tool_arguments`` for type fixups.

    Args:
        tool_name: Canonical tool name (e.g. ``"write_file"``).
        arguments: Raw arguments dict from the LLM.
        schema: Tool's JSON-Schema ``parameters`` dict.

    Returns:
        A *new* dict with normalized keys and coerced types.
    """
    args = dict(arguments)  # shallow copy — don't mutate the original

    # --- Phase 1: known alias map -------------------------------------------
    aliases = _PARAM_ALIASES.get(tool_name, {})
    for wrong_name, canonical in aliases.items():
        if wrong_name in args and canonical not in args:
            args[canonical] = args.pop(wrong_name)

    # --- Phase 2: generic fuzzy match for still-missing required params ------
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    known_params = set(properties.keys())

    for param in required:
        if param in args:
            continue  # already present
        # Look for an unrecognized arg whose name *contains* or *is contained by* the
        # missing param name (e.g. "file_path" contains "path").
        unrecognized = [k for k in args if k not in known_params]
        for unrec in unrecognized:
            lower_unrec = unrec.lower()
            lower_param = param.lower()
            if lower_param in lower_unrec or lower_unrec in lower_param:
                args[param] = args.pop(unrec)
                break

    # --- Phase 3: type coercion ----------------------------------------------
    try:
        from attocode.integrations.utilities.tool_coercion import coerce_tool_arguments
        args = coerce_tool_arguments(args, schema)
    except Exception:
        pass  # coercion is best-effort

    return args


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


def _derive_allow_pattern(tc: ToolCall, approval: Any) -> str | None:
    """Build a persisted allow-pattern for "always allow" grants."""
    explicit = getattr(approval, "allow_pattern", None)
    if explicit:
        return explicit

    if tc.name != "bash":
        return "*"

    command = " ".join(str((tc.arguments or {}).get("command", "")).split()).strip()
    if not command:
        return None

    # Never persist broad grants for destructive shell commands.
    lower = f" {command.lower()} "
    destructive_markers = (
        " rm ",
        "rm -",
        " sudo ",
        " chmod ",
        " chown ",
        " mkfs",
        " dd ",
        " git reset",
        " git clean",
        " git checkout .",
    )
    if any(marker in lower for marker in destructive_markers):
        return None

    return f"{command}*"


def _check_markup_mismatch(ctx: AgentContext, tc: ToolCall) -> None:
    """Emit diagnostic if pseudo-tool streamed text diverges from actual tool args."""
    if tc.name != "bash":
        return
    payload = getattr(ctx, "_last_suspicious_markup", None)
    if not payload:
        return
    expected = str(payload.get("command", "")).strip()
    actual = str((tc.arguments or {}).get("command", "")).strip()
    if expected and actual and expected != actual:
        ctx.emit_simple(
            EventType.TOOL_CALL_MISMATCH,
            tool=tc.name,
            iteration=ctx.iteration,
            metadata={
                "expected": expected,
                "actual": actual,
                "source": "stream_text_vs_structured_tool_call",
            },
        )
    ctx._last_suspicious_markup = None
    ctx._tool_markup_buffer = ""


def _is_loop_guard_blocked(ctx: AgentContext, tc: ToolCall) -> bool:
    """Block repeated identical bash calls once doom-loop is already detected."""
    if tc.name != "bash":
        return False
    economics = getattr(ctx, "economics", None)
    detector = getattr(economics, "loop_detector", None) if economics is not None else None
    if detector is None:
        return False
    try:
        detection = detector.peek(tc.name, tc.arguments or {})
    except Exception:
        return False
    if not detection.is_loop:
        return False

    msg = (
        f"Loop guard blocked repeated command: '{tc.name}' "
        f"seen {detection.count} times with identical arguments."
    )
    ctx.emit_simple(
        EventType.LOOP_GUARD_ACTIVATED,
        tool=tc.name,
        iteration=ctx.iteration,
        metadata={"tool": tc.name, "count": detection.count, "message": msg},
    )
    return True


def _is_subagent_failure_output(output: str) -> bool:
    text = (output or "").lower()
    return (
        "subagent failed" in text
        or "rate limit" in text
        or "429" in text
    )


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
            ctx.emit_simple(
                EventType.TOOL_APPROVAL_REQUESTED,
                tool=tc.name,
                args=tc.arguments,
                iteration=ctx.iteration,
                metadata={"reason": result.reason, "danger_level": str(result.danger_level)},
            )
            approval = await ctx.approval_callback(
                tc.name,
                tc.arguments,
                result.danger_level,
                result.reason,
            )
            if hasattr(approval, "approved") and approval.approved:
                ctx.emit_simple(
                    EventType.TOOL_APPROVAL_GRANTED,
                    tool=tc.name,
                    args=tc.arguments,
                    iteration=ctx.iteration,
                )
                if getattr(approval, "always_allow", False) and ctx.policy_engine:
                    pattern = _derive_allow_pattern(tc, approval)
                    if pattern:
                        ctx.policy_engine.approve_command(tc.name, pattern=pattern)
                        ctx.emit_simple(
                            EventType.PERMISSION_REMEMBERED,
                            tool=tc.name,
                            args=tc.arguments,
                            iteration=ctx.iteration,
                            metadata={"pattern": pattern},
                        )
                        if getattr(ctx, "session_store", None) and getattr(ctx, "session_id", None):
                            try:
                                await ctx.session_store.grant_permission(
                                    ctx.session_id,
                                    tc.name,
                                    pattern,
                                    "allow",
                                )
                            except Exception:
                                pass
                return None
            ctx.emit_simple(
                EventType.TOOL_APPROVAL_DENIED,
                tool=tc.name,
                args=tc.arguments,
                iteration=ctx.iteration,
            )
            return f"Tool '{tc.name}' was denied by user"
        except Exception:
            return f"Tool '{tc.name}' approval timed out or failed"

    # No approval callback but policy says PROMPT — auto-allow in non-interactive mode
    return None


def _notify_file_changed(ctx: AgentContext, path: str) -> None:
    """Notify code intelligence systems of a file change."""
    # Notify codebase context manager
    cbc = getattr(ctx, "codebase_context", None)
    if cbc:
        try:
            cbc.mark_file_dirty(path)
        except Exception:
            logger.debug("notify_file_changed: codebase_context.mark_file_dirty failed", exc_info=True)

    # Invalidate hierarchical explorer cache
    explorer = getattr(ctx, "_hierarchical_explorer", None)
    if explorer:
        try:
            explorer.invalidate()
        except Exception:
            logger.debug("notify_file_changed: hierarchical_explorer.invalidate failed", exc_info=True)

    # Notify AST service of file change (invalidate AST cache + cross-refs)
    ast_svc = getattr(ctx, "_ast_service", None)
    if ast_svc:
        try:
            ast_svc.notify_file_changed(path)
        except Exception:
            logger.debug("notify_file_changed: ast_service.notify_file_changed failed", exc_info=True)

    # Notify semantic search to re-index the changed file.
    # Prefer the manager's bounded queue to avoid spawning unbounded threads.
    sem_search = getattr(ctx, "_semantic_search", None)
    if sem_search:
        try:
            if hasattr(sem_search, "queue_reindex"):
                sem_search.queue_reindex(path)
            else:
                sem_search.reindex_file(path)
        except Exception:
            logger.debug("notify_file_changed: semantic_search reindex failed", exc_info=True)

    # Write to code_intel notification queue (.attocode/cache/file_changes)
    try:
        working_dir = getattr(ctx, "working_dir", None) or os.getcwd()
        queue_path = Path(working_dir) / ".attocode" / "cache" / "file_changes"
        if queue_path.parent.exists():
            rel = os.path.relpath(path, working_dir)
            with open(queue_path, "a", encoding="utf-8") as fh:
                fh.write(rel + "\n")
    except Exception:
        logger.debug("notify_file_changed: file_changes queue write failed", exc_info=True)


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
    # Early exit if arguments couldn't be parsed
    if tc.parse_error:
        error_msg = (
            f"Tool '{tc.name}' arguments could not be parsed from the model's response. "
            f"{tc.parse_error} — please retry with valid JSON."
        )
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            args=tc.arguments,
            iteration=ctx.iteration,
        )
        return ToolResult(call_id=tc.id, error=error_msg), False

    # Normalize arguments (alias mapping + fuzzy match + type coercion)
    tool = ctx.registry.get(tc.name)
    if tool and tool.spec.parameters:
        tc.arguments = _normalize_tool_arguments(
            tc.name, tc.arguments, tool.spec.parameters,
        )

    _check_markup_mismatch(ctx, tc)

    if tc.name == "spawn_agent" and getattr(ctx, "_subagent_fallback_mode", False):
        error_msg = (
            "Subagent spawning is temporarily disabled after repeated failures. "
            "Continue with local investigation tools instead."
        )
        ctx.emit_simple(
            EventType.RESILIENCE_FALLBACK,
            tool=tc.name,
            iteration=ctx.iteration,
            metadata={"reason": "subagent_failures", "message": error_msg},
        )
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            args=tc.arguments,
            iteration=ctx.iteration,
        )
        return ToolResult(call_id=tc.id, error=error_msg), False

    if _is_loop_guard_blocked(ctx, tc):
        error_msg = (
            f"Tool '{tc.name}' blocked by loop guard due to repeated identical calls. "
            "Provide a different command or summarize findings."
        )
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            args=tc.arguments,
            iteration=ctx.iteration,
        )
        return ToolResult(call_id=tc.id, error=error_msg), False

    # Validate required parameters exist
    if tool and tool.spec.parameters:
        required = tool.spec.parameters.get("required", [])
        missing = [p for p in required if p not in tc.arguments]
        if missing:
            error_msg = (
                f"Tool '{tc.name}' missing required parameters: {missing}. "
                f"Received: {list(tc.arguments.keys())}"
            )
            ctx.emit_simple(
                EventType.TOOL_ERROR,
                tool=tc.name,
                error=error_msg,
                args=tc.arguments,
                iteration=ctx.iteration,
            )
            return ToolResult(call_id=tc.id, error=error_msg), False

    # Permission check
    denial = await _check_permission(ctx, tc)
    if denial:
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=denial,
            args=tc.arguments,
            iteration=ctx.iteration,
        )
        return ToolResult(call_id=tc.id, error=denial), False

    ctx.emit_simple(
        EventType.TOOL_START,
        tool=tc.name,
        args=tc.arguments,
        iteration=ctx.iteration,
        metadata={"tool_id": tc.id},
    )
    start = time.monotonic()

    # Record tool call in economics if available
    if ctx.economics is not None:
        loop_detection, phase_nudge = ctx.economics.record_tool_call(
            tc.name, tc.arguments, ctx.iteration,
        )
        if loop_detection.is_loop:
            ctx.emit_simple(
                EventType.BUDGET_WARNING,
                iteration=ctx.iteration,
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
                    from pathlib import Path as _P  # noqa: N814
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
                from pathlib import Path as _P  # noqa: N814
                _after = _P(_track_path).read_text(encoding="utf-8") if _P(_track_path).exists() else None
                ctx.file_change_tracker.track_change(
                    _track_path, _before_content, _after, tc.name,
                )
            except Exception:
                pass

        # Notify code intel of file changes (AST, codebase context, explorer)
        if _track_path and not result.is_error:
            _notify_file_changed(ctx, _track_path)

        if tc.name == "spawn_agent":
            failures = int(getattr(ctx, "_subagent_failure_count", 0))
            if result.is_error or _is_subagent_failure_output(result.result or ""):
                failures += 1
            else:
                failures = 0
            ctx._subagent_failure_count = failures
            if failures >= 2:
                ctx._subagent_fallback_mode = True
                ctx.emit_simple(
                    EventType.RESILIENCE_FALLBACK,
                    tool=tc.name,
                    iteration=ctx.iteration,
                    metadata={
                        "reason": "subagent_failures",
                        "count": failures,
                        "message": "Repeated subagent failures detected; switched to local fallback mode.",
                    },
                )

        # Cap result size
        result_content = result.result or ""
        if result_content and len(result_content) > max_result_chars:
            result_content, was_truncated = _cap_result(result_content, max_result_chars)

        if result.is_error:
            ctx.emit_simple(
                EventType.TOOL_ERROR,
                tool=tc.name,
                error=result.error,
                args=tc.arguments,
                iteration=ctx.iteration,
                metadata={"duration_ms": duration * 1000, "tool_id": tc.id},
            )
        else:
            ctx.emit_simple(
                EventType.TOOL_COMPLETE,
                tool=tc.name,
                result=_truncate(result_content, 500),
                args=tc.arguments,
                iteration=ctx.iteration,
                metadata={
                    "duration_ms": duration * 1000,
                    "truncated": was_truncated,
                    "tool_id": tc.id,
                },
            )

        return ToolResult(
            call_id=tc.id,
            result=result_content if not result.is_error else result.result,
            error=result.error,
        ), was_truncated

    except TimeoutError:
        duration = time.monotonic() - start
        error_msg = f"Tool '{tc.name}' timed out after {effective_timeout}s"
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            args=tc.arguments,
            iteration=ctx.iteration,
            metadata={"duration_ms": duration * 1000, "timed_out": True, "tool_id": tc.id},
        )
        return ToolResult(call_id=tc.id, error=error_msg), False

    except Exception as e:
        duration = time.monotonic() - start
        error_msg = f"{type(e).__name__}: {e}"
        ctx.emit_simple(
            EventType.TOOL_ERROR,
            tool=tc.name,
            error=error_msg,
            args=tc.arguments,
            iteration=ctx.iteration,
            metadata={"duration_ms": duration * 1000, "tool_id": tc.id},
        )
        return ToolResult(call_id=tc.id, error=error_msg), False


def _partition_by_concurrency(
    tool_calls: list[ToolCall],
    registry: Any,  # ToolRegistry
) -> tuple[list[ToolCall], list[ToolCall]]:
    """Partition tool calls into concurrent-safe and exclusive groups."""
    safe: list[ToolCall] = []
    exclusive: list[ToolCall] = []
    for tc in tool_calls:
        tool = registry.get(tc.name) if registry else None
        if tool and not tool.spec.concurrent_safe:
            exclusive.append(tc)
        else:
            safe.append(tc)
    return safe, exclusive


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


async def execute_tool_calls_concurrent(
    ctx: AgentContext,
    tool_calls: list[ToolCall],
    *,
    timeout: float | None = None,
    max_result_chars: int = MAX_RESULT_CHARS,
) -> list[ToolResult]:
    """Execute tool calls with concurrency-aware partitioning.

    Concurrent-safe tools (reads, grep, glob) run in parallel.
    Exclusive tools (bash, write_file, edit_file) run sequentially.
    If an exclusive bash tool fails, remaining exclusive tools are aborted.

    Results are returned in the original tool_calls order.
    """
    if not tool_calls:
        return []

    safe, exclusive = _partition_by_concurrency(tool_calls, ctx.registry)

    # Track results by tool call ID for re-ordering
    results_by_id: dict[str, ToolResult] = {}

    # Run safe tools concurrently
    if safe:
        safe_results = await asyncio.gather(
            *[execute_single_tool(ctx, tc, timeout=timeout, max_result_chars=max_result_chars)
              for tc in safe],
        )
        for tc, (result, _) in zip(safe, safe_results):
            results_by_id[tc.id] = result

    # Run exclusive tools sequentially with abort-on-bash-failure
    for i, tc in enumerate(exclusive):
        result, _ = await execute_single_tool(
            ctx, tc, timeout=timeout, max_result_chars=max_result_chars,
        )
        results_by_id[tc.id] = result
        # Abort remaining exclusive tools if bash failed
        if tc.name == "bash" and result.is_error:
            for remaining_tc in exclusive[i + 1:]:
                results_by_id[remaining_tc.id] = ToolResult(
                    call_id=remaining_tc.id,
                    error="[Aborted: sibling bash command failed]",
                )
            break

    # Return in original order
    return [results_by_id[tc.id] for tc in tool_calls]


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
    for tc, result in zip(tool_calls, results, strict=False):
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
