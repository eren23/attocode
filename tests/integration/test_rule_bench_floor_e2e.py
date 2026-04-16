"""Integration: per-language floor rejects regressions inside ``MetaHarnessRunner``.

We drive the runner with a stubbed bench spec so the end-to-end flow runs
in milliseconds. The runner must:

1. Accept a candidate that improves the composite while keeping every
   language above the floor.
2. Reject a candidate whose composite goes UP but where a single language
   drops more than 5% — and record the floor_violation reason in the
   evolution journal.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from attoswarm.research.evaluator import EvalResult

from eval.meta_harness.meta_loop import MetaHarnessRunner, _BenchSpec
from eval.meta_harness.rule_bench.predicate import rule_accept_predicate


@dataclass
class _StubConfig:
    """Minimal config that satisfies _ConfigLike."""

    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label}

    def save_yaml(self, path: str) -> None:
        Path(path).write_text(f"label: {self.label}\n", encoding="utf-8")

    def validate(self) -> list[str]:
        return []


class _ScriptedEvaluator:
    """Replays a fixed sequence of EvalResults so we can drive the runner."""

    def __init__(self, results: list[EvalResult]) -> None:
        self._results = list(results)
        self._idx = 0

    async def evaluate(self, working_dir: str) -> EvalResult:  # noqa: ARG002
        if self._idx >= len(self._results):
            return EvalResult(
                metric_value=0.0, error="ran out of scripted results", success=False,
            )
        result = self._results[self._idx]
        self._idx += 1
        return result


def _make_propose(plan: list[tuple[_StubConfig, str]]):
    """Return a propose_fn that yields the planned candidates over iterations."""
    cursor = {"i": 0}

    def propose(
        current_best: Any,  # noqa: ARG001
        eval_metadata: dict[str, Any],  # noqa: ARG001
        history: list[dict[str, Any]],  # noqa: ARG001
        n_candidates: int,
        iteration: int,  # noqa: ARG001
    ) -> list[tuple[_StubConfig, str]]:
        out: list[tuple[_StubConfig, str]] = []
        for _ in range(n_candidates):
            if cursor["i"] >= len(plan):
                break
            out.append(plan[cursor["i"]])
            cursor["i"] += 1
        return out

    return propose


@pytest.fixture()
def isolated_results_dir(monkeypatch, tmp_path):
    """Direct meta-harness artifact writes into tmp_path."""
    monkeypatch.setenv("ATTOCODE_META_HARNESS_RESULTS", str(tmp_path))
    return tmp_path


def test_floor_rejects_regression_accepts_balanced(
    isolated_results_dir: Path,
) -> None:
    # Baseline: python=0.6, go=0.5 → composite ~0.55
    baseline = EvalResult(
        metric_value=0.55,
        metadata={"per_language": {"python": 0.6, "go": 0.5}},
        success=True,
    )
    # Candidate A: composite UP (0.65) but go drops to 0.35 (floor breach)
    candidate_a = EvalResult(
        metric_value=0.65,
        metadata={"per_language": {"python": 0.95, "go": 0.35}},
        success=True,
    )
    # Candidate B: composite UP (0.6) and go stays above floor (0.48 > 0.475)
    candidate_b = EvalResult(
        metric_value=0.6,
        metadata={"per_language": {"python": 0.72, "go": 0.48}},
        success=True,
    )

    evaluator = _ScriptedEvaluator([baseline, candidate_a, candidate_b])

    plan = [
        (_StubConfig(label="A"), "candidate A"),
        (_StubConfig(label="B"), "candidate B"),
    ]

    spec = _BenchSpec(
        name="rule",
        evaluator=evaluator,
        config_default=_StubConfig(label="default"),
        config_filename="rule_harness_config.yaml",
        propose_sweep=_make_propose(plan),
        propose_llm=_make_propose(plan),  # unused but required
        accept_predicate=rule_accept_predicate,
        artifact_prefix="rule_",
    )

    runner = MetaHarnessRunner(
        iterations=2,
        candidates_per_iteration=1,
        propose_mode="sweep",
        bench_spec=spec,
    )
    asyncio.run(runner.run())

    # Inspect the evolution journal
    evo_path = isolated_results_dir / "rule_evolution_summary.jsonl"
    assert evo_path.is_file(), f"missing {evo_path}"
    entries = [json.loads(line) for line in evo_path.read_text().splitlines()]
    assert len(entries) == 2

    # Iteration 1: candidate A → REJECTED with floor_violation:go
    a = entries[0]
    assert a["status"] == "rejected"
    assert a["reject_reason"] is not None
    assert "floor_violation:go" in a["reject_reason"]

    # Iteration 2: candidate B → ACCEPTED
    b = entries[1]
    assert b["status"] == "accepted"
    assert b["per_language"] == {"python": 0.72, "go": 0.48}
