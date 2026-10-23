"""Missing AST summaries may reuse navigation only with complete matching proof."""
import json
from dataclasses import asdict
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service, ast_snapshot, index_repair
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import SNAPSHOT_KEY


def close(service):
    service.stop_hydration()
    service._store.close()


def seed(root):
    (root / 'target.py').write_text('def target():\n    return 1\n\ndef caller():\n    return target()\n')
    service = ASTService(str(root))
    assert service.initialize_skeleton(indexing_depth='eager').phase == 'ready'
    return service


def evidence(service):
    return json.dumps({'asts': {p: asdict(a) for p, a in service._ast_cache.items()},
                       'definitions': {p: [asdict(d) for d in ds] for p, ds in service._index.definitions.items()},
                       'references': {p: [asdict(r) for r in rs] for p, rs in service._index.references.items()},
                       'counts': service._store.stats()}, sort_keys=True)


def test_identical_reparse_reuses_navigation_without_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 10)
    first = seed(tmp_path)
    expected = evidence(first)
    close(first)
    for _ in range(2):
        second = ASTService(str(tmp_path))
        try:
            with patch.object(index_repair, 'repair_index', wraps=index_repair.repair_index) as repair:
                assert second.initialize_skeleton(indexing_depth='eager').phase == 'ready'
            assert repair.call_count == 0, 'identical healthy reparse unnecessarily repaired navigation'
            assert evidence(second) == expected
        finally:
            close(second)


@pytest.mark.parametrize('damage', ['missing', 'malformed', 'mismatch', 'grammar', 'capped'])
def test_unverified_fingerprints_conservatively_repair(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 10)
    if damage == 'capped':
        monkeypatch.setattr(ast_snapshot, 'MAX_FINGERPRINT_BYTES', 1)
    first = seed(tmp_path)
    expected = evidence(first)
    raw = json.loads(first._store.get_meta(SNAPSHOT_KEY))
    if damage == 'missing':
        raw.pop('structures', None)
    elif damage == 'malformed':
        raw['structures'] = []
    elif damage == 'mismatch':
        raw['structures'] = {'target.py': '0' * 64}
    first._store.set_meta(SNAPSHOT_KEY, json.dumps(raw))
    close(first)
    if damage == 'grammar':
        monkeypatch.setattr(ast_snapshot, 'parser_identity', lambda _: 'new-direct-grammar-identity')
    second = ASTService(str(tmp_path))
    try:
        with patch.object(index_repair, 'repair_index', wraps=index_repair.repair_index) as repair:
            assert second.initialize_skeleton(indexing_depth='eager').phase == 'ready'
        assert repair.call_count == 1
        assert evidence(second) == expected
    finally:
        close(second)


def test_changed_extraction_with_unchanged_source_still_repairs(tmp_path, monkeypatch):
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 10)
    first = seed(tmp_path)
    close(first)
    original = ast_service.parse_file

    def changed(path, *args, **kwargs):
        ast = original(path, *args, **kwargs)
        ast.functions[0].name = 'newly_extracted'
        ast.functions[0].qualified_name = 'newly_extracted'
        return ast

    second = ASTService(str(tmp_path))
    try:
        with (patch.object(ast_service, 'parse_file', side_effect=changed),
              patch.object(index_repair, 'repair_index', wraps=index_repair.repair_index) as repair):
            assert second.initialize_skeleton(indexing_depth='eager').phase == 'ready'
        assert repair.call_count == 1
        assert second._index.get_definitions('newly_extracted')
        assert not second._index.get_definitions('target')
    finally:
        close(second)


def test_offline_edit_repairs_instead_of_reusing_old_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 10)
    first = seed(tmp_path)
    close(first)
    (tmp_path / 'target.py').write_text('def renamed():\n    return 2\n\ndef caller():\n    return renamed()\n')
    second = ASTService(str(tmp_path))
    try:
        with patch.object(index_repair, 'repair_index', wraps=index_repair.repair_index) as repair:
            assert second.initialize_skeleton(indexing_depth='eager').phase == 'ready'
        assert repair.call_count == 1
        assert second._index.get_definitions('renamed')
        assert not second._index.get_definitions('target')
        assert any(r.line == 5 for r in second._index.get_references('renamed'))
    finally:
        close(second)


@pytest.mark.parametrize('health', ['healthy', 'failed', 'minimal', 'no_source', 'no_grammar'])
def test_only_complete_healthy_direct_extraction_earns_a_fingerprint(monkeypatch, health):
    from attocode_intel._internal.integrations.context.codebase_ast import FileAST
    from attocode_intel._internal.integrations.context.parse_diagnostics import ParseFailure

    ast = FileAST(path='target.py', language='python', parsing_tier='tree_sitter',
                  content_sha256='a' * 64, top_level_vars=['first'])
    monkeypatch.setattr(ast_snapshot, 'parser_identity', lambda _: None if health == 'no_grammar' else 'direct-installed')
    if health == 'failed':
        ast.parse_failures = [ParseFailure('ValueError', 100000, 100000)]
    elif health == 'minimal':
        ast.parsing_tier = 'minimal'
    elif health == 'no_source':
        ast.content_sha256 = ''
    before = ast_snapshot.structural_fingerprints({'target.py': ast})
    if health == 'healthy':
        assert len(before['target.py']) == 64
        ast.top_level_vars.append('second')
        assert ast_snapshot.structural_fingerprints({'target.py': ast}) != before
    else:
        assert before == {}
