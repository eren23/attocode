"""Real small-workspace controls for the large-source qualification harness."""
import json

import pytest
from attocode_intel.gateway import OperationGateway

from eval.quality.capacity_experiment import generate, phase
from eval.quality.corpus_capture import journal_events


@pytest.mark.parametrize('damage', [False, True], ids=['valid-source', 'altered-snippet'])
async def test_capacity_phase_validates_actual_delivered_search_sources(tmp_path, monkeypatch, damage):
    monkeypatch.setenv('ATTOCODE_INTEL_MAX_FILES', '100000')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    tree = tmp_path / 'project'
    generate(tree, 2)
    if damage:
        original = OperationGateway.execute_mcp

        async def changed(self, tool, arguments):
            response = await original(self, tool, arguments)
            if tool == 'semantic_search':
                page = json.loads(response.content[0].text)
                if page.get('data', {}).get('results'):
                    page['data']['results'][0]['snippet'] = 'not the source in this fixture'
                    response.content[0].text = json.dumps(page)
            return response

        monkeypatch.setattr(OperationGateway, 'execute_mcp', changed)
    output = tmp_path / 'capture'
    spec = {'tree': str(tree), 'size': 2, 'phase': 'cold', 'seconds': 40}
    if damage:
        with pytest.raises(ValueError, match='source snippet does not match'):
            await phase(spec, output)
        assert json.loads((output / 'result.json').read_bytes())['complete'] is False
    else:
        result = await phase(spec, output)
        assert result['complete'] and result['closed'] and result['outcome'] == 'passed'
        events = journal_events(output / 'sources')
        validations = [value for request, _, value in events if request['event'] == 'source_validation']
        source_rows = [row for value in validations for row in value if row.get('kind') == 'source']
        assert len(source_rows) >= 3
        assert any(row.get('policy', {}).get('producer') for row in source_rows)
