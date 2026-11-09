"""Real notification routes preserve prior vectors and publish fresh source."""
import json
import threading
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context import embeddings
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.freshness import FreshnessTracker
from attocode_intel.service import CodeIntelService

ROUTES = ['direct', 'notify', 'notification-queue', 'watch', 'service', 'freshness']
OLD = 'def original():\n    return "oldquartz"\n'
NEW = 'def updated():\n    return "newlantern"\n'


class Provider:
    name = 'live-fixture'
    version = 'v1'

    def __init__(self):
        self.mode = 'good'
        self.calls = []

    def dimension(self):
        return 3

    def embed(self, texts):
        self.calls.append(list(texts))
        vectors = [[1.0, 0.0, 0.0] for _ in texts]
        if self.mode == 'raise':
            raise RuntimeError('controlled provider failure')
        if self.mode == 'empty':
            return [[] for _ in texts]
        if self.mode == 'short':
            return vectors[:-1]
        if self.mode == 'long':
            return vectors + [[0.0, 1.0, 0.0]]
        if self.mode == 'hole':
            return [[]] + vectors[1:]
        return vectors

    def embed_query(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def rows(value, name='target.py'):
    return value._store._get_conn().execute(
        'SELECT id,chunk_type,name,text,hex(vector),model_name,model_version,dimension,produced_at '
        'FROM vectors WHERE file_path=? ORDER BY id', (name,)).fetchall()


def current_lexical(value):
    value.search_candidates('updated', 10, 'target.py')
    assert value.wait_for_body_index(3), 'Lexical warmup did not finish'
    return value.search_candidates('updated', 10, 'target.py')


@contextmanager
def workspace(tmp_path, monkeypatch, *, vectors=True):
    (tmp_path / 'target.py').write_text(OLD)
    (tmp_path / 'untouched.py').write_text('def untouched():\n    return 42\n')
    provider = Provider()
    factories = []
    def create(*args, **kwargs):
        factories.append(True)
        return provider
    monkeypatch.setattr(embeddings, 'create_embedding_provider', create)
    value = SemanticSearchManager(str(tmp_path), nl_mode='none')
    ast = ASTService(str(tmp_path))
    ast.initialize_skeleton(indexing_depth='eager')
    service = CodeIntelService(str(tmp_path))
    service._ast_service = ast
    service._semantic_search = value
    tracker = FreshnessTracker(str(tmp_path))
    tracker.manifest = tracker.scan_manifest()
    completed = threading.Event()
    attempts = []
    original = SemanticSearchManager.reindex_file
    def observe(self, path):
        try:
            return original(self, path)
        finally:
            if self is value:
                attempts.append(str(path))
                completed.set()
    monkeypatch.setattr(SemanticSearchManager, 'reindex_file', observe)
    state = SimpleNamespace(root=tmp_path, value=value, ast=ast, service=service,
                            tracker=tracker, provider=provider, factories=factories,
                            completed=completed, attempts=attempts)
    try:
        assert [d.name for d in ast.get_file_symbols('target.py')] == ['original']
        if vectors:
            assert value.index() == 4
            assert len(rows(value)) == 2 and len(rows(value, 'untouched.py')) == 2
            assert value._store.get_file_metadata('target.py')['chunk_count'] == 2
        yield state
    finally:
        value.close()
        ast.stop_hydration()
        ast._store.close()


def route_change(state, route, monkeypatch, name='target.py'):
    path = state.root / name
    if route == 'direct':
        state.ast.notify_file_changed(name)
        state.value.invalidate_file(str(path))
        state.value.queue_reindex(str(path))
    elif route == 'service':
        state.service.notify_file_changed([name])
    elif route == 'freshness':
        state.tracker.refresh(state.service)
    else:
        from attocode_intel import server
        from attocode_intel.tools import search_tools
        monkeypatch.setattr(server, '_get_project_dir', lambda: str(state.root))
        monkeypatch.setattr(server, '_get_ast_service', lambda: state.ast)
        monkeypatch.setattr(server, '_semantic_search', state.value)
        monkeypatch.setattr(search_tools, '_get_semantic_search', lambda: state.value)
        monkeypatch.setattr(search_tools, '_get_trigram_index', lambda: None)
        if route == 'notify':
            server.notify_file_changed([name])
        elif route == 'notification-queue':
            queue = state.root / '.attocode' / 'cache' / 'file_changes'
            queue.parent.mkdir(parents=True, exist_ok=True)
            queue.write_text(name + '\n')
            assert server._process_notification_queue() == 1
        else:
            import watchfiles
            monkeypatch.setattr(server, '_watcher_thread', None)
            monkeypatch.setattr(server, '_queue_thread', None)
            monkeypatch.setattr(server, '_watcher_stop', threading.Event())
            change = watchfiles.Change.modified if path.exists() else watchfiles.Change.deleted
            monkeypatch.setattr(watchfiles, 'watch', lambda *a, **kw: iter([{(change, str(path))}]))
            server._start_file_watcher(str(state.root))
            try:
                server._watcher_thread.join(3)
                assert not server._watcher_thread.is_alive()
            finally:
                server._stop_file_watcher()
    if state.value._reindex_thread is not None:
        assert state.completed.wait(3), 'Queue worker did not finish the notified file'
    expected = ['updated'] if path.exists() else []
    assert [d.name for d in state.ast.get_file_symbols(name)] == expected


@pytest.mark.parametrize('route', ROUTES)
def test_public_edit_preserves_prior_vectors_on_failure(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch) as s:
        before = rows(s.value)
        metadata = s.value._store.get_file_metadata('target.py')
        other = rows(s.value, 'untouched.py')
        s.provider.calls.clear()
        s.provider.mode = 'raise'
        (tmp_path / 'target.py').write_text(NEW)
        route_change(s, route, monkeypatch)
        after = rows(s.value)
        record_property('observed', json.dumps({'before': before, 'after': after,
                                               'metadata': metadata, 'attempts': s.attempts,
                                               'embed_calls': s.provider.calls}))
        assert rows(s.value, 'untouched.py') == other
        record_property('qualified_input', 'true')
        assert after == before, 'REGRESSION: live notification deleted prior vectors'
        assert s.value._store.get_file_metadata('target.py') == metadata
        assert any('updated' in t for batch in s.provider.calls for t in batch)
        hits = current_lexical(s.value)
        assert hits and all('oldquartz' not in h.text for h in hits)


@pytest.mark.parametrize('route', ROUTES)
def test_public_edit_reaches_workspace_file(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch) as s:
        s.provider.calls.clear()
        (tmp_path / 'target.py').write_text(NEW)
        route_change(s, route, monkeypatch)
        actual = rows(s.value)
        record_property('observed', json.dumps({'rows': actual, 'attempts': s.attempts,
                                               'embed_calls': s.provider.calls}))
        record_property('qualified_input', 'true')
        assert {r[0] for r in actual} == {'file:target.py', 'func:target.py:updated'}, 'REGRESSION: notification did not reindex workspace file'
        assert any('updated' in t for batch in s.provider.calls for t in batch)


@pytest.mark.parametrize('route', ROUTES)
def test_public_deletion_removes_vectors_and_metadata(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch) as s:
        other = rows(s.value, 'untouched.py')
        (tmp_path / 'target.py').unlink()
        route_change(s, route, monkeypatch)
        actual = rows(s.value)
        metadata = s.value._store.get_file_metadata('target.py')
        assert rows(s.value, 'untouched.py') == other
        record_property('observed', json.dumps({'rows': actual, 'metadata': metadata}))
        record_property('qualified_input', 'true')
        assert not actual and metadata is None, 'REGRESSION: deletion left vector file metadata'


@pytest.mark.parametrize('route', ROUTES)
def test_notifications_never_initialize_provider(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch, vectors=False) as s:
        (tmp_path / 'target.py').write_text(NEW)
        route_change(s, route, monkeypatch)
        assert not s.factories and s.value._provider is None and s.value._store is None
        assert current_lexical(s.value)
        assert not s.factories
        record_property('qualified_input', 'true')


def test_dirty_status_survives_reopening(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        before = rows(s.value)
        metadata = s.value._store.get_file_metadata('target.py')
        (tmp_path / 'target.py').write_text(NEW)
        s.value.invalidate_file(str(tmp_path / 'target.py'))
    reopened = SemanticSearchManager(str(tmp_path), nl_mode='none')
    try:
        reopened._ensure_provider()
        actual = rows(reopened)
        progress = reopened.get_index_progress()
        record_property('observed', json.dumps({'before': before, 'after': actual,
                                               'progress': asdict(progress)}))
        record_property('qualified_input', 'true')
        assert actual == before and progress.indexed_files == 1, 'REGRESSION: dirty vector state lost on reopen'
        assert reopened._store.get_file_metadata('target.py') == metadata
    finally:
        reopened.close()


def test_dirty_file_excluded_from_readiness(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        (tmp_path / 'target.py').write_text(NEW)
        s.value.invalidate_file(str(tmp_path / 'target.py'))
        progress = s.value.get_index_progress()
        record_property('observed', json.dumps(asdict(progress)))
        record_property('qualified_input', 'true')
        assert progress.indexed_files == 1 and progress.coverage == .5 and not s.value.is_index_ready(), 'REGRESSION: dirty file counted ready'


@pytest.mark.parametrize('two_stage', [False, True])
def test_dirty_vectors_do_not_hide_fresh_source(tmp_path, monkeypatch, record_property, two_stage):
    with workspace(tmp_path, monkeypatch) as s:
        (tmp_path / 'target.py').write_text(NEW)
        s.value.invalidate_file(str(tmp_path / 'target.py'))
        hits = s.value.search('updated', 10, 'target.py', two_stage=two_stage, expand_query=False)
        record_property('observed', json.dumps([asdict(h) for h in hits]))
        record_property('qualified_input', 'true')
        assert hits and any(h.name == 'updated' for h in hits) and all(h.name != 'original' for h in hits), 'REGRESSION: dirty vectors hid current lexical evidence'


def writer(s, mode):
    if mode == 'full':
        context = SimpleNamespace(_ensure_fresh=lambda: None, _files=[
            SimpleNamespace(relative_path='target.py', path=str(s.root / 'target.py'), language='python')])
        return s.value.index(context)
    if mode == 'file':
        return s.value.reindex_file(str(s.root / 'target.py'))
    return s.value._run_background_indexing(threading.Event())


@pytest.mark.parametrize('route', ['full', 'file', 'background'])
@pytest.mark.parametrize('response', ['raise', 'empty', 'short', 'long', 'hole'])
def test_rejected_response_keeps_complete_file(tmp_path, monkeypatch, record_property, response, route):
    with workspace(tmp_path, monkeypatch) as s:
        (tmp_path / 'target.py').write_text(NEW)
        s.value._store.set_file_metadata('target.py', 0.0, 2)
        before, metadata = rows(s.value), s.value._store.get_file_metadata('target.py')
        s.provider.calls.clear()
        s.provider.mode = response
        writer(s, route)
        after, changed_metadata = rows(s.value), s.value._store.get_file_metadata('target.py')
        assert any('updated' in t for batch in s.provider.calls for t in batch)
        record_property('observed', json.dumps({'before': before, 'after': after, 'metadata': metadata,
                                               'after_metadata': changed_metadata, 'embed_calls': s.provider.calls}))
        record_property('qualified_input', 'true')
        assert after == before and metadata == changed_metadata, 'REGRESSION: incomplete response replaced ordinary file'


@pytest.mark.parametrize('route', ['full', 'file', 'background'])
def test_success_replaces_orphaned_file_rows(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch) as s:
        (tmp_path / 'target.py').write_text(NEW)
        s.value._store.set_file_metadata('target.py', 0.0, 2)
        writer(s, route)
        actual = rows(s.value)
        record_property('observed', json.dumps(actual))
        record_property('qualified_input', 'true')
        assert {r[0] for r in actual} == {'file:target.py', 'func:target.py:updated'}, 'REGRESSION: full index retained removed ordinary symbols'
