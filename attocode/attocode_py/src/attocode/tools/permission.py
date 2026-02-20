"""Permission checking for tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(slots=True)
class PermissionResult:
    """Result of a permission check."""

    decision: PermissionDecision
    reason: str | None = None
    modified_args: dict[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == PermissionDecision.ALLOW

    @staticmethod
    def allow(reason: str | None = None) -> PermissionResult:
        return PermissionResult(decision=PermissionDecision.ALLOW, reason=reason)

    @staticmethod
    def deny(reason: str) -> PermissionResult:
        return PermissionResult(decision=PermissionDecision.DENY, reason=reason)

    @staticmethod
    def ask(reason: str) -> PermissionResult:
        return PermissionResult(decision=PermissionDecision.ASK, reason=reason)


@runtime_checkable
class PermissionChecker(Protocol):
    async def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult: ...


class AllowAllPermissions:
    """Permission checker that allows everything."""

    async def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        return PermissionResult.allow()
