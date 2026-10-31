"""Explicit discovery budgets retain hard bounds and honest source coverage."""
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context import codebase_context as context
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager

ENV = 'ATTOCODE_INTEL_DISCOVERY_MAX_FILES'


@pytest.mark.parametrize(('setting', 'count', 'selected', 'truncated'), [
    (None, 50001, 50000, True),
    ('100000', 50001, 50001, False),
    ('100000', 100001, 100000, True),
], ids=['default-overflow', 'optin-past-old', 'optin-hard-overflow'])
def test_scan_budget_and_truncation_follow_selected_policy(tmp_path, monkeypatch, setting, count, selected, truncated):
    if setting is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, setting)
    names = [f'item_{i:06d}.notes' for i in range(count)]
    # A virtual metadata walk isolates enumeration without materializing100k files.
    monkeypatch.setattr(context.os, 'walk', lambda *a, **k: [(str(tmp_path), [], names)])
    monkeypatch.setattr(context.os.path, 'getsize', lambda path: 20)
    manager = context.CodebaseContextManager(str(tmp_path), max_files=100000)
    files = manager.discover_files()
    assert [f.relative_path for f in files] == names[:selected], 'discovery limit: wrong bounded inventory'
    assert manager.discovered_file_count == selected
    assert manager.discovery_truncated is truncated, 'discovery limit: overflow hidden or invented'


@pytest.mark.parametrize('setting', ['0', '-1', '100001', 'not-an-integer'],
                         ids=['zero', 'negative', 'above-hard', 'nonnumeric'])
def test_invalid_scan_budget_rejected_before_walk(tmp_path, monkeypatch, setting):
    monkeypatch.setenv(ENV, setting)
    walked = []
    monkeypatch.setattr(context.os, 'walk', lambda *a, **k: walked.append(True) or [])
    with pytest.raises(ValueError, match='discovery|DISCOVERY'):
        context.CodebaseContextManager(str(tmp_path)).discover_files()
    assert walked == []


@pytest.mark.parametrize('setting', [0, 100001, True], ids=['zero', 'above-hard', 'boolean'])
def test_explicit_scan_budget_cannot_exceed_hard_limit(tmp_path, setting):
    with pytest.raises(ValueError, match='discovery|DISCOVERY'):
        context.CodebaseContextManager(str(tmp_path), discovery_max_files=setting)


def test_mutated_scan_budget_cannot_bypass_hard_limit(tmp_path):
    manager = context.CodebaseContextManager(str(tmp_path))
    manager.discovery_max_files = 100001
    with pytest.raises(ValueError, match='discovery|DISCOVERY'):
        manager.discover_files()


@pytest.mark.parametrize('count', [4, 5], ids=['at-limit', 'over-limit'])
def test_exact_scan_limit_uses_eligible_lookahead(tmp_path, monkeypatch, count):
    monkeypatch.setenv(ENV, '4')
    for i in range(count):
        (tmp_path / f'item_{i}.notes').write_text('ordinary documentation\n')
    manager = context.CodebaseContextManager(str(tmp_path), max_files=100000)
    assert len(manager.discover_files()) == 4, 'discovery limit: descriptor budget exceeded'
    assert manager.discovery_truncated is (count > 4)


def test_excluded_files_after_limit_do_not_invent_overflow(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '4')
    root = tmp_path / 'project'
    root.mkdir()
    for i in range(4):
        (root / f'item_{i}.notes').write_text('ordinary documentation\n')
    (root / '.gitignore').write_text('zignored.notes\n')
    (root / 'zignored.notes').write_text('excluded\n')
    (root / 'zoversize.notes').write_bytes(b'x' * 1_000_001)
    outside = tmp_path / 'outside.notes'
    outside.write_text('outside\n')
    (root / 'zoutside.notes').symlink_to(outside)
    manager = context.CodebaseContextManager(str(root), max_files=100000)
    assert {f.relative_path for f in manager.discover_files()} == {f'item_{i}.notes' for i in range(4)}
    assert manager.discovery_truncated is False


def test_lower_budget_receiver_refuses_larger_complete_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '8')
    for i in range(5):
        (tmp_path / f'item_{i}.notes').write_text('ordinary documentation\n')
    donor = context.CodebaseContextManager(str(tmp_path), max_files=100000)
    donor.discover_files()
    assert donor._discovery_snapshot is not None and not donor.discovery_truncated
    monkeypatch.setenv(ENV, '4')
    receiver = context.CodebaseContextManager(str(tmp_path), max_files=100000)
    assert not receiver.reuse_discovery(donor._discovery_snapshot), 'discovery limit: donor bypassed recipient budget'
    assert receiver._files == []
    assert len(receiver.discover_files()) == 4 and receiver.discovery_truncated


def test_optin_search_reaches_document_beyond_fifty_thousand(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '100000')
    names = [f'item_{i:06d}.notes' for i in range(50001)]
    for name in names:
        (tmp_path / name).write_text('ordinary documentation\n')
    (tmp_path / names[-1]).write_text('higherceilingneedle\n')
    manager = SemanticSearchManager(str(tmp_path), max_files=100000)
    try:
        manager._warm_candidate_indexes()
        assert manager._keyword_search('higherceilingneedle', 5, names[-1]), 'discovery limit: configured late source omitted'
        conn = manager._open_body_db()
        try:
            assert {r[0] for r in conn.execute('SELECT file_path FROM kw_files')} == set(names)
            assert {r[0] for r in conn.execute('SELECT file_path FROM body_files')} == set(names)
        finally:
            conn.close()
        state = manager.candidate_diagnostics()
        assert state['status'] == 'ready' and state['discovery_discovered_files'] == 50001
        assert state['discovery_selected_files'] == 50001 and state['discovery_truncated'] is False
        assert Path(manager.root_dir).resolve() == tmp_path.resolve()
    finally:
        manager.close()
