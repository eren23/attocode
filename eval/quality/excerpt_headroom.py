"""Data-only source-budget probe. No retrieval, parser, model or fixture execution."""
from __future__ import annotations

import base64
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from urllib.parse import quote
from urllib.request import urlopen
import zipfile

ARCHIVE_SHA = 'b55778456790b76d9a5940a4faace0d70ba65bb3c33457d80fbfba34a1d4af3e'
INPUT_HEAD = 'aa19475254673bd3380fe6d5644a160a4bbba73a'
FIELDS = {'snippet', 'snippet_start_line', 'snippet_end_line', 'snippet_truncated'}


def load(path):
    return json.loads(path.read_bytes())


def read_events(folder):
    rows = []
    for line in (folder / 'events.jsonl').read_text().splitlines():
        event = json.loads(line)
        ref = event['response']
        assert ref['path'] == 'blobs/' + ref['sha256'] + '.json'
        body = (folder / ref['path']).read_bytes()
        assert len(body) == ref['bytes'] and hashlib.sha256(body).hexdigest() == ref['sha256']
        rows.append((event['request'], json.loads(body)))
    return rows


def expand(row, raw, policy):
    """Cap640 characters around the original floor, never relocate its evidence."""
    if not row.get('line') or not row.get('snippet') or policy['producer'] == 'metadata':
        return deepcopy(row)
    text = raw.decode('utf-8', errors=policy['errors'])
    if policy['newlines'] == 'universal':
        text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.splitlines(keepends=True)
    first, last = row['line'], row['end_line']
    assert 1 <= first <= row['snippet_start_line'] <= row['snippet_end_line'] <= last <= len(lines)
    selected = lines[first-1:last]
    body = ''.join(selected)
    offsets = [0]
    for line in selected:
        offsets.append(offsets[-1] + len(line))
    left = offsets[row['snippet_start_line']-first]
    right = offsets[row['snippet_end_line']-first+1]
    index = body.find(row['snippet'], left, right)
    while index >= 0:
        finish = index + len(row['snippet'])
        if index < offsets[row['snippet_start_line']-first+1] and finish > offsets[row['snippet_end_line']-first]:
            break
        index = body.find(row['snippet'], index+1, right)
    assert index >= 0
    if len(row['snippet']) >= 640:
        return deepcopy(row)
    begin = max(0, index - (640-len(row['snippet']))//2)
    end = min(len(body), begin+640)
    assert index+len(row['snippet']) <= end
    result = deepcopy(row)
    result.update(snippet=body[begin:end], snippet_start_line=first+bisect_right(offsets, begin)-1,
                  snippet_end_line=first+bisect_left(offsets, end)-1,
                  snippet_truncated=begin > 0 or end < len(body))
    return result


def visible(question, rows):
    def proof_seen(answer, proof):
        n = len(proof['quote'].splitlines())
        for row in rows:
            if row['file_path'] != answer['file'] or not row.get('snippet_start_line'):
                continue
            offset = proof['line'] - row['snippet_start_line']
            lines = row['snippet'].splitlines()
            if (0 <= offset and offset+n <= len(lines) and proof['line']+n-1 <= row['snippet_end_line']
                    and proof['quote'] in '\n'.join(lines[offset:offset+n])):
                return True
        return False
    return any(all(proof_seen(a,p) for p in a['proofs']) for a in question['answers'])


def run(root):
    from attocode_intel.output import compact_result, response_tokens, _restore_search_snippets
    from eval.quality.experiment_evidence import assert_engine
    from eval.quality.runner import REPO, write_json

    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    archive = Path(os.environ['EXCERPT_INPUT_ZIP'])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA
    folder = root / 'work/input'
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        assert len(infos) == len({i.filename for i in infos})
        assert sum(i.file_size for i in infos) < 64*2**20
        for i in infos:
            assert (folder/i.filename).resolve().is_relative_to(folder.resolve())
            assert not stat.S_ISLNK(i.external_attr >> 16)
        z.extractall(folder)
    evidence = next(folder.rglob('diagnostic.json')).parent
    outer = load(evidence/'report.json')
    assert outer['status'] == 'complete' and outer['cleanup_verified'] and outer['owned_scratch_removed']
    assert outer['identity']['commit'] == INPUT_HEAD
    question_bytes = subprocess.check_output(['git', 'show', INPUT_HEAD+':eval/quality/first_page_ranking_questions.json'])
    assert hashlib.sha256(question_bytes).hexdigest() == '80fa39767c93a0c22267f439256760ba0a746b3c663b14e046351794115d7b11'
    manifest = json.loads(question_bytes)
    tasks, cases = {}, []
    for group in manifest['repositories']:
        events = read_events(evidence/group['pack']/'journal')
        fixture = read_events(evidence/group['pack']/'fixture')[0][1]
        for q in group['questions']:
            if q['split'] != 'development':
                continue
            primary = next(data for event,data in events if event['event']=='primary' and event['id']==q['id'])
            request, response = next((event,data) for event,data in events if event['event']=='mcp_response'
                and event['arguments'].get('query')==q['query'] and event['arguments']['top_k']==10
                and event['arguments']['max_tokens']==2000)
            page = json.loads(response['content'][0]['text'])
            assert page == primary['page']
            policies = next(event['policies'] for event,data in events if event['event']=='source_validation'
                            and event['sequence']==request['sequence'])
            for row,policy in zip(page['data']['results'],policies,strict=True):
                if policy['producer'] == 'metadata':
                    continue
                path = row['file_path']
                assert path in fixture and fixture[path]['kind']=='file'
                assert policy['source_sha256']==fixture[path]['sha256']
                key = group['repo'],group['commit'],path
                tasks[key] = fixture[path]['sha256']
            cases.append((group,q,page,policies))
    def fetch(item):
        (repo,commit,path),expected = item
        assert len(commit)==40 and not Path(path).is_absolute() and '..' not in Path(path).parts
        url = 'https://raw.githubusercontent.com/'+repo+'/'+commit+'/'+quote(path,safe='/')
        with urlopen(url,timeout=25) as response:
            body = response.read(1_000_001)
        assert len(body)<=1_000_000 and hashlib.sha256(body).hexdigest()==expected
        return item[0],body
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(fetch,tasks.items()))
    rows=[]
    for group,q,page,policies in cases:
        originals=[]
        for row,policy in zip(page['data']['results'],policies,strict=True):
            raw = sources.get((group['repo'],group['commit'],row['file_path']),b'')
            originals.append(expand(row,raw,policy))
        old = compact_result(page['metadata'],page['data'])
        assert response_tokens(old)<=2000
        new = _restore_search_snippets(old, originals, 2000,
                                        upstream_truncated=page['metadata'].get('truncated',False))
        changed=json.loads(new.content[0].text)
        assert response_tokens(new)<=2000
        oldrows,newrows=page['data']['results'],changed['data']['results']
        assert len(oldrows)==len(newrows)
        for a,b in zip(oldrows,newrows,strict=True):
            assert {k:v for k,v in a.items() if k not in FIELDS}=={k:v for k,v in b.items() if k not in FIELDS}
            assert a['snippet'] in b['snippet']
        row={'id':q['id'],'pack':group['pack'],'before':visible(q,oldrows),'after':visible(q,newrows),
             'tokens_before':response_tokens(old),'tokens_after':response_tokens(new),
             'chars_before':sum(len(r['snippet']) for r in oldrows),
             'chars_after':sum(len(r['snippet']) for r in newrows),
             'page_before':page,'page_after':changed}
        assert not row['before'] or row['after']
        rows.append(row)
    assert len(rows)==24 and len({r['id'] for r in rows})==24
    gains=[r for r in rows if r['after'] and not r['before']]
    result={'status':'complete','scope':'Consumed retained-data mechanical headroom, no fresh queries or relevance verdict',
            'input_run':42234153782,'input_sha256':ARCHIVE_SHA,'queries_issued':0,'holdout_issued':0,
            'source_files':len(sources),'rows':rows,'gain_ids':[r['id'] for r in gains],
            'eligible':len(gains)>=2 and len({r['pack'] for r in gains})>=2,
            'origins':assert_engine(REPO/'packages/code-intel/src/attocode_intel')}
    write_json(root/'evidence/headroom.json',result)
