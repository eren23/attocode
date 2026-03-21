"""Automated post-mortem report generator.

Produces comprehensive markdown + JSON reports covering:
- Summary (outcome, success rate, cost, duration)
- Decomposition quality (validator score + metrics)
- Execution analysis (critical path, parallelism efficiency)
- Failures (root causes, poison tasks, wasted cost)
- Robustness events (rate limits, concurrency adjustments, budget warnings)
- Recommendations (actionable suggestions)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.causal_analyzer import CausalChainAnalyzer
    from attoswarm.coordinator.decompose_metrics import DecomposeMetrics, DecomposeScorecard
    from attoswarm.coordinator.trace_query import TraceQueryEngine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PostMortemReport:
    """Structured post-mortem report."""

    # Summary
    outcome: str = ""  # "completed" | "partial" | "failed" | "shutdown"
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    success_rate: float = 0.0
    total_cost_usd: float = 0.0
    total_duration_s: float = 0.0

    # Decomposition
    decomposition_score: float = 0.0
    decomposition_issues: list[dict[str, Any]] = field(default_factory=list)

    # Execution
    critical_path: list[str] = field(default_factory=list)
    critical_path_duration_s: float = 0.0
    parallel_efficiency: float = 0.0

    # Failures
    root_causes: list[dict[str, Any]] = field(default_factory=list)
    poison_tasks: list[dict[str, Any]] = field(default_factory=list)
    total_wasted_cost: float = 0.0

    # Robustness
    rate_limit_events: int = 0
    concurrency_adjustments: int = 0
    budget_warnings: int = 0

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "outcome": self.outcome,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
                "failed_tasks": self.failed_tasks,
                "skipped_tasks": self.skipped_tasks,
                "success_rate": round(self.success_rate, 3),
                "total_cost_usd": round(self.total_cost_usd, 4),
                "total_duration_s": round(self.total_duration_s, 1),
            },
            "decomposition": {
                "score": round(self.decomposition_score, 3),
                "issues": self.decomposition_issues,
            },
            "execution": {
                "critical_path": self.critical_path,
                "critical_path_duration_s": round(self.critical_path_duration_s, 1),
                "parallel_efficiency": round(self.parallel_efficiency, 3),
            },
            "failures": {
                "root_causes": self.root_causes,
                "poison_tasks": self.poison_tasks,
                "total_wasted_cost": round(self.total_wasted_cost, 4),
            },
            "robustness": {
                "rate_limit_events": self.rate_limit_events,
                "concurrency_adjustments": self.concurrency_adjustments,
                "budget_warnings": self.budget_warnings,
            },
            "recommendations": self.recommendations,
        }


class PostMortemGenerator:
    """Generates comprehensive post-mortem reports.

    Usage::

        gen = PostMortemGenerator(
            query_engine=engine,
            causal_analyzer=analyzer,
            decompose_metrics=metrics,
        )
        report = gen.generate(
            dag_summary=graph.summary(),
            budget_data=budget.as_dict(),
            wall_clock_s=elapsed,
            critical_path=graph.get_critical_path(),
            max_concurrency=4,
        )
        gen.persist(report, run_dir)
    """

    def __init__(
        self,
        query_engine: TraceQueryEngine | None = None,
        causal_analyzer: CausalChainAnalyzer | None = None,
        decompose_metrics: DecomposeMetrics | None = None,
    ) -> None:
        self._engine = query_engine
        self._causal = causal_analyzer
        self._metrics = decompose_metrics

    def generate(
        self,
        dag_summary: dict[str, int] | None = None,
        budget_data: dict[str, Any] | None = None,
        wall_clock_s: float = 0.0,
        critical_path: list[str] | None = None,
        max_concurrency: int = 4,
        validation_result: dict[str, Any] | None = None,
        poison_reports: list[dict[str, Any]] | None = None,
        concurrency_stats: dict[str, Any] | None = None,
    ) -> PostMortemReport:
        """Generate a complete post-mortem report."""
        report = PostMortemReport()
        summary = dag_summary or {}

        # Summary
        report.total_tasks = sum(summary.values())
        report.completed_tasks = summary.get("done", 0)
        report.failed_tasks = summary.get("failed", 0)
        report.skipped_tasks = summary.get("skipped", 0)
        report.total_duration_s = wall_clock_s

        if report.total_tasks > 0:
            report.success_rate = report.completed_tasks / report.total_tasks

        if report.completed_tasks == report.total_tasks:
            report.outcome = "completed"
        elif report.completed_tasks > 0:
            report.outcome = "partial"
        elif report.failed_tasks > 0:
            report.outcome = "failed"
        else:
            report.outcome = "shutdown"

        # Budget
        if budget_data:
            report.total_cost_usd = budget_data.get("cost_used_usd", 0.0)

        # Critical path
        if critical_path:
            report.critical_path = critical_path

        # Decomposition quality
        if validation_result:
            report.decomposition_score = validation_result.get("score", 0.0)
            report.decomposition_issues = validation_result.get("issues", [])

        if self._metrics and self._engine:
            scorecard = self._metrics.score(
                task_data=self._engine.task_data,
                wall_clock_s=wall_clock_s,
                max_concurrency=max_concurrency,
            )
            report.parallel_efficiency = scorecard.parallel_efficiency
            if not validation_result:
                report.decomposition_score = scorecard.overall_score

        # Failures
        if self._causal:
            root_causes = self._causal.get_root_causes()
            report.root_causes = [r.to_dict() for r in root_causes]
            report.total_wasted_cost = sum(r.wasted_cost for r in root_causes)

        if poison_reports:
            report.poison_tasks = [p for p in poison_reports if p.get("is_poison")]

        # Robustness events
        if self._engine:
            report.rate_limit_events = len(self._engine.search_events(
                r"rate.limit", event_types=["fail", "budget", "warning"],
            ))
            report.budget_warnings = len(self._engine.events_by_type("budget"))

        if concurrency_stats:
            report.concurrency_adjustments = (
                concurrency_stats.get("increases", 0)
                + concurrency_stats.get("decreases", 0)
            )

        # Recommendations
        report.recommendations = self._generate_recommendations(report)

        return report

    def _generate_recommendations(self, report: PostMortemReport) -> list[str]:
        """Generate actionable recommendations based on the report."""
        recs: list[str] = []

        if report.success_rate < 0.5:
            recs.append(
                "Low success rate — consider simplifying the goal or "
                "improving task descriptions"
            )

        if report.parallel_efficiency < 0.3 and report.total_tasks > 3:
            recs.append(
                "Low parallel efficiency — review dependency graph for "
                "unnecessary sequential constraints"
            )

        if report.total_wasted_cost > report.total_cost_usd * 0.3:
            recs.append(
                f"High wasted cost (${report.total_wasted_cost:.2f}) — "
                "investigate root causes and consider poison task detection"
            )

        if report.rate_limit_events > 3:
            recs.append(
                f"{report.rate_limit_events} rate limit events — "
                "consider reducing max concurrency or adding backoff"
            )

        for poison in report.poison_tasks:
            tid = poison.get("task_id", "?")
            rec = poison.get("recommendation", "skip")
            recs.append(f"Poison task '{tid}' — recommendation: {rec}")

        if report.decomposition_score < 0.5:
            recs.append(
                "Low decomposition quality — review task granularity "
                "and dependency edges"
            )

        for root in report.root_causes[:3]:
            tid = root.get("task_id", "?")
            cause = root.get("cause", "unknown")
            affected = len(root.get("affected_tasks", []))
            if affected > 1:
                recs.append(
                    f"Root cause '{tid}' ({cause}) blocked {affected} tasks — "
                    "prioritize fixing this task"
                )

        return recs

    def to_markdown(self, report: PostMortemReport) -> str:
        """Render the report as markdown."""
        lines: list[str] = []
        lines.append("# Swarm Post-Mortem Report")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append(f"- **Outcome**: {report.outcome}")
        lines.append(f"- **Tasks**: {report.completed_tasks}/{report.total_tasks} completed")
        lines.append(f"- **Success rate**: {report.success_rate:.0%}")
        lines.append(f"- **Cost**: ${report.total_cost_usd:.4f}")
        lines.append(f"- **Duration**: {report.total_duration_s:.1f}s")
        lines.append("")

        # Decomposition
        if report.decomposition_score > 0:
            lines.append("## Decomposition Quality")
            lines.append(f"- **Score**: {report.decomposition_score:.2f}/1.00")
            lines.append(f"- **Parallel efficiency**: {report.parallel_efficiency:.0%}")
            if report.decomposition_issues:
                lines.append(f"- **Issues**: {len(report.decomposition_issues)}")
            lines.append("")

        # Execution
        if report.critical_path:
            lines.append("## Execution")
            lines.append(f"- **Critical path**: {' → '.join(report.critical_path)}")
            if report.critical_path_duration_s:
                lines.append(f"- **Critical path time**: {report.critical_path_duration_s:.1f}s")
            lines.append("")

        # Failures
        if report.root_causes or report.poison_tasks:
            lines.append("## Failures")
            if report.root_causes:
                lines.append("### Root Causes")
                for rc in report.root_causes:
                    affected = len(rc.get("affected_tasks", []))
                    lines.append(
                        f"- **{rc.get('task_id')}** ({rc.get('cause')}): "
                        f"blocked {affected} tasks, wasted ${rc.get('wasted_cost', 0):.4f}"
                    )
            if report.poison_tasks:
                lines.append("### Poison Tasks")
                for pt in report.poison_tasks:
                    lines.append(f"- **{pt.get('task_id')}**: {pt.get('reason', 'unknown')}")
            lines.append(f"\n**Total wasted cost**: ${report.total_wasted_cost:.4f}")
            lines.append("")

        # Robustness
        if report.rate_limit_events or report.concurrency_adjustments or report.budget_warnings:
            lines.append("## Robustness Events")
            lines.append(f"- Rate limits: {report.rate_limit_events}")
            lines.append(f"- Concurrency adjustments: {report.concurrency_adjustments}")
            lines.append(f"- Budget warnings: {report.budget_warnings}")
            lines.append("")

        # Recommendations
        if report.recommendations:
            lines.append("## Recommendations")
            for rec in report.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines)

    def persist(self, report: PostMortemReport, run_dir: Path) -> None:
        """Persist the report as both JSON and markdown."""
        try:
            json_path = run_dir / "postmortem.json"
            json_path.write_text(
                json.dumps(report.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist postmortem JSON: %s", exc)

        try:
            md_path = run_dir / "postmortem.md"
            md_path.write_text(self.to_markdown(report), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist postmortem markdown: %s", exc)
