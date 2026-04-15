"""Outer-loop meta-harness runner for code-intel optimization.

Orchestrates the evolution loop: propose configs → evaluate → accept/reject.
Uses the research orchestrator as the campaign backbone when available,
with a standalone fallback for simpler usage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

import yaml

from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
from eval.meta_harness.harness_config import PARAMETER_RANGES, HarnessConfig

logger = logging.getLogger(__name__)


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


class MetaHarnessRunner:
    """Standalone meta-harness optimization loop.

    For each iteration:
    1. Loads current best config (or baseline defaults)
    2. Generates candidate configs (via LLM proposer or parameter sweep)
    3. Evaluates each candidate
    4. Accepts if score improves over current best
    5. Logs evolution_summary.jsonl
    """

    def __init__(
        self,
        iterations: int = 10,
        candidates_per_iteration: int = 3,
        search_repos: list[str] | None = None,
        bench_repos: list[str] | None = None,
        results_dir: str | None = None,
        propose_mode: str = "sweep",  # "sweep" | "llm"
    ) -> None:
        self._iterations = iterations
        self._candidates_per_iter = candidates_per_iteration
        self._results_dir = Path(results_dir or os.path.join(
            _PROJECT_ROOT, "eval", "meta_harness", "results",
        ))
        self._propose_mode = propose_mode

        self._evaluator = CodeIntelBenchEvaluator(
            search_repos=search_repos,
            bench_repos=bench_repos,
            split="eval",
        )

        self._best_config = HarnessConfig.default()
        self._best_score = 0.0
        self._baseline_score = 0.0
        self._history: list[EvolutionEntry] = []
        self._last_eval_metadata: dict[str, Any] = {}  # for LLM proposer context

    async def run(self) -> None:
        """Run the full evolution loop."""
        self._results_dir.mkdir(parents=True, exist_ok=True)
        evo_path = self._results_dir / "evolution_summary.jsonl"

        # Phase 0: Evaluate baseline
        print("Phase 0: Evaluating baseline...")
        baseline_result = await self._evaluator.evaluate(_PROJECT_ROOT)
        if not baseline_result.success:
            print(f"Baseline evaluation failed: {baseline_result.error}")
            return

        self._baseline_score = baseline_result.metric_value
        self._best_score = baseline_result.metric_value
        self._last_eval_metadata = baseline_result.metadata or {}
        self._last_eval_metadata["composite"] = baseline_result.metric_value
        print(f"  Baseline score: {self._baseline_score:.4f}")

        # Save baseline
        baseline_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "composite_score": baseline_result.metric_value,
            "metrics": baseline_result.metrics,
            "config": self._best_config.to_dict(),
        }
        with open(self._results_dir / "baseline.json", "w") as f:
            json.dump(baseline_data, f, indent=2, default=str)

        # Evolution iterations
        for iteration in range(1, self._iterations + 1):
            print(f"\nIteration {iteration}/{self._iterations}")
            print(f"  Current best: {self._best_score:.4f}")

            # Generate candidates: list of (HarnessConfig, hypothesis) tuples
            raw_candidates = self._propose_candidates(iteration)
            print(f"  Generated {len(raw_candidates)} candidates")

            for i, (candidate, hypothesis) in enumerate(raw_candidates, 1):
                errors = candidate.validate()
                if errors:
                    print(f"  Candidate {i}: INVALID - {errors}")
                    continue

                if hypothesis:
                    print(f"  Candidate {i} hypothesis: {hypothesis[:80]}")

                # Evaluate
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    candidate.save_yaml(os.path.join(tmpdir, "harness_config.yaml"))
                    result = await self._evaluator.evaluate(tmpdir)

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
                    )
                    self._history.append(entry)
                    self._write_entry(evo_path, entry)
                    print(f"  Candidate {i}: ERROR - {result.error}")
                    continue

                score = result.metric_value
                delta = score - self._best_score

                if score > self._best_score:
                    status = "accepted"
                    self._best_score = score
                    self._best_config = candidate
                    self._last_eval_metadata = result.metadata or {}
                    self._last_eval_metadata["composite"] = score
                    candidate.save_yaml(str(self._results_dir / "best_config.yaml"))
                    print(f"  Candidate {i}: ACCEPTED score={score:.4f} delta={delta:+.4f}")
                else:
                    status = "rejected"
                    print(f"  Candidate {i}: REJECTED score={score:.4f} delta={delta:+.4f}")

                entry = EvolutionEntry(
                    iteration=iteration,
                    config=candidate.to_dict(),
                    score=score,
                    status=status,
                    baseline_score=self._baseline_score,
                    delta=delta,
                    hypothesis=hypothesis,
                    search_quality=result.metadata.get("search_quality"),
                    mcp_bench=result.metadata.get("mcp_bench"),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                self._history.append(entry)
                self._write_entry(evo_path, entry)

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Evolution complete: {self._iterations} iterations")
        print(f"  Baseline:  {self._baseline_score:.4f}")
        print(f"  Best:      {self._best_score:.4f}")
        print(f"  Delta:     {self._best_score - self._baseline_score:+.4f}")
        accepted = sum(1 for e in self._history if e.status == "accepted")
        print(f"  Accepted:  {accepted}/{len(self._history)} candidates")
        if self._best_score > self._baseline_score:
            print(f"\n  Best config saved to: {self._results_dir / 'best_config.yaml'}")

    def _propose_candidates(self, iteration: int) -> list[tuple[HarnessConfig, str]]:
        """Generate candidate configs for this iteration.

        Returns list of (HarnessConfig, hypothesis) tuples.
        """
        if self._propose_mode == "llm":
            return self._propose_llm(iteration)
        return self._propose_sweep(iteration)

    def _propose_sweep(self, iteration: int) -> list[tuple[HarnessConfig, str]]:
        """Random parameter perturbation."""
        import random
        random.seed(42 + iteration)

        base_dict = self._best_config.to_dict()
        candidates: list[tuple[HarnessConfig, str]] = []

        param_names = list(PARAMETER_RANGES.keys())

        for _ in range(self._candidates_per_iter):
            new_dict = dict(base_dict)
            n_params = random.randint(1, 3)
            chosen = random.sample(param_names, min(n_params, len(param_names)))
            changes: list[str] = []

            for param in chosen:
                lo, hi = PARAMETER_RANGES[param]
                current = new_dict.get(param, (lo + hi) / 2)

                if isinstance(lo, int) and isinstance(hi, int):
                    new_val = random.randint(int(lo), int(hi))
                else:
                    spread = (hi - lo) * 0.2
                    new_val = max(lo, min(hi, current + random.gauss(0, spread)))

                new_dict[param] = new_val
                changes.append(f"{param}: {current}->{new_val:.3f}" if isinstance(new_val, float) else f"{param}: {current}->{new_val}")

            hypothesis = f"sweep: {', '.join(changes)}"
            candidates.append((HarnessConfig.from_dict(new_dict), hypothesis))

        return candidates

    def _propose_llm(self, iteration: int) -> list[tuple[HarnessConfig, str]]:
        """Use Claude to propose configs based on failure analysis."""
        from eval.meta_harness.proposer import propose_configs_llm

        history_dicts = [asdict(e) for e in self._history]

        print(f"  Calling Claude for proposals...")
        try:
            candidates = propose_configs_llm(
                current_config=self._best_config,
                eval_result=self._last_eval_metadata,
                history=history_dicts,
                n_candidates=self._candidates_per_iter,
            )
            if not candidates:
                print(f"  LLM returned no valid candidates, falling back to sweep")
                return self._propose_sweep(iteration)
            return candidates
        except Exception as exc:
            print(f"  LLM proposal failed ({exc}), falling back to sweep")
            return self._propose_sweep(iteration)

    @staticmethod
    def _write_entry(path: Path, entry: EvolutionEntry) -> None:
        """Append an evolution entry to JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(asdict(entry), default=str) + "\n")
