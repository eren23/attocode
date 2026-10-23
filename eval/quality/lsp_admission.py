"""Source-bound admission of the existing Rust real-server diagnostic fixture."""
import base64
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

SOURCES = ('eval/quality/lsp_trace.py',
           'packages/code-intel/src/attocode_intel/_internal/integrations/lsp/client.py',
           'packages/code-intel/tests/test_real_language_server.py')


def expected_sources():
    root = Path(__file__).resolve().parents[2]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}



TRACE_SOURCE_PATHS = SOURCES


class CaptureError(ValueError):
    """Required native diagnostic evidence is invalid or incomplete."""


TRACE_STAGES = ('warmup', 'selected_original', 'unused_namesake', 'edit_delivery',
                'selected_after_edit', 'original_after_retarget', 'shutdown')


RUST_FILES = {'src/first.rs': 'pub fn helper() -> i32 { 1 }\n',
              'src/second.rs': 'pub fn helper() -> i32 { 2 }\n',
              'src/lib.rs': 'pub mod first;\npub mod second;\npub fn caller() -> i32 { first::helper() }\n'}


RUST_CHANGED = 'pub mod first;\npub mod second;\n\npub fn caller() -> i32 { second::helper() }\n'


def require(condition, message):
    if not condition:
        raise CaptureError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate diagnostic JSON key: {key}')
        result[key] = value
    return result


def reject_constant(value):
    raise CaptureError(f'nonfinite diagnostic JSON number: {value}')


def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), 'nonfinite diagnostic JSON float')
    return parsed


def verify_diagnostic(raw, sources):
    try:
        return _verify_diagnostic(raw, sources)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise CaptureError(f'malformed diagnostic: {type(error).__name__}: {error}') from error


def _verify_diagnostic(raw, sources):
    require(len(raw) <= 4 * 2**20 and raw.endswith(b'\n'), 'oversize/incomplete diagnostic JSONL')
    lines = raw.decode('utf-8', errors='strict').splitlines()
    require(lines and all(lines), 'empty diagnostic JSONL row')
    rows = [json.loads(line, object_pairs_hook=strict_object, parse_constant=reject_constant,
                       parse_float=finite_float) for line in lines]
    require(all(isinstance(row, dict) for row in rows), 'diagnostic rows must be objects')
    header, footer = rows[0], rows[-1]
    require(header['kind'] == 'trace_start' and type(header['schema_version']) is int
            and header['schema_version'] == 1 and header['stage'] == 'setup', 'diagnostic header/schema')
    require(footer['kind'] == 'trace_end' and footer['status'] == 'passed'
            and footer['first_failure'] is None and footer['truncated'] is False, 'diagnostic did not fully pass')
    require(all(type(footer[key]) is int and footer[key] == 0 for key in
                ('dropped_events', 'oversized_events', 'capture_errors')), 'diagnostic capture loss')
    require(all(type(value) is int for value in header['limits'].values())
            and header['limits'] == {'max_bytes': 4194304, 'event_bytes': 65536,
            'prefix_bytes': 3142656, 'tail_bytes': 1047552}, 'diagnostic limits changed')
    require(set(sources) == set(TRACE_SOURCE_PATHS)
            and all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) for value in sources.values())
            and header['sources'] == sources, 'diagnostic source identity mismatch')
    runtime = header['runtime']
    require(runtime['RA_LOG'] == 'rust_analyzer=info'
            and isinstance(runtime['python'], str) and runtime['python']
            and isinstance(runtime['platform'], str) and runtime['platform'], 'diagnostic runtime/RA_LOG')
    root = header['root_uri']
    parsed = urlsplit(root)
    require(parsed.scheme == 'file' and not parsed.netloc and parsed.path.startswith('/')
            and not parsed.query and not parsed.fragment and not root.endswith('/'), 'diagnostic root URI')
    documents = {root + '/' + path: (path, text) for path, text in RUST_FILES.items()}
    caller = root + '/src/lib.rs'
    stage, stage_index, previous_time = 'setup', 0, -1.0
    identity = None
    requests, server_requests, replies = {}, {}, {}
    pending_sends, opens, changes, inspections = [], set(), [], {}
    initialization = None
    server_info, stopped, stderr_bytes, stderr_end = None, False, 0, False
    shutdown_id, exit_seen, warm_reference, edit_reference = None, False, False, False

    def message_id(message):
        value = message['id']
        require(type(value) is int or (isinstance(value, str) and value), 'invalid diagnostic protocol ID')
        return type(value).__name__, value

    def has_caller(message, line):
        result = message.get('result')
        return isinstance(result, list) and any(isinstance(item, dict) and item.get('uri') == caller
            and item.get('range', {}).get('start', {}).get('line') == line for item in result)

    for number, (row, line) in enumerate(zip(rows, lines, strict=True), 1):
        require(type(row['index']) is int and row['index'] == number, 'diagnostic event index/gap')
        monotonic = row['monotonic']
        require(type(monotonic) in (int, float) and math.isfinite(monotonic)
                and monotonic >= previous_time, 'diagnostic event time/order')
        previous_time = monotonic
        require(len(line.encode('utf-8')) + 1 <= (4096 if row['kind'] == 'trace_end' else 65536)
                and 'payload_omitted' not in row, 'oversize/omitted diagnostic event')
        kind = row['kind']
        if kind == 'stage':
            require(stage_index < len(TRACE_STAGES) and row['name'] == TRACE_STAGES[stage_index],
                    'diagnostic stage order')
            stage, stage_index = row['name'], stage_index + 1
        require(row['stage'] == stage, 'diagnostic active stage mismatch')
        if kind == 'trace_start':
            require(number == 1, 'duplicate diagnostic header')
        elif kind == 'trace_end':
            require(number == len(rows) and stage == 'shutdown', 'diagnostic footer order')
        elif kind == 'stage':
            continue
        elif kind in {'protocol', 'send_returned', 'stderr', 'stderr_end'}:
            require(not stopped and row['root_uri'] == root and row['language'] == 'rust'
                    and type(row['pid']) is int and row['pid'] > 0
                    and row['command'] == 'rust-analyzer' and row['args'] == [], 'diagnostic client identity')
            current = row['pid'], row['command'], row['args']
            if identity is None:
                identity = current
            require(current == identity, 'diagnostic changed client process')
            require(isinstance(row['documents'], dict), 'diagnostic document map')
            if stage_index >= 2:
                require(set(row['documents']) == set(documents), 'diagnostic incomplete active document map')
            for uri, content in row['documents'].items():
                require(uri in documents and set(content) == {'version', 'sha256'}, 'diagnostic unexpected document')
                version = content['version']
                require(type(version) is int and version in (1, 2)
                        and (version == 1 or (uri == caller and stage_index >= 4)), 'diagnostic document version')
                text = RUST_CHANGED if version == 2 else documents[uri][1]
                require(content['sha256'] == digest(text.encode()), 'diagnostic document hash')
                if uri == caller and stage_index >= 5:
                    require(version == 2, 'diagnostic stale caller context')
            if kind == 'stderr':
                chunk = base64.b64decode(row['base64'], validate=True)
                require(type(row['bytes']) is int and len(chunk) == row['bytes'] > 0
                        and chunk.decode(errors='replace') == row['text'], 'diagnostic stderr bytes/text mismatch')
                stderr_bytes += len(chunk)
            elif kind == 'stderr_end':
                require(isinstance(row['reason'], str) and row['reason'], 'diagnostic stderr end reason')
                stderr_end = True
            elif kind == 'send_returned':
                key = (type(row['id']).__name__, row['id'], row['method'])
                require(key in pending_sends, 'diagnostic unmatched send_returned')
                pending_sends.remove(key)
            else:
                message = row['message']
                require(isinstance(message, dict) and message['jsonrpc'] == '2.0'
                        and row['direction'] in {'in', 'out'}, 'diagnostic protocol envelope')
                method = message.get('method')
                if method is not None:
                    require(isinstance(method, str) and method and 'result' not in message and 'error' not in message,
                            'diagnostic method/response collision')
                else:
                    require(('result' in message) != ('error' in message), 'diagnostic malformed reply')
                    if 'error' in message:
                        require(isinstance(message['error'], dict) and type(message['error']['code']) is int
                                and isinstance(message['error']['message'], str), 'diagnostic malformed protocol error')
                if row['direction'] == 'out':
                    pending_sends.append((type(message.get('id')).__name__, message.get('id'), method))
                    if method is not None and 'id' in message:
                        key = message_id(message)
                        require(key not in requests, 'diagnostic duplicate request ID')
                        requests[key] = row
                    elif method is None:
                        key = message_id(message)
                        require(key in server_requests, 'diagnostic reply to unknown server request')
                        del server_requests[key]
                    if method == 'initialize':
                        require(initialization is None and stage == 'warmup'
                                and message['params']['rootUri'] == root, 'diagnostic initialize request')
                        initialization = message_id(message)
                    elif method == 'initialized':
                        require(server_info is not None and stage == 'warmup' and 'id' not in message,
                                'diagnostic initialized order')
                    elif method == 'textDocument/didOpen':
                        doc = message['params']['textDocument']
                        uri = doc['uri']
                        require(server_info is not None and stage == 'warmup' and uri in documents
                                and uri not in opens and 'id' not in message and doc['languageId'] == 'rust'
                                and type(doc['version']) is int and doc['version'] == 1
                                and doc['text'] == documents[uri][1]
                                and row['documents'].get(uri) == {'version': 1, 'sha256': digest(doc['text'].encode())},
                                'diagnostic didOpen fixture identity')
                        opens.add(uri)
                    elif method == 'textDocument/didChange':
                        doc = message['params']['textDocument']
                        require(stage == 'edit_delivery' and doc == {'uri': caller, 'version': 2}
                                and type(doc['version']) is int and 'id' not in message and not changes and opens == set(documents)
                                and message['params']['contentChanges'] == [{'text': RUST_CHANGED}]
                                and row['documents'].get(caller) == {'version': 2, 'sha256': digest(RUST_CHANGED.encode())},
                                'diagnostic didChange fixture identity')
                        changes.append(number)
                    elif method == 'shutdown':
                        require(stage == 'shutdown' and shutdown_id is None, 'diagnostic shutdown stage')
                        shutdown_id = message_id(message)
                    elif method == 'exit':
                        require(stage == 'shutdown' and shutdown_id in replies and not exit_seen and 'id' not in message,
                                'diagnostic exit/shutdown order')
                        exit_seen = True
                elif method is not None:
                    if 'id' in message:
                        key = message_id(message)
                        require(key not in server_requests, 'diagnostic duplicate active server request')
                        server_requests[key] = row
                else:
                    key = message_id(message)
                    require(key in requests and key not in replies, 'diagnostic unmatched/duplicate reply ID')
                    request = requests[key]
                    replies[key] = row
                    if key == initialization:
                        require('error' not in message and isinstance(message['result'], dict), 'diagnostic initialize reply')
                        server_info = message['result']['serverInfo']
                        require(isinstance(server_info, dict) and isinstance(server_info.get('name'), str)
                                and server_info['name'] and ('version' not in server_info
                                or isinstance(server_info['version'], str)), 'diagnostic serverInfo')
                    if request['message']['method'] == 'textDocument/references':
                        params = request['message']['params']
                        if params.get('position') == {'line': 0, 'character': 7} and params.get('context') == {'includeDeclaration': False}:
                            if request['stage'] == 'warmup' and params['textDocument']['uri'] == root + '/src/first.rs' and has_caller(message, 2):
                                warm_reference = True
                            if request['stage'] == 'edit_delivery' and changes and params['textDocument']['uri'] == root + '/src/second.rs' and has_caller(message, 3):
                                edit_reference = True
        elif kind == 'inspection':
            expected_path = {'selected_original': 'src/first.rs', 'unused_namesake': 'src/second.rs',
                'selected_after_edit': 'src/second.rs', 'original_after_retarget': 'src/first.rs'}
            require(stage in expected_path and stage not in inspections
                    and row['path'] == expected_path[stage] and row['is_error'] is False,
                    'diagnostic inspection stage/path/error')
            response = row['response']
            metadata, data = response['metadata'], response['data']
            require(metadata['workspace'] == unquote(parsed.path) and metadata['source'] == 'local'
                    and metadata['revision'] == 'working-tree' and data['status'] == 'found'
                    and data['definition']['name'] == 'helper' and data['definition']['file_path'] == row['path']
                    and data['definition']['start_line'] == 1 and data['source']['truncated'] is False
                    and data['source']['text'] == RUST_FILES[row['path']].rstrip('\n'),
                    'diagnostic inspection workspace/definition/source')
            references = data['references']
            require(isinstance(references, list) and all(isinstance(ref, dict) for ref in references),
                    'diagnostic inspection references')
            if stage == 'selected_original':
                require(warm_reference and metadata['analysis']['precision']['status'] == 'verified'
                        and any(ref.get('file_path') == 'src/lib.rs' and ref.get('source') == 'lsp'
                                and ref.get('line') == 3 for ref in references), 'diagnostic selected original evidence')
            elif stage == 'selected_after_edit':
                require(edit_reference and any(ref.get('file_path') == 'src/lib.rs'
                    and ref.get('line') == 4 and ref.get('source') == 'lsp' for ref in references),
                    'diagnostic selected after edit evidence')
            else:
                require(not any(ref.get('file_path') == 'src/lib.rs' for ref in references),
                        'diagnostic negative namesake/original evidence')
            inspections[stage] = row['path']
        elif kind == 'server_stop':
            require(stage == 'shutdown' and not stopped and identity is not None and row['pid'] == identity[0]
                    and type(row['returncode']) is int and row['returncode'] == 0
                    and exit_seen and stderr_end, 'diagnostic server stop/shutdown')
            stopped = True
        else:
            raise CaptureError(f'unknown/failure diagnostic event: {kind}')
    require(stage_index == len(TRACE_STAGES) and len(inspections) == 4 and opens == set(documents)
            and len(changes) == 1 and initialization in replies and server_info is not None
            and not pending_sends and not server_requests and warm_reference and edit_reference
            and exit_seen and stopped and stderr_bytes > 0,
            'incomplete diagnostic lifecycle')
    return {'events': len(rows), 'server_info': server_info, 'sources': sources,
            'inspections': len(inspections), 'stderr_bytes': stderr_bytes, 'stages': list(TRACE_STAGES),
            'root_uri': root, 'process_id': identity[0], 'status': footer['status']}
