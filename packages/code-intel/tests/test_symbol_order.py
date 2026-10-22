"""Bounded symbol search must not depend on index or process insertion order."""
import json
import os
import subprocess
import sys

import pytest
from attocode_intel._internal.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
)


def location(path, *, name='NewServer', line=1, end=2, kind='function', source='tree-sitter'):
    return SymbolLocation(name, name, kind, path, line, end, source)


@pytest.mark.parametrize('limit', [1, 5, 30, 50])
def test_equal_score_pages_ignore_definition_insertion_order(limit):
    locations = [location(f'src/{number:02}.go') for number in range(40)]
    pages = []
    for order in [locations, list(reversed(locations)), locations[17:] + locations[:17]]:
        index = CrossRefIndex()
        for loc in order:
            index.add_definition(loc)
        pages.append(index.search_definitions('NewServer', limit=limit))
    assert all(page == pages[0] for page in pages), 'equal-score page depends on insertion order'
    assert [loc.file_path for loc, _ in pages[0]] == [loc.file_path for loc in locations[:limit]]


def test_same_file_equal_score_locations_have_a_complete_tie_break():
    locations = [location('src/server.go', line=10, end=12, source='lsp'),
                 location('src/server.go', line=10, end=12),
                 location('src/server.go', line=10, end=11),
                 location('src/server.go', line=1, end=2)]
    pages = []
    for order in [locations, list(reversed(locations))]:
        index = CrossRefIndex()
        for loc in order:
            index.add_definition(loc)
        pages.append(index.search_definitions('NewServer'))
    assert pages[0] == pages[1], 'same-file equal-score page depends on insertion order'
    assert pages[0][0][0].source == 'lsp'
    assert pages[0][0][1] > pages[0][1][1]
    assert [(loc.start_line, loc.end_line) for loc, _ in pages[0][1:]] == [(1, 2), (10, 11), (10, 12)]


def test_match_quality_and_kind_filter_remain_primary():
    index = CrossRefIndex()
    index.add_definition(location('a.go', name='newFeatureServer'))
    index.add_definition(location('z.go'))
    index.add_definition(location('b.go', kind='class'))
    rows = index.search_definitions('NewServer', kind_filter='function')
    assert [loc.file_path for loc, _ in rows] == ['z.go', 'a.go']
    assert rows[0][1] > rows[1][1]
    assert all(loc.kind == 'function' for loc, _ in rows)


def test_symbol_pages_survive_fresh_process_restore_and_hash_seeds(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    for number in reversed(range(40)):
        (root / f'module_{number:02}.py').write_text(f'def new_feature_{number:02}_server():\n    return {number}\n')
    for number in range(7):
        (root / f'exact_{number}.py').write_text('def NewServer():\n    return 0\n')
    program = '''
import json, sys
from attocode_intel.service import CodeIntelService
from attocode_intel._internal.integrations.context.index_store import SNAPSHOT_KEY
service = CodeIntelService(sys.argv[1])
ast = service._get_ast_service(indexing_depth='eager')
try:
    assert ast.hydration_snapshot()['phase'] == 'ready'
    assert ast._store.get_meta(SNAPSHOT_KEY)
    print(json.dumps(service.search_symbols_data('NewServer', limit=30), sort_keys=True))
finally:
    ast.stop_hydration()
    ast._store.close()
'''
    pages = []
    for seed in ['1', '17', '91']:
        result = subprocess.run([sys.executable, '-c', program, str(root)],
                                env=dict(os.environ, PYTHONHASHSEED=seed),
                                capture_output=True, text=True, timeout=30, check=True)
        pages.append(json.loads(result.stdout))
    assert all(len(page) == 30 for page in pages)
    assert sum(row['name'] == 'NewServer' for row in pages[0]) == 7
    assert all(page == pages[0] for page in pages), 'symbol page changed across persisted restore/hash seeds'
