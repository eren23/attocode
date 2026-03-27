from __future__ import annotations

import asyncio
import shlex
import sys
from typing import TYPE_CHECKING

import pytest

from attoswarm.research.evaluator import (
    CommandEvaluator,
    CompositeEvaluator,
    EvalResult,
    ScriptEvaluator,
)
from attoswarm.research.evaluator import (
    TestPassRateEvaluator as ResearchTestPassRateEvaluator,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_command_evaluator_parses_last_numeric_from_mixed_output() -> None:
    evaluator = CommandEvaluator(
        f"{shlex.quote(sys.executable)} -c \"print('metric: 0.25'); print('final score 1.75')\""
    )

    result = asyncio.run(evaluator.evaluate("."))

    assert result.success is True
    assert result.metric_value == 1.75


def test_command_evaluator_handles_structured_error_and_no_numeric() -> None:
    structured = CommandEvaluator(
        f"{shlex.quote(sys.executable)} -c \"import json; print(json.dumps({{'primary_metric': 1.0, 'success': False, 'error': 'bad export'}}))\""
    )
    structured_result = asyncio.run(structured.evaluate("."))
    assert structured_result.success is False
    assert structured_result.error == "bad export"

    plain = CommandEvaluator(f"{shlex.quote(sys.executable)} -c \"print('no metric here')\"")
    plain_result = asyncio.run(plain.evaluate("."))
    assert plain_result.success is False
    assert plain_result.error == "No numeric value found in output"


def test_script_evaluator_supports_plain_metric_and_structured_output(tmp_path: Path) -> None:
    metric_script = tmp_path / "metric_eval.py"
    metric_script.write_text("print('{\"metric\": 2.5, \"seed\": 3}')\n", encoding="utf-8")

    structured_script = tmp_path / "structured_eval.py"
    structured_script.write_text(
        "import json\nprint(json.dumps({'primary_metric': 1.2, 'secondary_metrics': {'aux': 0.5}, 'artifacts': ['m.bin']}))\n",
        encoding="utf-8",
    )

    metric_result = asyncio.run(ScriptEvaluator(str(metric_script)).evaluate(str(tmp_path)))
    structured_result = asyncio.run(ScriptEvaluator(str(structured_script)).evaluate(str(tmp_path)))

    assert metric_result.success is True
    assert metric_result.metric_value == 2.5
    assert metric_result.seed == 3

    assert structured_result.success is True
    assert structured_result.metric_value == 1.2
    assert structured_result.metrics == {"aux": 0.5}
    assert structured_result.artifacts == ["m.bin"]


def test_script_evaluator_reports_invalid_json(tmp_path: Path) -> None:
    bad_script = tmp_path / "bad_eval.py"
    bad_script.write_text("print('not json')\n", encoding="utf-8")

    result = asyncio.run(ScriptEvaluator(str(bad_script)).evaluate(str(tmp_path)))

    assert result.success is False
    assert "Failed to parse script output" in result.error


def test_test_pass_rate_evaluator_runs_real_pytest(tmp_path: Path) -> None:
    passing = tmp_path / "test_ok.py"
    passing.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    failing = tmp_path / "test_bad.py"
    failing.write_text("def test_bad():\n    assert False\n", encoding="utf-8")

    result = asyncio.run(ResearchTestPassRateEvaluator(timeout=30.0).evaluate(str(tmp_path)))

    assert result.success is True
    assert result.metric_value == 0.5
    assert result.metadata == {"passed": 1, "failed": 1, "total": 2}


def test_composite_evaluator_handles_partial_and_total_failure() -> None:
    class StaticEvaluator:
        def __init__(self, result: EvalResult) -> None:
            self._result = result

        async def evaluate(self, working_dir: str) -> EvalResult:
            return self._result

    composite = CompositeEvaluator(
        [
            (StaticEvaluator(EvalResult(metric_value=2.0, raw_output="a")), 0.25),
            (StaticEvaluator(EvalResult(metric_value=4.0, raw_output="b")), 0.75),
            (StaticEvaluator(EvalResult(metric_value=0.0, success=False, error="failed")), 0.50),
        ]
    )
    result = asyncio.run(composite.evaluate("."))
    assert result.success is True
    assert result.metric_value == pytest.approx(3.5)
    assert result.metadata == {"errors": ["failed"]}

    total_failure = CompositeEvaluator(
        [(StaticEvaluator(EvalResult(metric_value=0.0, success=False, error="boom")), 1.0)]
    )
    failed = asyncio.run(total_failure.evaluate("."))
    assert failed.success is False
    assert "All evaluators failed" in failed.error


def test_composite_evaluator_rejects_zero_weights() -> None:
    from attoswarm.research.evaluator import CompositeEvaluator

    class DummyEval:
        async def evaluate(self, working_dir: str):
            pass

    with pytest.raises(ValueError, match="zero"):
        CompositeEvaluator([(DummyEval(), 0.0), (DummyEval(), 0.0)])
