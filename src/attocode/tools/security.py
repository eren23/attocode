"""Security scan agent tool."""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def _execute_security_scan(scanner: Any, args: dict[str, Any]) -> str:
    """Execute a security scan."""
    mode: str = args.get("mode", "full")
    path: str = args.get("path", "")

    valid_modes = ("quick", "full", "secrets", "patterns", "dependencies")
    if mode not in valid_modes:
        return f"Error: mode must be one of {valid_modes}, got '{mode}'"

    report = scanner.scan(mode=mode, path=path)
    return scanner.format_report(report)


def create_security_scan_tool(scanner: Any) -> Tool:
    """Create the security_scan tool bound to a SecurityScanner.

    Args:
        scanner: SecurityScanner instance.

    Returns:
        A Tool for running security scans.
    """

    async def _execute(args: dict[str, Any]) -> Any:
        return await _execute_security_scan(scanner, args)

    return Tool(
        spec=ToolSpec(
            name="security_scan",
            description=(
                "Scan the codebase for security issues: hardcoded secrets, "
                "code anti-patterns, and dependency pinning issues. "
                "All scanning is local (no external API calls). "
                "Returns a compliance score (0-100) and categorized findings."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["quick", "full", "secrets", "patterns", "dependencies"],
                        "default": "full",
                        "description": (
                            "Scan mode: 'quick' (secrets only), 'full' (all checks), "
                            "'secrets', 'patterns', or 'dependencies'."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "default": "",
                        "description": (
                            "Subdirectory to scan (relative to project root). "
                            "Empty for entire project."
                        ),
                    },
                },
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_execute,
        tags=["security", "audit"],
    )
