"""A later failed operation must retain earlier and failing runner responses."""
import json

import pytest
from mcp.types import CallToolResult, TextContent

from eval.quality import restart_worker


@pytest.mark.asyncio
@pytest.mark.parametrize('close_fails', [False, True])
async def test_failed_phase_preserves_raw_responses_and_partial_evidence(tmp_path, monkeypatch, close_fails):
    from attocode_intel import gateway

    class Peer:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def execute(self, operation, arguments):
            self.calls += 1
            if self.calls == 1:
                return CallToolResult(content=[TextContent(type='text', text='definition result')],
                    structuredContent={'data': [{'file_path': 'sample.go', 'start_line': 1, 'name': 'target'}]})
            return CallToolResult(isError=True, content=[TextContent(type='text', text='preserve this failure')])

        async def close(self):
            if close_fails:
                raise RuntimeError('close failed too')

    monkeypatch.setattr(gateway, 'OperationGateway', Peer)
    spec = {'symbol': 'target', 'file': 'sample.go', 'definition_line': 1, 'anchor': 'func target('}
    report = tmp_path / 'phase.json'
    expected = RuntimeError if close_fails else AssertionError
    with pytest.raises(expected):
        await restart_worker.navigate(tmp_path, spec, report)
    partial = json.loads(report.read_text())
    journal = [json.loads(line) for line in report.with_suffix('.jsonl').read_text().splitlines()]
    assert partial['status'] == 'incomplete'
    assert partial['evidence']['definition'][0]['name'] == 'target'
    assert partial['operations_seconds']['definition'] >= 0
    assert [row['label'] for row in journal] == ['definition', 'source']
    assert journal[-1]['response']['isError'] is True
    assert journal[-1]['response']['content'][0]['text'] == 'preserve this failure'
    assert bool(partial.get('close_failure')) is close_fails
