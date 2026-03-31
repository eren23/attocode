"""Research campaign orchestrator with isolated experiment worktrees."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from attoswarm.research.accept_policy import NeverRegressPolicy
from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import CommandEvaluator, EvalResult, Evaluator, constraints_pass
from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState, SteeringNote
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.hypothesis import HypothesisGenerator
from attoswarm.research.scoreboard import Scoreboard
from attoswarm.research.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CandidateSpec:
    experiment_id: str
    iteration: int
    strategy: str
    parent_experiment_id: str = ""
    related_experiment_ids: list[str] | None = None
    hypothesis: str = ""
    steering_notes: list[str] | None = None
    support_context: str = ""
    read_files: list[str] | None = None


class ResearchOrchestrator:
    """Orchestrates iterative experiment campaigns with isolated worktrees."""

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
        on_progress: Any | None = None,
        swarm_config: Any = None,
        experiment_mode: str = "auto",
    ) -> None:
        self._config = config
        self._goal = goal
        self._working_dir = str(Path(config.working_dir or ".").resolve())
        self._run_dir = Path(config.run_dir)

        self._evaluator = evaluator or CommandEvaluator(config.eval_command)
        self._accept_policy = accept_policy or NeverRegressPolicy()
        self._spawn_fn = spawn_fn
        self._event_bus = event_bus
        self._code_intel = code_intel
        self._on_progress = on_progress
        self._swarm_config = swarm_config
        self._experiment_mode = experiment_mode
        if experiment_mode == "auto":
            self._experiment_mode = "swarm" if (swarm_config and len(getattr(swarm_config, 'roles', [])) >= 2) else "simple"
        self._hypothesis_gen = HypothesisGenerator(
            goal=goal,
            target_files=config.target_files,
            code_intel=code_intel,
        )

        self._run_id = str(uuid.uuid4())[:8]
        self._state = ResearchState(
            run_id=self._run_id,
            goal=goal,
            metric_name=config.metric_name,
            metric_direction=config.metric_direction,
            started_at_epoch=time.time(),
        )
        self._experiments: list[Experiment] = []
        self._findings: list[FindingRecord] = []
        self._finding_experiment_ids: set[str] = set()
        self._db: ExperimentDB | None = None
        self._worktrees: WorktreeManager | None = None

    async def run(self, *, resume_run_id: str = "") -> ResearchState:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._db = ExperimentDB(self._run_dir / "research.db")
        self._worktrees = WorktreeManager(self._working_dir, self._run_dir)

        if resume_run_id:
            checkpoint = self._db.load_checkpoint(resume_run_id)
            if checkpoint:
                self._state = checkpoint
                self._run_id = resume_run_id
                self._experiments = self._db.get_experiments(resume_run_id)
                self._findings = self._db.list_findings(resume_run_id)
                self._finding_experiment_ids = {finding.experiment_id for finding in self._findings}
        else:
            self._db.create_run(self._run_id, self._goal, config=asdict(self._config))

        if self._state.started_at_epoch <= 0:
            self._state.started_at_epoch = time.time() - float(self._state.wall_seconds or 0.0)

        loop_start = time.time() - self._state.wall_seconds

        try:
            if self._state.baseline_value is None:
                # Pre-flight: verify eval command works in the working directory
                preflight = await self._evaluator.evaluate(self._working_dir)
                if not preflight.success:
                    self._state.status = "error"
                    self._state.error = f"Eval command pre-flight failed: {preflight.error}"
                    self._emit("research_error", message=self._state.error)
                    return self._state

                self._emit("research_baseline", message="Evaluating baseline metric")
                baseline = await self._evaluate_with_retry(repeats=max(self._config.baseline_repeats, 1))
                if not baseline.success:
                    self._state.status = "error"
                    self._state.error = baseline.error or f"Baseline eval failed (output: {baseline.raw_output[:500]})"
                    self._state.wall_seconds = time.time() - loop_start
                    return self._state
                self._state.baseline_value = baseline.metric_value
                self._state.best_value = baseline.metric_value
                self._state.best_branch = self._worktrees.get_head_commit()
                self._write_event("baseline_complete", f"Baseline: {baseline.metric_value}")
                self._notify_progress()

            while self._should_continue(loop_start):
                batch = self._plan_batch()
                if not batch:
                    break

                self._state.active_experiments = len(batch)
                results = await asyncio.gather(*(self._execute_candidate(spec) for spec in batch))
                self._state.active_experiments = 0

                for exp in results:
                    self._experiments.append(exp)
                    self._write_event(
                        f"experiment_{exp.status}",
                        f"{exp.experiment_id} ({exp.strategy}): metric={exp.metric_value}",
                        experiment_id=exp.experiment_id,
                        strategy=exp.strategy,
                        metric=exp.metric_value,
                        status=exp.status,
                    )
                    touched = self._reconcile_candidate(exp)
                    for item in touched:
                        self._db.save_experiment(self._run_id, item)
                    self._record_findings(touched)

                self._refresh_state()
                self._state.wall_seconds = time.time() - loop_start
                self._db.save_checkpoint(self._run_id, self._state)
                self._notify_progress()

            if self._state.status == "running":
                self._state.status = "completed"
                self._write_event("campaign_complete", f"Completed: {self._state.accepted_count} accepted, {self._state.rejected_count} rejected")
            self._state.wall_seconds = time.time() - loop_start
            self._db.update_run_status(self._run_id, self._state.status)
            self._db.save_checkpoint(self._run_id, self._state)
            return self._state
        finally:
            self._db.close()

    def _notify_progress(self) -> None:
        self._write_state_file()
        if self._on_progress:
            try:
                self._on_progress(self._state, self._experiments)
            except Exception:
                pass  # never let progress callback crash the campaign

    def _build_learning_summary(self) -> str:
        """Build a learning context from prior experiments for the next agent."""
        if not self._experiments:
            return ""
        lines: list[str] = []
        accepted = [e for e in self._experiments if e.status == "accepted"]
        rejected = [e for e in self._experiments if e.status == "rejected"]
        errors = [e for e in self._experiments if e.status in ("error", "invalid")]

        if accepted:
            lines.append("## What worked (accepted experiments):")
            for e in accepted[-5:]:
                lines.append(f"- Hypothesis: {e.hypothesis[:120]} → metric={e.metric_value}")
                if e.files_modified:
                    lines.append(f"  Modified: {', '.join(e.files_modified[:5])}")
                if e.diff:
                    lines.append(f"  Diff preview: {e.diff[:300]}")

        if rejected:
            lines.append("\n## What failed (rejected experiments — DO NOT repeat these):")
            for e in rejected[-5:]:
                lines.append(f"- Hypothesis: {e.hypothesis[:120]} → metric={e.metric_value} (reason: {e.reject_reason[:80]})")
                if e.files_modified:
                    lines.append(f"  Modified: {', '.join(e.files_modified[:5])}")

        if errors:
            lines.append("\n## Errors to avoid:")
            for e in errors[-3:]:
                lines.append(f"- {e.error[:200]}")

        if self._state.baseline_value is not None:
            lines.append(f"\nBaseline metric: {self._state.baseline_value}")
        if self._state.best_value is not None and self._state.best_value != self._state.baseline_value:
            lines.append(f"Current best: {self._state.best_value}")

        return "\n".join(lines)

    def _write_state_file(self) -> None:
        """Write a JSON state snapshot for external monitors (TUI, watch)."""
        try:
            state_path = self._run_dir / "research.state.json"
            data = {
                "state": asdict(self._state),
                "experiments": [exp.to_dict() for exp in self._experiments[-30:]],
                "findings": [asdict(f) for f in self._findings[-10:]],
            }
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
            tmp.rename(state_path)
        except Exception:
            pass  # never let state file writes crash the campaign

    def _write_event(self, event_type: str, message: str = "", **data: Any) -> None:
        """Append an event to research.events.jsonl for TUI/external monitors."""
        try:
            event_path = self._run_dir / "research.events.jsonl"
            entry = {"ts": time.time(), "type": event_type, "message": message, **data}
            with event_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    def _derive_experiment_config(self, worktree_path: Path, experiment_id: str) -> Any:
        """Create a micro-SwarmYamlConfig scoped to one experiment's worktree."""
        import copy
        cfg = copy.deepcopy(self._swarm_config)
        cfg.run.working_dir = str(worktree_path)
        cfg.run.run_dir = str(self._run_dir / experiment_id / "swarm")
        cfg.run.max_runtime_seconds = int(self._config.experiment_timeout_seconds)
        cfg.run.name = f"research-{experiment_id}"
        cfg.budget.max_tokens = self._config.experiment_max_tokens
        cfg.budget.max_cost_usd = self._config.experiment_max_cost_usd
        cfg.watchdog.task_max_duration_seconds = self._config.experiment_timeout_seconds * 0.8
        cfg.orchestration.max_tasks = 5
        cfg.workspace.mode = "shared"
        return cfg

    def get_scoreboard(self) -> Scoreboard:
        return Scoreboard(self._state, self._experiments, findings=self._findings)

    async def inject_steering_note(self, content: str, *, scope: str = "global", target: str = "") -> SteeringNote:
        if self._db is None:
            self._db = ExperimentDB(self._run_dir / "research.db")
        note = SteeringNote(
            note_id=f"note-{uuid.uuid4().hex[:8]}",
            run_id=self._run_id,
            content=content.strip(),
            scope=scope,
            target=target,
            active=True,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._db.add_steering_note(note)
        return note

    def _should_continue(self, loop_start: float) -> bool:
        elapsed = time.time() - loop_start
        if elapsed >= self._config.total_max_wall_seconds:
            self._state.status = "budget_exceeded"
            return False
        if self._state.total_cost_usd >= self._config.total_max_cost_usd:
            self._state.status = "budget_exceeded"
            return False
        return self._state.total_experiments < self._config.total_max_experiments

    def _plan_batch(self) -> list[CandidateSpec]:
        max_batch = max(1, self._config.max_parallel_experiments)
        remaining = self._config.total_max_experiments - self._state.total_experiments
        budget = min(max_batch, remaining)
        if budget <= 0:
            return []

        notes = self._active_steering_texts()
        best = self._best_experiment()
        pending = self._promotion_target()
        strategies = self._strategy_sequence()
        specs: list[CandidateSpec] = []

        if pending is not None:
            validation_count = self._validation_count(pending.experiment_id)
            while validation_count < max(self._config.promotion_repeats, 1) and len(specs) < budget:
                specs.append(self._make_candidate(
                    "reproduce",
                    pending,
                    notes,
                    iteration=self._state.total_experiments + len(specs) + 1,
                ))
                validation_count += 1

        while len(specs) < budget:
            strategy = strategies[len(specs) % len(strategies)]
            parent = best if strategy in {"exploit", "ablate", "compose", "reproduce"} else None
            related: list[Experiment] = []
            if strategy == "compose":
                partner = self._compose_partner(best)
                if partner is None:
                    strategy = "exploit" if best is not None else "explore"
                    parent = best if strategy == "exploit" else None
                else:
                    related.append(partner)
            elif strategy == "ablate" and best is None:
                strategy = "explore"
                parent = None
            specs.append(self._make_candidate(
                strategy,
                parent,
                notes,
                iteration=self._state.total_experiments + len(specs) + 1,
                related=related,
            ))

        return specs

    def _make_candidate(
        self,
        strategy: str,
        parent: Experiment | None,
        steering_notes: list[str],
        *,
        iteration: int,
        related: list[Experiment] | None = None,
    ) -> CandidateSpec:
        experiment_id = f"{self._run_id}-e{iteration:03d}-{uuid.uuid4().hex[:4]}"
        related = related or []
        hypothesis = self._hypothesis_gen.generate_candidate(
            iteration=iteration,
            strategy=strategy,
            history=self._experiments,
            best_metric=self._state.best_value,
            metric_name=self._config.metric_name,
            metric_direction=self._config.metric_direction,
            steering_notes=steering_notes,
        )
        read_files = self._candidate_read_files(parent, related)
        return CandidateSpec(
            experiment_id=experiment_id,
            iteration=iteration,
            strategy=strategy,
            parent_experiment_id=parent.experiment_id if parent else "",
            related_experiment_ids=[exp.experiment_id for exp in related],
            hypothesis=hypothesis,
            steering_notes=steering_notes,
            support_context=self._build_candidate_context(strategy, parent, related),
            read_files=read_files,
        )

    def _strategy_sequence(self) -> list[str]:
        mix = self._config.strategy_mix or {}
        ordered: list[str] = []
        for name in ("explore", "exploit", "ablate", "compose", "reproduce"):
            count = int(mix.get(name, 0))
            ordered.extend([name] * max(count, 0))
        return ordered or ["explore"]

    async def _execute_candidate(self, spec: CandidateSpec) -> Experiment:
        assert self._worktrees is not None
        start_ref = self._resolve_start_ref(spec.parent_experiment_id)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        started = time.time()
        eval_result: EvalResult | None = None
        agent_result: Any = None
        preparation_notes: list[str] = []
        worktree_path: str | None = None
        branch: str = ""
        try:
            worktree_path, branch = self._worktrees.create_worktree(spec.experiment_id, start_ref)
            exp = Experiment(
                experiment_id=spec.experiment_id,
                iteration=spec.iteration,
                hypothesis=spec.hypothesis,
                parent_experiment_id=spec.parent_experiment_id,
                related_experiment_ids=list(spec.related_experiment_ids or []),
                strategy=spec.strategy,
                status="running",
                branch=branch,
                worktree_path=str(worktree_path),
                baseline_value=self._state.best_value,
                steering_notes=list(spec.steering_notes or []),
                timestamp=timestamp,
            )
            self._emit("experiment_start", message=f"{exp.experiment_id} ({exp.strategy})", data=exp.to_dict())
            preparation_notes = self._prepare_candidate_workspace(spec, worktree_path)
            if spec.strategy != "reproduce":
                agent_result = await self._run_agent(spec, worktree_path)
                if agent_result is None and self._spawn_fn is None:
                    exp.status = "error"
                    exp.error = "No spawn function configured for non-reproduce experiment"
                    return self._finalize_candidate(exp)

            exp.files_modified = self._worktrees.list_changed_files(worktree_path)
            exp.commit_hash = self._worktrees.commit_all(
                worktree_path,
                f"[research] {spec.experiment_id}: {spec.hypothesis[:60]}",
            )
            exp.diff = self._worktrees.capture_commit_diff(worktree_path)

            eval_result = await self._evaluate_with_retry(
                working_dir=str(worktree_path),
                repeats=max(self._config.eval_repeat, 1),
            )
        except Exception as exc:
            if "exp" not in locals():
                # create_worktree or Experiment() itself failed — clean up worktree if created
                if worktree_path:
                    self._worktrees.remove_worktree(worktree_path, branch=branch)
                raise
            exp.status = "error"
            exp.error = str(exc)
            eval_result = None
        finally:
            if "exp" in locals():
                exp.duration_s = time.time() - started
                exp.tokens_used = int(getattr(agent_result, "tokens_used", 0) or 0)
                exp.cost_usd = float(getattr(agent_result, "cost_usd", 0.0) or 0.0)
                agent_summary = getattr(agent_result, "result_summary", "") or ""
                prep_summary = "\n".join(preparation_notes).strip()
                if prep_summary and agent_summary:
                    exp.raw_output = f"{prep_summary}\n\n{agent_summary}"
                else:
                    exp.raw_output = prep_summary or agent_summary

        if eval_result is None:
            exp.status = "error"
            if not exp.error:
                exp.error = "Experiment failed before evaluation"
            return self._finalize_candidate(exp)

        exp.metric_value = eval_result.metric_value
        exp.metrics = {
            "primary_metric": eval_result.metric_value,
            "secondary_metrics": eval_result.metrics,
            "metadata": eval_result.metadata,
            "constraint_checks": eval_result.constraint_checks,
        }
        exp.artifacts = list(eval_result.artifacts)

        # Guard against catastrophic regression (>50% drop from baseline)
        if (self._state.baseline_value is not None
                and eval_result.metric_value is not None
                and self._state.baseline_value > 0
                and eval_result.metric_value < self._state.baseline_value * 0.5):
            exp.status = "invalid"
            exp.reject_reason = f"catastrophic regression ({eval_result.metric_value:.1f} vs baseline {self._state.baseline_value:.1f})"
        elif not eval_result.success:
            exp.status = "invalid"
            exp.reject_reason = eval_result.error or "evaluation failed"
            exp.error = exp.reject_reason
        elif not constraints_pass(eval_result.constraint_checks):
            exp.status = "invalid"
            exp.reject_reason = "constraint checks failed"
        else:
            accepted, reason = self._accept_policy.should_accept(
                self._current_accept_baseline(eval_result.metric_value),
                eval_result.metric_value,
                self._config.metric_direction,
                self._metric_history(),
            )
            if accepted:
                exp.accepted = True
                exp.reject_reason = ""
                if self._config.promotion_repeats > 1:
                    exp.status = "validated" if spec.strategy == "reproduce" else "candidate"
                else:
                    exp.accepted = True
                    exp.status = "accepted"
            else:
                exp.accepted = False
                exp.reject_reason = reason
                exp.status = "rejected"

        return self._finalize_candidate(exp)

    def _finalize_candidate(self, exp: Experiment) -> Experiment:
        assert self._worktrees is not None
        if exp.status not in {"accepted", "running"} and not self._config.preserve_worktrees:
            self._worktrees.remove_worktree(exp.worktree_path, branch=exp.branch)
            exp.worktree_path = ""
        return exp

    async def _evaluate_with_retry(
        self,
        *,
        working_dir: str | None = None,
        repeats: int = 1,
        retries: int = 2,
    ) -> EvalResult:
        values: list[float] = []
        metrics: dict[str, Any] = {}
        artifacts: list[str] = []
        constraints: dict[str, Any] = {}
        target_dir = working_dir or self._working_dir

        for attempt in range(retries + 1):
            try:
                for _ in range(max(repeats, 1)):
                    result = await self._evaluator.evaluate(target_dir)
                    if not result.success:
                        if attempt < retries:
                            await asyncio.sleep(1.0)
                            break
                        return result
                    values.append(result.metric_value)
                    metrics = result.metrics or metrics
                    artifacts = result.artifacts or artifacts
                    constraints = result.constraint_checks or constraints
                else:
                    return EvalResult(
                        metric_value=sum(values) / len(values),
                        raw_output="avg of repeats",
                        metadata={"repeats": len(values)},
                        metrics=metrics,
                        artifacts=artifacts,
                        constraint_checks=constraints,
                    )
            except Exception as exc:
                if attempt >= retries:
                    return EvalResult(metric_value=0.0, error=str(exc), success=False)
                await asyncio.sleep(1.0)

        return EvalResult(metric_value=0.0, error="All retries exhausted", success=False)

    def _build_rich_task_dict(self, spec: CandidateSpec, worktree_path: str | Path) -> dict:
        """Build an enriched task dict for the agent, matching swarm-level context."""
        import ast as _ast

        hypothesis = spec.hypothesis
        support_context = spec.support_context or ""

        # Build description with concrete instructions
        description_parts = [
            hypothesis,
            "\nIMPORTANT: Make code changes directly. Do NOT ask questions. Read files, modify them, verify.",
        ]
        if support_context:
            description_parts.append(support_context)
        description_parts.append(
            f"\n## Verification\n"
            f"Run this command to check your work:\n```\n{self._config.eval_command}\n```\n"
            f"Current baseline: **{self._state.baseline_value}**\n"
            f"Direction: {self._config.metric_direction}\n"
            f"Your changes must IMPROVE this metric. If the metric drops, revert and try differently."
        )

        # Discover symbols from target files (lightweight AST parsing)
        symbol_scope: list[str] = []
        for tf in self._config.target_files[:3]:
            tf_path = Path(self._working_dir) / tf
            if tf_path.exists() and tf_path.suffix == ".py":
                try:
                    tree = _ast.parse(tf_path.read_text(encoding="utf-8"))
                    for node in _ast.walk(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            symbol_scope.append(f"{tf}:{node.name}()")
                        elif isinstance(node, _ast.ClassDef):
                            symbol_scope.append(f"{tf}:{node.name}")
                except Exception:
                    pass

        # Discover test files
        test_files: list[str] = []
        for tf in self._config.target_files:
            name = Path(tf).stem
            candidates = [
                f"tests/unit/**/test_{name}.py",
                f"tests/**/test_{name}.py",
                f"test_{name}.py",
            ]
            base = Path(self._working_dir)
            for pattern in candidates:
                for match in base.glob(pattern):
                    rel = str(match.relative_to(base))
                    if rel not in test_files:
                        test_files.append(rel)

        # Read files from parent experiment
        read_files = list(spec.read_files or [])

        # Learning context
        learning_context = self._build_learning_summary()

        task = {
            "task_id": f"research-{spec.experiment_id}",
            "title": hypothesis[:80],
            "description": "\n\n".join(description_parts),
            "target_files": list(self._config.target_files),
            "read_files": read_files,
            "working_dir": str(worktree_path),
            "symbol_scope": symbol_scope[:15],
            "test_files": test_files[:10],
            "test_command": self._config.eval_command,
            "learning_context": learning_context,
        }
        return task

    def _build_mini_swarm_goal(self, spec: CandidateSpec, worktree_path: Path) -> str:
        """Build a concrete, actionable goal for the mini-swarm coordinator."""
        import ast as _ast

        sections: list[str] = []

        # 1. Clear objective — not the abstract hypothesis, but a concrete coding task
        sections.append(f"# Objective\n\n{spec.hypothesis}")
        sections.append(
            "IMPORTANT: You are an autonomous coding agent. Make code changes directly. "
            "Do NOT ask clarifying questions. Do NOT explain what you would do — just do it. "
            "Read the target files, understand them, make improvements, and verify your changes work."
        )

        # 2. Support context from strategy (compose diffs, ablate context, etc.)
        if spec.support_context:
            sections.append(f"## Additional Context\n\n{spec.support_context}")

        # 3. Target files with actual content summaries
        if self._config.target_files:
            file_section = ["## Target Files\n\nThese are the files you should modify:\n"]
            for tf in self._config.target_files[:5]:
                tf_path = Path(str(worktree_path)) / tf
                if tf_path.exists():
                    try:
                        content = tf_path.read_text(encoding="utf-8")
                        lines = content.splitlines()
                        # Include structure: classes, functions, first 50 lines
                        symbols: list[str] = []
                        if tf.endswith(".py"):
                            try:
                                tree = _ast.parse(content)
                                for node in _ast.walk(tree):
                                    if isinstance(node, _ast.ClassDef):
                                        symbols.append(f"  class {node.name} (line {node.lineno})")
                                    elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                                        symbols.append(f"  def {node.name}() (line {node.lineno})")
                            except Exception:
                                pass
                        file_section.append(f"### `{tf}` ({len(lines)} lines)")
                        if symbols:
                            file_section.append("Structure:")
                            file_section.extend(symbols[:20])
                        # Include first 80 lines as preview
                        preview = "\n".join(lines[:80])
                        file_section.append(f"\n```\n{preview}\n```\n")
                    except Exception:
                        file_section.append(f"### `{tf}` (could not read)")
                else:
                    file_section.append(f"### `{tf}` (file not found in worktree)")
            sections.append("\n".join(file_section))

        # 4. Learning from prior experiments
        learning = self._build_learning_summary()
        if learning:
            sections.append(f"## Prior Experiment Results\n\n{learning}")

        # 5. Verification — how to check your work
        sections.append(
            f"## Verification\n\n"
            f"After making changes, verify by running:\n"
            f"```\n{self._config.eval_command}\n```\n\n"
            f"Current baseline metric: **{self._state.baseline_value}**\n"
            f"Direction: **{self._config.metric_direction}** (higher is {'better' if self._config.metric_direction == 'maximize' else 'worse'})\n\n"
            f"Your changes MUST improve this metric. If the eval command fails or the metric drops, "
            f"revert your changes and try a different approach."
        )

        return "\n\n".join(sections)

    async def _run_mini_swarm(self, spec: CandidateSpec, worktree_path: Path) -> Any:
        """Run a full swarm pipeline (decompose -> implement -> review -> merge) in the experiment worktree."""
        from types import SimpleNamespace

        micro_cfg = self._derive_experiment_config(worktree_path, spec.experiment_id)
        goal = self._build_mini_swarm_goal(spec, worktree_path)

        self._write_event("mini_swarm_start", f"Starting mini-swarm for {spec.experiment_id}", experiment_id=spec.experiment_id)

        from attoswarm.coordinator.loop import HybridCoordinator

        coordinator = HybridCoordinator(micro_cfg, goal)
        try:
            exit_code = await coordinator.run()
            tokens = getattr(coordinator.budget, 'total_tokens', 0)
            cost = getattr(coordinator.budget, 'total_cost', 0.0)
            self._write_event("mini_swarm_complete", f"Mini-swarm exit={exit_code} tokens={tokens}", experiment_id=spec.experiment_id)
            return SimpleNamespace(
                result_summary=f"Mini-swarm completed (exit={exit_code})",
                tokens_used=tokens,
                cost_usd=cost,
            )
        except Exception as exc:
            logger.warning("Mini-swarm failed for %s: %s", spec.experiment_id, exc)
            self._write_event("mini_swarm_error", f"Mini-swarm failed: {exc}", experiment_id=spec.experiment_id)
            tokens = getattr(coordinator.budget, 'total_tokens', 0) if hasattr(coordinator, 'budget') else 0
            cost = getattr(coordinator.budget, 'total_cost', 0.0) if hasattr(coordinator, 'budget') else 0.0
            return SimpleNamespace(
                result_summary=f"Mini-swarm failed: {exc}",
                tokens_used=tokens,
                cost_usd=cost,
            )

    async def _run_agent(self, spec: CandidateSpec, worktree_path: Path) -> Any:
        if self._experiment_mode == "swarm" and self._swarm_config:
            return await asyncio.wait_for(
                self._run_mini_swarm(spec, worktree_path),
                timeout=self._config.experiment_timeout_seconds,
            )
        if not self._spawn_fn:
            return None
        task = self._build_rich_task_dict(spec, worktree_path)
        return await asyncio.wait_for(
            self._spawn_fn(task),
            timeout=self._config.experiment_timeout_seconds,
        )

    def _prepare_candidate_workspace(self, spec: CandidateSpec, worktree_path: Path) -> list[str]:
        if spec.strategy != "compose" or not spec.related_experiment_ids:
            return []
        assert self._worktrees is not None

        notes: list[str] = []
        for experiment_id in spec.related_experiment_ids:
            related = next((exp for exp in self._experiments if exp.experiment_id == experiment_id), None)
            if related is None:
                notes.append(f"compose import skipped: missing experiment {experiment_id}")
                continue
            if not related.diff:
                notes.append(f"compose import skipped: {experiment_id} has no diff recorded")
                continue

            applied, detail = self._worktrees.apply_diff(worktree_path, related.diff)
            if applied:
                notes.append(f"compose import applied: {experiment_id} ({detail})")
            else:
                notes.append(f"compose import failed: {experiment_id} ({detail})")

        if notes:
            preparation = "\n".join(f"- {note}" for note in notes)
            if spec.support_context:
                spec.support_context = f"{spec.support_context}\n\n## Workspace Preparation\n{preparation}"
            else:
                spec.support_context = f"## Workspace Preparation\n{preparation}"
        return notes

    def _resolve_start_ref(self, parent_experiment_id: str) -> str:
        assert self._worktrees is not None
        if parent_experiment_id:
            parent = next((exp for exp in self._experiments if exp.experiment_id == parent_experiment_id), None)
            if parent and parent.commit_hash:
                return parent.commit_hash
        if self._state.best_experiment_id:
            best = self._best_experiment()
            if best and best.commit_hash:
                return best.commit_hash
        return self._worktrees.get_head_commit()

    def _best_experiment(self) -> Experiment | None:
        if not self._state.best_experiment_id:
            return None
        for exp in self._experiments:
            if exp.experiment_id == self._state.best_experiment_id:
                return exp
        return None

    def _promotion_target(self) -> Experiment | None:
        candidates = [
            exp for exp in self._experiments
            if exp.status == "candidate" and exp.metric_value is not None
        ]
        if not candidates:
            return None
        return self._rank_experiments(candidates)[0]

    def _validation_count(self, root_experiment_id: str) -> int:
        count = 0
        for exp in self._experiments:
            if exp.experiment_id == root_experiment_id and exp.status in {"candidate", "accepted"}:
                count += 1
            elif exp.parent_experiment_id == root_experiment_id and exp.status in {"validated", "accepted"}:
                count += 1
        return count

    def _compose_partner(self, best: Experiment | None) -> Experiment | None:
        accepted = [
            exp for exp in self._experiments
            if exp.accepted and exp.metric_value is not None and exp.experiment_id != (best.experiment_id if best else "")
        ]
        if not accepted:
            return None
        accepted.sort(key=lambda exp: self._compose_rank(exp, best))
        return accepted[0]

    def _compose_rank(self, exp: Experiment, best: Experiment | None) -> tuple[int, float, int]:
        overlap = 0
        if best is not None and best.files_modified and exp.files_modified:
            overlap = len(set(best.files_modified) & set(exp.files_modified))
        quality = exp.metric_value if exp.metric_value is not None else float("-inf")
        if self._config.metric_direction == "minimize":
            quality = -quality
        return (overlap, -quality, exp.iteration)

    def _rank_experiments(self, experiments: list[Experiment]) -> list[Experiment]:
        if self._config.metric_direction == "minimize":
            return sorted(
                experiments,
                key=lambda exp: (
                    exp.metric_value is None,
                    exp.metric_value if exp.metric_value is not None else float("inf"),
                    exp.iteration,
                ),
            )
        return sorted(
            experiments,
            key=lambda exp: (
                exp.metric_value is None,
                -(exp.metric_value if exp.metric_value is not None else float("-inf")),
                exp.iteration,
            ),
        )

    def _candidate_read_files(self, parent: Experiment | None, related: list[Experiment]) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for exp in ([parent] if parent is not None else []) + related:
            for path in exp.files_modified[:8]:
                if path and path not in seen:
                    seen.add(path)
                    files.append(path)
        return files[:12]

    def _build_candidate_context(
        self,
        strategy: str,
        parent: Experiment | None,
        related: list[Experiment],
    ) -> str:
        sections: list[str] = []
        if parent is not None:
            sections.append("## Baseline Branch")
            sections.extend(self._experiment_context_lines(parent, label="Current best"))
            if strategy == "ablate":
                sections.append(
                    "Instruction: remove or simplify one mechanism from the current best branch and verify whether the gain survives."
                )
        if related:
            sections.append("## Reference Experiments")
            for exp in related:
                sections.extend(self._experiment_context_lines(exp, label="Reference"))
            if strategy == "compose":
                sections.append(
                    "Instruction: preserve the current best branch, then port one orthogonal mechanism from the reference experiment into this branch."
                )
        return "\n".join(sections).strip()

    def _experiment_context_lines(self, exp: Experiment, *, label: str) -> list[str]:
        lines = [
            f"- {label}: {exp.experiment_id} [{exp.status}] strategy={exp.strategy} metric={exp.metric_value}",
            f"  hypothesis: {exp.hypothesis[:240]}",
        ]
        if exp.files_modified:
            lines.append(f"  files: {', '.join(exp.files_modified[:8])}")
        if exp.diff:
            diff_lines = [line for line in exp.diff.splitlines() if line.startswith(('+', '-'))][:12]
            if diff_lines:
                lines.append("  patch summary:")
                lines.extend(f"    {line[:160]}" for line in diff_lines)
        return lines

    def _metric_history(self) -> list[float]:
        values: list[float] = []
        if self._state.baseline_value is not None:
            values.append(self._state.baseline_value)
        for exp in self._experiments:
            if exp.accepted and exp.metric_value is not None:
                values.append(exp.metric_value)
        return values or [0.0]

    def _current_accept_baseline(self, fallback: float) -> float:
        if self._state.best_value is not None:
            return self._state.best_value
        if self._state.baseline_value is not None:
            return self._state.baseline_value
        return fallback

    def _refresh_state(self) -> None:
        self._state.total_experiments = len(self._experiments)
        self._state.total_cost_usd = sum(exp.cost_usd for exp in self._experiments)
        self._state.total_tokens = sum(exp.tokens_used for exp in self._experiments)
        self._state.accepted_count = sum(1 for exp in self._experiments if exp.status == "accepted")
        self._state.candidate_count = sum(1 for exp in self._experiments if exp.status in {"candidate", "validated"})
        self._state.held_count = sum(1 for exp in self._experiments if exp.status == "held")
        self._state.killed_count = sum(1 for exp in self._experiments if exp.status == "killed")
        self._state.rejected_count = sum(1 for exp in self._experiments if exp.status == "rejected")
        self._state.invalid_count = sum(1 for exp in self._experiments if exp.status in {"invalid", "error"})

        accepted = [
            exp for exp in self._experiments
            if exp.status == "accepted" and exp.metric_value is not None
        ]
        if accepted:
            best = self._rank_experiments(accepted)[0]
            self._state.best_value = best.metric_value
            self._state.best_experiment_id = best.experiment_id
            self._state.best_branch = best.branch
        else:
            # Fall back to candidates awaiting validation so exploit/ablate/compose
            # strategies still target the right starting ref (branch/experiment_id),
            # but keep best_value at baseline so the accept policy isn't inflated.
            candidates = [
                exp for exp in self._experiments
                if exp.status == "candidate" and exp.metric_value is not None
            ]
            if candidates:
                best_candidate = self._rank_experiments(candidates)[0]
                self._state.best_experiment_id = best_candidate.experiment_id
                self._state.best_branch = best_candidate.branch
            else:
                self._state.best_experiment_id = ""
                self._state.best_branch = self._worktrees.get_head_commit() if self._worktrees is not None else ""
            self._state.best_value = self._state.baseline_value

    def _reconcile_candidate(self, exp: Experiment) -> list[Experiment]:
        touched = [exp]
        if self._config.promotion_repeats <= 1:
            return touched
        if exp.status not in {"candidate", "validated"}:
            return touched

        root_id = exp.parent_experiment_id if exp.status == "validated" and exp.parent_experiment_id else exp.experiment_id
        root = next((item for item in self._experiments if item.experiment_id == root_id), None)
        if root is None:
            return touched
        if self._validation_count(root_id) < max(self._config.promotion_repeats, 1):
            root.reject_reason = f"awaiting validation ({self._validation_count(root_id)}/{self._config.promotion_repeats})"
            if root not in touched:
                touched.append(root)
            return touched

        root.status = "accepted"
        root.accepted = True
        root.reject_reason = ""
        if root not in touched:
            touched.append(root)
        return touched

    def _record_findings(self, experiments: list[Experiment]) -> None:
        for exp in experiments:
            if exp.experiment_id in self._finding_experiment_ids:
                continue
            finding = self._build_finding(exp)
            if finding is None:
                continue
            self._findings.append(finding)
            self._finding_experiment_ids.add(exp.experiment_id)
            assert self._db is not None
            self._db.add_finding(self._run_id, finding)

    def _active_steering_texts(self) -> list[str]:
        if not self._config.steering_enabled or self._db is None:
            return []
        notes = self._db.list_active_steering_notes(self._run_id)
        return [note.content for note in notes if note.active]

    def _build_finding(self, exp: Experiment) -> FindingRecord | None:
        if exp.status == "accepted" and exp.metric_value is not None:
            baseline = exp.baseline_value if exp.baseline_value is not None else self._state.baseline_value
            claim = (
                f"{exp.strategy} improved {self._config.metric_name}"
                f" from {baseline:.4f} to {exp.metric_value:.4f}"
                if baseline is not None
                else f"{exp.strategy} improved {self._config.metric_name} to {exp.metric_value:.4f}"
            )
            return FindingRecord(
                finding_id=f"finding-{uuid.uuid4().hex[:8]}",
                experiment_id=exp.experiment_id,
                claim=claim,
                evidence=exp.hypothesis[:500],
                confidence=0.75,
                scope="experiment",
                composeability=(
                    "likely" if exp.strategy in {"explore", "exploit", "compose"}
                    else "test" if exp.strategy == "ablate"
                    else "verify"
                ),
                status="validated",
                created_at=exp.timestamp,
            )
        if exp.status in {"invalid", "error"}:
            return FindingRecord(
                finding_id=f"finding-{uuid.uuid4().hex[:8]}",
                experiment_id=exp.experiment_id,
                claim=f"{exp.strategy} produced an invalid result",
                evidence=exp.reject_reason or exp.error,
                confidence=0.6,
                scope="experiment",
                composeability="avoid",
                status="proposed",
                created_at=exp.timestamp,
            )
        return None

    def _emit(self, event_type: str, message: str = "", data: dict[str, Any] | None = None) -> None:
        if self._event_bus:
            try:
                from attoswarm.coordinator.event_bus import SwarmEvent

                self._event_bus.emit(SwarmEvent(
                    event_type=event_type,
                    message=message,
                    data=data or {},
                ))
            except Exception:
                pass
