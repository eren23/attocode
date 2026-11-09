"""Whole-file deletion preserves existing native Go definition identities."""
import json
from collections import Counter
from dataclasses import asdict

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_ast import detect_language, parse_file
from attocode_intel._internal.integrations.context.codebase_context import CodebaseContextManager
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

CONSUMERS = ['notify', 'refresh', 'context']
CASES = [
    {'id': 'qualified-methods', 'name': 'removed.go',
     'files': {'types.go': 'package p\ntype A struct{}\ntype B struct{}\ntype Box[T any] struct{}\ntype Ω struct{}\n',
               'removed.go': 'package p\nfunc (a A) M() {}\nfunc (b *B) M() {}\n'
                             'func (b *Box[T]) Read(v T) T { return v }\n'
                             'func (o *Ω) read() {}\nfunc Plain() {}\n'
                             'type Local struct{}\nfunc (l Local) Inner() {}\n'},
     'expected': [('A.M', 'method'), ('B.M', 'method'), ('Box.Read', 'method'),
                  ('Ω.read', 'method'), ('Plain', 'function'), ('Local', 'class')]},
    {'id': 'unsupported-duplicates', 'name': 'removed.go',
     'files': {'types.go': 'package p\ntype A struct{}\ntype B struct{}\n',
               'removed.go': 'package p\nfunc (a **A) Odd() {}\nfunc (b **B) Odd() {}\n'},
     'expected': [('Odd', 'function'), ('Odd', 'function')]},
    {'id': 'same-file-class', 'name': 'removed.go',
     'files': {'removed.go': 'package p\ntype Local struct{}\nfunc (l Local) M() {}\nfunc Plain() {}\n'},
     'expected': [('Plain', 'function'), ('Local', 'class')]},
    {'id': 'python-control', 'name': 'removed.py',
     'files': {'removed.py': 'def plain(value: int = 1):\n    return value\n\n'
                            'class Local:\n    def method(self):\n        return 1\n'},
     'expected': [('plain', 'function'), ('Local', 'class')]},
    {'id': 'empty-go', 'name': 'removed.go', 'files': {'removed.go': 'package p\n'}, 'expected': []},
]


def observe_deletion(root, name, consumer):
    """Record real mutation and cleanup; the caller owns the identity oracle."""
    path = root / name
    record = {'consumer': consumer, 'closed': False}
    service = None
    try:
        if consumer == 'context':
            manager = CodebaseContextManager(root_dir=str(root))
            manager.discover_files()
            # Discovery builds a graph but does not populate this AST cache.
            manager.mark_file_dirty(str(path))
            manager.update_dirty_files()
            old = manager._ast_cache[name]
        else:
            service = ASTService(str(root))
            service.initialize_skeleton(indexing_depth='eager')
            old = service._ast_cache[name]
            record['before_symbols'] = [asdict(v) for v in service.get_file_symbols(name)]
            record['before_counts'] = service._store.stats()
        record['before_ast'] = asdict(old)
        assert old.parsing_tier == 'tree_sitter' and not old.parse_failures
        path.unlink()
        if consumer == 'context':
            manager.mark_file_dirty(str(path))
            envelopes = manager.update_dirty_files()
            changes = [change for result in envelopes for change in result.symbol_changes]
            record['envelopes'] = [asdict(result) for result in envelopes]
            assert all(result.file_path == name and result.was_incremental
                       and len(result.symbol_changes) == 1 for result in envelopes)
            assert name not in manager._ast_cache and not manager._dirty_files
            graph = manager.dependency_graph
            assert graph is not None
            assert name not in graph.forward and name not in graph.reverse
            assert all(name not in edges for edges in [*graph.forward.values(), *graph.reverse.values()])
            record['graph_after'] = {'forward': {k: sorted(v) for k, v in graph.forward.items()},
                                     'reverse': {k: sorted(v) for k, v in graph.reverse.items()}}
        else:
            changes = service.refresh() if consumer == 'refresh' else service.notify_file_changed(str(path))
            assert name not in service._ast_cache and not service.get_file_symbols(name)
            assert service._store.get_file(name) is None and not service._store.load_symbols(name)
            record['after_counts'] = service._store.stats()
            record['after_asts'] = {k: asdict(v) for k, v in service._ast_cache.items()}
            record['after_symbols'] = {k: [asdict(v) for v in values]
                                       for k, values in service._index.definitions.items()}
        previous = [*old.functions, *old.classes]
        assert len(changes) == len(previous)
        assert all(c.kind == 'removed' and c.file_path == name and c.previous is prior
                   for c, prior in zip(changes, previous, strict=True))
        record['changes'] = [asdict(change) for change in changes]
        record['source_deleted'] = not path.exists()
    finally:
        if service is not None:
            service.stop_hydration()
            service._store.close()
        record['closed'] = True
    if consumer != 'context':
        restarted = ASTService(str(root))
        try:
            restarted.initialize_skeleton(indexing_depth='eager')
            assert name not in restarted._ast_cache and not restarted.get_file_symbols(name)
            assert restarted._store.get_file(name) is None and not restarted._store.load_symbols(name)
            record['restart_asts'] = {k: asdict(v) for k, v in restarted._ast_cache.items()}
            record['restart_symbols'] = {k: [asdict(v) for v in values]
                                         for k, values in restarted._index.definitions.items()}
            assert record['after_asts'] == record['restart_asts']
            assert record['after_symbols'] == record['restart_symbols']
        finally:
            restarted.stop_hydration()
            restarted._store.close()
            record['restart_closed'] = True
    return record


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('case', CASES, ids=[case['id'] for case in CASES])
def test_native_whole_file_removals(tmp_path, record_property, case, consumer):
    trees = {}
    for name, source in case['files'].items():
        tree = syntax_tree(name, source, detect_language(name))
        assert tree is not None
        trees[name] = {'tree': str(tree.root_node), 'has_error': tree.root_node.has_error,
                       'bytes': len(source.encode()), 'end_byte': tree.root_node.end_byte}
        assert not tree.root_node.has_error and tree.root_node.end_byte == len(source.encode())
        ast = parse_file(name, source)
        assert ast.parsing_tier == 'tree_sitter' and not ast.parse_failures
        (tmp_path / name).write_text(source)
    record_property('native_inputs', json.dumps({'sources': case['files'], 'trees': trees}))
    result = observe_deletion(tmp_path, case['name'], consumer)
    record_property('observation', json.dumps(result))
    record_property('qualified_input', 'true')
    actual = Counter((change['symbol_name'], change['symbol_kind']) for change in result['changes'])
    assert actual == Counter(case['expected']), 'REGRESSION: Go deletion event identity'
