"""Tests for swarm critic -- wave review and fixup task generation."""

from __future__ import annotations

import pytest

from attocode.integrations.swarm.critic import (
    _build_review_prompt,
    _extract_content,
    _parse_review_response,
    build_fixup_tasks,
)
from attocode.integrations.swarm.types import (
    FixupTask,
    SubtaskType,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    WaveReviewResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "t1",
    description: str = "Implement feature X",
    status: SwarmTaskStatus = SwarmTaskStatus.COMPLETED,
    output: str = "Done. Created foo.py",
    files_modified: list[str] | None = None,
    quality_score: int | None = None,
    failure_mode: str | None = None,
) -> SwarmTask:
    result = SwarmTaskResult(
        success=True,
        output=output,
        files_modified=files_modified,
        quality_score=quality_score,
    )
    task = SwarmTask(
        id=task_id,
        description=description,
        type=SubtaskType.IMPLEMENT,
        status=status,
    )
    task.result = result
    if failure_mode:
        from attocode.integrations.swarm.types import TaskFailureMode
        task.failure_mode = TaskFailureMode(failure_mode)
    return task


# ---------------------------------------------------------------------------
# _build_review_prompt
# ---------------------------------------------------------------------------


class TestBuildReviewPrompt:
    def test_includes_wave_number(self):
        prompt = _build_review_prompt(2, [_make_task()], [])
        assert "Wave 3" in prompt  # 0-indexed wave_index=2 -> Wave 3

    def test_includes_completed_task_details(self):
        t = _make_task(task_id="abc", description="Add login", output="Created auth.py")
        prompt = _build_review_prompt(0, [t], [])
        assert "abc" in prompt
        assert "Add login" in prompt
        assert "Created auth.py" in prompt

    def test_truncates_long_output(self):
        t = _make_task(output="x" * 3000)
        prompt = _build_review_prompt(0, [t], [])
        assert "[truncated]" in prompt

    def test_includes_failed_tasks(self):
        completed = [_make_task(task_id="c1")]
        failed = [_make_task(task_id="f1", status=SwarmTaskStatus.FAILED, failure_mode="error")]
        prompt = _build_review_prompt(0, completed, failed)
        assert "f1" in prompt
        assert "Failed Tasks" in prompt

    def test_includes_files_modified(self):
        t = _make_task(files_modified=["src/foo.py", "src/bar.py"])
        prompt = _build_review_prompt(0, [t], [])
        assert "src/foo.py" in prompt
        assert "src/bar.py" in prompt

    def test_includes_quality_score(self):
        t = _make_task(quality_score=4)
        prompt = _build_review_prompt(0, [t], [])
        assert "4/5" in prompt

    def test_includes_instructions(self):
        prompt = _build_review_prompt(0, [_make_task()], [])
        assert "ASSESSMENT:" in prompt
        assert "FIXUP:" in prompt


# ---------------------------------------------------------------------------
# _parse_review_response
# ---------------------------------------------------------------------------


class TestParseReviewResponse:
    def test_good_assessment(self):
        content = "ASSESSMENT: good\n\nAll tasks look fine."
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "good"
        assert len(result.fixup_instructions) == 0

    def test_needs_fixes_assessment(self):
        content = (
            "ASSESSMENT: needs-fixes\n"
            "FIXUP: t1 | Missing error handling in foo.py"
        )
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "needs-fixes"
        assert len(result.fixup_instructions) == 1
        assert result.fixup_instructions[0]["fixes_task_id"] == "t1"
        assert "Missing error handling" in result.fixup_instructions[0]["fix_description"]

    def test_critical_issues_assessment(self):
        content = "ASSESSMENT: critical-issues\nFIXUP: t1 | Broken imports"
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "critical-issues"

    def test_multiple_fixups(self):
        content = (
            "ASSESSMENT: needs-fixes\n"
            "FIXUP: t1 | Fix error handling\n"
            "FIXUP: t2 | Add tests\n"
        )
        completed = [_make_task(task_id="t1"), _make_task(task_id="t2")]
        result = _parse_review_response(content, completed)
        assert len(result.fixup_instructions) == 2

    def test_tasks_without_fixups_marked_good(self):
        content = "ASSESSMENT: needs-fixes\nFIXUP: t1 | Fix something"
        completed = [_make_task(task_id="t1"), _make_task(task_id="t2")]
        result = _parse_review_response(content, completed)
        # t2 should be marked good
        t2_assessments = [a for a in result.task_assessments if a["task_id"] == "t2"]
        assert len(t2_assessments) == 1
        assert t2_assessments[0]["assessment"] == "good"

    def test_unknown_assessment_defaults_to_good(self):
        content = "ASSESSMENT: unknown_value"
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "good"

    def test_no_assessment_line_defaults_to_good(self):
        content = "Everything looks fine!"
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "good"

    def test_underscore_variant(self):
        content = "ASSESSMENT: needs_fixes\nFIXUP: t1 | Fix it"
        result = _parse_review_response(content, [_make_task()])
        assert result.assessment == "needs-fixes"


# ---------------------------------------------------------------------------
# build_fixup_tasks
# ---------------------------------------------------------------------------


class TestBuildFixupTasks:
    def test_good_assessment_returns_empty(self):
        result = WaveReviewResult(assessment="good", task_assessments=[])
        assert build_fixup_tasks(result, 0) == []

    def test_needs_fixes_creates_tasks(self):
        result = WaveReviewResult(
            assessment="needs-fixes",
            task_assessments=[],
            fixup_instructions=[
                {"fixes_task_id": "t1", "fix_description": "Add error handling"},
            ],
        )
        fixups = build_fixup_tasks(result, 2)
        assert len(fixups) == 1
        assert fixups[0].id == "fixup-w2-0"
        assert fixups[0].fixes_task_id == "t1"
        assert "error handling" in fixups[0].description
        assert "t1" in fixups[0].dependencies

    def test_skips_incomplete_instructions(self):
        result = WaveReviewResult(
            assessment="needs-fixes",
            task_assessments=[],
            fixup_instructions=[
                {"fixes_task_id": "", "fix_description": "Missing task id"},
                {"fixes_task_id": "t1", "fix_description": ""},
                {"fixes_task_id": "t2", "fix_description": "Valid fix"},
            ],
        )
        fixups = build_fixup_tasks(result, 0)
        assert len(fixups) == 1
        assert fixups[0].fixes_task_id == "t2"

    def test_multiple_fixups(self):
        result = WaveReviewResult(
            assessment="critical-issues",
            task_assessments=[],
            fixup_instructions=[
                {"fixes_task_id": "t1", "fix_description": "Fix A"},
                {"fixes_task_id": "t2", "fix_description": "Fix B"},
            ],
        )
        fixups = build_fixup_tasks(result, 1)
        assert len(fixups) == 2
        assert fixups[0].id == "fixup-w1-0"
        assert fixups[1].id == "fixup-w1-1"

    def test_fixup_has_target_files(self):
        result = WaveReviewResult(
            assessment="needs-fixes",
            task_assessments=[],
            fixup_instructions=[
                {
                    "fixes_task_id": "t1",
                    "fix_description": "Fix imports",
                    "target_files": ["src/foo.py"],
                },
            ],
        )
        fixups = build_fixup_tasks(result, 0)
        assert fixups[0].target_files == ["src/foo.py"]


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_string_response(self):
        assert _extract_content("hello") == "hello"

    def test_dict_with_content(self):
        assert _extract_content({"content": "world"}) == "world"

    def test_dict_with_message(self):
        assert _extract_content({"message": {"content": "nested"}}) == "nested"

    def test_object_with_content_str(self):
        class R:
            content = "attr"
        assert _extract_content(R()) == "attr"

    def test_object_with_content_list(self):
        class Block:
            def __init__(self, t: str):
                self.text = t
        class R:
            content = [Block("a"), Block("b")]
        assert "a" in _extract_content(R())
        assert "b" in _extract_content(R())

    def test_fallback_to_str(self):
        result = _extract_content(42)
        assert result == "42"
