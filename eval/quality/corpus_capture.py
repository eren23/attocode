"""Opt-in durable observations for bounded compatibility experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from attocode_intel.output import response_tokens

from eval.quality.experiment_evidence import read_source
from eval.quality.preview_sources import SourceTracker, source_spans


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_sources(tool, page, root, policies):
    """Follow each actual producer's decoding, newline and coordinate policy."""
    if tool == 'semantic_search' and isinstance(page.get('data'), dict) and 'results' in page['data']:
        return source_spans(page, root, policies)
    rows = []
    data = page.get('data', {})
    if tool == 'inspect_symbol' and isinstance(data, dict):
        for excerpt in [data.get('source', {}), *data.get('source_excerpts', [])]:
            if not excerpt.get('text'):
                continue
            name = excerpt.get('file_path', data.get('definition', {}).get('file_path'))
            path = (Path(root) / name).resolve()
            require(path.is_relative_to(Path(root).resolve()), 'source outside selected fixture')
            lines = read_source(path, errors='replace', newlines='universal').splitlines()
            start, end = excerpt['start_line'], excerpt['end_line']
            require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines)
                    and excerpt['text'] == '\n'.join(lines[start - 1:end]), 'source coordinates/text mismatch')
            rows.append({'kind': 'source', 'file_path': name, 'start_line': start, 'end_line': end,
                         'errors': 'replace', 'newlines': 'universal', 'line_join': 'LF'})
    return rows


class RecordedGateway:
    def __init__(self, peer, root, journal, *, generation=0):
        self.peer, self.root, self.journal = peer, Path(root), journal
        self.tracker = SourceTracker(root, journal)
        self.generation, self.captures = generation, []

    async def execute_mcp(self, tool, arguments):
        with self.tracker.capture():
            response = await self.peer.execute_mcp(tool, arguments)
        request = {'event': 'mcp_response', 'gateway': self.generation,
                   'sequence': len(self.captures), 'tool': tool, 'arguments': arguments}
        ref = self.journal.response(request, response.model_dump(mode='json'))
        capture = {'gateway': self.generation, 'sequence': len(self.captures), 'response_ref': ref}
        self.captures.append(capture)
        # Never classify a budget violation as a missing optional grammar.
        require(response_tokens(response) <= arguments['max_tokens'], 'MCP response exceeded output budget')
        page = json.loads(response.content[0].text)
        policies = (self.tracker.policies(page) if tool == 'semantic_search'
                    and isinstance(page.get('data'), dict) and 'results' in page['data'] else [])
        validation = validate_sources(tool, page, self.root, policies)
        self.journal.response({'event': 'source_validation', **capture, 'policies': policies}, validation)
        return response

    async def close(self):
        try:
            await self.peer.close()
        except BaseException as error:
            self.journal.response({'event': 'gateway_close', 'gateway': self.generation},
                                  {'status': 'failed', 'type': type(error).__name__})
            raise
        self.journal.response({'event': 'gateway_close', 'gateway': self.generation}, {'status': 'complete'})


def journal_events(folder):
    """Validate reference syntax and bytes before trusting any derived record."""
    result = []
    for line in (folder / 'events.jsonl').read_bytes().splitlines():
        event = json.loads(line)
        ref = event['response']
        sha = ref['sha256']
        require(isinstance(sha, str) and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha)
                and type(ref['bytes']) is int and ref['bytes'] > 0
                and str(PurePosixPath(ref['path'])) == f'blobs/{sha}.json', 'unsafe raw response reference')
        raw = (folder / ref['path']).read_bytes()
        require(len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == sha, 'raw response changed')
        result.append((event['request'], ref, json.loads(raw)))
    return result


def admit_worker(workspace, spec, evidence, summary, selected):
    """Raw admission is required before another pack can start."""
    from attocode_intel._internal.integrations.context.ts_parser import is_available
    from attocode_intel._internal.integrations.utilities.ignore import IgnoreManager
    from mcp.types import CallToolResult

    from eval.quality.fixture_identity import source_manifest
    from eval.quality.preview_sources import identity

    fixtures = journal_events(evidence / 'fixture')
    require(len(fixtures) == 1, 'missing pinned fixture')
    request, ref, manifest = fixtures[0]
    require(request == {'event': 'fixture_pinned', 'repo': spec['repo'], 'commit': spec['commit'],
                        'tree': summary['tree']} and ref == summary['fixture_ref'], 'pinned fixture binding mismatch')
    require(source_manifest(workspace) == manifest, 'fixture changed before admission')
    captures, policies, pending, closed, runtime = [], {}, None, set(), {}
    for request, ref, value in journal_events(evidence / 'journal'):
        kind = request['event']
        if kind in {'origin_start', 'origin_end', 'source_before', 'source_after'}:
            require(kind not in runtime, 'duplicate runtime identity')
            runtime[kind] = value
        elif kind == 'preview_input_identity':
            require(pending is None, 'provider evidence after response')
        elif kind == 'source_lineage':
            require(pending is None, 'provider lineage after response')
            key = tuple(request['identity'])
            if value['producer'] != 'metadata':
                path = (workspace / key[0]).resolve()
                require(path.is_relative_to(workspace.resolve())
                        and hashlib.sha256(path.read_bytes()).hexdigest() == value['source_sha256'],
                        'source lineage differs from fixture')
            policies[key] = value
        elif kind == 'mcp_response':
            require(pending is None, 'raw response lacks validation')
            generation = request['gateway']
            require(type(generation) is int and generation in {0, 1} and generation not in closed
                    and (generation == 0 or 0 in closed), 'gateway lifecycle/order mismatch')
            sequence = sum(c['gateway'] == generation for c in captures)
            require(type(request['sequence']) is int and request['sequence'] == sequence, 'raw response sequence mismatch')
            response = CallToolResult.model_validate(value)
            require(response_tokens(response) <= request['arguments']['max_tokens'], 'raw response exceeded budget')
            page = json.loads(response.content[0].text)
            selected_policies = ([policies[identity(h)] for h in page['data']['results']]
                if request['tool'] == 'semantic_search' and 'results' in page.get('data', {}) else [])
            pending = {'gateway': generation, 'sequence': sequence, 'response_ref': ref,
                       'request': request, 'response': response, 'page': page, 'policies': selected_policies}
            policies = {}
        elif kind == 'source_validation':
            require(pending is not None, 'validation has no preceding raw response')
            capture = {k: pending[k] for k in ('gateway', 'sequence', 'response_ref')}
            require(request == {'event': kind, **capture, 'policies': pending['policies']},
                    'source validation/raw binding mismatch')
            expected_validation = validate_sources(pending['request']['tool'], pending['page'], workspace,
                                                   pending['policies'])
            require(value == json.loads(json.dumps(expected_validation)), 'source validation replay mismatch')
            captures.append(pending)
            pending = None
        elif kind == 'gateway_close':
            require(pending is None and request['gateway'] not in closed and value == {'status': 'complete'},
                    'unverified or duplicate gateway shutdown')
            closed.add(request['gateway'])
        else:
            raise ValueError('unknown broad evidence event: ' + kind)
    require(pending is None and closed == {0, 1} and set(runtime) == {
        'origin_start', 'origin_end', 'source_before', 'source_after'}, 'missing raw/runtime evidence')
    for phase in ('origin_start', 'origin_end'):
        origins = runtime[phase]['origins']
        require(type(runtime[phase]['pid']) is int and runtime[phase]['pid'] > 0
                and origins.get('attocode_intel') == '__init__.py', 'invalid engine origin')
        for name, relative in origins.items():
            path = PurePosixPath(relative)
            require(name.startswith('attocode_intel') and not path.is_absolute() and '..' not in path.parts
                    and (selected / path).is_file(), 'child module outside selected engine')
    require(runtime['origin_start']['pid'] == runtime['origin_end']['pid']
            and runtime['source_before'] == runtime['source_after'] == {'sha256': digest(manifest)},
            'worker source/process identity changed')
    unavailable = spec.get('parser_requirement') == 'optional' and not is_available(spec['language'])
    excluded = IgnoreManager(workspace).is_ignored(spec['file']) or any(p.startswith('.') for p in Path(spec['file']).parts)
    text = (workspace / spec['file']).read_text()
    require(spec['anchor'] in text and (not spec.get('source_sha256')
            or hashlib.sha256(text.encode()).hexdigest() == spec['source_sha256']), 'selected source changed')
    line = text[:text.index(spec['anchor'])].count('\n') + 1
    selection = {'symbol_name': spec['symbol'], 'file_path': spec['file'], 'line': line}
    importer, caller, test = spec.get('importer'), spec.get('caller'), spec.get('test')

    def predicate(label, data):
        if label == 'definition':
            return any(d['file_path'] == spec['file'] and (d['name'] in {spec['symbol'], spec['symbol'].split('.')[-1]}
                       or ('.' not in spec['symbol'] and d['name'].split('.')[-1] == spec['symbol'])) for d in data)
        if label in {'source', 'restart'}:
            return (data.get('status') == 'found' and data['definition']['file_path'] == spec['file']
                    and (label == 'restart' or bool(data.get('source', {}).get('text'))))
        if label == 'scoped_search':
            return bool(data.get('results')) and all(d['file_path'] == spec['file'] for d in data['results'])
        if label == 'caller_syntax':
            return any(d['file_path'] == caller for d in data.get('references', [])) if caller else not data.get('absence_proven', False)
        if label == 'dependencies':
            return importer in data.get('imported_by', []) if importer else not data.get('absence_proven', False)
        if label == 'impact':
            return not data.get('absence_proven', False) and (not importer or importer in data.get('impacted_files', [])
                   or any(importer in layer['files'] for layer in data.get('layers', [])))
        if label == 'tests':
            return not data.get('absence_proven', False) and (not test or any(d['file_path'] == test for d in data.get('candidates', [])))
        raise ValueError('unknown compatibility check')

    at = 0
    def consume(row, tool, arguments, generation, label=None):
        nonlocal at
        refs = row['response_refs']
        require(bool(refs), 'missing check response references')
        expected, pages, warming = {'max_tokens': 4000, **arguments}, 0, 0
        for index, capture in enumerate(refs):
            require(at < len(captures), 'extra check capture')
            actual = captures[at]
            require(capture == {k: actual[k] for k in ('gateway', 'sequence', 'response_ref')}
                    and actual['request'] == {'event': 'mcp_response', 'gateway': generation,
                        'sequence': actual['sequence'], 'tool': tool, 'arguments': expected}, 'raw request/summary binding mismatch')
            response, page = actual['response'], actual['page']
            data = page.get('data', {})
            is_warming = (tool == 'semantic_search' and not response.isError
                          and data.get('ranking', {}).get('index', {}).get('status') == 'warming')
            if is_warming:
                warming += 1
                require(index + 1 < len(refs), 'unfinished index warming')
            else:
                pages += 1
                if index + 1 < len(refs):
                    require(label == 'caller_syntax' and not response.isError and not predicate(label, data)
                            and data.get('next_cursor') and pages < 10, 'unexpected extra MCP request')
                    expected = {'max_tokens': 4000, **arguments, 'cursor': data['next_cursor']}
            at += 1
        require(row.get('warming_responses', 0) == warming, 'warming response count mismatch')
        if label is not None:
            passed = not response.isError and bool(predicate(label, data))
            limited = label in {'caller_syntax', 'dependencies', 'impact', 'tests'} and not {
                'caller_syntax': caller, 'dependencies': importer, 'impact': importer, 'tests': test}[label]
            outcome = 'failed' if not passed else 'limited' if limited else 'passed'
            if not passed and ((unavailable and label in {'definition', 'source', 'restart'})
                    or (excluded and label in {'definition', 'source', 'scoped_search', 'restart'})):
                outcome = 'unsupported'
            require(row['name'] == label and row['tool'] == tool and row['pages_requested'] == pages
                    and row['response'] == {'ref': refs[-1]['response_ref']}
                    and row['contract_passed'] == passed and row['outcome'] == outcome
                    and row['passed'] == (outcome == 'passed') and outcome != 'failed', 'check differs from raw evidence')
        else:
            require(not response.isError, 'retrieval failed')
        return data, page

    expected_checks = ['definition', 'source', 'scoped_search', 'caller_syntax', 'dependencies', 'impact', 'tests', 'restart']
    require([r['name'] for r in summary['checks']] == expected_checks, 'missing/reordered compatibility checks')
    operations = [('search_symbols', {'name': spec['symbol']}), ('inspect_symbol', selection),
        ('semantic_search', {'query': spec.get('query', spec['symbol']), 'file_filter': spec['file'], 'top_k': 5}),
        ('cross_references', {'symbol_name': spec['symbol']}), ('dependencies', {'path': spec['file']}),
        ('impact_analysis', {'changed_files': [spec['file']]}), ('suggest_tests', {'files': [spec['file']]})]
    for row, (tool, arguments) in zip(summary['checks'][:7], operations, strict=True):
        data, _page = consume(row, tool, arguments, 0, row['name'])
        if row['name'] == 'definition':
            choices = [d for d in data if d['file_path'] == spec['file'] and (
                d['name'] in {spec['symbol'], spec['symbol'].split('.')[-1]}
                or ('.' not in spec['symbol'] and d['name'].split('.')[-1] == spec['symbol']))]
            if len(choices) > 1:
                choices = [d for d in choices if d['start_line'] <= line <= d['end_line']]
            if len(choices) == 1:
                selection['line'] = choices[0]['start_line']
    require([r['id'] for r in summary['retrieval']] == [q['id'] for q in spec.get('queries', [])], 'missing/reordered questions')
    for row, question in zip(summary['retrieval'], spec.get('queries', []), strict=True):
        for label in question['evidence']:
            path = (workspace / label['file']).resolve()
            require(path.is_relative_to(workspace.resolve()), 'question source outside fixture')
            text = path.read_text()
            require(hashlib.sha256(text.encode()).hexdigest() == label['source_sha256']
                    and label['quote'] in text, 'question source identity/anchor mismatch')
        data, page = consume(row, 'semantic_search', {'query': question['query'], 'top_k': 24, 'max_tokens': 8000}, 0)
        files = list(dict.fromkeys(hit['file_path'] for hit in data.get('results', [])))
        labels = sorted({v['file'] for v in question['evidence']})
        ranks = [i + 1 for i, name in enumerate(files) if name in labels]
        derived = {'query': question['query'], 'ranked_files': files, 'labeled_files': labels,
                   'first_labeled_rank': min(ranks) if ranks else None, 'hit_at_5': any(r <= 5 for r in ranks),
                   'hit_at_24': any(r <= 24 for r in ranks), 'delivered_files': len(files), 'metadata': page.get('metadata', {})}
        require(all(row[k] == v for k, v in derived.items()), 'retrieval summary differs from raw response')
    consume(summary['checks'][-1], 'inspect_symbol', selection, 1, 'restart')
    require(at == len(captures), 'unclaimed raw responses')
    return {'responses': at, 'source_sha256': digest(manifest), 'worker_pid': runtime['origin_start']['pid'],
            'checks': len(expected_checks), 'questions': len(summary['retrieval'])}
