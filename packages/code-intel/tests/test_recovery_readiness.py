"""A completed snapshot fallback must publish its reconstructed readiness."""

import json
import sqlite3
from contextlib import nullcontext
from dataclasses import asdict
from unittest.mock import patch

import pytest
from attocode_intel._internal.integrations.context import ast_service
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import SNAPSHOT_KEY, IndexStore
from attocode_intel.service import CodeIntelService

from eval.quality.readiness import coverage_ready


def close(service):
    service.stop_hydration()
    service._store.close()


def seed(root):
    (root / 'helper.py').write_text('def helper():\n    return 1\n')
    (root / 'caller.py').write_text('from helper import helper\ndef caller():\n    return helper()\n')
    (root / 'empty.py').write_text('# intentionally no definitions\n')
    service = ASTService(str(root))
    assert service.initialize_skeleton().phase == 'ready'
    return service


def navigation(service):
    index = service._index
    return {
        'asts': {p: asdict(ast) for p, ast in service._ast_cache.items()},
        'definitions': {p: [asdict(v) for v in values] for p, values in index.definitions.items()},
        'references': {p: [asdict(v) for v in values] for p, values in index.references.items()},
        'dependencies': index.file_dependencies,
        'calls': index.call_edges,
        'callers': index.callers_of,
        'stats': service._store.stats(),
    }


@pytest.mark.parametrize('fault', ['sqlite', 'malformed', 'shape'])
def test_recovered_snapshot_publishes_ready(tmp_path, fault):
    first = seed(tmp_path)
    expected = navigation(first)
    if fault != 'sqlite':
        first._store.set_meta(SNAPSHOT_KEY, '{bad json' if fault == 'malformed' else 'null')
    close(first)
    second = ASTService(str(tmp_path))
    failure = patch.object(IndexStore, 'load_symbols', side_effect=sqlite3.DatabaseError('read failed')) if fault == 'sqlite' else nullcontext()
    try:
        with failure, patch.object(second, '_index_references', wraps=second._index_references) as extracted:
            state = second.initialize_skeleton()
        assert extracted.call_count == state.total_files == state.parsed_files == state.reference_indexed_files == 3
        assert navigation(second) == expected
        assert json.loads(second._store.get_meta(SNAPSHOT_KEY))['parsed'] == sorted(expected['asts'])
        coverage = second.hydration_snapshot()
        assert coverage['parse_coverage'] == coverage['reference_coverage'] == 1.0
        assert state.phase == coverage['phase'] == 'ready', 'completed snapshot fallback still reports skeleton'
        assert coverage_ready(coverage)
    finally:
        close(second)
    third = ASTService(str(tmp_path))
    try:
        with patch.object(third, '_index_references', side_effect=AssertionError('reparsed healthy recovery')):
            assert third.initialize_skeleton().phase == 'ready'
        assert navigation(third) == expected
    finally:
        close(third)


@pytest.mark.parametrize('partial', ['budget', 'parse'])
def test_partial_snapshot_fallback_stays_skeleton(tmp_path, monkeypatch, partial):
    first = seed(tmp_path)
    close(first)
    if partial == 'budget':
        monkeypatch.setattr(ast_service, 'skeleton_budget', lambda *_: 1)
    second = ASTService(str(tmp_path))
    original = ast_service.parse_file

    def parse(path):
        if partial == 'parse' and str(path).endswith('/caller.py'):
            raise OSError('source read failed')
        return original(path)

    try:
        with (patch.object(IndexStore, 'load_symbols', side_effect=sqlite3.DatabaseError('read failed')),
              patch.object(ast_service, 'parse_file', parse)):
            state = second.initialize_skeleton()
        assert state.parsed_files < state.total_files
        assert state.phase == second.hydration_snapshot()['phase'] == 'skeleton'
        assert not coverage_ready(second.hydration_snapshot())
        assert not second._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(second)


def test_minimal_initialization_keeps_its_skeleton(tmp_path):
    first = seed(tmp_path)
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with patch.object(IndexStore, 'load_symbols', side_effect=AssertionError('minimal loaded snapshot')):
            state = second.initialize_skeleton(indexing_depth='minimal')
        assert state.phase == 'skeleton' and state.parsed_files == state.reference_indexed_files == 0
        assert not coverage_ready(second.hydration_snapshot())
    finally:
        close(second)


def test_empty_fallback_publishes_completed_empty_state(tmp_path):
    service = ASTService(str(tmp_path))
    service._store.set_meta(SNAPSHOT_KEY, 'null')
    try:
        state = service.initialize_skeleton()
        assert state.total_files == state.parsed_files == state.reference_indexed_files == 0
        assert state.phase == 'ready'
        assert service._store.get_meta(SNAPSHOT_KEY)
        assert not coverage_ready(service.hydration_snapshot())  # experiment barrier requires a nonempty fixture
    finally:
        close(service)


def test_interrupted_fallback_does_not_publish_ready(tmp_path):
    first = seed(tmp_path)
    close(first)
    second = ASTService(str(tmp_path))
    try:
        with (patch.object(IndexStore, 'load_symbols', side_effect=sqlite3.DatabaseError('read failed')),
              patch.object(IndexStore, 'save_files_batch', side_effect=OSError('write interrupted')),
              pytest.raises(OSError, match='write interrupted')):
            second.initialize_skeleton()
        assert second._hydration_state.phase == 'skeleton'
        assert not second.initialized and not second._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(second)


def test_service_uses_completed_recovery_without_background_hydration(tmp_path):
    first = seed(tmp_path)
    close(first)
    ast = ASTService(str(tmp_path))
    service = CodeIntelService(str(tmp_path))
    try:
        # Suppress the real background thread so it cannot hide the returned phase.
        with (patch.object(ASTService, 'get_instance', return_value=ast),
              patch.object(IndexStore, 'load_symbols', side_effect=sqlite3.DatabaseError('read failed')),
              patch.object(ASTService, 'start_hydration') as background):
            restored = service._get_ast_service()
        assert restored is ast and coverage_ready(restored.hydration_snapshot())
        assert background.call_count == 0
        assert ast._index.get_references('helper')
    finally:
        close(ast)
