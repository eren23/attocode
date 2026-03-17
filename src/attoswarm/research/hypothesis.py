"""Hypothesis generation for research experiments."""

from __future__ import annotations

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
                status = "ACCEPTED" if exp.accepted else "REJECTED"
                parts.append(
                    f"\n### Experiment {exp.iteration} [{status}]"
                    f"\n- Hypothesis: {exp.hypothesis[:200]}"
                    f"\n- Metric: {exp.metric_value}"
                    f"\n- Reason: {exp.reject_reason or 'accepted'}"
                )
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
