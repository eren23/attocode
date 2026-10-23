"""Full navigation readiness is independent of body-index readiness."""
import json
from types import SimpleNamespace

import pytest

from eval.quality.experiment_evidence import Journal
from eval.quality.readiness import coverage_ready, wait_ready


@pytest.mark.parametrize(
    "change", ["phase", "parsed", "references", "truncated", "rounded", "bool", "zero"]
)
def test_readiness_requires_exact_completed_counts(change):
    c = {
        "phase": "ready",
        "total_files": 1001,
        "parsed_files": 1001,
        "reference_indexed_files": 1001,
        "discovery_truncated": False,
    }
    assert coverage_ready(c)
    if change == "phase":
        c["phase"] = "hydrating"
    if change == "parsed":
        c["parsed_files"] = 1000
    if change == "references":
        c["reference_indexed_files"] = 1000
    if change == "truncated":
        c["discovery_truncated"] = True
    if change == "rounded":
        c.update(parsed_files=1000, parse_coverage=1.0)
    if change == "bool":
        c["reference_indexed_files"] = True
    if change == "zero":
        c["total_files"] = 0
    assert not coverage_ready(c)


@pytest.mark.asyncio
async def test_initialization_and_every_readiness_response_are_retained_before_inspection(tmp_path):
    journal = Journal(tmp_path / "journal", 8192)
    calls = []

    class Gateway:
        async def execute(self, name, args):
            calls.append(name)
            data = {
                "capabilities": {
                    "coverage": {
                        "phase": "ready",
                        "total_files": 1,
                        "parsed_files": 1,
                        "reference_indexed_files": 1,
                        "discovery_truncated": False,
                    }
                }
            }
            return SimpleNamespace(
                isError=False,
                structuredContent=data,
                model_dump=lambda **kw: {"content": [], "structuredContent": data},
            )

    result = await wait_ready(Gateway(), journal)
    assert calls == ["search_symbols", "capabilities"] and result["polls"] == 1
    events = [json.loads(line) for line in (journal.root / "events.jsonl").read_text().splitlines()]
    assert [e["request"]["event"] for e in events] == ["readiness_initialize", "readiness_poll"]
    assert all((journal.root / e["response"]["path"]).is_file() for e in events)

