"""Tests for InteractivePlanner and associated prompt/parse helpers."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from attocode.errors import AgentError
from attocode.integrations.tasks.interactive_planning import (
    InteractivePlanner,
    _extract_llm_content,
    _parse_steps_json,
    build_discuss_prompt,
    build_draft_prompt,
    build_step_prompt,
)
from attocode.integrations.tasks.planning import (
    InteractivePlan,
    PlanCheckpoint,
    PlanPhase,
    PlanStep,
)
from attocode.types.agent import TaskStatus


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------


class MockLLMProvider:
    """Simple mock that satisfies the _LLMProvider protocol."""

    def __init__(
        self,
        response: dict[str, Any] | str | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._response is None:
            return {"content": ""}
        if isinstance(self._response, str):
            return {"content": self._response}
        return self._response


# ---------------------------------------------------------------------------
# Helpers to build standard test data
# ---------------------------------------------------------------------------


def _make_steps_json(steps: list[dict[str, Any]]) -> str:
    """Serialise a list of raw step dicts to JSON."""
    return json.dumps(steps)


def _sample_steps_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "step-1",
            "description": "Analyse requirements",
            "dependencies": [],
            "estimated_tokens": 500,
        },
        {
            "id": "step-2",
            "description": "Write code",
            "dependencies": ["step-1"],
            "estimated_tokens": 1000,
        },
        {
            "id": "step-3",
            "description": "Write tests",
            "dependencies": ["step-2"],
            "estimated_tokens": 800,
        },
    ]


def _make_plan(
    *,
    goal: str = "Build feature X",
    phase: PlanPhase = PlanPhase.DRAFTING,
    steps: list[PlanStep] | None = None,
) -> InteractivePlan:
    return InteractivePlan(
        goal=goal,
        phase=phase,
        steps=steps if steps is not None else [],
    )


# =========================================================================
# Prompt builders
# =========================================================================


class TestBuildDraftPrompt:
    def test_includes_goal(self) -> None:
        prompt = build_draft_prompt("Refactor auth module", "some context")
        assert "Refactor auth module" in prompt

    def test_includes_context(self) -> None:
        prompt = build_draft_prompt("goal", "detailed project context here")
        assert "detailed project context here" in prompt

    def test_includes_json_schema_instructions(self) -> None:
        prompt = build_draft_prompt("goal", "ctx")
        assert "JSON array" in prompt
        assert '"description"' in prompt
        assert '"dependencies"' in prompt
        assert '"estimated_tokens"' in prompt

    def test_mentions_step_id_format(self) -> None:
        prompt = build_draft_prompt("goal", "ctx")
        assert "step-1" in prompt

    def test_empty_context(self) -> None:
        prompt = build_draft_prompt("my goal", "")
        assert "## Goal" in prompt
        assert "## Context" in prompt
        assert "my goal" in prompt


class TestBuildDiscussPrompt:
    def test_includes_current_steps_json(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="First step", dependencies=[], estimated_tokens=100),
        ])
        prompt = build_discuss_prompt(plan, "make it faster")
        assert '"step-1"' in prompt
        assert '"First step"' in prompt

    def test_includes_user_feedback(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="Do X"),
        ])
        prompt = build_discuss_prompt(plan, "add error handling step")
        assert "add error handling step" in prompt

    def test_valid_json_in_prompt(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", estimated_tokens=50),
            PlanStep(id="step-2", description="B", dependencies=["step-1"], estimated_tokens=100),
        ])
        prompt = build_discuss_prompt(plan, "feedback")
        # The prompt embeds the JSON inside a markdown code fence.
        # Extract the fenced block to validate it is well-formed JSON.
        import re
        fence_match = re.search(r"```json\s*([\s\S]*?)\s*```", prompt)
        assert fence_match is not None, "Expected a JSON code fence in the prompt"
        parsed = json.loads(fence_match.group(1))
        assert len(parsed) == 2
        assert parsed[0]["id"] == "step-1"
        assert parsed[1]["dependencies"] == ["step-1"]

    def test_includes_revision_instructions(self) -> None:
        plan = _make_plan(steps=[PlanStep(id="step-1", description="A")])
        prompt = build_discuss_prompt(plan, "feedback")
        assert "revised" in prompt.lower() or "revise" in prompt.lower()


class TestBuildStepPrompt:
    def test_includes_goal(self) -> None:
        plan = _make_plan(goal="Deploy to production")
        step = PlanStep(id="step-1", description="Run deploy script")
        prompt = build_step_prompt(plan, step)
        assert "Deploy to production" in prompt

    def test_includes_completed_steps(self) -> None:
        completed_step = PlanStep(
            id="step-1",
            description="Set up CI",
            status=TaskStatus.COMPLETED,
            result="CI configured",
        )
        current_step = PlanStep(id="step-2", description="Deploy")
        plan = _make_plan(steps=[completed_step, current_step])
        prompt = build_step_prompt(plan, current_step)
        assert "Set up CI" in prompt
        assert "CI configured" in prompt

    def test_no_completed_steps_shows_none(self) -> None:
        plan = _make_plan(steps=[PlanStep(id="step-1", description="First")])
        step = plan.steps[0]
        prompt = build_step_prompt(plan, step)
        assert "None yet." in prompt

    def test_includes_current_step(self) -> None:
        step = PlanStep(id="step-3", description="Write documentation")
        plan = _make_plan(steps=[step])
        prompt = build_step_prompt(plan, step)
        assert "step-3" in prompt
        assert "Write documentation" in prompt

    def test_completed_step_without_result_shows_done(self) -> None:
        completed_step = PlanStep(
            id="step-1",
            description="Prepare",
            status=TaskStatus.COMPLETED,
            result=None,
        )
        current_step = PlanStep(id="step-2", description="Execute")
        plan = _make_plan(steps=[completed_step, current_step])
        prompt = build_step_prompt(plan, current_step)
        assert "Prepare: done" in prompt


# =========================================================================
# Response parsing
# =========================================================================


class TestParseStepsJson:
    def test_clean_json_array(self) -> None:
        payload = _sample_steps_payload()
        text = json.dumps(payload)
        steps = _parse_steps_json(text)
        assert len(steps) == 3
        assert steps[0].id == "step-1"
        assert steps[0].description == "Analyse requirements"
        assert steps[0].dependencies == []
        assert steps[0].estimated_tokens == 500
        assert steps[1].dependencies == ["step-1"]

    def test_markdown_fenced_json(self) -> None:
        payload = _sample_steps_payload()
        text = f"```json\n{json.dumps(payload, indent=2)}\n```"
        steps = _parse_steps_json(text)
        assert len(steps) == 3
        assert steps[0].id == "step-1"

    def test_markdown_fenced_no_language(self) -> None:
        payload = _sample_steps_payload()
        text = f"```\n{json.dumps(payload)}\n```"
        steps = _parse_steps_json(text)
        assert len(steps) == 3

    def test_embedded_json_array_in_text(self) -> None:
        payload = _sample_steps_payload()[:2]
        text = f"Here is the plan:\n\n{json.dumps(payload)}\n\nLet me know!"
        steps = _parse_steps_json(text)
        assert len(steps) == 2
        assert steps[0].description == "Analyse requirements"

    def test_invalid_json_returns_empty(self) -> None:
        steps = _parse_steps_json("this is not json at all")
        assert steps == []

    def test_empty_array_returns_empty(self) -> None:
        steps = _parse_steps_json("[]")
        assert steps == []

    def test_missing_fields_use_defaults(self) -> None:
        text = json.dumps([{"description": "Only description"}])
        steps = _parse_steps_json(text)
        assert len(steps) == 1
        assert steps[0].id == "step-1"  # auto-generated
        assert steps[0].description == "Only description"
        assert steps[0].dependencies == []
        assert steps[0].estimated_tokens == 0

    def test_missing_description_uses_default(self) -> None:
        text = json.dumps([{"id": "s1"}])
        steps = _parse_steps_json(text)
        assert len(steps) == 1
        assert steps[0].description == "Step 1"

    def test_all_steps_have_pending_status(self) -> None:
        payload = _sample_steps_payload()
        steps = _parse_steps_json(json.dumps(payload))
        for step in steps:
            assert step.status == TaskStatus.PENDING


class TestExtractLlmContent:
    def test_string_input(self) -> None:
        assert _extract_llm_content("hello world") == "hello world"

    def test_dict_with_content_key(self) -> None:
        assert _extract_llm_content({"content": "the answer"}) == "the answer"

    def test_dict_with_message_content(self) -> None:
        response = {"message": {"content": "nested answer"}}
        assert _extract_llm_content(response) == "nested answer"

    def test_dict_empty_content_falls_through_to_message(self) -> None:
        response = {"content": "", "message": {"content": "fallback"}}
        assert _extract_llm_content(response) == "fallback"

    def test_empty_response_dict(self) -> None:
        assert _extract_llm_content({}) == ""

    def test_dict_with_no_content_or_message(self) -> None:
        assert _extract_llm_content({"status": "ok"}) == ""

    def test_message_not_a_dict(self) -> None:
        # message is a string, not a dict — should not crash
        result = _extract_llm_content({"content": "", "message": "plain"})
        assert result == ""


# =========================================================================
# InteractivePlanner — draft
# =========================================================================


class TestPlannerDraft:
    @pytest.mark.asyncio
    async def test_draft_without_provider_returns_single_step_fallback(self) -> None:
        planner = InteractivePlanner(provider=None)
        plan = await planner.draft("Build a parser")
        assert plan.goal == "Build a parser"
        assert plan.phase == PlanPhase.DRAFTING
        assert len(plan.steps) == 1
        assert plan.steps[0].id == "step-1"
        assert plan.steps[0].description == "Build a parser"

    @pytest.mark.asyncio
    async def test_draft_with_provider_returning_valid_json(self) -> None:
        payload = _sample_steps_payload()
        provider = MockLLMProvider(response=json.dumps(payload))
        planner = InteractivePlanner(provider=provider, model="test-model")
        plan = await planner.draft("Build feature", context="some context")

        assert plan.goal == "Build feature"
        assert len(plan.steps) == 3
        assert plan.steps[0].id == "step-1"
        assert plan.steps[2].dependencies == ["step-2"]

        # Verify the provider was called correctly
        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["model"] == "test-model"
        assert call["max_tokens"] == 2000
        assert call["temperature"] == 0.3
        assert len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_draft_with_provider_exception_falls_back(self) -> None:
        provider = MockLLMProvider(raise_exc=RuntimeError("API down"))
        planner = InteractivePlanner(provider=provider)
        plan = await planner.draft("Do something")

        assert len(plan.steps) == 1
        assert plan.steps[0].id == "step-1"
        assert plan.steps[0].description == "Do something"

    @pytest.mark.asyncio
    async def test_draft_with_provider_returning_empty_falls_back(self) -> None:
        provider = MockLLMProvider(response="")
        planner = InteractivePlanner(provider=provider)
        plan = await planner.draft("Goal with empty response")

        # Empty string won't parse to steps, so fallback kicks in
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "Goal with empty response"

    @pytest.mark.asyncio
    async def test_draft_with_provider_returning_empty_array_falls_back(self) -> None:
        provider = MockLLMProvider(response="[]")
        planner = InteractivePlanner(provider=provider)
        plan = await planner.draft("Goal with empty array")

        # _parse_steps_json returns [] for empty array, fallback kicks in
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "Goal with empty array"


# =========================================================================
# InteractivePlanner — discuss
# =========================================================================


class TestPlannerDiscuss:
    @pytest.mark.asyncio
    async def test_discuss_without_provider_sets_discussing_phase(self) -> None:
        planner = InteractivePlanner(provider=None)
        plan = _make_plan(
            phase=PlanPhase.DRAFTING,
            steps=[PlanStep(id="step-1", description="Original step")],
        )
        result = await planner.discuss(plan, "add more detail")

        assert result.phase == PlanPhase.DISCUSSING
        # Steps remain unchanged since no provider
        assert len(result.steps) == 1
        assert result.steps[0].description == "Original step"

    @pytest.mark.asyncio
    async def test_discuss_with_provider_revises_steps(self) -> None:
        revised_payload = [
            {"id": "step-1", "description": "Revised step A", "dependencies": [], "estimated_tokens": 200},
            {"id": "step-2", "description": "New step B", "dependencies": ["step-1"], "estimated_tokens": 300},
        ]
        provider = MockLLMProvider(response=json.dumps(revised_payload))
        planner = InteractivePlanner(provider=provider)

        plan = _make_plan(
            steps=[PlanStep(id="step-1", description="Original")],
        )
        result = await planner.discuss(plan, "add a second step")

        assert result.phase == PlanPhase.DISCUSSING
        assert len(result.steps) == 2
        assert result.steps[0].description == "Revised step A"
        assert result.steps[1].description == "New step B"

    @pytest.mark.asyncio
    async def test_discuss_with_provider_exception_keeps_steps(self) -> None:
        provider = MockLLMProvider(raise_exc=RuntimeError("LLM failed"))
        planner = InteractivePlanner(provider=provider)

        plan = _make_plan(
            steps=[PlanStep(id="step-1", description="Keep me")],
        )
        result = await planner.discuss(plan, "any feedback")

        assert result.phase == PlanPhase.DISCUSSING
        assert len(result.steps) == 1
        assert result.steps[0].description == "Keep me"

    @pytest.mark.asyncio
    async def test_discuss_with_empty_response_keeps_steps(self) -> None:
        provider = MockLLMProvider(response="not valid json at all")
        planner = InteractivePlanner(provider=provider)

        plan = _make_plan(
            steps=[PlanStep(id="step-1", description="Unchanged")],
        )
        result = await planner.discuss(plan, "feedback")

        # parse fails, new_steps is empty, so original steps remain
        assert len(result.steps) == 1
        assert result.steps[0].description == "Unchanged"


# =========================================================================
# InteractivePlanner — approve
# =========================================================================


class TestPlannerApprove:
    def test_approve_from_drafting(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.DRAFTING)
        result = planner.approve(plan)
        assert result.phase == PlanPhase.APPROVED
        assert result.approved_at is not None

    def test_approve_from_discussing(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.DISCUSSING)
        result = planner.approve(plan)
        assert result.phase == PlanPhase.APPROVED

    def test_approve_from_approved_is_idempotent(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.APPROVED)
        result = planner.approve(plan)
        assert result.phase == PlanPhase.APPROVED

    def test_approve_completed_plan_raises(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.COMPLETED)
        with pytest.raises(AgentError, match="Cannot approve"):
            planner.approve(plan)

    def test_approve_rejected_plan_raises(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.REJECTED)
        with pytest.raises(AgentError, match="Cannot approve"):
            planner.approve(plan)


# =========================================================================
# InteractivePlanner — reject
# =========================================================================


class TestPlannerReject:
    def test_reject_sets_phase(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.DRAFTING)
        result = planner.reject(plan, reason="bad plan")
        assert result.phase == PlanPhase.REJECTED

    def test_reject_without_reason(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.DISCUSSING)
        result = planner.reject(plan)
        assert result.phase == PlanPhase.REJECTED

    def test_reject_from_approved(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.APPROVED)
        result = planner.reject(plan, reason="changed mind")
        assert result.phase == PlanPhase.REJECTED


# =========================================================================
# InteractivePlanner — start_execution
# =========================================================================


class TestPlannerStartExecution:
    def test_start_from_approved(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.APPROVED,
            steps=[
                PlanStep(id="step-1", description="First"),
                PlanStep(id="step-2", description="Second", dependencies=["step-1"]),
            ],
        )
        result = planner.start_execution(plan)
        assert result.phase == PlanPhase.EXECUTING
        assert result.steps[0].status == TaskStatus.IN_PROGRESS
        assert result.steps[1].status == TaskStatus.PENDING

    def test_start_from_checkpointing(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.CHECKPOINTING,
            steps=[PlanStep(id="step-1", description="First")],
        )
        result = planner.start_execution(plan)
        assert result.phase == PlanPhase.EXECUTING

    def test_start_from_wrong_phase_raises(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.DRAFTING)
        with pytest.raises(AgentError, match="Cannot start execution"):
            planner.start_execution(plan)

    def test_start_from_completed_raises(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.COMPLETED)
        with pytest.raises(AgentError, match="Cannot start execution"):
            planner.start_execution(plan)

    def test_start_with_no_steps(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(phase=PlanPhase.APPROVED, steps=[])
        result = planner.start_execution(plan)
        assert result.phase == PlanPhase.EXECUTING
        # No steps to set in progress

    def test_start_respects_dependencies(self) -> None:
        planner = InteractivePlanner()
        step1 = PlanStep(id="step-1", description="Prerequisite")
        step2 = PlanStep(id="step-2", description="Dependent", dependencies=["step-1"])
        plan = _make_plan(phase=PlanPhase.APPROVED, steps=[step1, step2])

        result = planner.start_execution(plan)
        # Only step-1 (no deps) should be in progress
        assert result.steps[0].status == TaskStatus.IN_PROGRESS
        assert result.steps[1].status == TaskStatus.PENDING


# =========================================================================
# InteractivePlanner — advance_step
# =========================================================================


class TestPlannerAdvanceStep:
    def test_advance_marks_current_completed_and_starts_next(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="First", status=TaskStatus.IN_PROGRESS),
                PlanStep(id="step-2", description="Second"),
            ],
        )
        result = planner.advance_step(plan, result="step 1 done")

        assert result.steps[0].status == TaskStatus.COMPLETED
        assert result.steps[0].result == "step 1 done"
        assert result.steps[1].status == TaskStatus.IN_PROGRESS

    def test_advance_last_step_completes_plan(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="Only step", status=TaskStatus.IN_PROGRESS),
            ],
        )
        result = planner.advance_step(plan)

        assert result.steps[0].status == TaskStatus.COMPLETED
        assert result.phase == PlanPhase.COMPLETED

    def test_advance_with_no_current_step_completes_plan(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="Done", status=TaskStatus.COMPLETED),
            ],
        )
        result = planner.advance_step(plan)
        assert result.phase == PlanPhase.COMPLETED

    def test_advance_respects_dependency_order(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="First", status=TaskStatus.IN_PROGRESS),
                PlanStep(id="step-2", description="Second", dependencies=["step-1"]),
                PlanStep(id="step-3", description="Third", dependencies=["step-2"]),
            ],
        )
        # Advance step-1 -> step-2 should start
        result = planner.advance_step(plan, result="done 1")
        assert result.steps[0].status == TaskStatus.COMPLETED
        assert result.steps[1].status == TaskStatus.IN_PROGRESS
        assert result.steps[2].status == TaskStatus.PENDING

        # Advance step-2 -> step-3 should start (chain through result)
        result = planner.advance_step(result, result="done 2")
        assert result.steps[1].status == TaskStatus.COMPLETED
        assert result.steps[2].status == TaskStatus.IN_PROGRESS

        # Advance step-3 -> plan completes (chain through result)
        result = planner.advance_step(result, result="done 3")
        assert result.steps[2].status == TaskStatus.COMPLETED
        assert result.phase == PlanPhase.COMPLETED

    def test_advance_with_empty_result_sets_none(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="First", status=TaskStatus.IN_PROGRESS),
                PlanStep(id="step-2", description="Second"),
            ],
        )
        planner.advance_step(plan, result="")
        assert plan.steps[0].result is None

    def test_advance_skips_steps_with_unmet_dependencies(self) -> None:
        planner = InteractivePlanner()
        # step-2 depends on step-1 (completed) AND step-3 (pending)
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="First", status=TaskStatus.IN_PROGRESS),
                PlanStep(id="step-2", description="Needs both", dependencies=["step-1", "step-3"]),
                PlanStep(id="step-3", description="Independent"),
            ],
        )
        result = planner.advance_step(plan, result="first done")

        # step-1 completed, step-2 can't start (needs step-3),
        # step-3 has no deps so it starts
        assert result.steps[0].status == TaskStatus.COMPLETED
        assert result.steps[1].status == TaskStatus.PENDING
        assert result.steps[2].status == TaskStatus.IN_PROGRESS


# =========================================================================
# InteractivePlanner — checkpoint
# =========================================================================


class TestPlannerCheckpoint:
    def test_checkpoint_returns_plan_checkpoint(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[
                PlanStep(id="step-1", description="Done", status=TaskStatus.COMPLETED),
                PlanStep(id="step-2", description="Current", status=TaskStatus.IN_PROGRESS),
            ],
        )
        cp = planner.checkpoint(plan)
        assert isinstance(cp, PlanCheckpoint)
        assert cp.step_index == 1  # index of step-2

    def test_checkpoint_with_messages_and_metrics(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[PlanStep(id="step-1", description="Step", status=TaskStatus.IN_PROGRESS)],
        )
        messages = [{"role": "user", "content": "hi"}]
        metrics = {"tokens": 100.0, "cost": 0.01}
        cp = planner.checkpoint(plan, messages=messages, metrics=metrics)

        assert cp.messages_snapshot == [{"role": "user", "content": "hi"}]
        assert cp.metrics_snapshot == {"tokens": 100.0, "cost": 0.01}
        # Verify snapshots are copies
        messages.append({"role": "assistant", "content": "hello"})
        assert len(cp.messages_snapshot) == 1

    def test_checkpoint_preserves_executing_phase(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[PlanStep(id="step-1", description="Step", status=TaskStatus.IN_PROGRESS)],
        )
        planner.checkpoint(plan)
        assert plan.phase == PlanPhase.EXECUTING

    def test_checkpoint_from_non_executing_stays_checkpointing(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.APPROVED,
            steps=[PlanStep(id="step-1", description="Step")],
        )
        planner.checkpoint(plan)
        # Phase was APPROVED -> set to CHECKPOINTING, but not restored
        # because previous_phase != EXECUTING
        assert plan.phase == PlanPhase.CHECKPOINTING

    def test_checkpoint_appended_to_plan(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[PlanStep(id="step-1", description="Step", status=TaskStatus.IN_PROGRESS)],
        )
        assert len(plan.checkpoints) == 0
        planner.checkpoint(plan)
        assert len(plan.checkpoints) == 1
        planner.checkpoint(plan)
        assert len(plan.checkpoints) == 2

    def test_checkpoint_step_index_zero_when_no_current_step(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[PlanStep(id="step-1", description="Done", status=TaskStatus.COMPLETED)],
        )
        cp = planner.checkpoint(plan)
        assert cp.step_index == 0

    def test_checkpoint_no_messages_or_metrics(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(
            phase=PlanPhase.EXECUTING,
            steps=[PlanStep(id="step-1", description="Step", status=TaskStatus.IN_PROGRESS)],
        )
        cp = planner.checkpoint(plan)
        assert cp.messages_snapshot == []
        assert cp.metrics_snapshot == {}


# =========================================================================
# InteractivePlanner — get_current_step
# =========================================================================


class TestGetCurrentStep:
    def test_returns_in_progress_step(self) -> None:
        planner = InteractivePlanner()
        step = PlanStep(id="step-2", description="Active", status=TaskStatus.IN_PROGRESS)
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="Done", status=TaskStatus.COMPLETED),
            step,
            PlanStep(id="step-3", description="Pending"),
        ])
        result = planner.get_current_step(plan)
        assert result is not None
        assert result.id == "step-2"

    def test_returns_none_when_no_in_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="Done", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="Pending"),
        ])
        assert planner.get_current_step(plan) is None

    def test_returns_none_for_empty_plan(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[])
        assert planner.get_current_step(plan) is None

    def test_returns_first_in_progress_when_multiple(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="First active", status=TaskStatus.IN_PROGRESS),
            PlanStep(id="step-2", description="Second active", status=TaskStatus.IN_PROGRESS),
        ])
        result = planner.get_current_step(plan)
        assert result is not None
        assert result.id == "step-1"


# =========================================================================
# InteractivePlanner — get_progress
# =========================================================================


class TestGetProgress:
    def test_zero_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A"),
            PlanStep(id="step-2", description="B"),
        ])
        assert planner.get_progress(plan) == 0.0

    def test_half_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B"),
        ])
        assert planner.get_progress(plan) == 0.5

    def test_full_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B", status=TaskStatus.COMPLETED),
        ])
        assert planner.get_progress(plan) == 1.0

    def test_empty_plan_returns_one(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[])
        assert planner.get_progress(plan) == 1.0

    def test_skipped_counts_as_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B", status=TaskStatus.SKIPPED),
        ])
        assert planner.get_progress(plan) == 1.0

    def test_mixed_statuses(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B", status=TaskStatus.IN_PROGRESS),
            PlanStep(id="step-3", description="C", status=TaskStatus.PENDING),
            PlanStep(id="step-4", description="D", status=TaskStatus.SKIPPED),
        ])
        # 2 out of 4 (completed + skipped)
        assert planner.get_progress(plan) == 0.5

    def test_one_third_progress(self) -> None:
        planner = InteractivePlanner()
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B"),
            PlanStep(id="step-3", description="C"),
        ])
        assert abs(planner.get_progress(plan) - 1 / 3) < 1e-9


# =========================================================================
# InteractivePlanner — _find_next_step (tested indirectly but also directly)
# =========================================================================


class TestFindNextStep:
    def test_finds_first_pending_with_no_deps(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A"),
            PlanStep(id="step-2", description="B"),
        ])
        result = InteractivePlanner._find_next_step(plan)
        assert result is not None
        assert result.id == "step-1"

    def test_skips_step_with_unmet_deps(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.IN_PROGRESS),
            PlanStep(id="step-2", description="B", dependencies=["step-1"]),
            PlanStep(id="step-3", description="C"),
        ])
        result = InteractivePlanner._find_next_step(plan)
        assert result is not None
        assert result.id == "step-3"

    def test_returns_none_when_all_in_progress_or_completed(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.COMPLETED),
            PlanStep(id="step-2", description="B", status=TaskStatus.IN_PROGRESS),
        ])
        assert InteractivePlanner._find_next_step(plan) is None

    def test_returns_none_for_empty_plan(self) -> None:
        plan = _make_plan(steps=[])
        assert InteractivePlanner._find_next_step(plan) is None

    def test_skipped_dep_counts_as_satisfied(self) -> None:
        plan = _make_plan(steps=[
            PlanStep(id="step-1", description="A", status=TaskStatus.SKIPPED),
            PlanStep(id="step-2", description="B", dependencies=["step-1"]),
        ])
        result = InteractivePlanner._find_next_step(plan)
        assert result is not None
        assert result.id == "step-2"
