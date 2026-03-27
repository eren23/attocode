"""Hypothesis generation for research experiments."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from attoswarm.research.experiment import Experiment

logger = logging.getLogger(__name__)


class HypothesisGenerator:
    """Generates hypotheses for research experiments using LLM.

    Builds a prompt from the goal, experiment history, current best metric,
    and optionally code-intel context for target files.
    """

    def __init__(
        self,
        goal: str,
        target_files: list[str] | None = None,
        code_intel: Any = None,
    ) -> None:
        self._goal = goal
        self._target_files = target_files or []
        self._code_intel = code_intel

    def build_prompt(
        self,
        iteration: int,
        history: list[Experiment],
        best_metric: float | None,
        metric_name: str = "score",
        metric_direction: str = "maximize",
    ) -> str:
        """Build the hypothesis generation prompt.

        Returns a prompt string suitable for an LLM call.
        """
        parts = [
            "You are a research experiment designer. Your goal is to improve a metric "
            "by proposing targeted code changes.\n",
            f"## Goal\n{self._goal}\n",
            f"## Metric\n- Name: {metric_name}\n- Direction: {metric_direction}\n",
        ]

        if best_metric is not None:
            parts.append(f"- Current best: {best_metric}\n")

        # Experiment history (last 10)
        if history:
            parts.append("\n## Previous Experiments")
            for exp in history[-10:]:
                if exp.accepted:
                    status_label = "ACCEPTED"
                elif exp.status == "error":
                    status_label = "ERROR"
                elif exp.reject_reason:
                    status_label = "REJECTED"
                else:
                    status_label = exp.status.upper()
                lines = [
                    f"\n### Experiment {exp.iteration} [{status_label}] strategy={exp.strategy}",
                    f"- Hypothesis: {exp.hypothesis[:200]}",
                    f"- Metric: {exp.metric_value}",
                ]
                if exp.reject_reason:
                    lines.append(f"- Reject reason: {exp.reject_reason[:150]}")
                if exp.files_modified:
                    files_str = ", ".join(exp.files_modified[:3])
                    if len(exp.files_modified) > 3:
                        files_str += f" (+{len(exp.files_modified) - 3} more)"
                    lines.append(f"- Files modified: {files_str}")
                parts.append("\n".join(lines))
            parts.append("")

        # Target files context
        if self._target_files:
            parts.append(f"\n## Target Files\n{', '.join(self._target_files)}\n")

        # Code-intel context
        if self._code_intel and self._target_files:
            for tf in self._target_files[:3]:
                try:
                    analysis = self._code_intel.file_analysis_data(tf)
                    if isinstance(analysis, dict):
                        summary = analysis.get("summary", "")
                        if summary:
                            parts.append(f"\n### {tf}\n{str(summary)[:500]}\n")
                except Exception:
                    pass

        parts.append(
            "\n## Instructions\n"
            f"This is iteration {iteration}. Based on the history above, "
            "propose a SPECIFIC, TARGETED hypothesis for the next experiment. "
            "Focus on one change that is most likely to improve the metric.\n\n"
            "Respond with ONLY the hypothesis (1-3 sentences). "
            "Be specific about what to change and why."
        )

        return "\n".join(parts)

    def generate_candidate(
        self,
        *,
        iteration: int,
        strategy: str,
        history: list[Experiment],
        best_metric: float | None,
        metric_name: str = "score",
        metric_direction: str = "maximize",
        steering_notes: list[str] | None = None,
    ) -> str:
        """Generate a concise candidate hypothesis without requiring an LLM call."""
        prompt = self.build_prompt(
            iteration=iteration,
            history=history,
            best_metric=best_metric,
            metric_name=metric_name,
            metric_direction=metric_direction,
        )
        notes = [note.strip() for note in steering_notes or [] if note.strip()]
        note_prefix = f"Steering: {notes[0]}. " if notes else ""
        focus = {
            "explore": "Try a NOVEL approach different from all prior experiments. Think creatively — what hasn't been tried yet?",
            "exploit": "Build on the current best result and refine the most promising mechanism. Make a targeted improvement.",
            "ablate": "Start from the best branch and REMOVE or simplify one mechanism to test if it was actually helping.",
            "compose": "Combine proven techniques from multiple accepted experiments into a single improved approach.",
            "reproduce": "Re-run the current best approach in a fresh workspace to validate the improvement is real.",
        }.get(strategy, "Try one targeted code change likely to improve the metric.")
        history_hint = ""
        if history:
            latest = history[-1]
            if latest.reject_reason:
                history_hint = f" Avoid repeating the last rejected pattern: {latest.reject_reason[:120]}."
        return (
            f"{note_prefix}{focus}"
            f" Optimize {metric_name} ({metric_direction})."
            f"{history_hint} Target files: {', '.join(self._target_files[:5]) or 'repo-local changes'}."
            f" [strategy={strategy}; iteration={iteration}; ctx={len(prompt)}]"
        )

    async def generate_candidate_llm(
        self,
        *,
        iteration: int,
        strategy: str,
        history: list[Experiment],
        best_metric: float | None,
        metric_name: str = "score",
        metric_direction: str = "maximize",
        steering_notes: list[str] | None = None,
        spawn_fn: Any | None = None,
    ) -> str:
        """Generate a hypothesis using the LLM via spawn_fn.

        Falls back to the static ``generate_candidate()`` when *spawn_fn* is
        ``None`` or when the LLM call fails.
        """
        if spawn_fn is None:
            return self.generate_candidate(
                iteration=iteration,
                strategy=strategy,
                history=history,
                best_metric=best_metric,
                metric_name=metric_name,
                metric_direction=metric_direction,
                steering_notes=steering_notes,
            )

        prompt = self.build_prompt(
            iteration=iteration,
            history=history,
            best_metric=best_metric,
            metric_name=metric_name,
            metric_direction=metric_direction,
        )

        # Strategy-specific instruction
        strategy_instruction = {
            "explore": (
                "Generate a NOVEL hypothesis different from all prior experiments. "
                "Try a completely new approach that hasn't been tried."
            ),
            "exploit": (
                "Analyze the best accepted experiment. What made it work? "
                "Propose a specific refinement that pushes the metric further."
            ),
            "ablate": (
                "The best experiment made several changes. Propose removing ONE "
                "specific change to test if it was actually helping or hurting."
            ),
            "compose": (
                "Multiple experiments improved the metric independently. "
                "Propose a way to combine their approaches for a bigger gain."
            ),
            "reproduce": (
                "Re-run the current best experiment to validate the gain is "
                "real and reproducible."
            ),
        }.get(strategy, "Propose a targeted improvement.")

        notes = [n.strip() for n in steering_notes or [] if n.strip()]
        steering_block = ""
        if notes:
            steering_block = (
                "\n\n## Steering Notes\n" + "\n".join(f"- {n}" for n in notes)
            )

        full_prompt = (
            f"{prompt}{steering_block}"
            f"\n\n## Your Task\n{strategy_instruction}\n\n"
            "Respond with ONLY the hypothesis text (1-3 sentences). "
            "Be specific about what code change to make."
        )

        try:
            import shutil
            import tempfile
            from pathlib import Path

            # Create a temp working dir for the hypothesis generation call
            tmp = Path(tempfile.mkdtemp(prefix="hypothesis-"))
            result = await asyncio.wait_for(
                spawn_fn(
                    {
                        "task_id": f"hypothesis-{iteration}",
                        "title": f"Generate research hypothesis ({strategy})",
                        "description": full_prompt,
                        "target_files": self._target_files,
                        "working_dir": str(tmp),
                    }
                ),
                timeout=60.0,
            )
            hypothesis = getattr(result, "result_summary", "") or ""
            # Clean up temp dir
            shutil.rmtree(tmp, ignore_errors=True)

            if hypothesis and len(hypothesis) > 10:
                return hypothesis[:500]
        except Exception:
            logger.debug("LLM hypothesis generation failed, falling back to static", exc_info=True)

        return self.generate_candidate(
            iteration=iteration,
            strategy=strategy,
            history=history,
            best_metric=best_metric,
            metric_name=metric_name,
            metric_direction=metric_direction,
            steering_notes=steering_notes,
        )
