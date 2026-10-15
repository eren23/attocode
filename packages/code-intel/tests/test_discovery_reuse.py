"""Discovery handoff cannot omit changed/new sources or alter cap/ranking policy."""
import os
from dataclasses import asdict, replace
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import codebase_context as context
from attocode_intel._internal.integrations.context import discovery_snapshot as snapshots
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.service import CodeIntelService


def fixture(root):
    root.mkdir(exist_ok=True)
    (root / 'src').mkdir()
    (root / 'src/helper.py').write_text('def meaningfulHTTPValue():\n    return "needle"\n')
    (root / 'README.md').write_text('needle helper')
    (root / 'build').mkdir()
    (root / 'build/keep.py').write_text('def allowed_build(): return 2\n')
    (root / '.gitignore').write_text('!build/\n')
    donor = context.CodebaseContextManager(str(root), max_files=100000)
    donor.discover_files()
    assert donor._discovery_snapshot
    return donor


def rows(manager):
    conn = manager._open_body_db()
    try:
        return {table: conn.execute(f'SELECT rowid,* FROM {table} ORDER BY rowid').fetchall()
                for table in ('kw_docs', 'kw_files', 'body_fts', 'body_file_fts', 'body_files')}
    finally:
        conn.close()


def test_immutable_inventory_preserves_file_order_scores_and_does_not_rediscover(tmp_path):
    donor = fixture(tmp_path)
    expected = [asdict(f) for f in donor._files]
    snap = donor._discovery_snapshot
    recipient = context.CodebaseContextManager(str(tmp_path))
    with patch.object(context.CodebaseContextManager, 'discover_files', side_effect=AssertionError('rediscovery')):
        assert recipient.reuse_discovery(snap)
        recipient._ensure_fresh()
    assert [asdict(f) for f in recipient._files] == expected
    assert recipient._last_refresh_time == snap.refreshed_at
    recipient._files[0].importance = -1
    donor._files[1].importance = -2
    assert snap.files[0][4] == expected[0]['importance']
    assert snap.files[1][4] == expected[1]['importance']


@pytest.mark.parametrize('change', ['add', 'delete', 'same_metadata_edit', 'ignore', 'new_directory', 'oversize'])
def test_changed_tree_refuses_snapshot_and_fresh_fallback_matches(tmp_path, change):
    donor = fixture(tmp_path)
    source = tmp_path / 'src/helper.py'
    if change == 'add':
        (tmp_path / 'src/new.py').write_text('def new_symbol(): return 1')
    elif change == 'delete':
        source.unlink()
    elif change == 'same_metadata_edit':
        st = source.stat()
        source.write_text(source.read_text().replace('needle', 'latest'))
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    elif change == 'ignore':
        (tmp_path / '.gitignore').write_text('src/\n')
    elif change == 'new_directory':
        (tmp_path / 'other').mkdir()
        (tmp_path / 'other/new.py').write_text('def added(): return 1')
    else:
        source.write_text('#' * 1_000_001)
    recipient = context.CodebaseContextManager(str(tmp_path))
    assert not recipient.reuse_discovery(donor._discovery_snapshot)
    recipient._ensure_fresh()
    reference = context.CodebaseContextManager(str(tmp_path))
    assert [asdict(f) for f in recipient._files] == [asdict(f) for f in reference.discover_files()]


def test_link_retarget_and_target_edit_never_reuse_outside_source(tmp_path):
    root = tmp_path / 'project'
    donor = fixture(root)
    alias = root / 'alias.py'
    alias.symlink_to(root / 'src/helper.py')
    donor.discover_files()
    assert context.CodebaseContextManager(str(root)).reuse_discovery(donor._discovery_snapshot)
    outside = tmp_path / 'outside.py'
    outside.write_text('def secret_outside(): return 1')
    alias.unlink()
    alias.symlink_to(outside)
    recipient = context.CodebaseContextManager(str(root))
    assert not recipient.reuse_discovery(donor._discovery_snapshot)
    assert 'alias.py' not in {f.relative_path for f in recipient.discover_files()}
    alias.unlink()
    alias.symlink_to(root / 'src/helper.py')
    donor.discover_files()
    (root / 'src/helper.py').write_text('def changed_target(): return 1')
    assert not context.CodebaseContextManager(str(root)).reuse_discovery(donor._discovery_snapshot)


def test_stale_wrong_root_policy_and_cancelled_snapshots_refused(tmp_path):
    donor = fixture(tmp_path)
    snap = donor._discovery_snapshot
    recipient = context.CodebaseContextManager(str(tmp_path))
    assert not recipient.reuse_discovery(replace(snap, refreshed_at=snap.refreshed_at-301))
    assert not recipient.reuse_discovery(replace(snap, root=str(tmp_path/'other')))
    assert not recipient.reuse_discovery(replace(snap, ignores=frozenset({'different'})))
    recipient.cancelled = lambda: True
    with pytest.raises(InterruptedError):
        recipient.reuse_discovery(snap)
    assert not recipient._files
    donor.mark_file_dirty('src/helper.py')
    assert donor._discovery_snapshot is None


def test_consumer_cap_is_applied_to_complete_donor_and_truncated_donor_not_published(tmp_path):
    # Pure inventory cap control, without creating thousands of disk files.
    donor = fixture(tmp_path)
    files = tuple((str(tmp_path/f'f{i}.py'), f'f{i}.py', 10, 'python', 1-i/10000,
                   False, False, 1) for i in range(1001))
    files += tuple((str(tmp_path/f'd{i}.md'), f'd{i}.md', 10, '', .1, False, False, 1)
                   for i in range(1200))
    snap = replace(donor._discovery_snapshot, files=files)
    recipient = context.CodebaseContextManager(str(tmp_path))
    assert recipient.reuse_discovery(snap)
    assert len(recipient._files) == 2000 and recipient.discovery_truncated
    assert recipient.discovered_file_count == 2201
    with patch.object(context, '_compute_dynamic_cap', return_value=1):
        donor.discover_files()
    assert donor.discovery_truncated and donor._discovery_snapshot is None


def test_edit_during_enumeration_prevents_publication(tmp_path, monkeypatch):
    fixture(tmp_path)
    original = os.walk
    def edited(*args, **kwargs):
        for row in original(*args, **kwargs):
            if row[0] == str(tmp_path/'src'):
                (tmp_path/'src/during.py').write_text('def during(): return 1')
            yield row
    monkeypatch.setattr(context.os, 'walk', edited)
    donor = context.CodebaseContextManager(str(tmp_path))
    donor.discover_files()
    assert donor._discovery_snapshot is None


def test_permission_error_in_validation_falls_back(tmp_path, monkeypatch):
    donor = fixture(tmp_path)
    def denied(_):
        raise PermissionError('injected')
    monkeypatch.setattr(snapshots, 'path_signature', denied)
    assert not context.CodebaseContextManager(str(tmp_path)).reuse_discovery(donor._discovery_snapshot)


def test_service_uses_existing_discovery_without_initializing_ast(tmp_path):
    fixture(tmp_path)
    service = CodeIntelService(str(tmp_path))
    manager = service._get_semantic_search()
    try:
        assert manager.discovery_snapshot() is None and service._ast_service is None
        ast = service._get_ast_service()
        assert manager.discovery_snapshot() is ast._context_mgr._discovery_snapshot
        # Baseline normal search rows, then rebuild from the same source metadata.
        with patch.object(context.CodebaseContextManager, 'discover_files', side_effect=AssertionError('redundant discovery')):
            manager._warm_candidate_indexes()
        assert manager._body_index_built and manager._kw_index_built
        expected = rows(manager)
        docs = [asdict(d) for d in manager._kw_docs]
        scores = manager._keyword_search('meaningful needle', 24, '')
        reference = SemanticSearchManager(str(tmp_path))
        reference._kw_cache_db_path = manager._kw_cache_db_path + ".reference"
        try:
            reference._warm_candidate_indexes()
            assert rows(reference) == expected
            assert [asdict(d) for d in reference._kw_docs] == docs
            assert reference._keyword_search('meaningful needle', 24, '') == scores
        finally:
            reference.close()
    finally:
        manager.close()
        if service._ast_service is not None:
            service._ast_service._hydration_stop.set()
            if service._ast_service._hydration_thread:
                service._ast_service._hydration_thread.join(5)
            service._ast_service._store.close()


def test_lexical_handoff_fallback_and_cancel_do_not_publish_false_readiness(tmp_path):
    donor = fixture(tmp_path)
    manager = SemanticSearchManager(str(tmp_path), discovery_snapshot=lambda: donor._discovery_snapshot)
    try:
        manager._closed = True
        manager._warm_candidate_indexes()
        assert not manager._body_index_built and not manager._kw_index_built
    finally:
        manager.close()


def test_oversize_file_becoming_eligible_invalidates_snapshot(tmp_path):
    donor = fixture(tmp_path)
    source = tmp_path / 'big.py'
    source.write_text('#' * 1_000_001)
    donor.discover_files()
    assert 'big.py' not in {f.relative_path for f in donor._files}
    snap = donor._discovery_snapshot
    source.write_text('def now_eligible(): return 1')
    recipient = context.CodebaseContextManager(str(tmp_path))
    assert not recipient.reuse_discovery(snap)
    assert 'big.py' in {f.relative_path for f in recipient.discover_files()}


def test_snapshot_guard_budget_does_not_truncate_normal_discovery(tmp_path, monkeypatch):
    donor = fixture(tmp_path)
    expected = [asdict(f) for f in donor._files]
    monkeypatch.setattr(snapshots, 'MAX_GUARDS', 2)
    assert [asdict(f) for f in donor.discover_files()] == expected
    assert donor._discovery_snapshot is None


def test_freshness_validation_does_not_read_source_contents(tmp_path, monkeypatch):
    donor = fixture(tmp_path)
    recipient = context.CodebaseContextManager(str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError('source content read')
    monkeypatch.setattr('builtins.open', forbidden)
    assert recipient.reuse_discovery(donor._discovery_snapshot)


def test_provider_failure_uses_fresh_discovery(tmp_path):
    fixture(tmp_path)
    def unavailable():
        raise RuntimeError('injected handoff failure')
    manager = SemanticSearchManager(str(tmp_path), discovery_snapshot=unavailable)
    try:
        manager._warm_candidate_indexes()
        assert manager._kw_index_built and manager._body_index_built
        assert any(d.name == 'meaningfulHTTPValue' for d in manager._kw_docs)
    finally:
        manager.close()
