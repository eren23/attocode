"""Research scoreboard and leaderboard rendering."""

from __future__ import annotations

from typing import Any

from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState, SteeringNote


class Scoreboard:
    """Renders campaign state, leaderboard, and findings."""

    def __init__(
        self,
        state: ResearchState,
        experiments: list[Experiment],
        *,
        findings: list[FindingRecord] | None = None,
    ) -> None:
        self._state = state
        self._experiments = experiments
        self._findings = findings or []

    def render_summary(self) -> str:
        s = self._state
        lines = [
            f"Research Run: {s.run_id}",
            f"Goal: {s.goal[:100]}",
            f"Metric: {s.metric_name} ({s.metric_direction})",
            f"Status: {s.status}",
            *([ f"Error: {s.error}"] if getattr(s, 'error', '') else []),
            "",
            f"Baseline: {s.baseline_value}",
            f"Best: {s.best_value} (experiment {s.best_experiment_id or 'n/a'})",
            f"Best branch: {s.best_branch or 'n/a'}",
            (
                "Experiments: "
                f"{s.total_experiments} ({s.accepted_count} accepted, "
                f"{s.candidate_count} pending, {s.held_count} held, "
                f"{s.killed_count} killed, {s.rejected_count} rejected, {s.invalid_count} invalid)"
            ),
            f"Cost: ${s.total_cost_usd:.4f} | Tokens: {s.total_tokens:,}",
            f"Wall time: {s.wall_seconds:.0f}s | Active: {s.active_experiments}",
        ]
        return "\n".join(lines)

    def render_table(self, limit: int = 20) -> str:
        header = (
            f"{'#':>3} {'Status':<8} {'Strat':<9} {'Metric':>10} "
            f"{'Delta':>10} {'Files':>5} {'Hypothesis':<40}"
        )
        sep = "-" * len(header)
        lines = [header, sep]
        baseline = self._state.baseline_value or 0.0

        if self._state.metric_direction == "minimize":
            ranked = sorted(
                self._experiments,
                key=lambda exp: (
                    exp.metric_value is None,
                    exp.metric_value if exp.metric_value is not None else float("inf"),
                ),
            )
        else:
            ranked = sorted(
                self._experiments,
                key=lambda exp: (
                    exp.metric_value is None,
                    -(exp.metric_value if exp.metric_value is not None else float("-inf")),
                ),
            )

        for exp in ranked[:limit]:
            metric = f"{exp.metric_value:.4f}" if exp.metric_value is not None else "N/A"
            delta = ""
            if exp.metric_value is not None:
                d = exp.metric_value - baseline
                delta = f"{d:+.4f}"
            n_files = str(len(exp.files_modified)) if exp.files_modified else "-"
            # Build hypothesis text with optional reject reason suffix
            hyp_text = exp.hypothesis[:36]
            if exp.reject_reason:
                reason_short = exp.reject_reason[:20]
                hyp_text = f"{exp.hypothesis[:24]}.. [{reason_short}]"
            elif len(exp.hypothesis) > 38:
                hyp_text = exp.hypothesis[:36] + ".."
            lines.append(
                f"{exp.iteration:>3} {exp.status[:8]:<8} {exp.strategy[:9]:<9} "
                f"{metric:>10} {delta:>10} {n_files:>5} {hyp_text:<40}"
            )
        return "\n".join(lines)

    def render_findings(self, limit: int = 10) -> str:
        if not self._findings:
            return "No findings recorded."
        lines = ["Findings:"]
        for finding in self._findings[:limit]:
            pct = int(finding.confidence * 100)
            lines.append(f"- [{finding.status}] {finding.claim} ({pct}%)")
        return "\n".join(lines)

    def render_steering_notes(self, notes: list[SteeringNote], limit: int = 10) -> str:
        if not notes:
            return "No active steering notes."
        lines = ["Steering Notes:"]
        for note in notes[:limit]:
            target = f" target={note.target}" if note.target else ""
            lines.append(f"- [{note.scope}{target}] {note.content}")
        return "\n".join(lines)

    def render_candidates(self, limit: int = 10, promotion_repeats: int = 1) -> str:
        roots = [
            exp for exp in self._experiments
            if exp.status in {"candidate", "held"} and not exp.parent_experiment_id
        ]
        if not roots:
            return "No pending candidates."
        lines = ["Candidates:"]
        for exp in roots[:limit]:
            validations = 1 + sum(
                1 for child in self._experiments
                if child.parent_experiment_id == exp.experiment_id and child.status in {"validated", "accepted"}
            )
            lines.append(
                f"- [{exp.status}] {exp.experiment_id} metric={exp.metric_value} "
                f"progress={validations}/{max(promotion_repeats, 1)} strategy={exp.strategy}"
            )
            lines.append(f"  hypothesis={exp.hypothesis[:180]}")
        return "\n".join(lines)

    def render_feed(
        self,
        *,
        notes: list[SteeringNote] | None = None,
        leaderboard_limit: int = 5,
        findings_limit: int = 10,
        notes_limit: int = 10,
        promotion_repeats: int = 1,
    ) -> str:
        sections = [
            self.render_summary(),
            self.render_candidates(limit=leaderboard_limit, promotion_repeats=promotion_repeats),
            self.render_table(limit=leaderboard_limit),
            self.render_findings(limit=findings_limit),
            self.render_steering_notes(notes or [], limit=notes_limit),
        ]
        return "\n\n".join(sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self._state.to_dict(),
            "experiments": [e.to_dict() for e in self._experiments],
            "findings": [f.to_dict() for f in self._findings],
            "summary": self.render_summary(),
        }
