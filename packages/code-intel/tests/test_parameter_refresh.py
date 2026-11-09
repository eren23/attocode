"""Canonical signatures and source edits must reach diff and refresh consumers."""

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    ParamDef,
    detect_language,
    diff_file_ast,
    parse_file,
)
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

EDITS = [
    pytest.param('sample.go', 'package sample\nfunc consume(value int) {}\n',
                 'package sample\nfunc consume(other int) {}\n', 'consume', id='go-name'),
    pytest.param('sample.go', 'package sample\nfunc consume(value int) {}\n',
                 'package sample\nfunc consume(value string) {}\n', 'consume', id='go-type'),
    pytest.param('sample.go', 'package sample\nfunc consume(values string) {}\n',
                 'package sample\nfunc consume(values ...string) {}\n', 'consume', id='go-rest'),
    pytest.param('sample.go', 'package sample\ntype Box struct{}\nfunc (b *Box) consume(value int) {}\n',
                 'package sample\ntype Box struct{}\nfunc (b *Box) consume(other int) {}\n', 'Box.consume', id='go-receiver'),
    pytest.param('sample.go', 'package sample\ntype Service interface { consume(value int) }\n',
                 'package sample\ntype Service interface { consume(value string) }\n', 'Service.consume', id='go-interface'),
    pytest.param('sample.c', 'void consume(int value) {}\n',
                 'void consume(long value) {}\n', 'consume', id='c-type'),
    pytest.param('Sample.java', 'class Box { void consume(int value) {} }\n',
                 'class Box { void consume(long value) {} }\n', 'Box.consume', id='java-method'),
]


def selected(ast, qualified):
    functions = {f.name: f for f in ast.functions}
    functions.update({c.name + '.' + m.name: m for c in ast.classes for m in c.methods})
    return functions[qualified]


def native_pair(name, before, after, qualified, record_property):
    observations = []
    for source in (before, after):
        tree = syntax_tree(name, source, detect_language(name))
        observations.append({'tree': str(tree.root_node) if tree else None,
                             'has_error': tree.root_node.has_error if tree else None,
                             'end_byte': tree.root_node.end_byte if tree else None,
                             'bytes': len(source.encode())})
    record_property('native_trees', json.dumps(observations))
    assert all(o['has_error'] is False and o['end_byte'] == o['bytes'] for o in observations)
    old, new = parse_file(name, before), parse_file(name, after)
    assert old.parsing_tier == new.parsing_tier == 'tree_sitter'
    first, second = selected(old, qualified), selected(new, qualified)
    record_property('before_function', json.dumps(asdict(first)))
    record_property('after_function', json.dumps(asdict(second)))
    assert first.parameters != second.parameters
    for field in ('params', 'return_type', 'decorators', 'is_async', 'start_line', 'end_line'):
        assert getattr(first, field) == getattr(second, field), field
    assert first.params == second.params == []
    return old, new


def change_rows(changes):
    return [(c.kind, c.symbol_name, c.symbol_kind) for c in changes]


@pytest.mark.parametrize('name,before,after,qualified', EDITS)
def test_native_parameter_only_edits_are_modified_symbols(name, before, after, qualified, record_property):
    old, new = native_pair(name, before, after, qualified, record_property)
    changes = diff_file_ast(old, new)
    record_property('changes', json.dumps(change_rows(changes)))
    assert change_rows(changes) == [('modified', qualified, 'method' if '.' in qualified else 'function')]
    assert changes[0].previous is selected(old, qualified)


@contextmanager
def indexed(root, name, source):
    path = root / name
    path.write_text(source)
    service = ASTService(str(root))
    try:
        service.initialize_skeleton(indexing_depth='eager')
        yield service, path
    finally:
        service.stop_hydration()
        service._store.close()


@pytest.mark.parametrize('name,before,after,qualified', EDITS)
def test_refresh_updates_parameter_metadata(tmp_path, name, before, after, qualified, record_property):
    old, expected = native_pair(name, before, after, qualified, record_property)
    with indexed(tmp_path, name, before) as (service, path):
        assert selected(service._ast_cache[name], qualified).parameters == selected(old, qualified).parameters
        path.write_text(after)
        changes = service.refresh()
        actual = service._ast_cache[name]
        record_property('refresh_changes', json.dumps(change_rows(changes)))
        record_property('cached_function', json.dumps(asdict(selected(actual, qualified))))
        record_property('cached_source_sha256', actual.content_sha256)
        record_property('expected_source_sha256', expected.content_sha256)
        assert selected(actual, qualified).parameters == selected(expected, qualified).parameters
        assert actual.content_sha256 == expected.content_sha256
        assert change_rows(changes) == [('modified', qualified, 'method' if '.' in qualified else 'function')]


def test_body_only_refresh_updates_source_and_callers_without_signature_event(tmp_path, record_property):
    name = 'calls.go'
    before = 'package sample\nfunc alpha() {}\nfunc omega() {}\nfunc consume() { alpha() }\n'
    after = before.replace('{ alpha() }', '{ omega() }')
    assert len(before.encode()) == len(after.encode())
    observations = []
    for source in (before, after):
        tree = syntax_tree(name, source, 'go')
        observations.append({'tree': str(tree.root_node) if tree else None,
                             'has_error': tree.root_node.has_error if tree else None,
                             'end_byte': tree.root_node.end_byte if tree else None,
                             'bytes': len(source.encode())})
    record_property('native_trees', json.dumps(observations))
    assert all(o['has_error'] is False and o['end_byte'] == o['bytes'] for o in observations)
    expected = parse_file(name, after)
    assert expected.parsing_tier == 'tree_sitter'
    with indexed(tmp_path, name, before) as (service, path):
        service.ensure_references_indexed(name)
        assert service.get_callees_of('consume') == {'alpha'}
        assert diff_file_ast(service._ast_cache[name], expected) == []
        stamp = path.stat()
        path.write_text(after)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert path.stat().st_size == stamp.st_size and path.stat().st_mtime_ns == stamp.st_mtime_ns
        changes = service.refresh()
        actual = service._ast_cache[name]
        record_property('refresh_changes', json.dumps(change_rows(changes)))
        record_property('cached_source_sha256', actual.content_sha256)
        record_property('expected_source_sha256', expected.content_sha256)
        record_property('actual_callees', json.dumps(sorted(service.get_callees_of('consume'))))
        record_property('expected_callees', json.dumps(['omega']))
        assert changes == []
        assert actual.content_sha256 == expected.content_sha256
        assert service.get_callees_of('consume') == {'omega'}
        assert service.get_callers_of('alpha') == set()
        assert service.get_callers_of('omega') == {'consume'}


def test_identical_source_and_metadata_do_not_reindex(tmp_path):
    name, source = 'same.go', 'package sample\nfunc consume(value int) {}\n'
    first, second = parse_file(name, source), parse_file(name, source)
    assert first.functions[0].parameters and first.functions[0].parameters == second.functions[0].parameters
    assert diff_file_ast(first, second) == []
    with indexed(tmp_path, name, source) as (service, _):
        cached = service._ast_cache[name]
        assert service.refresh() == []
        assert service._ast_cache[name] is cached


def test_unbound_source_hash_does_not_trigger_content_only_refresh(tmp_path, monkeypatch):
    name, source = 'unreadable.go', 'package sample\nvar Value int\n'
    with indexed(tmp_path, name, source) as (service, target):
        cached = service._ast_cache[name]
        assert cached.top_level_vars == ['Value'] and cached.content_sha256
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == target:
                raise PermissionError('controlled source-read failure')
            return original(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, 'read_text', read_text)
            assert parse_file(str(target)).content_sha256 == ''
            assert service.refresh() == []
        assert service._ast_cache[name] is cached


def detailed_ast(parameter, method):
    function = FunctionDef('consume', 1, 1, parameters=[parameter])
    return FileAST('manual.py', 'python',
                   functions=[] if method else [function],
                   classes=[ClassDef('Box', 1, 1, methods=[function])] if method else [])


@pytest.mark.parametrize('method', [False, True], ids=['function', 'method'])
@pytest.mark.parametrize('change', [{'default_value': '1'}, {'is_kwonly': True}, {'is_kwargs': True}],
                         ids=['default', 'keyword-only', 'kwargs'])
def test_detailed_parameter_metadata_is_part_of_signature(change, method):
    first = ParamDef('value', type_annotation='int')
    second = replace(first, **change)
    old, new = detailed_ast(first, method), detailed_ast(second, method)
    assert selected(old, 'Box.consume' if method else 'consume').params == []
    assert change_rows(diff_file_ast(old, new)) == [('modified', 'Box.consume' if method else 'consume',
                                                   'method' if method else 'function')]


@pytest.mark.parametrize('method', [False, True], ids=['function', 'method'])
def test_legacy_only_parameter_lists_remain_supported(method):
    old, new = detailed_ast(ParamDef('value'), method), detailed_ast(ParamDef('value'), method)
    qualified = 'Box.consume' if method else 'consume'
    selected(old, qualified).parameters = selected(new, qualified).parameters = []
    selected(old, qualified).params = ['before']
    selected(new, qualified).params = ['after']
    assert change_rows(diff_file_ast(old, new)) == [('modified', qualified, 'method' if method else 'function')]
