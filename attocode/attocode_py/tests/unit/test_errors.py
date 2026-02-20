"""Tests for error hierarchy."""

from __future__ import annotations

import pytest

from attocode.errors import (
    AgentError,
    BudgetExhaustedError,
    CancellationError,
    ConfigurationError,
    ErrorCategory,
    LLMError,
    PermissionDeniedError,
    ProviderError,
    ToolError,
    ToolNotFoundError,
    ToolTimeoutError,
)


class TestErrorCategory:
    def test_values(self) -> None:
        assert ErrorCategory.LLM == "llm"
        assert ErrorCategory.PROVIDER == "provider"
        assert ErrorCategory.TOOL == "tool"
        assert ErrorCategory.BUDGET == "budget"
        assert ErrorCategory.PERMISSION == "permission"


class TestAgentError:
    def test_basic(self) -> None:
        e = AgentError("test error")
        assert str(e) == "test error"
        assert e.category == ErrorCategory.INTERNAL
        assert not e.retryable
        assert e.details == {}

    def test_with_details(self) -> None:
        e = AgentError("test", details={"key": "val"}, retryable=True)
        assert e.retryable
        assert e.details["key"] == "val"

    def test_repr(self) -> None:
        e = AgentError("test error", category=ErrorCategory.LLM)
        r = repr(e)
        assert "AgentError" in r
        assert "test error" in r

    def test_is_exception(self) -> None:
        e = AgentError("test")
        assert isinstance(e, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(AgentError, match="boom"):
            raise AgentError("boom")


class TestLLMError:
    def test_defaults(self) -> None:
        e = LLMError("empty response")
        assert e.category == ErrorCategory.LLM
        assert e.retryable  # default True for LLM errors

    def test_non_retryable(self) -> None:
        e = LLMError("bad request", retryable=False)
        assert not e.retryable

    def test_inherits_agent_error(self) -> None:
        e = LLMError("test")
        assert isinstance(e, AgentError)


class TestProviderError:
    def test_basic(self) -> None:
        e = ProviderError("rate limit", provider="anthropic", status_code=429)
        assert e.category == ErrorCategory.PROVIDER
        assert e.provider == "anthropic"
        assert e.status_code == 429
        assert e.retryable  # default True

    def test_non_retryable(self) -> None:
        e = ProviderError("auth failed", provider="openai", status_code=401, retryable=False)
        assert not e.retryable

    def test_inherits(self) -> None:
        e = ProviderError("test")
        assert isinstance(e, AgentError)


class TestToolError:
    def test_basic(self) -> None:
        e = ToolError("execution failed", tool_name="bash")
        assert e.category == ErrorCategory.TOOL
        assert e.tool_name == "bash"
        assert not e.retryable

    def test_inherits(self) -> None:
        e = ToolError("test")
        assert isinstance(e, AgentError)


class TestToolNotFoundError:
    def test_message(self) -> None:
        e = ToolNotFoundError("unknown_tool")
        assert "unknown_tool" in str(e)
        assert e.tool_name == "unknown_tool"
        assert isinstance(e, ToolError)


class TestToolTimeoutError:
    def test_message(self) -> None:
        e = ToolTimeoutError("bash", 30.0)
        assert "bash" in str(e)
        assert "30" in str(e)
        assert e.timeout == 30.0
        assert e.retryable  # timeouts are retryable

    def test_inherits(self) -> None:
        e = ToolTimeoutError("bash", 10.0)
        assert isinstance(e, ToolError)


class TestBudgetExhaustedError:
    def test_default_message(self) -> None:
        e = BudgetExhaustedError()
        assert "exhausted" in str(e).lower()
        assert e.category == ErrorCategory.BUDGET
        assert not e.retryable

    def test_custom_message(self) -> None:
        e = BudgetExhaustedError("token limit reached")
        assert str(e) == "token limit reached"


class TestCancellationError:
    def test_default(self) -> None:
        e = CancellationError()
        assert e.category == ErrorCategory.CANCELLATION
        assert not e.retryable


class TestPermissionDeniedError:
    def test_basic(self) -> None:
        e = PermissionDeniedError("not allowed", tool_name="bash")
        assert e.category == ErrorCategory.PERMISSION
        assert e.tool_name == "bash"
        assert not e.retryable


class TestConfigurationError:
    def test_basic(self) -> None:
        e = ConfigurationError("missing api key")
        assert e.category == ErrorCategory.CONFIGURATION
        assert not e.retryable


class TestErrorHierarchy:
    """Test that all errors can be caught as AgentError."""

    def test_catch_all(self) -> None:
        errors = [
            LLMError("test"),
            ProviderError("test"),
            ToolError("test"),
            ToolNotFoundError("test"),
            ToolTimeoutError("test", 10),
            BudgetExhaustedError(),
            CancellationError(),
            PermissionDeniedError("test"),
            ConfigurationError("test"),
        ]
        for err in errors:
            assert isinstance(err, AgentError)
            assert isinstance(err, Exception)
