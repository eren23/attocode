"""Preserve established indexed and never-indexed scope during dirty scans."""
import re

import pytest
from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex
from attocode_intel.gateway import OperationGateway

MARKER = 'REGRESSION:dirty fallback changed established file scope'


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    monkeypatch.setenv('ATTOCODE_NL_EMBEDDING_MODE', 'none')


async def search(gateway, operation, pattern):
    args = {'pattern': pattern}
    if operation == 'frecency_search':
        args['use_frecency'] = False
    result = await gateway.execute(operation, args)
    assert not result.isError, result
    return result.content[0].text


def paths(text):
    return set(re.findall(r'(?m)^([\w./-]+\.py):\d+:', text))


@pytest.mark.parametrize('operation', ['fast_search', 'regex_search', 'frecency_search'])
async def test_dirty_scan_preserves_binary_exclusion(tmp_path, monkeypatch, record_property, operation):
    active = tmp_path / 'active.py'
    active.write_text('def probe():\n    return "scopefreshneedle"\n')
    (tmp_path / 'binary_decoy.py').write_bytes(b'\x00' * 64 + b'scopefreshneedle\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await gateway.execute('symbols', {'path': 'active.py'})
        assert paths(await search(gateway, 'fast_search', 'scopefreshneedle')) == {'active.py'}
        assert next(iter(gateway._stores.values()))['trigrams'].is_ready()
        active.write_text('def probe():\n    return "scopefreshneedle edited"\n')
        if operation == 'fast_search':
            def failed_build(*args, **kwargs):
                raise OSError('controlled optional cache build failure')

            monkeypatch.setattr(TrigramIndex, 'build', failed_build)
        text = await search(gateway, operation, 'scopefreshneedle')
        record_property('qualified_input', 'true')
        record_property('raw_response', text)
        assert paths(text) == {'active.py'}, MARKER
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())


async def test_dirty_frecency_preserves_ready_snapshot_ignore_scope(tmp_path, record_property):
    active = tmp_path / 'active.py'
    active.write_text('scopefreshneedle\n')
    (tmp_path / '.gitignore').write_text('ignored_area/\n')
    decoy = tmp_path / 'ignored_area' / 'indexed.py'
    decoy.parent.mkdir()
    decoy.write_text('scopefreshneedle\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    expected = {'active.py', 'ignored_area/indexed.py'}
    try:
        await gateway.execute('symbols', {'path': 'active.py'})
        assert paths(await search(gateway, 'fast_search', 'scopefreshneedle')) == expected
        active.write_text('scopefreshneedle edited\n')
        text = await search(gateway, 'frecency_search', 'scopefreshneedle')
        record_property('qualified_input', 'true')
        record_property('raw_response', text)
        assert paths(text) == expected, MARKER
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())


async def test_never_indexed_regex_retains_its_existing_scope(tmp_path, record_property):
    active = tmp_path / 'active.py'
    active.write_text('def probe(): return 1\n')
    decoy = tmp_path / '.private' / 'decoy.py'
    decoy.parent.mkdir()
    decoy.write_text('neverindexedneedle\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await gateway.execute('symbols', {'path': 'active.py'})
        assert paths(await search(gateway, 'regex_search', 'neverindexedneedle')) == {'.private/decoy.py'}
        assert not (tmp_path / '.attocode' / 'index' / 'trigrams.lookup').exists()
        active.write_text('def probe(): return 2\n')
        text = await search(gateway, 'regex_search', 'neverindexedneedle')
        record_property('qualified_input', 'true')
        record_property('raw_response', text)
        assert paths(text) == {'.private/decoy.py'}, MARKER
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())
