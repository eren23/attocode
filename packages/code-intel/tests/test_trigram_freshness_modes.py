"""A current snapshot must choose genuine no-trigram and threshold modes."""
import os
import re

import pytest
from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex
from attocode_intel.gateway import OperationGateway

MARKER = 'REGRESSION:dirty trigram changed full-scan mode or regular-file eligibility'


@pytest.mark.parametrize('operation', ['fast_search', 'regex_search', 'threshold-regex'])
async def test_live_change_preserves_genuine_full_scan_mode(tmp_path, monkeypatch, record_property, operation):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    monkeypatch.setenv('ATTOCODE_NL_EMBEDDING_MODE', 'none')
    active = tmp_path / 'active.py'
    active.write_text('def probe(): return 1\n')
    pattern = 'xy'
    if operation == 'threshold-regex':
        operation, pattern = 'regex_search', 'thresholdneedle'
        for i in range(100):
            (tmp_path / f'filler{i:03}.py').write_text('thresholdneedle\n')
    hidden = tmp_path / '.private' / 'decoy.py'
    hidden.parent.mkdir()
    hidden.write_text(pattern + '\n')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await gateway.execute('symbols', {'path': 'active.py'})
        ready = await gateway.execute('fast_search', {'pattern': 'probe'})
        assert not ready.isError and next(iter(gateway._stores.values()))['trigrams'].is_ready()
        before = await gateway.execute(operation, {'pattern': pattern, 'max_results': 200})
        assert not before.isError and re.search(r'(?m)^\.private/decoy\.py:\d+:', before.content[0].text)
        active.write_text('def probe(): return 2\n')
        after = await gateway.execute(operation, {'pattern': pattern, 'max_results': 200})
        assert not after.isError
        record_property('qualified_input', 'true')
        record_property('before', before.content[0].text)
        record_property('after', after.content[0].text)
        assert re.search(r'(?m)^\.private/decoy\.py:\d+:', after.content[0].text), MARKER
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())


def test_trigram_enumeration_excludes_non_regular_entries(tmp_path, record_property):
    pipe = tmp_path / 'pipe'
    os.mkfifo(pipe)
    try:
        record_property('qualified_input', 'true')
        assert 'pipe' not in TrigramIndex._enumerate_files(tmp_path), MARKER
    finally:
        pipe.unlink()
        record_property('owned_gateway_closed', str(not pipe.exists()).lower())
