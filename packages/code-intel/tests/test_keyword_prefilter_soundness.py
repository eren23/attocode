"""File-path metadata must survive an unrelated raw-content trigram index."""
from contextlib import asynccontextmanager
import hashlib
import json

import pytest

from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.gateway import OperationGateway

MARKER = 'REGRESSION:file metadata eliminated by content-only prefilter'
SOURCE = '[project]\nname = "fixture"\n'


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    monkeypatch.setenv('ATTOCODE_INTEL_RANKING_PROVIDER', 'off')
    monkeypatch.setenv('ATTOCODE_NL_EMBEDDING_MODE', 'none')


def fixture_files(root, target='manifestneedle.toml'):
    path = root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE)
    (root / 'source.py').write_text(
        'def worker():\n    """unaffectedneedle"""\n    return "opaqueother"\n'
        '\nclass UPPERCASEONLY:\n    pass\n'
    )
    (root / 'io.toml').write_text('[project]\nname = "shortfixture"\n')
    return path


@asynccontextmanager
async def owned_gateway(root, record_property):
    gateway = OperationGateway(str(root), 'full', watch=False)
    try:
        yield gateway
    finally:
        await gateway.close()
        record_property('owned_gateway_closed', str(gateway._closed).lower())


async def search(gateway, query, *, mode='auto', compact=False, file_filter=''):
    response = await gateway.execute('semantic_search', {
        'query': query, 'top_k': 5, 'file_filter': file_filter, 'mode': mode, 'max_tokens': 2000,
    }, compact=compact)
    assert not response.isError
    structured = json.loads(response.content[0].text) if compact else response.structuredContent
    assert not structured['metadata']['truncated']
    assert structured['data']['ranking']['index']['status'] == 'ready'
    return structured['data']['results']


def contains_source(rows, target):
    return any(row['file_path'] == target and '[project]' in row['snippet']
               and 'fixture' in row['snippet'] for row in rows)


def manager(gateway):
    return next(iter(gateway._stores.values()))['service']._get_semantic_search()


async def real_trigrams(gateway):
    result = await gateway.execute('fast_search', {'pattern': 'fixture', 'max_tokens': 2000})
    assert not result.isError
    index = next(iter(gateway._stores.values()))['trigrams']
    assert index.is_ready()
    assert manager(gateway)._get_trigram_index().is_ready()


def qualified(record_property, path, before, after):
    record_property('fixture_sha256', hashlib.sha256(path.read_bytes()).hexdigest())
    record_property('before', json.dumps(before))
    record_property('after', json.dumps(after))
    record_property('qualified_input', 'true')


def metadata_and_raw_exclusion(gateway, token, target):
    mgr = manager(gateway)
    docs = [doc for doc in mgr._kw_docs if doc.chunk_type == 'file' and doc.file_path == target]
    assert len(docs) == 1 and docs[0].term_freqs.get(token, 0) > 0
    assert mgr._get_trigram_index().is_ready()
    raw = mgr._trigram_prefilter([token])
    assert raw is not None and target not in raw


@pytest.mark.parametrize('mode', ['auto', 'keyword'])
@pytest.mark.parametrize('compact', [False, True])
async def test_public_file_metadata_survives_ready_index(tmp_path, record_property, mode, compact):
    path = fixture_files(tmp_path)
    async with owned_gateway(tmp_path, record_property) as gateway:
        before = await search(gateway, 'manifestneedle', mode=mode, compact=compact)
        assert contains_source(before, path.name)
        await real_trigrams(gateway)
        candidates = manager(gateway)._trigram_prefilter(['manifestneedle'])
        assert candidates is not None and path.name not in candidates
        metadata_and_raw_exclusion(gateway, 'manifestneedle', path.name)
        excluded = await search(gateway, 'manifestneedle', mode=mode, compact=compact, file_filter='*.py')
        assert not any(row['file_path'] == path.name for row in excluded)
        after = await search(gateway, 'manifestneedle', mode=mode, compact=compact)
        qualified(record_property, path, before, after)
        assert contains_source(after, path.name), MARKER


async def test_directory_path_token_survives_ready_index(tmp_path, record_property):
    path = fixture_files(tmp_path, 'manifestzone/settings.toml')
    async with owned_gateway(tmp_path, record_property) as gateway:
        before = await search(gateway, 'manifestzone', file_filter='manifestzone/*.toml')
        assert contains_source(before, 'manifestzone/settings.toml')
        await real_trigrams(gateway)
        metadata_and_raw_exclusion(gateway, 'manifestzone', 'manifestzone/settings.toml')
        after = await search(gateway, 'manifestzone', file_filter='manifestzone/*.toml')
        qualified(record_property, path, before, after)
        assert contains_source(after, 'manifestzone/settings.toml'), MARKER


async def test_path_metadata_is_rebuilt_from_warm_cache(tmp_path, record_property, monkeypatch):
    path = fixture_files(tmp_path)
    async with owned_gateway(tmp_path, record_property) as gateway:
        before = await search(gateway, 'manifestneedle')
        assert contains_source(before, path.name)
        await real_trigrams(gateway)
        cache_path = manager(gateway)._kw_cache_db_path
    assert (tmp_path / '.attocode/index/kw_index.db').is_file()
    async with owned_gateway(tmp_path, record_property) as reopened:
        loaded = []
        original_load = SemanticSearchManager._load_kw_cache

        def witness_load(instance, *args, **kwargs):
            cached = original_load(instance, *args, **kwargs)
            stores = next(iter(reopened._stores.values()), {})
            owned = stores.get('service')
            if owned is not None and owned._semantic_search is instance and cached is not None:
                docs, stale = cached
                loaded.extend(doc for doc in docs if doc.file_path == path.name
                              and doc.chunk_type == 'file' and path.name not in stale)
            return cached

        with monkeypatch.context() as scope:
            scope.setattr(SemanticSearchManager, '_load_kw_cache', witness_load)
            after = await search(reopened, 'manifestneedle')
        assert manager(reopened)._kw_cache_db_path == cache_path
        assert loaded and any(doc is cached for doc in manager(reopened)._kw_docs for cached in loaded)
        metadata_and_raw_exclusion(reopened, 'manifestneedle', path.name)
        record_property('unchanged_cached_file_doc_reused', 'true')
        qualified(record_property, path, before, after)
        assert contains_source(after, path.name), MARKER


async def test_rename_and_delete_do_not_restore_stale_path(tmp_path, record_property):
    path = fixture_files(tmp_path)
    async with owned_gateway(tmp_path, record_property) as gateway:
        before = await search(gateway, 'manifestneedle')
        assert contains_source(before, path.name)
        await real_trigrams(gateway)
        new = path.with_name('renamedneedle.toml')
        path.rename(new)
        mgr = manager(gateway)
        mgr.invalidate_file(str(path))
        mgr.warm()
        assert mgr.wait_for_body_index(20)
        after = await search(gateway, 'renamedneedle')
        assert all(row['file_path'] != path.name for row in after)
        assert not any(doc.file_path == path.name for doc in mgr._kw_docs)
        metadata_and_raw_exclusion(gateway, 'renamedneedle', new.name)
        qualified(record_property, new, before, after)
        assert contains_source(after, new.name), MARKER
        new.unlink()
        mgr.invalidate_file(str(new))
        mgr.warm()
        assert mgr.wait_for_body_index(20)
        deleted = await search(gateway, 'renamedneedle')
        assert all(row['file_path'] not in {path.name, new.name} for row in deleted)


@pytest.mark.parametrize('query, excluded', [
    ('manifestneedle opaqueother', 'manifestneedle.toml'),
    ('io opaqueother', 'io.toml'),
    ('uppercaseonly', 'manifestneedle.toml'),
])
async def test_path_admission_does_not_expand_other_query_forms(tmp_path, record_property, query, excluded):
    fixture_files(tmp_path)
    async with owned_gateway(tmp_path, record_property) as gateway:
        assert await search(gateway, 'unaffectedneedle')
        if query == 'uppercaseonly':
            unfiltered = manager(gateway)._keyword_search(query, 50, '')
            assert any(row.chunk_type == 'class' and row.name == 'UPPERCASEONLY' for row in unfiltered)
        await real_trigrams(gateway)
        if query == 'uppercaseonly':
            raw = manager(gateway)._trigram_prefilter([query])
            assert raw is not None and 'source.py' not in raw
            assert manager(gateway)._keyword_search(query, 50, '') == []
        rows = await search(gateway, query)
        assert rows and any(row['file_path'] == 'source.py' for row in rows)
        assert all(row['file_path'] != excluded for row in rows)


async def test_none_prefilter_retains_existing_full_scan(tmp_path, record_property, monkeypatch):
    path = fixture_files(tmp_path)
    async with owned_gateway(tmp_path, record_property) as gateway:
        before = await search(gateway, 'manifestneedle')
        assert contains_source(before, path.name)
        await real_trigrams(gateway)
        monkeypatch.setattr(type(manager(gateway)), '_trigram_prefilter', lambda self, terms: None)
        after = await search(gateway, 'manifestneedle')
        assert contains_source(after, path.name)


def test_cache_builder_stops_path_metadata_after_close(tmp_path, monkeypatch, record_property):
    from types import SimpleNamespace

    from attocode_intel._internal.integrations.context import semantic_search as module

    names = ['firstmanifest.toml', 'secondmanifest.toml']
    for name in names:
        (tmp_path / name).write_text(SOURCE)
    context = SimpleNamespace(
        _ensure_fresh=lambda: None,
        _files=[SimpleNamespace(path=str(tmp_path / name), relative_path=name,
                                is_test=False, importance=0.5) for name in names],
    )
    warm = SemanticSearchManager(str(tmp_path))
    try:
        warm._build_keyword_index(context)
        assert warm._kw_index_built
    finally:
        warm.close()
    mgr = SemanticSearchManager(str(tmp_path))
    original_load = SemanticSearchManager._load_kw_cache
    original_tokenize = module._tokenize
    tokenized = []
    loaded = []

    def load(self, current_files):
        result = original_load(self, current_files)
        if self is mgr:
            assert result is not None and not result[1]
            assert {doc.file_path for doc in result[0] if doc.chunk_type == 'file'} == set(names)
            assert sum(doc.chunk_type == 'file' for doc in result[0]) == 2
            loaded.extend(doc for doc in result[0] if doc.chunk_type == 'file')
        return result

    def tokenize(text):
        if text in names:
            tokenized.append(text)
            if len(tokenized) == 1:
                mgr.close()
                assert mgr._closed
        return original_tokenize(text)

    monkeypatch.setattr(SemanticSearchManager, '_load_kw_cache', load)
    monkeypatch.setattr(module, '_tokenize', tokenize)
    try:
        assert not mgr._kw_docs and not mgr._kw_path_terms and not mgr._kw_index_built
        mgr._build_keyword_index(context)
        assert loaded and mgr._closed
        record_property('cache_input_qualified', 'true')
        record_property('path_tokenizations_after_close', str(len(tokenized) - 1))
        assert tokenized == [loaded[0].file_path], 'REGRESSION:path metadata construction continues after close'
        assert not mgr._kw_docs and not mgr._kw_path_terms and not mgr._kw_index_built
    finally:
        mgr.close()
        record_property('owned_manager_closed', str(mgr._closed).lower())
