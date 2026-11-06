"""Temporary data-only token accounting on consumed, immutable response bytes."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import zipfile


def run(root):
    from mcp import types
    from attocode_intel.output import response_tokens, _compact_search_ranking
    from eval.quality.experiment_evidence import assert_engine
    from eval.quality.runner import REPO, write_json
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    archive = Path(os.environ['RANKING_INPUT_ZIP'])
    archive_sha = 'b55778456790b76d9a5940a4faace0d70ba65bb3c33457d80fbfba34a1d4af3e'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha
    with zipfile.ZipFile(archive) as z:
        assert sum(i.file_size for i in z.infolist()) < 64*2**20
        cases = []
        journals = [n for n in z.namelist() if n.endswith('/journal/events.jsonl')]
        assert len(journals) == 6
        for name in journals:
            events = []
            for line in z.read(name).splitlines():
                event = json.loads(line)
                ref = event['response']
                assert ref['path'] == 'blobs/' + ref['sha256'] + '.json'
                raw = z.read(str(Path(name).parent / ref['path']))
                assert len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
                events.append((event['request'], json.loads(raw)))
            for request, primary in events:
                if request['event'] != 'primary':
                    continue
                matches = [response for event, response in events
                           if event['event'] == 'mcp_response'
                           and event['arguments'].get('top_k') == 10
                           and event['arguments'].get('max_tokens') == 2000
                           and json.loads(response['content'][0]['text']) == primary['page']]
                assert len(matches) == 1, request['id']
                cases.append((request['id'], matches[0]))
    rows=[]
    for case_id, response in cases:
        # Preserve the original JSON field order: the derived report sorts keys,
        # which changes BPE token counts despite an equal decoded page.
        old=types.CallToolResult.model_validate(response)
        page=json.loads(old.content[0].text)
        new=_compact_search_ranking(old,2000)
        after=json.loads(new.content[0].text)
        assert after['data']==page['data']
        assert {k:v for k,v in after['metadata'].items() if k!='ranking'} == {
            k:v for k,v in page['metadata'].items() if k!='ranking'}
        assert {k:v for k,v in after['metadata']['ranking'].items() if k!='index'} == {
            k:v for k,v in page['metadata']['ranking'].items() if k!='index'}
        assert after['data']['ranking']['index']==page['data']['ranking']['index']
        assert response_tokens(new)<=response_tokens(old)<=2000, (case_id,response_tokens(old),response_tokens(new))
        rows.append({'id':case_id,'before':response_tokens(old),'after':response_tokens(new),
                     'saved':response_tokens(old)-response_tokens(new),'data_unchanged':True})
    assert len(rows)==24 and len({r['id'] for r in rows})==24
    assert all(r['saved']>0 for r in rows)
    report={'status':'complete','rows':rows,'queries_issued':0,'holdout_issued':0,
            'source':'Known retained bytes, not fresh relevance or task-speed evidence',
            'input_run':42234153782, 'input_sha256':archive_sha,
            'median_tokens_saved':statistics.median(r['saved'] for r in rows),
            'total_tokens_saved':sum(r['saved'] for r in rows),
            'origins':assert_engine(REPO/'packages/code-intel/src/attocode_intel')}
    write_json(root/'evidence/ranking-summary.json',report)
