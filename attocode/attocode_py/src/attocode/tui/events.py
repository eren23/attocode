"""Custom Textual Messages for agent events."""

from __future__ import annotations

from typing import Any

from textual.message import Message


class AgentStarted(Message):
    """Agent execution started."""


class AgentCompleted(Message):
    """Agent execution completed."""

    def __init__(self, success: bool, response: str, error: str | None = None) -> None:
        super().__init__()
        self.success = success
        self.response = response
        self.error = error


class ToolStarted(Message):
    """A tool call started."""

    def __init__(self, tool_id: str, name: str, args: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.tool_id = tool_id
        self.name = name
        self.args = args or {}


class ToolCompleted(Message):
    """A tool call completed."""

    def __init__(
        self,
        tool_id: str,
        name: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        super().__init__()
        self.tool_id = tool_id
        self.name = name
        self.result = result
        self.error = error


class LLMStarted(Message):
    """LLM call started."""


class LLMCompleted(Message):
    """LLM call completed."""

    def __init__(self, tokens: int = 0, cost: float = 0.0) -> None:
        super().__init__()
        self.tokens = tokens
        self.cost = cost


class LLMStreamStart(Message):
    """LLM streaming response started."""


class LLMStreamChunk(Message):
    """A chunk of streaming LLM response."""

    def __init__(self, content: str, chunk_type: str = "text") -> None:
        super().__init__()
        self.content = content
        self.chunk_type = chunk_type  # "text" | "thinking"


class LLMStreamEnd(Message):
    """LLM streaming response ended."""

    def __init__(self, tokens: int = 0, cost: float = 0.0) -> None:
        super().__init__()
        self.tokens = tokens
        self.cost = cost


class LLMRetry(Message):
    """LLM call is being retried."""

    def __init__(self, attempt: int, max_retries: int, delay: float, error: str) -> None:
        super().__init__()
        self.attempt = attempt
        self.max_retries = max_retries
        self.delay = delay
        self.error = error


class BudgetWarning(Message):
    """Budget warning threshold reached."""

    def __init__(self, usage_fraction: float, message: str = "") -> None:
        super().__init__()
        self.usage_fraction = usage_fraction
        self.message = message


class ApprovalRequired(Message):
    """Tool needs user approval."""

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any],
        danger_level: str = "moderate",
        context: str = "",
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args = args
        self.danger_level = danger_level
        self.context = context


class StatusUpdate(Message):
    """General status update."""

    def __init__(self, text: str, mode: str = "info") -> None:
        super().__init__()
        self.text = text
        self.mode = mode


class IterationUpdate(Message):
    """Iteration counter update."""

    def __init__(self, iteration: int) -> None:
        super().__init__()
        self.iteration = iteration


class SwarmStatusUpdate(Message):
    """Swarm status snapshot update."""

    def __init__(self, status: Any) -> None:
        super().__init__()
        self.status = status
