"""Tests for eval harness instance wiring."""

from __future__ import annotations

import pytest

from eval.harness import BenchInstance, EvalHarness, InstanceStatus


class _FactoryWithInstanceHook:
    def __init__(self) -> None:
        self.bound_instance: BenchInstance | None = None

    def set_instance(self, instance: BenchInstance) -> None:
        self.bound_instance = instance

    async def create_and_run(
        self,
        working_dir: str,
        problem_statement: str,
        *,
        model: str | None = None,
        max_iterations: int = 50,
        timeout: float = 600.0,
    ) -> dict[str, object]:
        assert self.bound_instance is not None
        return {
            "output": "ok",
            "tokens_used": 1,
            "cost": 0.01,
            "iterations": 1,
            "tool_calls": 1,
            "model": model or "test-model",
        }


@pytest.mark.asyncio
async def test_run_instance_calls_factory_set_instance(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    instance = BenchInstance(
        instance_id="example__repo-1",
        repo=".",
        base_commit="",
        problem_statement="Fix bug",
    )
    factory = _FactoryWithInstanceHook()
    harness = EvalHarness(
        agent_factory=factory,
        results_db=str(tmp_path / "eval.db"),
        work_dir=str(tmp_path / "work"),
        model="test-model",
    )

    instance_dir = tmp_path / "work" / instance.instance_id
    instance_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "eval.harness.setup_instance", lambda _instance, _work_dir: str(instance_dir)
    )
    monkeypatch.setattr(
        "eval.harness.get_generated_patch", lambda _instance_dir: "diff --git a b"
    )
    monkeypatch.setattr(
        "eval.harness.verify_instance", lambda _instance, _instance_dir: True
    )

    result = await harness.run_instance(instance)
    harness.close()

    assert factory.bound_instance is instance
    assert result.status == InstanceStatus.PASSED
