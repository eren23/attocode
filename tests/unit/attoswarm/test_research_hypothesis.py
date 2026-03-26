from __future__ import annotations

from attoswarm.research.experiment import Experiment
from attoswarm.research.hypothesis import HypothesisGenerator


def test_hypothesis_build_prompt_includes_history_targets_and_code_intel() -> None:
    class FakeCodeIntel:
        def file_analysis_data(self, path: str) -> dict[str, str]:
            return {"summary": f"summary for {path}"}

    history = [
        Experiment(
            experiment_id="exp-1",
            iteration=1,
            hypothesis="try EMA",
            metric_value=1.1,
            reject_reason="too noisy",
        ),
        Experiment(
            experiment_id="exp-2",
            iteration=2,
            hypothesis="try bigger hash",
            metric_value=1.2,
            accepted=True,
        ),
    ]
    generator = HypothesisGenerator(
        goal="improve val_bpb",
        target_files=["train_gpt.py", "export.py"],
        code_intel=FakeCodeIntel(),
    )

    prompt = generator.build_prompt(
        iteration=3,
        history=history,
        best_metric=1.05,
        metric_name="val_bpb",
        metric_direction="minimize",
    )

    assert "## Goal" in prompt
    assert "Current best: 1.05" in prompt
    assert "### Experiment 1 [REJECTED]" in prompt
    assert "### Experiment 2 [ACCEPTED]" in prompt
    assert "train_gpt.py, export.py" in prompt
    assert "summary for train_gpt.py" in prompt


def test_hypothesis_build_prompt_tolerates_code_intel_errors() -> None:
    class FailingCodeIntel:
        def file_analysis_data(self, path: str) -> dict[str, str]:
            raise RuntimeError(path)

    generator = HypothesisGenerator(
        goal="improve score",
        target_files=["target.txt"],
        code_intel=FailingCodeIntel(),
    )

    prompt = generator.build_prompt(
        iteration=1,
        history=[],
        best_metric=None,
    )

    assert "## Goal" in prompt
    assert "target.txt" in prompt


def test_hypothesis_generate_candidate_covers_strategies_and_notes() -> None:
    history = [
        Experiment(
            experiment_id="exp-last",
            iteration=7,
            hypothesis="bad idea",
            reject_reason="blew up training",
        )
    ]
    generator = HypothesisGenerator(goal="improve score", target_files=["train.py"])

    explore = generator.generate_candidate(
        iteration=8,
        strategy="explore",
        history=history,
        best_metric=1.0,
        steering_notes=["focus on quantization"],
    )
    assert explore.startswith("Steering: focus on quantization.")
    assert "opens a new direction" in explore
    assert "Avoid repeating the last rejected pattern" in explore

    exploit = generator.generate_candidate(
        iteration=8,
        strategy="exploit",
        history=[],
        best_metric=1.0,
    )
    assert "Build on the current best branch" in exploit

    ablate = generator.generate_candidate(
        iteration=8,
        strategy="ablate",
        history=[],
        best_metric=1.0,
    )
    assert "remove or simplify one mechanism" in ablate

    compose = generator.generate_candidate(
        iteration=8,
        strategy="compose",
        history=[],
        best_metric=1.0,
    )
    assert "integrate one proven technique" in compose

    reproduce = generator.generate_candidate(
        iteration=8,
        strategy="reproduce",
        history=[],
        best_metric=1.0,
    )
    assert "validate the gain" in reproduce

    fallback = generator.generate_candidate(
        iteration=8,
        strategy="mystery",
        history=[],
        best_metric=1.0,
    )
    assert "likely to improve the metric" in fallback
