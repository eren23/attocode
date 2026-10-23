"""Source-bound readiness barrier shared by new online experiments."""

from __future__ import annotations

import asyncio
import time


def coverage_ready(coverage):
    """Rounded ratios cannot substitute for exact completed file counts."""
    return (
        isinstance(coverage, dict)
        and coverage.get("phase") == "ready"
        and coverage.get("discovery_truncated") is False
        and type(coverage.get("total_files")) is int
        and coverage["total_files"] > 0
        and all(
            type(coverage.get(key)) is int and coverage[key] >= coverage["total_files"]
            for key in ("parsed_files", "reference_indexed_files")
        )
    )


async def wait_ready(gateway, journal, *, poll_seconds=0.1):
    started, polls = time.monotonic(), 0
    response = await gateway.execute("search_symbols", {"name": "__quality_initialize__"})
    journal.response(
        {
            "event": "readiness_initialize",
            "operation": "search_symbols",
            "arguments": {"name": "__quality_initialize__"},
        },
        response.model_dump(mode="json"),
    )
    if response.isError:
        raise ValueError("readiness initialization failed")
    while True:
        response = await gateway.execute("capabilities", {})
        ref = journal.response(
            {"event": "readiness_poll", "operation": "capabilities", "arguments": {}},
            response.model_dump(mode="json"),
        )
        if response.isError:
            raise ValueError("readiness poll failed")
        coverage = response.structuredContent["capabilities"]["coverage"]
        polls += 1
        if coverage_ready(coverage):
            return {"polls": polls, "seconds": time.monotonic() - started, "response_ref": ref,
                    "poll_interval_seconds": poll_seconds}
        await asyncio.sleep(poll_seconds)
