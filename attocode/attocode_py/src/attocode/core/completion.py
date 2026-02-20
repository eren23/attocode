"""Completion analysis - determines if the agent should stop."""

from __future__ import annotations

import re
from dataclasses import dataclass

from attocode.types.agent import CompletionReason
from attocode.types.messages import ChatResponse, StopReason


@dataclass(slots=True)
class CompletionAnalysis:
    """Result of analyzing whether the agent should stop."""

    should_stop: bool
    reason: CompletionReason
    message: str = ""

    @staticmethod
    def continue_running() -> CompletionAnalysis:
        return CompletionAnalysis(
            should_stop=False,
            reason=CompletionReason.COMPLETED,
        )

    @staticmethod
    def stop(reason: CompletionReason, message: str = "") -> CompletionAnalysis:
        return CompletionAnalysis(
            should_stop=True,
            reason=reason,
            message=message,
        )


def analyze_completion(response: ChatResponse) -> CompletionAnalysis:
    """Analyze an LLM response to determine if the agent should continue.

    Decision logic:
    1. If response has tool calls → continue (execute them)
    2. If stop reason is MAX_TOKENS → continue (truncated response)
    3. If content mentions future work → flag as future_intent
    4. Otherwise → completed
    """
    # Tool calls mean we need to continue
    if response.has_tool_calls:
        return CompletionAnalysis.continue_running()

    # Max tokens means truncated — might need to continue
    if response.stop_reason == StopReason.MAX_TOKENS:
        return CompletionAnalysis.continue_running()

    # Check for future intent signals in the response content
    content = response.content.strip().lower() if response.content else ""

    if _has_future_intent(content):
        return CompletionAnalysis.stop(
            CompletionReason.FUTURE_INTENT,
            "Agent indicated future work is needed",
        )

    if _has_incomplete_action(content):
        return CompletionAnalysis.stop(
            CompletionReason.INCOMPLETE_ACTION,
            "Agent's response suggests incomplete work",
        )

    # Normal completion
    return CompletionAnalysis.stop(CompletionReason.COMPLETED)


# Pre-compiled patterns that suggest the agent wants to continue later
_FUTURE_PATTERNS = [
    re.compile(r"i(?:'ll| will) (?:need to|continue|proceed|come back)"),
    re.compile(r"(?:next|remaining) (?:step|task|item)s? (?:include|are|would be)"),
    re.compile(r"there (?:are|is) (?:still\s+)?more (?:work|things|items)"),
    re.compile(r"there (?:are|is) still (?:work|things|items|more)"),
    re.compile(r"we still need to"),
    re.compile(r"todo:?\s"),
    re.compile(r"i haven'?t (?:yet|finished)"),
]

_INCOMPLETE_PATTERNS = [
    re.compile(r"i was (?:unable|not able) to (?:complete|finish)"),
    re.compile(r"i couldn'?t (?:complete|finish)"),
    re.compile(r"(?:but|however),? (?:i|this) (?:didn'?t|hasn'?t|haven'?t)"),
    re.compile(r"the (?:remaining|rest of the) (?:work|tasks?)"),
]


def _has_future_intent(content: str) -> bool:
    """Check if content suggests future work is needed."""
    if not content:
        return False
    return any(p.search(content) for p in _FUTURE_PATTERNS)


def _has_incomplete_action(content: str) -> bool:
    """Check if content suggests the action is incomplete."""
    if not content:
        return False
    return any(p.search(content) for p in _INCOMPLETE_PATTERNS)
