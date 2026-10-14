"""Every advertised operation rejects malformed input before opening a workspace.

This is schema evidence only. Runtime observations separately identify operations
with successful responses and operations tested only through rejection paths.
"""
import pytest
from attocode_intel.catalog import tool_catalog
from attocode_intel.gateway import OperationGateway
from jsonschema.exceptions import ValidationError


@pytest.mark.parametrize('operation', [t.name for t in tool_catalog('full')])
async def test_catalog_operation_rejects_invalid_workspace_before_execution(tmp_path, operation):
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        with pytest.raises(ValidationError):
            await gateway.execute(operation, {'workspace': []})
        assert gateway._stores == {} and gateway._workers == {}
        assert list(tmp_path.iterdir()) == []
    finally:
        await gateway.close()


@pytest.mark.parametrize('operation,arguments,expected', [
    ('fast_search', {'pattern':'quality_helper'}, 'helper.py'),
    ('regex_search', {'pattern':'quality_helper'}, 'helper.py'),
    ('fuzzy_filename_search', {'pattern':'helper'}, 'helper.py'),
    ('explore_codebase', {'importance_threshold':0}, 'helper.py'),
    ('relevant_context', {'files':['caller.py']}, 'quality_helper'),
    ('call_graph', {'symbol':'quality_entry', 'direction':'callees'}, 'quality_helper'),
    ('file_analysis', {'path':'helper.py'}, 'quality_helper'),
    ('dependency_graph', {'start_file':'caller.py'}, 'helper.py'),
    ('graph_query', {'file':'caller.py'}, 'helper.py'),
    ('repo_map', {}, 'helper.py'),
])
async def test_source_navigation_operations_return_fixture_evidence(tmp_path, monkeypatch, operation, arguments, expected):
    import json
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'helper.py').write_text('def quality_helper(): return 1\n')
    (tmp_path / 'caller.py').write_text('from helper import quality_helper\ndef quality_entry(): return quality_helper()\n')
    (tmp_path / 'ignored.py').write_text('def secret_ignored_helper(): return 2\n')
    (tmp_path / '.gitignore').write_text('ignored.py\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        response = await gateway.execute(operation, arguments)
        assert not response.isError
        rendered = json.dumps(response.structuredContent.get('data', response.structuredContent))
        assert expected in rendered, rendered
        assert 'secret_ignored_helper' not in rendered
    finally:
        await gateway.close()
