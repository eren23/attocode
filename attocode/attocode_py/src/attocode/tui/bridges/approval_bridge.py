"""Approval bridge connecting agent requests to TUI dialogs."""

from __future__ import annotations

import asyncio
from typing import Any

from attocode.tui.dialogs.approval import ApprovalResult


class ApprovalBridge:
    """Bridges between agent approval requests and TUI dialogs.

    Uses asyncio.Future for clean async communication between
    the agent execution loop and the Textual app.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Future[ApprovalResult] | None = None
        self._always_allowed: set[str] = set()
        self._on_request: Any = None

    def set_handler(self, handler: Any) -> None:
        """Set the handler called when approval is needed.

        The handler receives (tool_name, args, danger_level, context)
        and should show a dialog.
        """
        self._on_request = handler

    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        danger_level: str = "moderate",
        context: str = "",
        timeout: float = 60.0,
    ) -> ApprovalResult:
        """Request approval for a tool call.

        Returns ApprovalResult. Raises asyncio.TimeoutError if timeout exceeded.
        """
        # Check always-allowed patterns
        pattern = f"{tool_name}:{_first_arg(args)}"
        if danger_level in ("safe", "low") and (
            tool_name in self._always_allowed or pattern in self._always_allowed
        ):
            return ApprovalResult(approved=True, always_allow=True)

        # Create future for this request
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()

        # Notify handler to show dialog
        if self._on_request:
            self._on_request(tool_name, args, danger_level, context)

        try:
            result = await asyncio.wait_for(self._pending, timeout=timeout)
        except asyncio.TimeoutError:
            result = ApprovalResult(approved=False)
        finally:
            self._pending = None

        # Record always-allow
        if result.always_allow:
            self._always_allowed.add(pattern)

        return result

    def resolve(self, result: ApprovalResult) -> None:
        """Resolve a pending approval request."""
        if self._pending and not self._pending.done():
            self._pending.set_result(result)

    def has_pending(self) -> bool:
        """Check if there's a pending approval request."""
        return self._pending is not None and not self._pending.done()

    def clear_always_allowed(self) -> None:
        """Clear all always-allowed patterns."""
        self._always_allowed.clear()


class BudgetBridge:
    """Bridges between agent budget extension requests and TUI dialogs."""

    def __init__(self) -> None:
        self._pending: asyncio.Future[bool] | None = None
        self._on_request: Any = None

    def set_handler(self, handler: Any) -> None:
        """Set the handler called when budget extension is needed."""
        self._on_request = handler

    async def request_extension(
        self,
        current_tokens: int,
        used_pct: float,
        requested_tokens: int,
        reason: str = "",
        timeout: float = 60.0,
    ) -> bool:
        """Request a budget extension. Returns True if approved."""
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()

        if self._on_request:
            self._on_request(current_tokens, used_pct, requested_tokens, reason)

        try:
            result = await asyncio.wait_for(self._pending, timeout=timeout)
        except asyncio.TimeoutError:
            result = False
        finally:
            self._pending = None

        return result

    def resolve(self, approved: bool) -> None:
        """Resolve a pending budget request."""
        if self._pending and not self._pending.done():
            self._pending.set_result(approved)

    def has_pending(self) -> bool:
        """Check if there's a pending budget request."""
        return self._pending is not None and not self._pending.done()


def _first_arg(args: dict[str, Any]) -> str:
    """Get the first argument value as a string for pattern matching."""
    if not args:
        return ""
    first_val = next(iter(args.values()))
    return str(first_val)[:50]
