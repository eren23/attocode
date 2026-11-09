"""Go receiver chunks retain identity through real optional vector persistence."""
import inspect
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context import embeddings
from attocode_intel._internal.integrations.context.ast_chunker import chunk_file
from attocode_intel._internal.integrations.context.codebase_ast import detect_language, parse_file
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from attocode_intel._internal.integrations.context.vector_store import (
    VectorEntry,
    VectorStore,
    VectorStoreDimensionMismatchError,
    VectorStoreRotationActiveError,
)

FILES = {
    'types.go': 'package p\ntype A struct{}\ntype B struct{}\ntype Box[T any] struct{}\ntype Ω struct{}\n',
    'methods.go': 'package p\nfunc (a A) M() int { return 1 }\nfunc (b *B) M() int { return 2 }\n'
                  'func (b *Box[T]) Get(v T) T { return v }\nfunc (o *Ω) read() {}\n'
                  'func M() int { return 3 }\nfunc Plain() {}\ntype Local struct{}\n'
                  'func (l Local) Inner() {}\n',
}
EXPECTED = {
    'file:methods.go': ('file', 'methods.go'),
    'method:methods.go:A.M': ('method', 'A.M'),
    'method:methods.go:B.M': ('method', 'B.M'),
    'method:methods.go:Box.Get': ('method', 'Box.Get'),
    'method:methods.go:Ω.read': ('method', 'Ω.read'),
    'func:methods.go:M': ('function', 'M'),
    'func:methods.go:Plain': ('function', 'Plain'),
    'cls:methods.go:Local': ('class', 'Local'),
    'method:methods.go:Local.Inner': ('method', 'Local.Inner'),
}


class DeterministicProvider:
    name = 'test-go-chunks'
    version = 'fixture-v1'

    def __init__(self, mode='good'):
        self.mode = mode
        self.calls = []

    def dimension(self):
        return 3

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.mode == 'raise':
            raise RuntimeError('controlled embedding failure')
        return [[] if self.mode == 'partial' and 'Inner' in t else [1.0, 0.0, 0.0] for t in texts]

    def embed_query(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def qualified_files(root, files=FILES):
    observations = {}
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        tree = syntax_tree(name, text, detect_language(name))
        assert tree is not None and not tree.root_node.has_error
        assert tree.root_node.end_byte == len(text.encode())
        ast = parse_file(str(path), text)
        assert ast.parsing_tier == 'tree_sitter' and not ast.parse_failures
        observations[name] = {'source': text, 'tree': str(tree.root_node), 'ast': asdict(ast)}
    return observations


@contextmanager
def manager(root, provider, monkeypatch):
    monkeypatch.setattr(embeddings, 'create_embedding_provider', lambda *args, **kwargs: provider)
    value = SemanticSearchManager(str(root), nl_mode='none')
    try:
        value._ensure_provider()
        assert value._provider is provider and not value._keyword_fallback
        yield value
    finally:
        value.close()


def rows(store, name='methods.go'):
    return store._get_conn().execute(
        'SELECT id,chunk_type,name,text,hex(vector),model_name,model_version,dimension,blob_oid,action_hash '
        'FROM vectors WHERE file_path=? ORDER BY id', (name,)).fetchall()


def legacy(store, root, name='methods.go'):
    store.upsert_batch([
        VectorEntry('file:' + name, name, 'file', Path(name).name, 'legacy file', [1.0, 0.0, 0.0]),
        VectorEntry('func:' + name + ':M', name, 'function', 'M', 'legacy collision', [1.0, 0.0, 0.0]),
        VectorEntry('func:' + name + ':OldRemoved', name, 'function', 'OldRemoved', 'legacy orphan', [1.0, 0.0, 0.0]),
        VectorEntry('untouched', 'unrelated.txt', 'file', 'untouched', 'preserve me', [0.0, 1.0, 0.0]),
    ])
    store.set_file_metadata(name, (root / name).stat().st_mtime, 3)


def run_route(value, root, route):
    if route == 'full':
        return value.index()
    if route == 'file':
        return value.reindex_file(str(root / 'methods.go'))
    if route == 'stale':
        return value.reindex_stale_files()
    value._run_background_indexing(threading.Event())
    return asdict(value._index_progress)


def stored_identity(actual):
    return {row[0]: (row[1], row[2]) for row in actual}


@pytest.mark.parametrize('builder', ['structural', 'vector'])
@pytest.mark.parametrize('case', ['receivers', 'same-file', 'python', 'unsupported'])
def test_native_chunk_builder_identity(tmp_path, monkeypatch, record_property, case, builder):
    files = FILES
    expected = EXPECTED
    name = 'methods.go'
    if case == 'same-file':
        files = {name: 'package p\ntype R struct{}\nfunc (r R) M() {}\nfunc M() {}\n'}
        expected = {'file:methods.go': ('file', 'methods.go'), 'cls:methods.go:R': ('class', 'R'),
                    'method:methods.go:R.M': ('method', 'R.M'), 'func:methods.go:M': ('function', 'M')}
    elif case == 'python':
        name = 'methods.py'
        files = {name: 'def M():\n    return 1\nclass R:\n    def M(self):\n        return 2\n'}
        expected = {'file:methods.py': ('file', 'methods.py'), 'cls:methods.py:R': ('class', 'R'),
                    'method:methods.py:R.M': ('method', 'R.M'), 'func:methods.py:M': ('function', 'M')}
    elif case == 'unsupported':
        files = {name: 'package p\nfunc (r **R) Odd() {}\n'}
        expected = {'file:methods.go': ('file', 'methods.go'), 'func:methods.go:Odd': ('function', 'Odd')}
    record_property('inputs', json.dumps(qualified_files(tmp_path, files)))
    if builder == 'structural':
        chunks = chunk_file(str(tmp_path / name), name)
        actual = {c.id: (c.chunk_type, c.name) for c in chunks}
        record_property('chunks', json.dumps([asdict(c) for c in chunks]))
    else:
        with manager(tmp_path, DeterministicProvider(), monkeypatch) as value:
            chunks = value._chunk_single_file(name, str(tmp_path / name))
            actual = {c[0]: (c[2], c[0].split(':')[-1]) for c in chunks}
            record_property('chunks', json.dumps(chunks))
    record_property('qualified_input', 'true')
    assert actual == expected and len(chunks) == len(expected), 'REGRESSION: Go chunk builder identity'


@pytest.mark.parametrize('route', ['full', 'file', 'background'])
def test_native_vector_index_keeps_both_receivers(tmp_path, monkeypatch, record_property, route):
    record_property('inputs', json.dumps(qualified_files(tmp_path)))
    provider = DeterministicProvider()
    with manager(tmp_path, provider, monkeypatch) as value:
        record_property('index_result', json.dumps(run_route(value, tmp_path, route)))
        actual = rows(value._store)
        hits = value.search('M', top_k=30, file_filter='methods.go', two_stage=False, expand_query=False)
        record_property('stored_rows', json.dumps(actual))
        record_property('hits', json.dumps([asdict(h) for h in hits]))
    record_property('qualified_input', 'true')
    assert stored_identity(actual) == EXPECTED, 'REGRESSION: Go vector rows lost receiver identity'
    assert {'A.M', 'B.M'} <= {h.name for h in hits if h.chunk_type == 'method'}


@pytest.mark.parametrize('route', ['full', 'stale', 'background'])
def test_unchanged_legacy_go_cache_is_repaired(tmp_path, monkeypatch, record_property, route):
    record_property('inputs', json.dumps(qualified_files(tmp_path)))
    provider = DeterministicProvider()
    stamps = {p: (tmp_path / p).stat().st_mtime_ns for p in FILES}
    with manager(tmp_path, provider, monkeypatch) as value:
        legacy(value._store, tmp_path)
        before = rows(value._store)
        untouched = rows(value._store, 'unrelated.txt')
        record_property('route_result', json.dumps(run_route(value, tmp_path, route)))
        after = rows(value._store)
        assert rows(value._store, 'unrelated.txt') == untouched
    with manager(tmp_path, provider, monkeypatch) as reopened:
        restored = rows(reopened._store)
        calls = len(provider.calls)
        if route != 'full':
            run_route(reopened, tmp_path, route)
            assert len(provider.calls) == calls
        assert rows(reopened._store) == restored
    assert all((tmp_path / p).stat().st_mtime_ns == stamps[p] for p in FILES)
    record_property('cache', json.dumps({'before': before, 'after': after, 'restored': restored,
                                        'embed_calls': provider.calls, 'source_mtimes': stamps}))
    record_property('qualified_input', 'true')
    assert stored_identity(after) == EXPECTED and after == restored, 'REGRESSION: unchanged Go vector cache stayed legacy'


@pytest.mark.parametrize('route', ['full', 'file', 'background'])
@pytest.mark.parametrize('failure', ['raise', 'partial'])
def test_failed_go_replacement_preserves_old_rows(tmp_path, monkeypatch, record_property, failure, route):
    record_property('inputs', json.dumps(qualified_files(tmp_path)))
    provider = DeterministicProvider(failure)
    with manager(tmp_path, provider, monkeypatch) as value:
        legacy(value._store, tmp_path)
        # This probe must attempt replacement, even before cache-ID migration
        # exists. Unchanged-cache behavior has its own separate regression.
        value._store.set_file_metadata('methods.go', 0.0, 3)
        before, metadata = rows(value._store), value._store.get_file_metadata('methods.go')
        record_property('route_result', json.dumps(run_route(value, tmp_path, route)))
        after = rows(value._store)
        after_metadata = value._store.get_file_metadata('methods.go')
        record_property('cache', json.dumps({'before': before, 'after': after,
                                            'metadata': metadata, 'after_metadata': after_metadata}))
    assert any('Inner' in text for batch in provider.calls for text in batch)
    record_property('attempted_texts', json.dumps(provider.calls))
    record_property('qualified_input', 'true')
    assert after == before and metadata == after_metadata, 'REGRESSION: partial Go embedding replaced old rows'


@pytest.mark.parametrize('case', ['success', 'wrong-file', 'duplicate-id', 'conflicting-owner',
                                 'sql-error', 'rotation', 'rotation-race', 'dimension'])
def test_atomic_file_replacement(tmp_path, monkeypatch, record_property, case):
    qualified_files(tmp_path)
    path = str(tmp_path / 'vectors.db')
    value = VectorStore(path, 3, model_name='fixture', model_version='v1')
    try:
        legacy(value, tmp_path)
        before = rows(value)
        assert len(before) == 3 and len(rows(value, 'unrelated.txt')) == 1
        record_property('sqlite_before', json.dumps(before))
        new = [VectorEntry('method:methods.go:' + owner + '.M', 'methods.go', 'method', owner + '.M',
                           'replacement', [1.0, 0.0, 0.0]) for owner in ['A', 'B']]
        record_property('qualified_input', 'true')
        assert 'replace_file' in inspect.signature(value.upsert_batch).parameters, 'REGRESSION: atomic Go file replacement missing'
        if case == 'success':
            value.upsert_batch(new, replace_file='methods.go')
            assert {r[0] for r in rows(value)} == {e.id for e in new}
            assert rows(value, 'unrelated.txt')[0][0] == 'untouched'
            return
        error = ValueError
        if case == 'wrong-file':
            new[0].file_path = 'other.go'
        elif case == 'duplicate-id':
            new[1].id = new[0].id
        elif case == 'conflicting-owner':
            value.upsert(VectorEntry(new[0].id, 'unrelated.txt', 'file', 'owner', 'keep', [1.0, 0.0, 0.0]))
        elif case == 'sql-error':
            value._get_conn().execute("CREATE TRIGGER fail_chunk BEFORE INSERT ON vectors WHEN NEW.id LIKE '%B.M' BEGIN SELECT RAISE(ABORT,'blocked'); END")
            value._get_conn().commit()
            error = sqlite3.IntegrityError
        elif case in {'rotation', 'rotation-race'}:
            def activate():
                value._get_conn().execute("INSERT OR REPLACE INTO store_metadata VALUES ('rotation_state','pending')")
                value._get_conn().commit()
            if case == 'rotation':
                activate()
            else:
                guard = value._guard_writes
                def change_after_guard():
                    guard()
                    activate()
                monkeypatch.setattr(VectorStore, '_guard_writes', lambda self: change_after_guard())
            error = VectorStoreRotationActiveError
        elif case == 'dimension':
            value.close()
            value = VectorStore(path, 4, strict_dimension=False)
            assert value.degraded
            error = VectorStoreDimensionMismatchError
        unrelated = rows(value, 'unrelated.txt')
        with pytest.raises(error):
            value.upsert_batch(new, replace_file='methods.go')
        assert rows(value) == before and rows(value, 'unrelated.txt') == unrelated
        assert not value._get_conn().in_transaction
    finally:
        value.close()
