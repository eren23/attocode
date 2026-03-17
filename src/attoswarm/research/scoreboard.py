"""Research scoreboard — experiment history rendering and analysis."""

from __future__ import annotations

from typing import Any

from attoswarm.research.experiment import Experiment, ResearchState


class Scoreboard:
    """Renders experiment history as formatted reports."""

    def __init__(self, state: ResearchState, experiments: list[Experiment]) -> None:
        self._state = state
        self._experiments = experiments

    def render_summary(self) -> str:
        """Render a brief summary of the research run."""
        s = self._state
        lines = [
            f"Research Run: {s.run_id}",
            f"Goal: {s.goal[:100]}",
            f"Metric: {s.metric_name} ({s.metric_direction})",
            f"Status: {s.status}",
            "",
            f"Baseline: {s.baseline_value}",
            f"Best: {s.best_value} (experiment {s.best_experiment_id})",
            f"Experiments: {s.total_experiments} ({s.accepted_count} accepted, {s.rejected_count} rejected)",
            f"Cost: ${s.total_cost_usd:.4f} | Tokens: {s.total_tokens:,}",
            f"Wall time: {s.wall_seconds:.0f}s",
        ]
        return "\n".join(lines)

    def render_table(self) -> str:
        """Render experiment history as a table."""
        header = (
            f"{'#':>3} {'Status':<8} {'Metric':>10} {'Delta':>10} "
            f"{'Cost':>8} {'Hypothesis':<40}"
        )
        sep = "-" * len(header)
        lines = [header, sep]

        baseline = self._state.baseline_value or 0.0
        prev_best = baseline

        for exp in self._experiments:
            status = "ACCEPT" if exp.accepted else "REJECT"
            metric = f"{exp.metric_value:.4f}" if exp.metric_value is not None else "N/A"
            delta = ""
            if exp.metric_value is not None:
                d = exp.metric_value - (exp.baseline_value or baseline)
                sign = "+" if d >= 0 else ""
                delta = f"{sign}{d:.4f}"
                if exp.accepted:
                    prev_best = exp.metric_value

            hyp = exp.hypothesis[:38] + ".." if len(exp.hypothesis) > 40 else exp.hypothesis
            cost = f"${exp.cost_usd:.3f}"

            lines.append(
                f"{exp.iteration:>3} {status:<8} {metric:>10} {delta:>10} "
                f"{cost:>8} {hyp:<40}"
            )

        return "\n".join(lines)

    def render_trend(self) -> str:
        """Render metric progression trend."""
        if not self._experiments:
            return "No experiments yet."

        accepted = [e for e in self._experiments if e.accepted and e.metric_value is not None]
        if not accepted:
            return "No accepted experiments."

        lines = ["Metric Progression (accepted only):"]
        baseline = self._state.baseline_value or 0.0
        lines.append(f"  Baseline: {baseline:.4f}")

        for exp in accepted:
            improvement = (exp.metric_value or 0.0) - baseline
            bar_len = min(int(abs(improvement) * 50), 40)
            bar = "+" * bar_len if improvement >= 0 else "-" * bar_len
            lines.append(f"  #{exp.iteration:>3}: {exp.metric_value:.4f} [{bar}]")

        # Summary stats
        values = [e.metric_value for e in accepted if e.metric_value is not None]
        if len(values) >= 2:
            trend = values[-1] - values[0]
            lines.append(f"\n  Overall trend: {'+' if trend >= 0 else ''}{trend:.4f}")
            lines.append(f"  Mean: {sum(values) / len(values):.4f}")
            lines.append(f"  Best: {max(values) if self._state.metric_direction == 'maximize' else min(values):.4f}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Full scoreboard as dict."""
        return {
            "state": self._state.to_dict(),
            "experiments": [e.to_dict() for e in self._experiments],
            "summary": self.render_summary(),
        }
