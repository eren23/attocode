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
    raise NotImplementedError('broad raw admission before advancing')
