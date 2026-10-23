"""Full navigation readiness is independent of body-index readiness."""
import asyncio
import json
import threading
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


@pytest.mark.asyncio
async def test_navigation_barrier_waits_for_delayed_real_reference_hydration(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context import ast_service as module
    from attocode_intel.gateway import OperationGateway

    workspace = tmp_path / 'source'
    workspace.mkdir()
    for n in range(4):
        (workspace / f'unit{n}.py').write_text(f'def unit{n}():\n    return {n}\n')
    release = threading.Event()
    entered = threading.Event()
    original = module.ASTService._run_hydration

    def delayed(service):
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError('controlled hydration was never released')
        return original(service)

    monkeypatch.setattr(module, 'skeleton_budget', lambda tier, count: 1)
    monkeypatch.setattr(module.ASTService, '_run_hydration', delayed)
    gateway = OperationGateway(str(workspace), 'daily', watch=False)
    try:
        journal = Journal(tmp_path / 'capture', 1024 * 1024)
        initialize = await gateway.execute('search_symbols', {'name': '__delayed_fixture_initialize__'})
        journal.response({'event': 'control_initialize'}, initialize.model_dump(mode='json'))
        assert not initialize.isError and entered.wait(timeout=1)
        before = await gateway.execute('capabilities', {})
        journal.response({'event': 'control_before'}, before.model_dump(mode='json'))
        partial = before.structuredContent['capabilities']['coverage']
        assert partial['phase'] == 'hydrating' and partial['total_files'] == 4
        assert partial['reference_indexed_files'] < partial['total_files']
        assert not coverage_ready(partial)
        raw_response = journal.response
        observed = []

        def retain_then_release(request, value):
            ref = raw_response(request, value)
            if request['event'] == 'readiness_poll':
                c = value['structuredContent']['capabilities']['coverage']
                observed.append(c)
                if len(observed) == 1:
                    assert not coverage_ready(c)
                    release.set()
            return ref

        monkeypatch.setattr(journal, 'response', retain_then_release)
        admitted = await asyncio.wait_for(wait_ready(gateway, journal), timeout=5)
        assert len(observed) >= 2 and admitted['polls'] == len(observed)
        assert coverage_ready(observed[-1]) and observed[-1]['reference_indexed_files'] == 4
        events = [json.loads(line) for line in (journal.root / 'events.jsonl').read_text().splitlines()]
        assert all((journal.root / event['response']['path']).is_file() for event in events)
    finally:
        release.set()
        await gateway.close()
