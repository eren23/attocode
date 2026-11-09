"""Future-cache refusal and metadata-only fusion keep prior evidence intact."""
import hashlib
import json
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest
from test_go_search_identity import Provider, opened, seed_legacy


@pytest.mark.parametrize('schema', ['schema_version','body_schema_version'])
def test_future_delete_journal_cache_stays_untouched(tmp_path, monkeypatch, record_property, schema):
    path = Path(seed_legacy(tmp_path, monkeypatch))
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('UPDATE metadata SET value=? WHERE key=?', ('999',schema))
        conn.commit()
        assert conn.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
        assert conn.execute('SELECT value FROM metadata WHERE key=?',(schema,)).fetchone() == ('999',)
    path.chmod(0o640)
    before = path.read_bytes()
    with opened(tmp_path,monkeypatch,require_body=False) as value:
        assert value._provider is None
    after = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    record_property('qualified_input','true')
    record_property('observed',json.dumps({'before_sha256':hashlib.sha256(before).hexdigest(),
                                         'after_sha256':hashlib.sha256(after).hexdigest(),'mode':oct(mode)}))
    assert before == after and mode == 0o640, 'REGRESSION: future cache mutated before refusal'


def test_metadata_only_fusion_preserves_vector_text(tmp_path,monkeypatch,record_property):
    source = 'def preserve(identity):\n    """Retain the vector evidence detail."""\n    return identity\n'
    (tmp_path/'single.py').write_text(source)
    provider = Provider()
    with opened(tmp_path,monkeypatch,provider) as value:
        assert value.index() > 0
        value._body_index_available = False
        metadata = [hit for hit in value._keyword_search('identity',128,'single.py')
                    if hit.name == 'preserve']
        assert len(metadata) == 1 and metadata[0].start_line == 0
        assert (metadata[0].definition_start_line,metadata[0].definition_end_line) == (1,3)
        stored = value._store._get_conn().execute(
            'SELECT text FROM vectors WHERE id=?',('func:single.py:preserve',)).fetchone()[0]
        assert stored != metadata[0].text
        hits = [hit for hit in value.search('identity',128,'single.py',expand_query=False)
                if hit.name == 'preserve' and hit.chunk_type == 'function']
        assert provider.queries
    record_property('qualified_input','true')
    record_property('observed',json.dumps({'stored_vector_text':stored,'metadata_text':metadata[0].text,
                                         'fused_texts':[hit.text for hit in hits]}))
    assert len(hits) == 1 and hits[0].text == stored, 'REGRESSION: metadata-only fusion replaced vector evidence'
