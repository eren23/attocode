"""Research orchestrator — iterative experimentation with numeric metrics.

Core loop:
1. Evaluate baseline
2. Generate hypothesis
3. Run agent with hypothesis
4. Evaluate result
5. Accept/reject based on policy
6. Persist and repeat
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from attoswarm.research.accept_policy import NeverRegressPolicy
from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import CommandEvaluator, Evaluator
from attoswarm.research.experiment import Experiment, ResearchState
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.hypothesis import HypothesisGenerator
from attoswarm.research.scoreboard import Scoreboard

logger = logging.getLogger(__name__)


class ResearchOrchestrator:
    """Orchestrates iterative research experiments.

    Each experiment:
    1. Generate a hypothesis (LLM-assisted).
    2. Snapshot git state.
    3. Run an agent to implement the hypothesis.
    4. Evaluate the result (eval command).
    5. Accept/reject based on policy.
    6. Revert if rejected, keep if accepted.
    """

    def __init__(
        self,
        config: ResearchConfig,
        goal: str,
        *,
        evaluator: Evaluator | None = None,
        accept_policy: Any | None = None,
        spawn_fn: Any | None = None,
        event_bus: Any | None = None,
        code_intel: Any = None,
    ) -> None:
        self._config = config
        self._goal = goal
        self._working_dir = config.working_dir or "."
        self._run_dir = Path(config.run_dir)

        # Components
        self._evaluator = evaluator or CommandEvaluator(config.eval_command)
        self._accept_policy = accept_policy or NeverRegressPolicy()
        self._spawn_fn = spawn_fn
        self._event_bus = event_bus
        self._code_intel = code_intel
        self._hypothesis_gen = HypothesisGenerator(
            goal=goal,
            target_files=config.target_files,
            code_intel=code_intel,
        )

        # State
        self._run_id = str(uuid.uuid4())[:8]
        self._state = ResearchState(
            run_id=self._run_id,
            goal=goal,
            metric_name=config.metric_name,
            metric_direction=config.metric_direction,
        )
        self._experiments: list[Experiment] = []
        self._db: ExperimentDB | None = None

    async def run(self, *, resume_run_id: str = "") -> ResearchState:
        """Execute the research loop.

        Returns final ResearchState with results.
        """
        self._run_dir.mkdir(parents=True, exist_ok=True)

        # Initialize DB
        db_path = self._run_dir / "research.db"
        self._db = ExperimentDB(db_path)

        # Resume or start fresh
        if resume_run_id:
            checkpoint = self._db.load_checkpoint(resume_run_id)
            if checkpoint:
                self._state = checkpoint
                self._run_id = resume_run_id
                self._experiments = self._db.get_experiments(resume_run_id)
                logger.info("Resumed research run %s at experiment %d",
                            resume_run_id, self._state.total_experiments)
        else:
            self._db.create_run(self._run_id, self._goal)

        start_time = time.time()

        # 1. Evaluate baseline
        logger.info("Evaluating baseline...")
        self._emit("research_baseline", message="Evaluating baseline metric")
        baseline_result = await self._evaluate_with_retry()
        if not baseline_result.success:
            self._state.status = "error"
            self._state.wall_seconds = time.time() - start_time
            logger.error("Baseline evaluation failed: %s", baseline_result.error)
            return self._state

        self._state.baseline_value = baseline_result.metric_value
        self._state.best_value = baseline_result.metric_value
        logger.info("Baseline %s: %.4f", self._config.metric_name, baseline_result.metric_value)

        # 2. Main experiment loop
        metric_history: list[float] = [baseline_result.metric_value]

        for iteration in range(self._state.total_experiments, self._config.total_max_experiments):
            # Budget checks
            wall_elapsed = time.time() - start_time
            if wall_elapsed >= self._config.total_max_wall_seconds:
                self._state.status = "budget_exceeded"
                logger.info("Wall time budget exceeded")
                break
            if self._state.total_cost_usd >= self._config.total_max_cost_usd:
                self._state.status = "budget_exceeded"
                logger.info("Cost budget exceeded")
                break

            # Generate hypothesis
            prompt = self._hypothesis_gen.build_prompt(
                iteration=iteration,
                history=self._experiments,
                best_metric=self._state.best_value,
                metric_name=self._config.metric_name,
                metric_direction=self._config.metric_direction,
            )

            # For now, use the prompt as the hypothesis
            # In full implementation, this would call an LLM
            hypothesis = f"Experiment {iteration}: implement changes to improve {self._config.metric_name}"

            self._emit("experiment_start", message=f"Experiment {iteration}", data={"hypothesis": hypothesis})

            # Snapshot git state
            self._git_snapshot()

            # Run agent
            exp_start = time.time()
            agent_result = await self._run_agent(hypothesis)
            exp_duration = time.time() - exp_start

            # Get diff
            diff = self._git_diff()

            # Evaluate
            eval_result = await self._evaluate_with_retry()
            metric_value = eval_result.metric_value if eval_result.success else None

            # Accept/reject
            accepted = False
            reject_reason = ""
            if metric_value is not None and self._state.best_value is not None:
                accepted, reject_reason = self._accept_policy.should_accept(
                    self._state.best_value,
                    metric_value,
                    self._config.metric_direction,
                    metric_history,
                )
            elif metric_value is None:
                reject_reason = f"Evaluation failed: {eval_result.error}"

            # Build experiment record
            exp = Experiment(
                experiment_id=f"{self._run_id}-{iteration}",
                iteration=iteration,
                hypothesis=hypothesis,
                diff=diff,
                metric_value=metric_value,
                baseline_value=self._state.best_value,
                accepted=accepted,
                reject_reason=reject_reason,
                tokens_used=getattr(agent_result, "tokens_used", 0) if agent_result else 0,
                cost_usd=getattr(agent_result, "cost_usd", 0.0) if agent_result else 0.0,
                duration_s=exp_duration,
                files_modified=getattr(agent_result, "files_modified", []) if agent_result else [],
                error=getattr(agent_result, "error", "") if agent_result else "",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            self._experiments.append(exp)
            self._db.save_experiment(self._run_id, exp)

            # Update state
            self._state.total_experiments += 1
            self._state.total_cost_usd += exp.cost_usd
            self._state.total_tokens += exp.tokens_used

            if accepted:
                self._state.accepted_count += 1
                if metric_value is not None:
                    self._state.best_value = metric_value
                    self._state.best_experiment_id = exp.experiment_id
                    metric_history.append(metric_value)
                self._emit("experiment_accepted", message=f"Experiment {iteration} accepted: {metric_value}")
                logger.info("Experiment %d ACCEPTED: %.4f", iteration, metric_value or 0)
            else:
                self._state.rejected_count += 1
                # Revert changes
                self._git_revert()
                self._emit("experiment_rejected", message=f"Experiment {iteration} rejected: {reject_reason}")
                logger.info("Experiment %d REJECTED: %s", iteration, reject_reason)

            # Checkpoint
            self._state.wall_seconds = time.time() - start_time
            self._db.save_checkpoint(self._run_id, self._state)

        # Finalize
        if self._state.status == "running":
            self._state.status = "completed"
        self._state.wall_seconds = time.time() - start_time
        self._db.update_run_status(self._run_id, self._state.status)
        self._db.save_checkpoint(self._run_id, self._state)
        self._db.close()

        return self._state

    def get_scoreboard(self) -> Scoreboard:
        return Scoreboard(self._state, self._experiments)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _evaluate_with_retry(self, retries: int = 2) -> Any:
        """Run evaluation with retries for transient failures."""
        repeat = max(self._config.eval_repeat, 1)
        values: list[float] = []

        for attempt in range(retries + 1):
            try:
                for _ in range(repeat):
                    result = await self._evaluator.evaluate(self._working_dir)
                    if result.success:
                        values.append(result.metric_value)
                    else:
                        if attempt < retries:
                            await asyncio.sleep(1.0)
                            break
                        return result
                else:
                    # All repeats succeeded
                    if values:
                        from attoswarm.research.evaluator import EvalResult
                        avg = sum(values) / len(values)
                        return EvalResult(metric_value=avg, raw_output=f"avg of {len(values)} runs")
            except Exception as exc:
                if attempt >= retries:
                    from attoswarm.research.evaluator import EvalResult
                    return EvalResult(metric_value=0.0, error=str(exc), success=False)
                await asyncio.sleep(1.0)

        from attoswarm.research.evaluator import EvalResult
        return EvalResult(metric_value=0.0, error="All retries exhausted", success=False)

    async def _run_agent(self, hypothesis: str) -> Any:
        """Run the coding agent with the hypothesis."""
        if not self._spawn_fn:
            return None

        task = {
            "task_id": f"research-{self._state.total_experiments}",
            "title": f"Research experiment {self._state.total_experiments}",
            "description": hypothesis,
            "target_files": self._config.target_files,
        }

        try:
            result = await asyncio.wait_for(
                self._spawn_fn(task),
                timeout=self._config.experiment_timeout_seconds,
            )
            return result
        except TimeoutError:
            logger.warning("Agent timed out after %.0fs", self._config.experiment_timeout_seconds)
            return None
        except Exception as exc:
            logger.warning("Agent failed: %s", exc)
            return None

    def _git_snapshot(self) -> None:
        """Snapshot git state before an experiment."""
        if not self._config.use_git_stash:
            return
        try:
            subprocess.run(
                ["git", "stash", "push", "-m", f"research-{self._run_id}-{self._state.total_experiments}"],
                cwd=self._working_dir, capture_output=True, check=False,
            )
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=self._working_dir, capture_output=True, check=False,
            )
        except Exception:
            pass

    def _git_diff(self) -> str:
        """Get current git diff."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=self._working_dir, capture_output=True, text=True, check=False,
            )
            return result.stdout[:2000]
        except Exception:
            return ""

    def _git_revert(self) -> None:
        """Revert uncommitted changes after a rejected experiment."""
        try:
            # Revert tracked file changes
            subprocess.run(
                ["git", "checkout", "."],
                cwd=self._working_dir, capture_output=True, check=False,
            )
            # Remove untracked files created by the experiment
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=self._working_dir, capture_output=True, check=False,
            )
        except Exception:
            pass

    def _emit(self, event_type: str, message: str = "", data: dict[str, Any] | None = None) -> None:
        if self._event_bus:
            try:
                from attoswarm.coordinator.event_bus import SwarmEvent
                self._event_bus.emit(SwarmEvent(
                    event_type=event_type, message=message, data=data or {},
                ))
            except Exception:
                pass
