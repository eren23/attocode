"""Outer-loop meta-harness runner for code-intel optimization.

Orchestrates the evolution loop: propose configs → evaluate → accept/reject.
The runner is bench-agnostic: pass any evaluator that yields ``EvalResult``,
any config dataclass with ``to_dict``/``from_dict``/``save_yaml``/``validate``
shape, and any propose function with the correct signature. Defaults remain
the search bench (``CodeIntelBenchEvaluator`` + ``HarnessConfig``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from attoswarm.research.evaluator import EvalResult

from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.paths import (
    baseline_path as default_baseline_path,
)
from eval.meta_harness.paths import (
    best_config_path as default_best_config_path,
)
from eval.meta_harness.paths import (
    evolution_path as default_evolution_path,
)
from eval.meta_harness.paths import (
    results_dir as default_results_dir,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class _ConfigLike(Protocol):
    """Minimal protocol every bench config dataclass must satisfy."""

    def to_dict(self) -> dict[str, Any]: ...
    def save_yaml(self, path: str) -> None: ...
    def validate(self) -> list[str]: ...


# A propose function takes (current_best_config, eval_metadata, history,
# n_candidates, iteration) and returns a list of (candidate, hypothesis)
# tuples. Implementations may ignore arguments they don't need.
ProposeFn = Callable[
    [Any, dict[str, Any], list[dict[str, Any]], int, int],
    list[tuple[Any, str]],
]

# An accept predicate decides whether a candidate's result improves on
# current best. Returns (accepted, reason). Default: strict score > best.
AcceptPredicate = Callable[
    [EvalResult, EvalResult | None, float],
    tuple[bool, str],
]


def default_accept_predicate(
    result: EvalResult,
    baseline_result: EvalResult | None,  # noqa: ARG001 - signature parity
    current_best: float,
) -> tuple[bool, str]:
    """Strict-improvement predicate (preserves legacy search-bench behavior)."""
    if result.metric_value > current_best:
        return True, "improved"
    return False, f"no_improvement: {result.metric_value:.4f} <= {current_best:.4f}"


@dataclass
class EvolutionEntry:
    """A single entry in the evolution summary."""

    iteration: int
    config: dict[str, Any]
    score: float
    status: str  # "accepted" | "rejected" | "error"
    baseline_score: float
    delta: float
    hypothesis: str = ""
    search_quality: dict[str, Any] | None = None
    mcp_bench: dict[str, Any] | None = None
    timestamp: str = ""

    # Rule-bench additions — optional so search-bench entries stay compact.
    per_language: dict[str, float] | None = None
    reject_reason: str | None = None
    bench_metadata: dict[str, Any] | None = None


def _default_search_propose(
    current_best: HarnessConfig,
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int,
    iteration: int,
) -> list[tuple[HarnessConfig, str]]:
    """Default search-bench proposer — random parameter sweep."""
    import random

    from eval.meta_harness.harness_config import PARAMETER_RANGES

    random.seed(42 + iteration)
    base_dict = current_best.to_dict()
    candidates: list[tuple[HarnessConfig, str]] = []
    param_names = list(PARAMETER_RANGES.keys())

    for _ in range(n_candidates):
        new_dict = dict(base_dict)
        n_params = random.randint(1, 3)
        chosen = random.sample(param_names, min(n_params, len(param_names)))
        changes: list[str] = []

        for param in chosen:
            lo, hi = PARAMETER_RANGES[param]
            current = new_dict.get(param, (lo + hi) / 2)

            if isinstance(lo, int) and isinstance(hi, int):
                new_val: float | int = random.randint(int(lo), int(hi))
            else:
                spread = (hi - lo) * 0.2
                new_val = max(lo, min(hi, current + random.gauss(0, spread)))

            new_dict[param] = new_val
            if isinstance(new_val, float):
                changes.append(f"{param}: {current}->{new_val:.3f}")
            else:
                changes.append(f"{param}: {current}->{new_val}")

        hypothesis = f"sweep: {', '.join(changes)}"
        candidates.append((HarnessConfig.from_dict(new_dict), hypothesis))

    return candidates


def _default_search_propose_llm(
    current_best: HarnessConfig,
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int,
    iteration: int,  # noqa: ARG001 - signature parity
) -> list[tuple[HarnessConfig, str]]:
    """Default search-bench LLM proposer — wraps ``proposer.propose_configs_llm``."""
    from eval.meta_harness.proposer import propose_configs_llm

    try:
        return propose_configs_llm(
            current_config=current_best,
            eval_result=eval_metadata,
            history=history,
            n_candidates=n_candidates,
        )
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("LLM proposal failed (%s), returning empty list", exc)
        return []


@dataclass
class _BenchSpec:
    """Per-bench plumbing used by :class:`MetaHarnessRunner`."""

    name: str
    evaluator: Any
    config_default: _ConfigLike
    config_filename: str
    propose_sweep: ProposeFn
    propose_llm: ProposeFn
    accept_predicate: AcceptPredicate = field(default=default_accept_predicate)
    artifact_prefix: str = ""


def make_search_bench_spec(
    *,
    search_repos: list[str] | None = None,
    bench_repos: list[str] | None = None,
    split: str = "eval",
) -> _BenchSpec:
    """Construct the default search-bench spec (back-compat shim)."""
    return _BenchSpec(
        name="search",
        evaluator=CodeIntelBenchEvaluator(
            search_repos=search_repos,
            bench_repos=bench_repos,
            split=split,
        ),
        config_default=HarnessConfig.default(),
        config_filename="harness_config.yaml",
        propose_sweep=_default_search_propose,
        propose_llm=_default_search_propose_llm,
        accept_predicate=default_accept_predicate,
        artifact_prefix="",
    )


class MetaHarnessRunner:
    """Standalone meta-harness optimization loop.

    For each iteration:
    1. Loads current best config (or baseline defaults)
    2. Generates candidate configs (via LLM proposer or parameter sweep)
    3. Evaluates each candidate
    4. Calls the bench's ``accept_predicate`` to decide accept/reject
    5. Logs the evolution entry to JSONL

    The default constructor preserves legacy search-bench behavior. Pass
    ``bench_spec=`` to drive a different bench (e.g. rule-bench).
    """

    def __init__(
        self,
        iterations: int = 10,
        candidates_per_iteration: int = 3,
        search_repos: list[str] | None = None,
        bench_repos: list[str] | None = None,
        results_dir: str | None = None,
        propose_mode: str = "sweep",  # "sweep" | "llm"
        *,
        bench_spec: _BenchSpec | None = None,
    ) -> None:
        self._iterations = iterations
        self._candidates_per_iter = candidates_per_iteration
        self._results_dir = Path(results_dir or default_results_dir())
        self._propose_mode = propose_mode

        self._spec = bench_spec or make_search_bench_spec(
            search_repos=search_repos,
            bench_repos=bench_repos,
        )

        self._best_config: _ConfigLike = self._spec.config_default
        self._best_score = 0.0
        self._baseline_score = 0.0
        self._baseline_result: EvalResult | None = None
        self._history: list[EvolutionEntry] = []
        self._last_eval_metadata: dict[str, Any] = {}

    # ---------------------------------------------------------------
    # Path helpers (per-bench prefixed)
    # ---------------------------------------------------------------

    def _baseline_artifact(self) -> Path:
        return Path(default_baseline_path(self._spec.artifact_prefix))

    def _evolution_artifact(self) -> Path:
        return Path(default_evolution_path(self._spec.artifact_prefix))

    def _best_config_artifact(self) -> Path:
        return Path(default_best_config_path(self._spec.artifact_prefix))

    # ---------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------

    async def run(self) -> None:
        """Run the full evolution loop."""
        self._results_dir.mkdir(parents=True, exist_ok=True)
        evo_path = self._evolution_artifact()

        # Phase 0: Evaluate baseline
        print(f"Phase 0: Evaluating baseline ({self._spec.name} bench)...")
        baseline_result = await self._spec.evaluator.evaluate(_PROJECT_ROOT)
        if not baseline_result.success:
            print(f"Baseline evaluation failed: {baseline_result.error}")
            return

        self._baseline_result = baseline_result
        self._baseline_score = baseline_result.metric_value
        self._best_score = baseline_result.metric_value
        self._last_eval_metadata = baseline_result.metadata or {}
        self._last_eval_metadata["composite"] = baseline_result.metric_value
        print(f"  Baseline score: {self._baseline_score:.4f}")

        # Save baseline
        baseline_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "bench": self._spec.name,
            "composite_score": baseline_result.metric_value,
            "metrics": baseline_result.metrics,
            "metadata": baseline_result.metadata,
            "config": self._best_config.to_dict(),
        }
        with open(self._baseline_artifact(), "w") as f:
            json.dump(baseline_data, f, indent=2, default=str)

        # Evolution iterations
        for iteration in range(1, self._iterations + 1):
            print(f"\nIteration {iteration}/{self._iterations}")
            print(f"  Current best: {self._best_score:.4f}")

            raw_candidates = self._propose_candidates(iteration)
            print(f"  Generated {len(raw_candidates)} candidates")

            for i, (candidate, hypothesis) in enumerate(raw_candidates, 1):
                errors = candidate.validate()
                if errors:
                    print(f"  Candidate {i}: INVALID - {errors}")
                    continue

                if hypothesis:
                    print(f"  Candidate {i} hypothesis: {hypothesis[:80]}")

                with tempfile.TemporaryDirectory() as tmpdir:
                    candidate.save_yaml(os.path.join(tmpdir, self._spec.config_filename))
                    result = await self._spec.evaluator.evaluate(tmpdir)

                if not result.success:
                    entry = EvolutionEntry(
                        iteration=iteration,
                        config=candidate.to_dict(),
                        score=0.0,
                        status="error",
                        baseline_score=self._baseline_score,
                        delta=0.0,
                        hypothesis=hypothesis,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                        reject_reason=f"error: {result.error}",
                    )
                    self._history.append(entry)
                    self._write_entry(evo_path, entry)
                    print(f"  Candidate {i}: ERROR - {result.error}")
                    continue

                score = result.metric_value
                delta = score - self._best_score

                accepted, reason = self._spec.accept_predicate(
                    result, self._baseline_result, self._best_score,
                )

                if accepted:
                    status = "accepted"
                    self._best_score = score
                    self._best_config = candidate
                    self._last_eval_metadata = result.metadata or {}
                    self._last_eval_metadata["composite"] = score
                    candidate.save_yaml(str(self._best_config_artifact()))
                    print(f"  Candidate {i}: ACCEPTED score={score:.4f} delta={delta:+.4f}")
                else:
                    status = "rejected"
                    print(f"  Candidate {i}: REJECTED score={score:.4f} delta={delta:+.4f} reason={reason}")

                metadata = result.metadata or {}
                entry = EvolutionEntry(
                    iteration=iteration,
                    config=candidate.to_dict(),
                    score=score,
                    status=status,
                    baseline_score=self._baseline_score,
                    delta=delta,
                    hypothesis=hypothesis,
                    search_quality=metadata.get("search_quality"),
                    mcp_bench=metadata.get("mcp_bench"),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                    per_language=metadata.get("per_language"),
                    reject_reason=None if accepted else reason,
                    bench_metadata=metadata.get(self._spec.name),
                )
                self._history.append(entry)
                self._write_entry(evo_path, entry)

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Evolution complete: {self._iterations} iterations ({self._spec.name} bench)")
        print(f"  Baseline:  {self._baseline_score:.4f}")
        print(f"  Best:      {self._best_score:.4f}")
        print(f"  Delta:     {self._best_score - self._baseline_score:+.4f}")
        accepted = sum(1 for e in self._history if e.status == "accepted")
        print(f"  Accepted:  {accepted}/{len(self._history)} candidates")
        if self._best_score > self._baseline_score:
            print(f"\n  Best config saved to: {self._best_config_artifact()}")

    # ---------------------------------------------------------------
    # Proposer dispatch
    # ---------------------------------------------------------------

    def _propose_candidates(self, iteration: int) -> list[tuple[Any, str]]:
        history_dicts = [asdict(e) for e in self._history]
        if self._propose_mode == "llm":
            try:
                candidates = self._spec.propose_llm(
                    self._best_config,
                    self._last_eval_metadata,
                    history_dicts,
                    self._candidates_per_iter,
                    iteration,
                )
                if candidates:
                    return candidates
                print("  LLM returned no valid candidates, falling back to sweep")
            except Exception as exc:
                print(f"  LLM proposal failed ({exc}), falling back to sweep")
        return self._spec.propose_sweep(
            self._best_config,
            self._last_eval_metadata,
            history_dicts,
            self._candidates_per_iter,
            iteration,
        )

    @staticmethod
    def _write_entry(path: Path, entry: EvolutionEntry) -> None:
        """Append an evolution entry to JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(asdict(entry), default=str) + "\n")
