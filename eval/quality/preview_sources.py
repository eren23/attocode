"""Declare the actual source producer before validating a delivered preview."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from attocode_intel import gateway as gateway_module
from attocode_intel import search_evidence

from eval.quality.experiment_evidence import read_source

POLICIES = {
    'body_index': {'errors': 'replace', 'newlines': 'universal'},
    'hydrated_metadata': {'errors': 'strict', 'newlines': 'raw'},
    'exact_scoped_source': {'errors': 'replace', 'newlines': 'raw'},
}


def identity(row):
    if isinstance(row, dict):
        return tuple(row.get(k) for k in ('file_path', 'name', 'chunk_type', 'line', 'end_line'))
    return row.file_path, row.name, row.chunk_type, row.start_line or None, row.end_line or None


def source_spans(page, root, policies):
    """Admit exact intersected line bounds, including partial first/last lines."""
    root = Path(root).resolve()
    hits = page['data']['results']
    if len(hits) != len(policies):
        raise ValueError('source policy/result count mismatch')
    result = []
    for hit, policy in zip(hits, policies, strict=True):
        first, last = hit.get('snippet_start_line'), hit.get('snippet_end_line')
        snippet = hit.get('snippet', '')
        if first is None and last is None:
            if policy['producer'] != 'metadata' and snippet:
                raise ValueError('source text has no source coordinates')
            result.append({'kind': 'metadata_only', 'spans': []})
            continue
        expected = POLICIES.get(policy['producer'])
        if expected is None or any(policy.get(k) != v for k, v in expected.items()):
            raise ValueError('unknown or mismatched source producer policy')
        if not isinstance(snippet, str) or not snippet:
            raise ValueError('source snippet must be nonempty text')
        path = (root / hit['file_path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('source outside selected fixture')
        source = read_source(path, **expected)
        lines = source.splitlines(keepends=True)
        start, end = hit.get('line'), hit.get('end_line')
        if (not all(type(n) is int for n in (start, end, first, last))
                or not 1 <= start <= first <= last <= end <= len(lines)):
            raise ValueError('invalid source coordinates')
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        window = source[offsets[first - 1]:offsets[last]]
        found, valid = window.find(snippet), []
        while found >= 0:
            begin = offsets[first - 1] + found
            finish = begin + len(snippet)
            if begin < offsets[first] and finish > offsets[last - 1]:
                valid.append((begin, finish))
            found = window.find(snippet, found + 1)
        if not valid:
            raise ValueError('source snippet does not match its exact line bounds')
        result.append({'kind': 'source', 'spans': valid, 'policy': policy})
    return result


class SourceTracker:
    def __init__(self, root, journal):
        self.root, self.journal = Path(root).resolve(), journal
        self._policies = {}

    def _record(self, row, producer):
        policy = {'producer': producer, **POLICIES.get(producer, {})}
        key = identity(row)
        # Store large bodies only once by content hash; pages retain references.
        ref = self.journal.response({'event': 'preview_input', 'identity': key},
                                    {'body': search_evidence.source_body(row)})
        policy['body_ref'] = ref
        if producer != 'metadata':
            path = (self.root / row.file_path).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('provider source outside fixture')
            policy['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.journal.response({'event': 'source_lineage', 'identity': key}, policy)
        self._policies[key] = policy

    @contextmanager
    def capture(self):
        """Observe only these CI worker calls, returning original results intact."""
        self._policies = {}
        hydrate = gateway_module.hydrate_selected_sources
        scoped = search_evidence.exact_scoped_source

        def observe_hydrate(root_dir, rows):
            if Path(root_dir).resolve() != self.root:
                raise ValueError('provider workspace mismatch')
            selected = hydrate(root_dir, rows)
            for before, after in zip(rows, selected, strict=True):
                previous = self._policies.get(identity(before))
                if not after.start_line:
                    producer = 'metadata'
                elif previous is not None:
                    producer = previous['producer']
                else:
                    producer = 'body_index' if before.start_line else 'hydrated_metadata'
                self._record(after, producer)
            return selected

        def observe_scoped(*args, **kwargs):
            selected = scoped(*args, **kwargs)
            if selected is not None:
                self._record(selected, 'exact_scoped_source')
            return selected

        with patch.object(gateway_module, 'hydrate_selected_sources', observe_hydrate), \
                patch.object(search_evidence, 'exact_scoped_source', observe_scoped):
            yield self

    def policies(self, page):
        result = []
        for row in page['data']['results']:
            policy = self._policies.get(identity(row))
            if policy is None:
                raise ValueError('delivered row has no observed source producer')
            result.append(policy)
        return result
