"""Attocode error hierarchy."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    """Category of error for classification and handling."""

    LLM = "llm"
    PROVIDER = "provider"
    TOOL = "tool"
    BUDGET = "budget"
    CANCELLATION = "cancellation"
    PERMISSION = "permission"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"


class AgentError(Exception):
    """Base error for all agent exceptions."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)!r}, category={self.category!r})"


class LLMError(AgentError):
    """Error from LLM interaction (empty response, malformed output, etc.)."""

    def __init__(self, message: str, *, retryable: bool = True, **kwargs: Any) -> None:
        super().__init__(message, category=ErrorCategory.LLM, retryable=retryable, **kwargs)


class ProviderError(AgentError):
    """Error from an LLM provider (rate limit, network, auth)."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        retryable: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, category=ErrorCategory.PROVIDER, retryable=retryable, **kwargs)
        self.provider = provider
        self.status_code = status_code


class ToolError(AgentError):
    """Error during tool execution."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        retryable: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, category=ErrorCategory.TOOL, retryable=retryable, **kwargs)
        self.tool_name = tool_name


class ToolNotFoundError(ToolError):
    """Requested tool does not exist."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool not found: {tool_name}", tool_name=tool_name)


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""

    def __init__(self, tool_name: str, timeout: float) -> None:
        super().__init__(
            f"Tool '{tool_name}' timed out after {timeout}s",
            tool_name=tool_name,
            retryable=True,
        )
        self.timeout = timeout


class BudgetExhaustedError(AgentError):
    """Token/cost/time budget has been exhausted."""

    def __init__(self, message: str = "Budget exhausted") -> None:
        super().__init__(message, category=ErrorCategory.BUDGET, retryable=False)


class CancellationError(AgentError):
    """Operation was cancelled by user or system."""

    def __init__(self, message: str = "Operation cancelled") -> None:
        super().__init__(message, category=ErrorCategory.CANCELLATION, retryable=False)


class PermissionDeniedError(AgentError):
    """Tool execution was denied by permission system."""

    def __init__(self, message: str, *, tool_name: str | None = None) -> None:
        super().__init__(message, category=ErrorCategory.PERMISSION, retryable=False)
        self.tool_name = tool_name


class ConfigurationError(AgentError):
    """Invalid or missing configuration."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.CONFIGURATION, retryable=False)
