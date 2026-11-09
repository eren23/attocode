"""Go search labels and fusion retain owners, source spans and cache boundaries."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

import pytest
from attocode_intel._internal.integrations.context import embeddings, ts_parser
from attocode_intel._internal.integrations.context.semantic_search import (
    SearchScoringConfig,
    SemanticSearchManager,
)
from test_chunk_identity import JAVA
from test_go_semantic_chunks import DeterministicProvider, qualified_files

FILES = {
    'types.go': 'package p\ntype A struct{}\ntype B struct{}\ntype Box[T any] struct{}\ntype Ω struct{}\n',
    'methods.go': 'package p\nfunc (a A) M(identity int) int { return identity }\n'
                  'func (b *B) M(identity int) int { return identity }\n'
                  'func (b *Box[T]) Get(identity T) T { return identity }\n'
                  'func (o *Ω) read(identity int) {}\nfunc M(identity int) int { return identity }\n'
                  'func Plain(identity int) {}\ntype Local struct{}\nfunc (l Local) Inner(identity int) {}\n',
}
EXPECTED = {
    ('method', 'A.M', 2, 2), ('method', 'B.M', 3, 3),
    ('method', 'Box.Get', 4, 4), ('method', 'Ω.read', 5, 5),
    ('function', 'M', 6, 6), ('function', 'Plain', 7, 7),
    ('method', 'Local.Inner', 9, 9),
}


class Provider(DeterministicProvider):
    def __init__(self):
        super().__init__()
        self.queries = []

    def embed_query(self, texts):
        self.queries.append(list(texts))
        return super().embed_query(texts)


@contextmanager
def opened(root, monkeypatch, provider=None, *, require_body=True):
    if provider is not None:
        monkeypatch.setattr(embeddings, 'create_embedding_provider', lambda *a, **k: provider)
    value = SemanticSearchManager(str(root), nl_mode='none',
                                 scoring_config=SearchScoringConfig(max_chunks_per_file=128))
    try:
        value.warm()
        value.wait_for_body_index(10)
        assert value._body_thread is None or not value._body_thread.is_alive()
        assert value._kw_index_built and (value._body_index_built or not require_body)
        yield value
    finally:
        value.close()


def identities(hits, located=True):
    return [(h.chunk_type, h.name,
             (h.start_line or h.definition_start_line) if located else 0,
             (h.end_line or h.definition_end_line) if located else 0)
            for h in hits if h.chunk_type in {'method', 'function'}]


@pytest.mark.parametrize('case', ['receivers', 'same-file', 'unsupported'])
@pytest.mark.parametrize('route', ['keyword', 'body', 'default', 'vector', 'fused'])
def test_go_receivers_agree_across_modalities(tmp_path, monkeypatch, record_property, case, route):
    files, expected = FILES, EXPECTED
    if case == 'same-file':
        files = {'methods.go': 'package p\ntype R struct{}\nfunc (r R) M(identity int) {}\n'
                               'func M(identity int) {}\n'}
        expected = {('method', 'R.M', 3, 3), ('function', 'M', 4, 4)}
    elif case == 'unsupported':
        files = {'methods.go': 'package p\nfunc (r **R) Odd(identity int) {}\n'}
        expected = {('function', 'Odd', 2, 2)}
    record_property('inputs', json.dumps(qualified_files(tmp_path, files)))
    provider, snapshots = Provider(), []
    for opening in range(2):
        with opened(tmp_path, monkeypatch, provider) as value:
            assert value._provider is None
            if route in {'vector', 'fused'}:
                if opening == 0:
                    assert value.index() > 0
                else:
                    value._ensure_provider()
                assert value._store.count() > 0
            if route == 'keyword':
                hits = value._keyword_search('identity', 128, 'methods.go')
            elif route == 'body':
                hits = value._body_search(['identity'], 128, 'methods.go')
            else:
                hits = value.search('identity', 128, 'methods.go', two_stage=route != 'vector',
                                    expand_query=False)
            assert hits
            if route in {'vector', 'fused'}:
                assert provider.queries
            else:
                assert value._provider is None
            snapshots.append([asdict(h) for h in hits])
    record_property('hits', json.dumps(snapshots))
    record_property('qualified_input', 'true')
    record_property('observed', json.dumps(snapshots))
    wanted = expected if route != 'vector' else {(kind, name, 0, 0) for kind, name, _, _ in expected}
    for snapshot in snapshots:
        actual = [(h['chunk_type'], h['name'],
                   (h['start_line'] or h['definition_start_line']) if route != 'vector' else 0,
                   (h['end_line'] or h['definition_end_line']) if route != 'vector' else 0)
                  for h in snapshot if h['chunk_type'] in {'function', 'method'}]
        assert set(actual) == wanted and len(actual) == len(wanted), 'REGRESSION: Go search modalities disagree on receiver identity'


def cache_rows(path, file):
    with sqlite3.connect(path) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} WHERE file_path=? ORDER BY 1', (file,)).fetchall()
                for table in ['kw_docs', 'kw_files', 'body_fts', 'body_files', 'body_file_fts']}


def seed_legacy(root, monkeypatch):
    qualified_files(root, FILES)
    (root/'unrelated.py').write_text('def untouched(identity):\n    return identity\n')
    with opened(root, monkeypatch) as value:
        path = value._kw_cache_db_path
    with sqlite3.connect(path) as conn:
        # The old schema4/body5 format has no Go-identity migration markers.
        conn.execute("DELETE FROM metadata WHERE key NOT IN ('schema_version','body_schema_version')")
        for _, name, first, last in EXPECTED:
            if '.' not in name:
                continue
            bare = name.rsplit('.', 1)[1]
            # A same-file Go method may appear in both the legacy function
            # and class lists. Seed one literal legacy owner without trying
            # to assign the same primary key to two existing cache rows.
            selected = conn.execute(
                'SELECT id FROM kw_docs WHERE file_path=? AND start_line=? ORDER BY id LIMIT 1',
                ('methods.go', first),
            ).fetchone()
            assert selected is not None
            conn.execute('DELETE FROM kw_docs WHERE file_path=? AND start_line=? AND id!=?',
                         ('methods.go', first, selected[0]))
            conn.execute('UPDATE kw_docs SET id=?,chunk_type=?,name=?,text=? WHERE file_path=? AND start_line=?',
                         (f'func:methods.go:{bare}:{first}:{last}', 'function', bare,
                          f'function {bare} (identity)', 'methods.go', first))
            conn.execute('UPDATE body_fts SET chunk_type=?,name=? WHERE file_path=? AND start_line=?',
                         ('function', bare, 'methods.go', first))
    return path


def test_unchanged_go_lexical_caches_repair_once(tmp_path, monkeypatch, record_property):
    path = seed_legacy(tmp_path, monkeypatch)
    stamps = {p.name:p.stat().st_mtime_ns for p in tmp_path.iterdir() if p.is_file()}
    untouched = cache_rows(path, 'unrelated.py')
    parsed, snapshots, parse_counts = [], [], []
    from attocode_intel._internal.integrations.context import codebase_ast
    original = codebase_ast.parse_file

    def counted(file, *args, **kwargs):
        parsed.append(str(file))
        return original(file, *args, **kwargs)

    monkeypatch.setattr(codebase_ast, 'parse_file', counted)
    for _ in range(2):
        with opened(tmp_path, monkeypatch) as value:
            snapshots.append({'keyword':identities(value._keyword_search('identity',128,'methods.go')),
                              'body':identities(value._body_search(['identity'],128,'methods.go'))})
        assert cache_rows(path, 'unrelated.py') == untouched
        parse_counts.append(len(parsed))
    assert all(p.stat().st_mtime_ns == stamps[p.name] for p in tmp_path.iterdir() if p.is_file())
    record_property('hits', json.dumps(snapshots))
    record_property('parse_calls', json.dumps(parsed))
    record_property('qualified_input', 'true')
    record_property('observed', json.dumps(snapshots))
    correct = all(set(s[route]) == EXPECTED for s in snapshots for route in ['keyword','body'])
    assert correct and not any(p.endswith('unrelated.py') for p in parsed) and parse_counts[0] == parse_counts[1], 'REGRESSION: unchanged Go lexical caches stayed legacy'


@pytest.mark.parametrize('schema', ['schema_version', 'body_schema_version'])
def test_future_lexical_cache_stays_unmodified(tmp_path, monkeypatch, record_property, schema):
    path = seed_legacy(tmp_path, monkeypatch)
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE metadata SET value=? WHERE key=?', ('999',schema))
    from pathlib import Path
    before = Path(path).read_bytes()
    with opened(tmp_path, monkeypatch, require_body=False) as value:
        hits = value.search('identity',128,'methods.go',expand_query=False)
        assert value._provider is None
    after = Path(path).read_bytes()
    record_property('qualified_input', 'true')
    record_property('observed', json.dumps({'schema':schema,'unchanged':before==after,'hits':[asdict(h) for h in hits]}))
    assert before == after, 'REGRESSION: future lexical cache was modified'


@pytest.mark.parametrize('case', ['java-overloads', 'long-method', 'anonymous', 'macro'])
def test_vector_fusion_preserves_distinct_lexical_spans(tmp_path, monkeypatch, record_property, case):
    filename, text, query = 'Parser.java', JAVA, 'parse'
    if case == 'long-method':
        filename, query = 'worker.py', 'quota'
        text = 'class Worker:\n    def quota(self):\n' + '        quota = 1\n'*100
    elif case == 'anonymous':
        filename, query = 'callbacks.js', 'retry quota'
        text = 'import {expect} from "test";\n' + ''.join(
            f'it("retry quota case{n}", function() {{\n  expect(quota).toEqual({n});\n}});\n' for n in range(40))
    elif case == 'macro':
        filename, query = 'cases.rs', 'retry quota'
        text = 'use crate::quota;\n' + ''.join(
            f'rgtest!(retry_quota_{n}, |dir, cmd| {{\n  cmd.arg("quota");\n}});\n' for n in range(40))
    record_property('inputs', json.dumps(qualified_files(tmp_path, {filename:text})))
    provider = Provider()
    with opened(tmp_path, monkeypatch, provider) as value:
        lexical = value.search_candidates(query,128,filename)
        spans = {(h.name,h.start_line,h.end_line) for h in lexical if h.start_line}
        assert len(spans) >= (2 if case=='java-overloads' else 3)
        if case=='java-overloads':
            assert {(first,last) for name,first,last in spans if name=='Parser.parse'} == {(2,4),(5,7)}
        assert value.index() > 0
        fused = value.search(query,128,filename,expand_query=False)
        assert provider.queries
    actual = {(h.name,h.start_line,h.end_line) for h in fused if h.start_line}
    record_property('qualified_input', 'true')
    record_property('observed', json.dumps({'lexical':[asdict(h) for h in lexical], 'fused':[asdict(h) for h in fused]}))
    assert spans <= actual, 'REGRESSION: vector fusion collapsed distinct lexical spans'


def test_missing_go_parser_keeps_fallback_conservative(tmp_path, monkeypatch, record_property):
    qualified_files(tmp_path, FILES)
    monkeypatch.setattr(ts_parser, '_get_parser', lambda *a,**k: None)
    with opened(tmp_path, monkeypatch) as value:
        hits = value.search('identity',128,'methods.go',expand_query=False)
        assert hits and value._provider is None
    record_property('qualified_input', 'true')
    record_property('observed', json.dumps([asdict(h) for h in hits]))
    assert not any(h.chunk_type=='method' and h.name in {'A.M','B.M','Box.Get','Ω.read'} for h in hits)
