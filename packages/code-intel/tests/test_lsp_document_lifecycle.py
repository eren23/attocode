"""Document ownership must be shared across warmup, precision and edit callers."""
import sys

import pytest
from attocode_intel._internal.integrations.lsp.client import LanguageServerConfig, _LSPClient

SERVER = r'''
import json,sys
states={};errors=[];events=[]
def send(mid,result):
    raw=json.dumps({'jsonrpc':'2.0','id':mid,'result':result}).encode()
    sys.stdout.buffer.write(f'Content-Length: {len(raw)}\r\n\r\n'.encode()+raw);sys.stdout.buffer.flush()
while True:
    header=sys.stdin.buffer.readline()
    if not header:break
    size=int(header.split(b':')[1])
    while sys.stdin.buffer.readline().strip():pass
    msg=json.loads(sys.stdin.buffer.read(size));method=msg.get('method');p=msg.get('params') or {}
    if method=='exit':break
    if method in ('textDocument/didOpen','textDocument/didChange','textDocument/didClose'):
        doc=p['textDocument'];uri=doc['uri'];events.append(method)
        if method.endswith('didOpen'):
            if uri in states:errors.append('duplicate open')
            states[uri]={'version':doc['version'],'text':doc['text']}
        elif method.endswith('didChange'):
            if uri not in states:errors.append('change before open')
            elif doc['version']<=states[uri]['version']:errors.append('non-increasing version')
            states[uri]={'version':doc['version'],'text':p['contentChanges'][0]['text']}
        else:
            if uri not in states:errors.append('unbalanced close')
            states.pop(uri,None)
    if 'id' in msg:
        result={'capabilities':{}} if method=='initialize' else {'states':states,'errors':errors,'events':events}
        send(msg['id'],result)
'''


@pytest.mark.asyncio
async def test_shared_document_notifications_are_balanced_and_versions_increase(tmp_path):
    server = tmp_path / 'server.py'
    server.write_text(SERVER)
    client = _LSPClient(LanguageServerConfig(command=sys.executable, args=[str(server)], language_id='rust'), tmp_path.as_uri())
    uri = (tmp_path / 'first.rs').as_uri()
    payload = 'π🙂\ud800'  # JSON can carry an unpaired UTF-16 code unit too.
    await client.start()
    try:
        client.notify_document_open(uri, 'first')
        client.notify_document_open(uri, 'first')  # precision after external warmup
        client.notify_document_change(uri, 'second', 2)
        client.notify_document_change(uri, 'second', 2)  # same edit from two callers
        client.notify_document_change(uri, 'third', 2)  # caller-local version is stale
        client.notify_document_open(uri, 'fourth')  # refresh through another owner
        state = await client._request('quality/state', {})
        assert state['errors'] == []
        assert state['states'][uri] == {'text': 'fourth', 'version': 4}
        assert state['events'].count('textDocument/didOpen') == 1
        assert state['events'].count('textDocument/didChange') == 3
        client.notify_document_close(uri)
        client.notify_document_close(uri)
        client.notify_document_change(uri, payload, 7)
        client.notify_document_open(uri, payload)
        client.notify_document_change(uri, payload + 'changed', 7)
        state = await client._request('quality/state', {})
        assert state['errors'] == []
        assert state['states'][uri]['text'] == payload + 'changed'
        assert state['events'].count('textDocument/didClose') == 1
        assert state['events'].count('textDocument/didOpen') == 2
    finally:
        await client.stop()
    # Reusing the client after a process restart must send a new open.
    await client.start()
    try:
        client.notify_document_open(uri, payload)
        state = await client._request('quality/state', {})
        assert state['errors'] == [] and uri in state['states']
        assert state['events'] == ['textDocument/didOpen']
    finally:
        await client.stop()
