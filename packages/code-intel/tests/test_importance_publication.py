"""Keyword readiness must include a complete importance snapshot."""
import threading
from types import SimpleNamespace

from attocode_intel._internal.integrations.context.codebase_context import CodebaseContextManager
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager


def seed(root):
    (root / 'worker.py').write_text('def compute_worker(value):\n    return value + 1\n')
    (root / 'caller.py').write_text('from worker import compute_worker\ncompute_worker(1)\n')


def test_query_during_cache_save_never_rediscovers_importance(tmp_path, monkeypatch):
    seed(tmp_path)
    paused, release = threading.Event(), threading.Event()
    original_save = SemanticSearchManager._save_kw_cache
    original_load = SemanticSearchManager._load_importance_scores
    loads = []
    def load(self, context_manager=None):
        loads.append(context_manager)
        assert context_manager is not None, 'foreground query started independent discovery'
        return original_load(self, context_manager)
    def save(self, *args):
        paused.set()
        assert release.wait(5), 'test did not release cache save'
        return original_save(self, *args)
    monkeypatch.setattr(SemanticSearchManager, '_load_importance_scores', load)
    monkeypatch.setattr(SemanticSearchManager, '_save_kw_cache', save)
    mgr = SemanticSearchManager(str(tmp_path))
    try:
        mgr.search_candidates('compute worker')
        assert paused.wait(5)
        assert mgr._kw_index_built
        # Reproduces the actual publication window, before warmup returns.
        rows = mgr.search_candidates('compute worker')
        assert rows and mgr._importance_scores and len(loads) == 1
        scores = mgr._keyword_search('compute worker', 24, '')
        release.set()
        assert mgr.wait_for_body_index(5)
        assert mgr._keyword_search('compute worker', 24, '') == scores
        assert len(loads) == 1
    finally:
        release.set()
        mgr.close()


def test_rebuild_replaces_scores_after_delete_and_rename(tmp_path):
    seed(tmp_path)
    mgr = SemanticSearchManager(str(tmp_path))
    try:
        mgr._warm_candidate_indexes()
        assert 'worker.py' in mgr._importance_scores
        (tmp_path / 'worker.py').rename(tmp_path / 'replacement.py')
        (tmp_path / 'caller.py').unlink()
        mgr.invalidate_file(str(tmp_path / 'worker.py'))
        mgr._warm_candidate_indexes()
        fresh = CodebaseContextManager(str(tmp_path))
        expected = {f.relative_path: f.importance for f in fresh.discover_files()}
        assert mgr._importance_scores == expected
        assert 'worker.py' not in mgr._importance_scores and 'caller.py' not in mgr._importance_scores
    finally:
        mgr.close()


def test_failed_importance_read_does_not_publish_partial_snapshot(tmp_path):
    mgr = SemanticSearchManager(str(tmp_path))
    before = {'old.py': .3}
    mgr._importance_scores = before
    def broken():
        yield SimpleNamespace(relative_path='new.py', importance=.9)
        raise OSError('interrupted inventory')
    mgr._load_importance_scores(SimpleNamespace(_ensure_fresh=lambda: None, _files=broken()))
    assert mgr._importance_scores == {'old.py': .3}
    assert mgr._importance_scores is before
    mgr.close()


def test_direct_builder_publishes_exact_context_importance(tmp_path):
    seed(tmp_path)
    ctx = CodebaseContextManager(str(tmp_path))
    ctx.discover_files()
    mgr = SemanticSearchManager(str(tmp_path))
    try:
        mgr._build_keyword_index(ctx)
        assert mgr._kw_index_built
        assert mgr._importance_scores == {f.relative_path: f.importance for f in ctx._files}
    finally:
        mgr.close()
