"""Readiness report tool for the code-intel MCP server.

Tools: readiness_report.
"""

from __future__ import annotations

from attocode.code_intel.server import (
    _get_project_dir,
    mcp,
)


@mcp.tool()
def readiness_report(
    phases: list[int] | None = None,
    scope: str = "",
    tracer_bullets: bool = True,
    min_severity: str = "info",
) -> str:
    """Run a comprehensive readiness audit of the codebase.

    Executes 8 analysis phases covering baseline health, API completeness,
    frontend flows, data layer, test coverage, security, observability,
    and deployability. Orchestrates existing tools (security_scan, dead_code,
    hotspots, conventions, etc.) plus new phase-specific analysis.

    Returns severity-tagged findings with file:line evidence and an overall
    readiness grade (A-F).

    Args:
        phases: List of phase numbers to run (0-7). None = all phases.
            0=Baseline, 1=API/Logic, 2=Frontend, 3=Data, 4=Tests,
            5=Security, 6=Observability, 7=Deployability.
        scope: Restrict analysis to files under this directory prefix.
        tracer_bullets: Whether to run tracer bullet analysis (default True).
        min_severity: Minimum severity to include: "pass", "info", "warning", "critical".
    """
    from attocode.code_intel.readiness import ReadinessEngine, ReadinessSeverity

    project_dir = _get_project_dir()
    engine = ReadinessEngine(project_dir=project_dir)

    report = engine.run(
        phases=phases,
        scope=scope,
        tracer_bullets=tracer_bullets,
    )

    # Filter findings by min_severity
    severity_order = [
        ReadinessSeverity.PASS,
        ReadinessSeverity.INFO,
        ReadinessSeverity.WARNING,
        ReadinessSeverity.CRITICAL,
    ]
    try:
        min_idx = severity_order.index(ReadinessSeverity(min_severity))
    except (ValueError, KeyError):
        min_idx = 0

    for pr in report.phase_results:
        pr.findings = [
            f for f in pr.findings
            if severity_order.index(f.severity) >= min_idx
        ]

    return engine.format_report(report)
