"""Tests for completion analysis."""

from __future__ import annotations

import pytest

from attocode.core.completion import (
    CompletionAnalysis,
    analyze_completion,
    _has_future_intent,
    _has_incomplete_action,
)
from attocode.types.agent import CompletionReason
from attocode.types.messages import ChatResponse, StopReason, ToolCall


class TestCompletionAnalysisDataclass:
    def test_continue(self) -> None:
        a = CompletionAnalysis.continue_running()
        assert not a.should_stop

    def test_stop(self) -> None:
        a = CompletionAnalysis.stop(CompletionReason.COMPLETED, "all done")
        assert a.should_stop
        assert a.reason == CompletionReason.COMPLETED
        assert a.message == "all done"


class TestAnalyzeCompletion:
    def test_tool_calls_continue(self) -> None:
        tc = ToolCall(id="1", name="read_file", arguments={})
        resp = ChatResponse(content="reading", tool_calls=[tc], stop_reason=StopReason.TOOL_USE)
        result = analyze_completion(resp)
        assert not result.should_stop

    def test_max_tokens_continue(self) -> None:
        resp = ChatResponse(content="truncated...", stop_reason=StopReason.MAX_TOKENS)
        result = analyze_completion(resp)
        assert not result.should_stop

    def test_normal_completion(self) -> None:
        resp = ChatResponse(content="Here is the answer.", stop_reason=StopReason.END_TURN)
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED

    def test_empty_content_completes(self) -> None:
        resp = ChatResponse(content="", stop_reason=StopReason.END_TURN)
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED

    def test_future_intent_no_longer_kills_agent(self) -> None:
        """Future intent text should complete normally (not kill agent)."""
        resp = ChatResponse(
            content="I'll need to continue with the remaining tasks.",
            stop_reason=StopReason.END_TURN,
        )
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED

    def test_todo_text_no_longer_kills_agent(self) -> None:
        """TODO text should complete normally (not kill agent)."""
        resp = ChatResponse(
            content="Done with step 1. TODO: implement step 2.",
            stop_reason=StopReason.END_TURN,
        )
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED

    def test_incomplete_action_no_longer_kills_agent(self) -> None:
        """Incomplete action text should complete normally (not kill agent)."""
        resp = ChatResponse(
            content="I was unable to complete the task due to a missing dependency.",
            stop_reason=StopReason.END_TURN,
        )
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED

    def test_no_false_positive_on_normal_text(self) -> None:
        resp = ChatResponse(
            content="The file has been updated successfully. All tests pass.",
            stop_reason=StopReason.END_TURN,
        )
        result = analyze_completion(resp)
        assert result.should_stop
        assert result.reason == CompletionReason.COMPLETED


class TestFutureIntentPatterns:
    def test_will_continue(self) -> None:
        assert _has_future_intent("i'll continue with the next step")

    def test_next_steps(self) -> None:
        assert _has_future_intent("next steps include updating the tests")

    def test_still_more(self) -> None:
        assert _has_future_intent("there are still more items to handle")

    def test_we_still_need(self) -> None:
        assert _has_future_intent("we still need to update the config")

    def test_havent_yet(self) -> None:
        assert _has_future_intent("i haven't yet addressed the edge cases")

    def test_no_match(self) -> None:
        assert not _has_future_intent("all done, everything works great")

    def test_empty(self) -> None:
        assert not _has_future_intent("")


class TestIncompleteActionPatterns:
    def test_unable_to_complete(self) -> None:
        assert _has_incomplete_action("i was unable to complete the task")

    def test_couldnt_finish(self) -> None:
        assert _has_incomplete_action("i couldn't finish the implementation")

    def test_remaining_work(self) -> None:
        assert _has_incomplete_action("the remaining work needs attention")

    def test_no_match(self) -> None:
        assert not _has_incomplete_action("everything is working perfectly")
