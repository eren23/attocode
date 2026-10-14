"""Opt-in pytest observations, not inferred accuracy from test names.

Use ``-p eval.quality.coverage --quality-operations=PATH``. Only calls made in
this pytest process through OperationGateway.execute are observed; subprocess
MCP and direct internal calls remain separate protocol/unit evidence.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption('--quality-operations', help='Write a catalog-to-passing-test call inventory')


def pytest_configure(config):
    config._quality_calls = defaultdict(list)
    config._quality_outcomes = defaultdict(dict)


@pytest.fixture(autouse=True)
def _record_quality_operations(request, monkeypatch):
    if not request.config.getoption('--quality-operations'):
        return
    from attocode_intel.gateway import OperationGateway
    original = OperationGateway.execute

    async def execute(self, name, arguments, **kwargs):
        try:
            response = await original(self, name, arguments, **kwargs)
        except BaseException:
            request.config._quality_calls[request.node.nodeid].append((name, 'raised'))
            raise
        request.config._quality_calls[request.node.nodeid].append((name, 'error' if response.isError else 'response'))
        return response

    monkeypatch.setattr(OperationGateway, 'execute', execute)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    item.config._quality_outcomes[item.nodeid][report.when] = report.outcome


def operation_inventory(names, calls, outcomes):
    rows = []
    for name in sorted(names):
        tests = []
        for node, observations in sorted(calls.items()):
            selected = [status for operation, status in observations if operation == name]
            phases = outcomes.get(node, {})
            if selected and all(phases.get(phase) == 'passed' for phase in ('setup', 'call', 'teardown')):
                tests.append({'test': node, 'responses': selected.count('response'),
                              'errors': selected.count('error'), 'raised': selected.count('raised')})
        responses = sum(t['responses'] for t in tests)
        rows.append({'operation': name, 'status': 'response_observed' if responses else 'error_only' if tests else 'unmapped', 'tests': tests})
    return {'schema_version': 1, 'operations': rows,
            'observed': sum(r['status'] == 'response_observed' for r in rows),
            'error_only': sum(r['status'] == 'error_only' for r in rows),
            'unmapped': sum(r['status'] == 'unmapped' for r in rows), 'total': len(rows),
            'scope': 'Gateway calls in passing tests, including tested errors; not proof of semantic accuracy, '
                     'complete branch coverage, or subprocess/direct-internal coverage'}


def pytest_sessionfinish(session, exitstatus):
    destination = session.config.getoption('--quality-operations')
    if not destination:
        return
    from attocode_intel.catalog import tool_catalog
    result = operation_inventory([t.name for t in tool_catalog()], session.config._quality_calls,
                                 session.config._quality_outcomes)
    result['pytest_exit_code'] = int(exitstatus)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
