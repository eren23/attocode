"""Temporary data-only token accounting on consumed, immutable response bytes."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import zipfile


def run(root):
    from attocode_intel.output import compact_result, response_tokens, _compact_search_ranking
    from eval.quality.experiment_evidence import assert_engine
    from eval.quality.runner import REPO, write_json
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    archive = Path(os.environ['RANKING_INPUT_ZIP'])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == '02c15442e09616bd9cdef7453cfadc6a817a9cc7947b17f70f62ed43b50d7ecc'
    with zipfile.ZipFile(archive) as z:
        assert sum(i.file_size for i in z.infolist()) < 16*2**20
        names = [n for n in z.namelist() if Path(n).name == 'headroom.json']
        assert len(names) == 1
        inputs = json.loads(z.read(names[0]))
    assert inputs['status'] == 'complete' and inputs['queries_issued'] == inputs['holdout_issued'] == 0
    rows=[]
    for row in inputs['rows']:
        page=row['page_before']  # Never replay the closed source-growth mechanism.
        old=compact_result(page['metadata'],page['data'])
        new=_compact_search_ranking(old,2000)
        after=json.loads(new.content[0].text)
        assert after['data']==page['data']
        assert {k:v for k,v in after['metadata'].items() if k!='ranking'} == {
            k:v for k,v in page['metadata'].items() if k!='ranking'}
        assert {k:v for k,v in after['metadata']['ranking'].items() if k!='index'} == {
            k:v for k,v in page['metadata']['ranking'].items() if k!='index'}
        assert after['data']['ranking']['index']==page['data']['ranking']['index']
        assert response_tokens(new)<=response_tokens(old)<=2000
        rows.append({'id':row['id'],'before':response_tokens(old),'after':response_tokens(new),
                     'saved':response_tokens(old)-response_tokens(new),'data_unchanged':True})
    assert len(rows)==24 and len({r['id'] for r in rows})==24
    assert all(r['saved']>0 for r in rows)
    report={'status':'complete','rows':rows,'queries_issued':0,'holdout_issued':0,
            'source':'Known retained bytes, not fresh relevance or task-speed evidence',
            'median_tokens_saved':statistics.median(r['saved'] for r in rows),
            'total_tokens_saved':sum(r['saved'] for r in rows),
            'origins':assert_engine(REPO/'packages/code-intel/src/attocode_intel')}
    write_json(root/'evidence/ranking-summary.json',report)
