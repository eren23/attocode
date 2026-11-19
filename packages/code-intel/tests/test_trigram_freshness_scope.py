"""A dirty snapshot must preserve search scope and remain dirty on build failure."""
import re

import pytest
from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex
from attocode_intel.gateway import OperationGateway


@pytest.mark.parametrize('operation', ['fast_search', 'regex_search', 'frecency_search'])
async def test_dirty_fallback_keeps_index_file_exclusions(tmp_path, monkeypatch, operation):
    for name in ['ATTOCODE_INTEL_PRECISION', 'ATTOCODE_INTEL_RANKING_PROVIDER']:
        monkeypatch.setenv(name, 'off')
    monkeypatch.setenv('ATTOCODE_NL_EMBEDDING_MODE', 'none')
    active = tmp_path / 'active.py'
    active.write_text('def probe():\n    return "scopefreshneedle"\n')
    for directory in ['.private', 'node_modules']:
        decoy = tmp_path / directory / 'decoy.py'
        decoy.parent.mkdir()
        decoy.write_text('scopefreshneedle\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await gateway.execute('symbols', {'path': 'active.py'})
        baseline = await gateway.execute('fast_search', {'pattern': 'scopefreshneedle'})
        assert not baseline.isError
        assert 'decoy.py' not in baseline.content[0].text
        active.write_text('def probe():\n    return "scopefreshneedle plus edited body"\n')
        real_build = TrigramIndex.build
        if operation == 'fast_search':
            def failed_build(*args, **kwargs):
                raise OSError('controlled optional cache build failure')

            monkeypatch.setattr(TrigramIndex, 'build', failed_build)
        args = {'pattern': 'scopefreshneedle'}
        if operation == 'frecency_search':
            args['use_frecency'] = False
        response = await gateway.execute(operation, args)
        assert not response.isError, response
        text = response.content[0].text
        assert 'active.py' in text and re.search(r'(?m)^.*active\.py', text), text
        assert 'decoy.py' not in text, text
        if operation == 'fast_search':
            # A failed build may not reactivate the stale disk prefilter.
            follow = await gateway.execute('regex_search', {'pattern': 'plus'})
            assert not follow.isError and 'active.py' in follow.content[0].text
            monkeypatch.setattr(TrigramIndex, 'build', real_build)
        rebuilt = await gateway.execute('fast_search', {'pattern': 'scopefreshneedle'})
        assert not rebuilt.isError and 'decoy.py' not in rebuilt.content[0].text
        assert next(iter(gateway._stores.values()))['trigrams'].is_ready()
    finally:
        await gateway.close()
