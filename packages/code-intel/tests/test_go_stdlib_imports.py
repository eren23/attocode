"""Declared Go std roots provide package dependencies without SDK guesses."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.module_resolution import FileIndex
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel.gateway import OperationGateway


@pytest.mark.parametrize('case', [
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go', 'math/b.go', 'math/a_test.go', 'math/sub/no.go', 'cmd/use.go'],
                  'module': 'math', 'source': 'cmd/use.go', 'expected': ['math/a.go', 'math/b.go']}, id='workspace-std-root'),
    pytest.param({'configs': {'src/go.mod': 'module std\ngo 1.23\n'}, 'paths': ['src/sync/atomic/type.go', 'src/sync/atomic/atomic_test.go'],
                  'module': 'sync/atomic', 'source': 'src/sync/atomic/atomic_test.go', 'expected': ['src/sync/atomic/type.go']}, id='real-layout'),
    pytest.param({'configs': {'library/go.mod': 'module std\n'}, 'paths': ['library/math/a.go', 'library/client/use.go'],
                  'module': 'math', 'source': 'library/client/use.go', 'expected': ['library/math/a.go']}, id='declared-root-not-folder-name'),
    pytest.param({'configs': {'one/go.mod': 'module std\n', 'two/go.mod': 'module std\n'},
                  'paths': ['one/math/a.go', 'two/math/b.go', 'one/client/use.go'],
                  'module': 'math', 'source': 'one/client/use.go', 'expected': ['one/math/a.go']}, id='separate-checkouts'),
    pytest.param({'configs': {'sdk/go.mod': 'module std\n', 'sdk/nested/go.mod': 'module std\n'},
                  'paths': ['sdk/math/a.go', 'sdk/nested/math/b.go', 'sdk/nested/client/use.go'],
                  'module': 'math', 'source': 'sdk/nested/client/use.go', 'expected': ['sdk/nested/math/b.go']}, id='nearest-root'),
    pytest.param({'configs': {'sdk/go.mod': 'module std\n', 'sdk/nested/go.mod': 'module std\n'},
                  'paths': ['sdk/math/a.go', 'sdk/nested/client/use.go'],
                  'module': 'math', 'source': 'sdk/nested/client/use.go', 'expected': []}, id='nearer-root-missing-package'),
    pytest.param({'configs': {'sdk/go.mod': 'module std\n'}, 'paths': ['sdk/math/a.go', 'app/use.go'],
                  'module': 'math', 'source': 'app/use.go', 'expected': []}, id='outside-std-root'),
    pytest.param({'configs': {'sdk/src/go.mod': 'module std\n'}, 'paths': ['sdk/src/math/a.go', 'sdk/src-other/use.go'],
                  'module': 'math', 'source': 'sdk/src-other/use.go', 'expected': []}, id='root-prefix-boundary'),
    pytest.param({'configs': {'sdk/go.mod': 'module std\n', 'app/go.mod': 'module example.org/app\n'},
                  'paths': ['sdk/pkg/no.go', 'app/pkg/yes.go', 'sdk/client/use.go'],
                  'module': 'example.org/app/pkg', 'source': 'sdk/client/use.go', 'expected': ['app/pkg/yes.go']}, id='ordinary-prefix-preserved'),
    pytest.param({'configs': {'src/go.mod': 'module std\n'}, 'paths': ['src/math/a.go', 'src/cmd/use.go'],
                  'module': '../math', 'source': 'src/cmd/use.go', 'expected': ['src/math/a.go']}, id='relative-import-preserved'),
    pytest.param({'configs': {'src/go.mod': 'module std\n'}, 'paths': ['src/example.org/math/a.go', 'src/client/use.go'],
                  'module': 'example.org/math', 'source': 'src/client/use.go', 'expected': []}, id='external-dotted-component'),
    pytest.param({'configs': {'src/go.mod': 'module std\n'}, 'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'strings', 'source': 'src/client/use.go', 'expected': []}, id='absent-package'),
    pytest.param({'configs': {'src/go.mod': 'module example.org/app\n'}, 'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'math', 'source': 'src/client/use.go', 'expected': []}, id='no-declared-std-root'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go', 'client/use.go'],
                  'module': '../../../math', 'source': 'client/use.go', 'expected': []}, id='relative-escape'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go'],
                  'module': 'math', 'source': '/outside/use.go', 'expected': []}, id='absolute-source-outside'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go'],
                  'module': 'math', 'source': '../outside.go', 'expected': []}, id='parent-source-outside'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['root.go', 'math/a.go', 'client/use.go'],
                  'module': '', 'source': 'client/use.go', 'expected': []}, id='empty-import'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go', 'client/use.go'],
                  'module': '/math', 'source': 'client/use.go', 'expected': []}, id='absolute-import'),
    pytest.param({'configs': {'go.mod': 'module std\n'}, 'paths': ['math/a.go', 'client/use.go'],
                  'module': 'net/../math', 'source': 'client/use.go', 'expected': []}, id='import-parent-component'),
    pytest.param({'configs': {'src/go.mod': 'module "std" // declared\n'}, 'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'math', 'source': 'src/client/use.go', 'expected': ['src/math/a.go']}, id='quoted-std-module'),
    pytest.param({'configs': {'src/go.mod': 'module std\n', 'src/math/go.mod': 'module example.org/independent\n'},
                  'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'math', 'source': 'src/client/use.go', 'expected': []}, id='target-owned-by-other-module'),
    pytest.param({'configs': {'src/go.mod': 'module std\n', 'src/net/go.mod': 'module example.org/independent\n'},
                  'paths': ['src/net/http/a.go', 'src/client/use.go'],
                  'module': 'net/http', 'source': 'src/client/use.go', 'expected': []}, id='target-below-other-module'),
    pytest.param({'configs': {'src/go.mod': 'module std\n', 'src/other/go.mod': 'module std\n'},
                  'paths': ['src/other/math/a.go', 'src/client/use.go'],
                  'module': 'other/math', 'source': 'src/client/use.go', 'expected': []}, id='target-inside-another-std-root'),
    pytest.param({'configs': {'src/go.mod': 'module std\n', 'src/math/go.mod': ''},
                  'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'math', 'source': 'src/client/use.go', 'expected': []}, id='empty-target-module-boundary'),
    pytest.param({'configs': {'src/go.mod': 'module std\n', 'src/math/go.mod': 'not a module declaration\n'},
                  'paths': ['src/math/a.go', 'src/client/use.go'],
                  'module': 'math', 'source': 'src/client/use.go', 'expected': []}, id='unparseable-target-module-boundary'),
])
def test_go_std_package_candidates_use_declared_owner(tmp_path, record_property, case):
    files = {**dict.fromkeys(case['paths'], 'package sample\n'), **case['configs']}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    index = FileIndex({name: name for name in files})
    index.configure_go(tmp_path)
    actual = index.go_candidates(case['module'], case['source'])
    record_property('go_modules', json.dumps(index.go_modules))
    record_property('go_packages', json.dumps({name: sorted(paths) for name, paths in index.go_packages.items()}))
    record_property('expected_candidates', json.dumps(case['expected']))
    record_property('actual_candidates', json.dumps(actual))
    assert actual == case['expected']


def write_sources(root, binding):
    call = {'': 'math.Alpha()', 'm ': 'm.Alpha()', '. ': 'Alpha()', '_ ': ''}[binding]
    files = {'src/go.mod': 'module std\ngo 1.23\n',
             'src/math/a.go': 'package math\nfunc Alpha() int { return 1 }\n',
             'src/math/b.go': 'package math\nfunc Beta() int { return 2 }\n',
             'src/client/client_test.go': 'package client\nimport "testing"\nimport ' + binding + '"math"\nfunc TestUse(t *testing.T) { ' + call + ' }\n'}
    trees = []
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if name.endswith('.go'):
            tree = syntax_tree(name, content, 'go')
            trees.append({'path': name, 'bytes': len(content.encode()), 'end_byte': tree.root_node.end_byte,
                          'has_error': tree.root_node.has_error, 'tree': str(tree.root_node)})
    return trees


@pytest.mark.parametrize('binding', ['', 'm ', '. ', '_ '], ids=['plain', 'alias', 'dot', 'blank'])
async def test_go_std_public_graph_and_import_bound_tests(tmp_path, monkeypatch, record_property, binding):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    trees = write_sources(tmp_path, binding)
    record_property('native_trees', json.dumps(trees))
    assert all(not t['has_error'] and t['end_byte'] == t['bytes'] for t in trees)
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        responses = {}
        for tag, tool, arguments in [
            ('dependencies', 'dependencies', {'path': 'src/math/a.go'}),
            ('other_package_file', 'dependencies', {'path': 'src/math/b.go'}),
            ('impact', 'impact_analysis', {'changed_files': ['src/math/a.go']}),
            ('tests', 'suggest_tests', {'files': ['src/math/a.go'], 'symbol_name': 'Alpha', 'task_hint': 'client'}),
        ]:
            response = await peer.execute(tool, arguments)
            responses[tag] = {'is_error': response.isError, 'response': response.structuredContent}
        record_property('public_responses', json.dumps(responses))
        assert all(not r['is_error'] for r in responses.values())
        caller = 'src/client/client_test.go'
        for tag in ('dependencies', 'other_package_file'):
            assert responses[tag]['response']['data']['imported_by'] == [caller]
        assert caller in responses['impact']['response']['data']['impacted_files']
        assert any(t['file_path'] == caller and t['evidence']['import_distance'] == 1
                   for t in responses['tests']['response']['data']['candidates'])
    finally:
        await peer.close()


async def test_go_std_config_only_edit_updates_public_edges(tmp_path, monkeypatch, record_property):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    trees = write_sources(tmp_path, '. ')
    record_property('native_trees', json.dumps(trees))
    assert all(not t['has_error'] and t['end_byte'] == t['bytes'] for t in trees)
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    rows = []
    try:
        for module in ('std', 'example.org/unrelated', 'std'):
            (tmp_path / 'src/go.mod').write_text('module ' + module + '\ngo 1.23\n')
            response = await peer.execute('dependencies', {'path': 'src/math/a.go'})
            rows.append({'module': module, 'is_error': response.isError, 'response': response.structuredContent})
        record_property('config_responses', json.dumps(rows))
        assert all(not r['is_error'] for r in rows)
        assert [r['response']['data']['imported_by'] for r in rows] == [
            ['src/client/client_test.go'], [], ['src/client/client_test.go']]
    finally:
        await peer.close()


async def test_go_std_nested_module_config_boundary_updates_public_edges(tmp_path, monkeypatch, record_property):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    trees = write_sources(tmp_path, '. ')
    record_property('native_trees', json.dumps(trees))
    assert all(not t['has_error'] and t['end_byte'] == t['bytes'] for t in trees)
    config = tmp_path / 'src/math/go.mod'
    config.write_text('module example.org/independent\ngo 1.23\n')
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    rows = []
    try:
        for kind in ('foreign', 'absent', 'empty', 'foreign'):
            if kind == 'foreign':
                config.write_text('module example.org/independent\ngo 1.23\n')
            elif kind == 'absent':
                config.unlink()
            else:
                config.write_text('')
            response = await peer.execute('dependencies', {'path': 'src/math/a.go'})
            rows.append({'nested_module': kind, 'is_error': response.isError, 'response': response.structuredContent})
        record_property('nested_config_responses', json.dumps(rows))
        assert all(not r['is_error'] for r in rows)
        assert [r['response']['data']['imported_by'] for r in rows] == [
            [], ['src/client/client_test.go'], [], []]
    finally:
        await peer.close()


def test_go_std_unstatable_indexed_module_keeps_boundary(tmp_path, monkeypatch, record_property):
    files = {'src/go.mod': 'module std\n', 'src/math/go.mod': 'module example.org/independent\n',
             'src/math/a.go': 'package math\n', 'src/strings/a.go': 'package strings\n'}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    original = Path.is_file

    def is_file(path):
        if path == tmp_path / 'src/math/go.mod':
            raise PermissionError('indexed module parent became unsearchable')
        return original(path)

    monkeypatch.setattr(Path, 'is_file', is_file)
    index = FileIndex({name: name for name in files})
    error = None
    try:
        index.configure_go(tmp_path)
    except OSError as caught:
        error = type(caught).__name__
    candidates = {name: index.go_candidates(name, 'src/client/use.go') for name in ('math', 'strings')}
    record_property('unstatable_module', json.dumps({'error': error, 'candidates': candidates,
                    'module_roots': sorted(index.go_module_roots)}))
    assert error is None
    assert 'src/math' in index.go_module_roots
    assert candidates == {'math': [], 'strings': ['src/strings/a.go']}


@pytest.mark.parametrize('payload,accepted', [(b'{}', True), (b'xx', False), (b'{}extra', False)],
                         ids=['exact', 'wrong-hash', 'oversized'])
def test_ci_pinned_grammar_asset_identity(monkeypatch, payload, accepted):
    path = Path(__file__).resolve().parents[1] / 'scripts/check_optional_grammars.py'
    spec = importlib.util.spec_from_file_location('grammar_acquisition_controls', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(payload))
    args = ('https://api.github.com/asset', 2, hashlib.sha256(b'{}').hexdigest())
    if accepted:
        assert module._download_exact(*args) == b'{}'
    else:
        with pytest.raises(ValueError, match='asset identity'):
            module._download_exact(*args)
