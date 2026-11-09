"""Source and transaction boundaries around real optional vector writes."""
import json
import os
import sqlite3
import struct
import threading
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
from test_live_vector_freshness import NEW, rows, workspace, writer

LATEST = 'def renewed():\n    return "lastfalcon"\n'


@pytest.mark.parametrize('change', ['edit', 'same-mtime', 'unnotified', 'delete', 'rename'])
def test_superseded_embedding_never_commits(tmp_path, monkeypatch, record_property, change):
    with workspace(tmp_path, monkeypatch) as s:
        before = rows(s.value)
        path = tmp_path / 'target.py'
        path.write_text(NEW)
        entered, release = threading.Event(), threading.Event()
        original = s.provider.embed
        def blocked(texts):
            entered.set()
            assert release.wait(3)
            return original(texts)
        s.provider.embed = blocked
        errors = []
        def run():
            try:
                s.value.reindex_file(str(path))
            except Exception as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert entered.wait(3), 'Real embedding provider was not reached'
            stamp = path.stat()
            if change == 'delete':
                path.unlink()
            elif change == 'rename':
                path.rename(tmp_path / 'renamed.py')
            else:
                path.write_text(LATEST)
                if change == 'same-mtime':
                    assert len(NEW.encode()) == len(LATEST.encode())
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            if change != 'unnotified':
                s.value.invalidate_file(str(path))
        finally:
            release.set()
            thread.join(3)
        assert not thread.is_alive()
        actual = rows(s.value)
        metadata = s.value._store.get_file_metadata('target.py')
        record_property('observed', json.dumps({'before': before, 'after': actual,
                                               'metadata': metadata, 'errors': errors,
                                               'embed_calls': s.provider.calls}))
        record_property('qualified_input', 'true')
        expected = [] if change in {'delete', 'rename'} else before
        assert not errors and actual == expected, 'REGRESSION: superseded embedding overwrote notified source'
        if change in {'delete', 'rename'}:
            assert metadata is None


@pytest.mark.parametrize('failure', ['vector', 'metadata'])
def test_vectors_and_metadata_rollback_together(tmp_path, monkeypatch, record_property, failure):
    with workspace(tmp_path, monkeypatch) as s:
        before, metadata = rows(s.value), s.value._store.get_file_metadata('target.py')
        conn = s.value._store._get_conn()
        if failure == 'vector':
            conn.execute("CREATE TRIGGER fail_replacement BEFORE INSERT ON vectors WHEN NEW.id LIKE '%:updated' BEGIN SELECT RAISE(ABORT,'blocked vector'); END")
        else:
            conn.execute("CREATE TRIGGER fail_metadata BEFORE INSERT ON file_metadata WHEN NEW.file_path='target.py' BEGIN SELECT RAISE(ABORT,'blocked metadata'); END")
        conn.commit()
        (tmp_path / 'target.py').write_text(NEW)
        error = None
        try:
            s.value.reindex_file(str(tmp_path / 'target.py'))
        except sqlite3.DatabaseError as exc:
            error = str(exc)
        after = rows(s.value)
        after_metadata = s.value._store.get_file_metadata('target.py')
        transaction_open = conn.in_transaction
        conn.rollback()
        assert error is not None and any('updated' in t for batch in s.provider.calls for t in batch)
        record_property('observed', json.dumps({'before': before, 'after': after, 'metadata': metadata,
                                               'after_metadata': after_metadata, 'error': error,
                                               'transaction_open': transaction_open}))
        record_property('qualified_input', 'true')
        assert after == before and metadata == after_metadata and not transaction_open, 'REGRESSION: vector metadata replacement was not atomic'


def test_second_edit_while_pending_gets_followup(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        entered, release, second = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def controlled(self, path):
            calls.append(str(path))
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)
            else:
                second.set()
            return 0
        monkeypatch.setattr(SemanticSearchManager, 'reindex_file', controlled)
        path = tmp_path / 'target.py'
        path.write_text(NEW)
        s.value.queue_reindex(str(path))
        try:
            assert entered.wait(3)
            path.write_text(LATEST)
            s.value.queue_reindex(str(path))
        finally:
            release.set()
        followed_up = second.wait(1)
        record_property('observed', json.dumps({'calls': calls, 'followed_up': followed_up}))
        record_property('qualified_input', 'true')
        assert followed_up and len(calls) == 2 and all(Path(p).name == 'target.py' for p in calls), 'REGRESSION: pending queue discarded second edit'


def test_close_drains_active_worker(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        entered, release = threading.Event(), threading.Event()
        def controlled(self, path):
            entered.set()
            assert release.wait(3)
            assert self._store._conn is not None
            return 0
        monkeypatch.setattr(SemanticSearchManager, 'reindex_file', controlled)
        s.value.queue_reindex(str(tmp_path / 'target.py'))
        assert entered.wait(3)
        closer = threading.Thread(target=s.value.close)
        closer.start()
        release.set()
        closer.join(3)
        assert not closer.is_alive() and not s.value._reindex_thread.is_alive()
        assert s.value._store._conn is None
        record_property('qualified_input', 'true')


@pytest.mark.parametrize('language', ['python', 'javascript'])
def test_duplicate_identity_keeps_last_body_and_correct_count(tmp_path, monkeypatch, record_property, language):
    with workspace(tmp_path, monkeypatch) as s:
        name = 'duplicate.py' if language == 'python' else 'duplicate.js'
        source = ('def same():\n    return "firstvalue"\ndef same():\n    return "lastvalue"\n'
                  if language == 'python' else
                  'function same() {\n return "firstvalue";\n}\nfunction same() {\n return "lastvalue";\n}\n')
        path = tmp_path / name
        path.write_text(source)
        ast = parse_file(str(path), source)
        assert sum(f.name == 'same' for f in ast.functions) == 2 and not ast.parse_failures
        original = s.provider.embed
        def tagged(texts):
            original(texts)
            return [[0.0, 1.0, 0.0] if 'lastvalue' in t else [1.0, 0.0, 0.0] for t in texts]
        s.provider.embed = tagged
        s.value.reindex_file(str(path))
        actual = rows(s.value, name)
        metadata = s.value._store.get_file_metadata(name)
        assert any('lastvalue' in t for batch in s.provider.calls for t in batch)
        record_property('observed', json.dumps({'rows': actual, 'metadata': metadata}))
        record_property('qualified_input', 'true')
        assert len(actual) == 2 and metadata['chunk_count'] == 2, 'REGRESSION: duplicate IDs overstated indexed chunks'
        assert next(r[4] for r in actual if r[0].endswith(':same')) == struct.pack('<3f', 0, 1, 0).hex().upper()


@pytest.mark.parametrize('route', ['full', 'file', 'background'])
def test_empty_valid_file_commits_zero_chunk_metadata(tmp_path, monkeypatch, record_property, route):
    with workspace(tmp_path, monkeypatch) as s:
        (tmp_path / 'target.py').write_text('')
        s.value._store.set_file_metadata('target.py', 0.0, 2)
        s.provider.calls.clear()
        writer(s, route)
        actual, metadata = rows(s.value), s.value._store.get_file_metadata('target.py')
        record_property('observed', json.dumps({'rows': actual, 'metadata': metadata}))
        record_property('qualified_input', 'true')
        assert not actual and metadata is not None and metadata['chunk_count'] == 0, 'REGRESSION: empty source was not durably indexed'
        assert not s.provider.calls


def test_reindex_rejects_outside_workspace(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        outside = tmp_path.parent / (tmp_path.name + '-outside.py')
        outside.write_text('def outside():\n    return 1\n')
        s.provider.calls.clear()
        try:
            s.value.reindex_file(str(outside))
            paths = s.value._store._get_conn().execute('SELECT DISTINCT file_path FROM vectors').fetchall()
            record_property('observed', json.dumps(paths))
            record_property('qualified_input', 'true')
            assert not s.provider.calls and all(not p[0].startswith('..') for p in paths), 'REGRESSION: reindex accepted outside workspace'
        finally:
            outside.unlink()


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
def test_incomplete_native_source_preserves_prior_vectors(tmp_path, monkeypatch, record_property, language):
    with workspace(tmp_path, monkeypatch) as s:
        name = {'python': 'target.py', 'javascript': 'target.js', 'typescript': 'target.ts'}[language]
        path = tmp_path / name
        if language != 'python':
            path.write_text('function original() {\n return 1;\n}\n')
            s.value.reindex_file(str(path))
        before, metadata = rows(s.value, name), s.value._store.get_file_metadata(name)
        assert len(before) == 2
        source = 'def broken(' if language == 'python' else 'function broken('
        path.write_text(source)
        tree = syntax_tree(str(path), source, language)
        assert tree is not None and tree.root_node.has_error
        s.value.reindex_file(str(path))
        actual, after_metadata = rows(s.value, name), s.value._store.get_file_metadata(name)
        record_property('observed', json.dumps({'before': before, 'after': actual, 'metadata': metadata,
                                               'after_metadata': after_metadata, 'tree': str(tree.root_node)}))
        record_property('qualified_input', 'true')
        assert actual == before and metadata == after_metadata, 'REGRESSION: malformed native source erased vectors'


def test_other_connection_observes_vector_publication(tmp_path, monkeypatch, record_property):
    from attocode_intel._internal.integrations.context import vector_store
    assert vector_store._HAS_NUMPY
    with workspace(tmp_path, monkeypatch) as s:
        second = SemanticSearchManager(str(tmp_path), nl_mode='none')
        try:
            second._ensure_provider()
            old = second.search('original', 10, 'target.py', two_stage=False, expand_query=False)
            assert any(h.name == 'original' for h in old) and second._store._vec_meta
            (tmp_path / 'target.py').write_text(NEW)
            s.value.reindex_file(str(tmp_path / 'target.py'))
            assert {r[0] for r in rows(second)} == {'file:target.py', 'func:target.py:updated'}
            actual = second.search('updated', 10, 'target.py', two_stage=False, expand_query=False)
            record_property('observed', json.dumps({'before': [h.name for h in old], 'after': [h.name for h in actual]}))
            record_property('qualified_input', 'true')
            assert any(h.name == 'updated' for h in actual) and all(h.name != 'original' for h in actual), 'REGRESSION: second connection served old vector matrix'
        finally:
            second.close()


def test_cache_loader_keeps_the_version_of_its_rows(tmp_path, monkeypatch, record_property):
    from attocode_intel._internal.integrations.context import vector_store
    assert vector_store._HAS_NUMPY
    with workspace(tmp_path, monkeypatch) as s:
        loaded, release = threading.Event(), threading.Event()
        original = vector_store.np.vstack
        def blocked(arrays):
            loaded.set()
            assert release.wait(3)
            return original(arrays)
        monkeypatch.setattr(vector_store.np, 'vstack', blocked)
        errors = []
        def search():
            try:
                s.value._store.search([1.0, 0.0, 0.0], file_filter='target.py')
            except Exception as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=search)
        thread.start()
        try:
            assert loaded.wait(3)
            (tmp_path / 'target.py').write_text(NEW)
            s.value.reindex_file(str(tmp_path / 'target.py'))
        finally:
            release.set()
            thread.join(3)
        assert not errors and not thread.is_alive()
        actual = s.value._store.search([1.0, 0.0, 0.0], file_filter='target.py')
        assert {r[0] for r in rows(s.value)} == {'file:target.py', 'func:target.py:updated'}
        record_property('observed', json.dumps({'after': [h.name for h in actual],
                                               'loaded_version': s.value._store._vec_loaded_version,
                                               'current_version': s.value._store._vec_cache_version}))
        record_property('qualified_input', 'true')
        assert any(h.name == 'updated' for h in actual) and all(h.name != 'original' for h in actual), 'REGRESSION: cache loader published old rows as new'


@pytest.mark.parametrize('refusal', ['rotation', 'dimension', 'sqlite'])
def test_optional_write_refusal_does_not_abort_freshness(tmp_path, monkeypatch, record_property, refusal):
    from test_live_vector_freshness import current_lexical
    with workspace(tmp_path, monkeypatch) as s:
        before = rows(s.value)
        conn = s.value._store._get_conn()
        if refusal == 'rotation':
            conn.execute("INSERT OR REPLACE INTO store_metadata VALUES ('rotation_state','pending')")
            conn.commit()
        elif refusal == 'dimension':
            s.value._store.degraded = True
        else:
            conn.execute("CREATE TRIGGER block_dirty BEFORE INSERT ON file_states BEGIN SELECT RAISE(ABORT,'blocked dirty state'); END")
            conn.commit()
        (tmp_path / 'target.py').write_text(NEW)
        error = None
        try:
            s.tracker.refresh(s.service)
        except Exception as exc:
            error = str(exc)
        actual = rows(s.value)
        assert [d.name for d in s.ast.get_file_symbols('target.py')] == ['updated']
        record_property('observed', json.dumps({'error': error, 'before': before, 'after': actual}))
        record_property('qualified_input', 'true')
        assert error is None and actual == before, 'REGRESSION: optional vector refusal aborted source freshness'
        assert current_lexical(s.value)


@pytest.mark.parametrize('source', ['function broken(', 'console.log("ready");', ''], ids=['malformed', 'unvalidated-nonempty', 'blank-control'])
def test_missing_parser_cannot_certify_nonempty_replacement(tmp_path, monkeypatch, record_property, source):
    from attocode_intel._internal.integrations.context import ts_parser
    with workspace(tmp_path, monkeypatch) as s:
        path = tmp_path / 'target.js'
        path.write_text('function original() {\n return 1;\n}\n')
        s.value.reindex_file(str(path))
        before, metadata = rows(s.value, 'target.js'), s.value._store.get_file_metadata('target.js')
        path.write_text(source)
        monkeypatch.setattr(ts_parser, '_get_parser', lambda language: None)
        ast = parse_file(str(path), source)
        assert ast.parsing_tier == 'regex' and not ast.parse_failures and not ast.functions
        s.value.reindex_file(str(path))
        actual, after_metadata = rows(s.value, 'target.js'), s.value._store.get_file_metadata('target.js')
        record_property('observed', json.dumps({'before': before, 'after': actual, 'metadata': metadata,
                                               'after_metadata': after_metadata, 'tier': ast.parsing_tier, 'source': source}))
        record_property('qualified_input', 'true')
        if not source:
            assert not actual and after_metadata['chunk_count'] == 0
        else:
            assert actual == before and after_metadata == metadata, 'REGRESSION: parser absence certified nonempty empty source'


def test_generic_native_error_does_not_replace_vectors(tmp_path, monkeypatch, record_property):
    from attocode_intel._internal.integrations.context import ts_parser
    with workspace(tmp_path, monkeypatch) as s:
        path = tmp_path / 'target.c'
        path.write_text('int original(void) {\n return 1;\n}\n')
        s.value.reindex_file(str(path))
        before, metadata = rows(s.value, 'target.c'), s.value._store.get_file_metadata('target.c')
        assert len(before) == 2
        source = 'int broken('
        path.write_text(source)
        primary = ts_parser.ts_parse_file
        monkeypatch.setattr(ts_parser, 'ts_parse_file', lambda file_path, **kw:
                            None if str(file_path) == str(path) else primary(file_path, **kw))
        ast = parse_file(str(path), source)
        tree = syntax_tree(str(path), source, 'c')
        assert ast.parsing_tier == 'generic_ts' and not ast.parse_failures
        assert tree is not None and tree.root_node.has_error
        s.value.reindex_file(str(path))
        actual, after_metadata = rows(s.value, 'target.c'), s.value._store.get_file_metadata('target.c')
        record_property('observed', json.dumps({'before': before, 'after': actual, 'metadata': metadata,
                                               'after_metadata': after_metadata, 'tier': ast.parsing_tier,
                                               'tree': str(tree.root_node)}))
        record_property('qualified_input', 'true')
        assert actual == before and after_metadata == metadata, 'REGRESSION: generic syntax errors erased vectors'


def test_manager_reconciles_newer_durable_revision(tmp_path, monkeypatch, record_property):
    with workspace(tmp_path, monkeypatch) as s:
        other = SemanticSearchManager(str(tmp_path), nl_mode='none')
        try:
            other._ensure_provider()
            path = tmp_path / 'target.py'
            path.write_text(NEW)
            s.value.invalidate_file(str(path))
            assert 'target.py' in s.value._invalidated_files
            other.reindex_file(str(path))
            state = s.value._store.get_file_states()['target.py']
            assert not state['dirty'] and {r[0] for r in rows(s.value)} == {'file:target.py', 'func:target.py:updated'}
            calls = len(s.provider.calls)
            assert s.value.reindex_stale_files() == 0 and len(s.provider.calls) == calls
            progress = s.value.get_index_progress()
            record_property('observed', json.dumps({'state': state, 'indexed_files': progress.indexed_files,
                                                   'invalidated': sorted(s.value._invalidated_files)}))
            record_property('qualified_input', 'true')
            assert progress.indexed_files == 2 and progress.coverage == 1.0 and 'target.py' not in s.value._invalidated_files, 'REGRESSION: memory invalidation hid newer durable revision'
        finally:
            other.close()
