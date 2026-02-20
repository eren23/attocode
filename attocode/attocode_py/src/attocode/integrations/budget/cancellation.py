"""Asyncio-based cancellation system.

Replaces the 680-line TS cancellation.ts with a thin asyncio wrapper.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class CancellationToken:
    """A token that can be checked for cancellation.

    Uses asyncio.Event internally. Thread-safe for checking, but
    cancel() should be called from the event loop.
    """

    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _reason: str = ""

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        """Signal cancellation."""
        self._reason = reason
        self._event.set()

    def check(self) -> None:
        """Raise CancelledError if cancelled."""
        if self.is_cancelled:
            raise asyncio.CancelledError(self._reason)

    async def wait(self) -> None:
        """Wait until cancellation is signalled."""
        await self._event.wait()


@dataclass
class CancellationTokenSource:
    """Creates and manages a cancellation token.

    Supports linked tokens that cancel when any parent cancels.
    """

    _token: CancellationToken = field(default_factory=CancellationToken)
    _children: list[CancellationTokenSource] = field(default_factory=list, repr=False)

    @property
    def token(self) -> CancellationToken:
        return self._token

    def cancel(self, reason: str = "cancelled") -> None:
        """Cancel this source and all children."""
        self._token.cancel(reason)
        for child in self._children:
            child.cancel(reason)

    def create_linked(self) -> CancellationTokenSource:
        """Create a child source linked to this one.

        The child will be cancelled when this source is cancelled.
        """
        child = CancellationTokenSource()
        self._children.append(child)
        # If already cancelled, propagate immediately
        if self._token.is_cancelled:
            child.cancel(self._token.reason)
        return child

    def dispose(self) -> None:
        """Release all child references."""
        self._children.clear()
