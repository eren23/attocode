"""Approval bridge connecting agent requests to TUI dialogs."""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from attocode.tui.dialogs.approval import ApprovalResult


class ApprovalBridge:
    """Bridges between agent approval requests and TUI dialogs.

    Uses asyncio.Future for clean async communication between
    the agent execution loop and the Textual app.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Future[ApprovalResult] | None = None
        self._always_allowed: dict[str, set[str]] = {}
        self._on_request: Any = None

    @staticmethod
    def _args_signature(tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "bash":
            return str(args.get("command", "")).strip()
        return _first_arg(args)

    @staticmethod
    def _derive_allow_pattern(
        tool_name: str,
        args: dict[str, Any],
        danger_level: str,
    ) -> str | None:
        """Create a scoped allow-pattern for session grants.

        For bash, never create wildcard grants for destructive commands.
        """
        if tool_name != "bash":
            return "*"

        cmd = " ".join(str(args.get("command", "")).split()).strip()
        if not cmd:
            return None

        lower = cmd.lower()
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
        wrapped = f" {lower} "
        if any(marker in wrapped for marker in destructive_markers):
            return None
        if danger_level in ("high", "critical"):
            return None
        return f"{cmd}*"

    def _is_always_allowed(self, tool_name: str, args: dict[str, Any]) -> bool:
        patterns = self._always_allowed.get(tool_name)
        if not patterns:
            return False
        sig = self._args_signature(tool_name, args)
        return any(p == "*" or fnmatch.fnmatch(sig, p) for p in patterns)

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
        # Check always-allowed tools (bare tool name, any args/danger level)
        if self._is_always_allowed(tool_name, args):
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
            pattern = result.allow_pattern or self._derive_allow_pattern(
                tool_name, args, danger_level,
            )
            if pattern:
                self._always_allowed.setdefault(tool_name, set()).add(pattern)
                result.allow_pattern = pattern
            else:
                # Allow this call only; do not persist a risky wildcard.
                result.always_allow = False

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
        self._always_allowed = {}


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
