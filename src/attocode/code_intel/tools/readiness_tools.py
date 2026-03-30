"""Readiness report tool for the code-intel MCP server.

Tools: readiness_report.
"""

from __future__ import annotations

from attocode.code_intel._shared import (
    _get_service,
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
    return _get_service().readiness_report(
        phases=phases,
        scope=scope,
        tracer_bullets=tracer_bullets,
        min_severity=min_severity,
    )
