"""Live source changes must never be excluded by a previously ready trigram snapshot."""
import asyncio
import hashlib
import json
import re
import subprocess
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex
from attocode_intel.freshness import FreshnessTracker
from attocode_intel.gateway import OperationGateway
from attocode_intel.request_context import RequestContext, bind_request
from attocode_intel.tools.search_tools import _get_trigram_index

MARKER = 'REGRESSION:live source excluded by stale trigram snapshot'
INITIAL = 'def initial_probe():\n    return "amberfreshneedle"\n'
EDITED = 'def edited_probe():\n    return "jadefreshneedle"\n'


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    monkeypatch.setenv('ATTOCODE_NL_EMBEDDING_MODE', 'none')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def project(root):
    (root / 'active.py').write_text(INITIAL)
    (root / 'control.py').write_text('def control_probe():\n    return "stablefreshneedle"\n')


async def call(gateway, name, **args):
    response = await gateway.execute(name, args)
    assert not response.isError, response
    return response


def match_paths(response):
    return set(re.findall(r'(?m)^([\w./-]+\.py):\d+:', response.content[0].text))


@pytest.mark.parametrize('operation', ['fast_search', 'regex_search'])
@pytest.mark.parametrize('mutation', ['edit', 'rename', 'add', 'branch-switch'])
async def test_public_content_search_after_live_change(tmp_path, record_property, operation, mutation):
    project(tmp_path)
    if mutation == 'branch-switch':
        git(tmp_path, 'init', '-b', 'audit-a')
        git(tmp_path, 'config', 'user.name', 'Freshness fixture')
        git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
        (tmp_path / '.gitignore').write_text('.attocode/\n')
        git(tmp_path, 'add', '.')
        git(tmp_path, 'commit', '-m', 'initial')
        git(tmp_path, 'switch', '-c', 'audit-b')
        (tmp_path / 'active.py').write_text(EDITED)
        git(tmp_path, 'add', '.')
        git(tmp_path, 'commit', '-m', 'edited')
        git(tmp_path, 'switch', 'audit-a')
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await call(gateway, 'symbols', path='active.py')
        baseline = await call(gateway, 'fast_search', pattern='amberfreshneedle')
        assert match_paths(baseline) == {'active.py'}
        original = next(iter(gateway._stores.values()))['trigrams']
        assert original.is_ready()
        expected, token = 'active.py', 'jadefreshneedle'
        if mutation == 'edit':
            (tmp_path / 'active.py').write_text(EDITED)
        elif mutation == 'rename':
            (tmp_path / 'active.py').rename(tmp_path / 'renamed.py')
            expected, token = 'renamed.py', 'amberfreshneedle'
        elif mutation == 'add':
            (tmp_path / 'added.py').write_text(EDITED)
            expected = 'added.py'
        else:
            git(tmp_path, 'switch', 'audit-b')
        result = await call(gateway, operation, pattern=token)
        record_property('fixture_sha256', hashlib.sha256((tmp_path / expected).read_bytes()).hexdigest())
        record_property('qualified_input', 'true')
        record_property('raw_response', result.content[0].text)
        assert match_paths(result) == {expected}, MARKER
        # Stable content and a newly ready index must both remain usable.
        control = await call(gateway, 'fast_search', pattern='stablefreshneedle')
        assert match_paths(control) == {'control.py'}
        rebuilt = next(iter(gateway._stores.values()))['trigrams']
        assert rebuilt.is_ready()
        again = await call(gateway, 'regex_search', pattern=token)
        assert match_paths(again) == {expected}
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())
    assert not original.is_ready()


async def test_semantic_prefilter_cannot_reload_old_snapshot_after_refresh(tmp_path, record_property):
    project(tmp_path)
    gateway = OperationGateway(str(tmp_path), 'full', watch=False)
    try:
        await call(gateway, 'symbols', path='active.py')
        await call(gateway, 'fast_search', pattern='amberfreshneedle')
        await call(gateway, 'semantic_search', query='amberfreshneedle', mode='keyword')
        service = next(iter(gateway._stores.values()))['service']
        manager = service._semantic_search
        context = RequestContext(str(tmp_path), str(tmp_path), stores=next(iter(gateway._stores.values())))
        worker = next(iter(gateway._workers.values()))

        def prefilter(token):
            with bind_request(context):
                return manager._trigram_prefilter([token])

        before = await asyncio.wrap_future(worker.submit(prefilter, 'amberfreshneedle'))
        assert before is not None and 'active.py' in before
        (tmp_path / 'active.py').write_text(EDITED)
        await call(gateway, 'symbols', path='active.py')
        # This lookup runs on the owning worker, under the actual request scope.
        candidates = await asyncio.wrap_future(worker.submit(prefilter, 'jadefreshneedle'))
        record_property('observed_candidates', json.dumps(sorted(candidates) if candidates is not None else None))
        record_property('qualified_input', 'true')
        assert candidates is None or 'active.py' in candidates, MARKER
        result = await call(gateway, 'regex_search', pattern='jadefreshneedle')
        assert match_paths(result) == {'active.py'}
        await call(gateway, 'fast_search', pattern='jadefreshneedle')
        candidates = await asyncio.wrap_future(worker.submit(prefilter, 'jadefreshneedle'))
        assert candidates is not None and 'active.py' in candidates
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())


def test_source_change_invalidates_prefilter_before_ast_initialization(tmp_path, record_property):
    project(tmp_path)
    index = TrigramIndex(str(tmp_path / '.attocode' / 'index'))
    index.build(str(tmp_path))
    assert index.is_ready()
    tracker = FreshnessTracker(str(tmp_path))
    service = SimpleNamespace(_ast_service=None, _semantic_search=None)
    context = RequestContext(str(tmp_path), str(tmp_path))
    context.stores['trigrams'] = index
    try:
        with bind_request(context):
            tracker.refresh(service)
            (tmp_path / 'active.py').write_text(EDITED)
            tracker.refresh(service)
            loaded = _get_trigram_index()
            candidates = loaded.query('jadefreshneedle') if loaded is not None else None
            record_property('qualified_input', 'true')
            record_property('observed_candidates', json.dumps(candidates))
            assert candidates is None or 'active.py' in candidates, MARKER
    finally:
        index.close()
        record_property('owned_index_closed', str(not index.is_ready()).lower())
