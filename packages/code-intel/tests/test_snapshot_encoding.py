"""Exact snapshot wire/budget semantics and observable interpreted serialization work."""
import cProfile
import hashlib
import json
import os
import pstats
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context import ast_snapshot
from attocode_intel._internal.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    ImportDef,
)


def reference_fields(value):
    if not is_dataclass(value):
        raise TypeError(type(value).__name__)
    return {f.name: getattr(value, f.name) for f in fields(value)}


def reference_bounded(value, limit):
    """Frozen e0c345 baseline, used only by paired controls, never by the product."""
    chunks, size = [], 0
    for chunk in json.JSONEncoder(default=reference_fields, separators=(',', ':'), ensure_ascii=True).iterencode(value):
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return ''.join(chunks)


@pytest.mark.parametrize('value', [
    None, True, False, 0, -19, 10**80, -0.0, 1.25, float('inf'), float('nan'),
    '', 'a"\\\n\t\x00é𝄞\ud800', [], {}, [1, False, None, 'é'],
    {'z': [1, {'é': '\udfff'}], 'a': True, 1: 'integer', '1': 'text', None: 'null', 'null': 'text'}, (1, 'x'),
], ids=['null', 'true', 'false', 'zero', 'negative', 'large-int', 'negative-zero', 'float',
        'infinity', 'nan', 'empty-string', 'escaped-unicode', 'empty-list', 'empty-dict',
        'mixed-list', 'ordered-dict', 'tuple'])
def test_all_ascii_byte_boundaries_match_independent_json(value):
    # Break caught: byte/escape accounting silently changes accepted cache entries.
    expected = json.dumps(value, separators=(',', ':'), ensure_ascii=True)
    for limit in range(len(expected) + 2):
        want = expected if len(expected) <= limit else None
        assert ast_snapshot._bounded_json(value, limit) == want
        assert reference_bounded(value, limit) == want


def test_complete_nested_ast_wire_matches_independent_dataclass_oracle():
    # Break caught: field ordering, optional fields or nested values are dropped by preparation.
    fn = FunctionDef('method', 2, 9, params=['x'], decorators=['é'], is_async=True,
                     docstring='line\n𝄞', qualified_name='Thing.method')
    value = FileAST('src/é.py', 'python', functions=[fn], classes=[ClassDef('Thing', 1, 10, methods=[fn])],
                    imports=[ImportDef('example', names=['x'], is_from=True)],
                    top_level_vars=['v'], line_count=11, parsing_tier='tree_sitter', content_sha256='a'*64)
    expected = json.dumps(asdict(value), separators=(',', ':'), ensure_ascii=True)
    for limit in [0, len(expected)-1, len(expected), len(expected)+1]:
        assert ast_snapshot._bounded_json(value, limit) == (expected if len(expected) <= limit else None)
    assert value.functions[0] is fn and value.classes[0].methods[0] is fn


def test_overflow_stops_before_visiting_later_records():
    # Break caught: preparation walks/builds the complete oversized structure before truncation.
    seen = []

    @dataclass
    class Record:
        text: str

        def __getattribute__(self, name):
            if name == 'text':
                seen.append(id(self))
            return object.__getattribute__(self, name)

    first, later = Record('x'*1000), Record('unvisited')
    assert ast_snapshot._bounded_json([first, *[later]*10000], 32) is None
    assert seen == [id(first)]


def test_real_file_ast_overflow_does_not_touch_later_functions():
    # Break caught: a full AST copy/encoding allocates all later records despite the file bound.
    class Later(FunctionDef):
        def __getattribute__(self, name):
            if name == 'name':
                raise AssertionError('oversized AST visited a later function')
            return super().__getattribute__(name)

    value = FileAST('example.py', 'python', functions=[
        FunctionDef('first', 1, 2, docstring='x'*(2**20+100)),
        *[Later('unvisited', 3, 4)]*10000,
    ])
    assert ast_snapshot._bounded_json(value, 2**20) is None


@pytest.mark.parametrize('kind', ['unsupported', 'cycle'])
def test_invalid_values_fail_safely(kind):
    # Break caught: unsupported or cyclic data becomes an accepted disposable summary.
    if kind == 'unsupported':
        with pytest.raises(TypeError):
            ast_snapshot._bounded_json({'x': object()}, 4096)
    else:
        value = []
        value.append(value)
        with pytest.raises(ValueError, match='Circular'):
            ast_snapshot._bounded_json(value, 4096)


def test_total_and_per_file_bounds_preserve_partial_cache_selection(monkeypatch):
    # Break caught: faster encoding changes the retained subset or bypasses the file/total limits.
    monkeypatch.setattr(ast_snapshot, 'parser_identity', lambda _: 'grammar')
    a = FileAST('a.py', 'python', parsing_tier='tree_sitter', content_sha256='a'*64)
    b = FileAST('b.py', 'python', functions=[FunctionDef('large', 1, 2, docstring='x'*2000)],
                parsing_tier='tree_sitter', content_sha256='b'*64)
    c = FileAST('c.py', 'python', parsing_tier='tree_sitter', content_sha256='c'*64)
    header = {'snapshot': hashlib.sha256(b'snapshot').hexdigest(), 'parsers': {'python': 'grammar'}}
    expected = json.dumps({**header, 'files': {'a.py': asdict(a), 'c.py': asdict(c)}},
                          separators=(',', ':'), ensure_ascii=True)
    monkeypatch.setattr(ast_snapshot, 'MAX_FILE_BYTES', 512)
    monkeypatch.setattr(ast_snapshot, 'MAX_CACHE_BYTES', 4096)
    assert ast_snapshot.encode_summaries({'c.py': c, 'b.py': b, 'a.py': a}, 'snapshot') == expected
    only_a = json.dumps({**header, 'files': {'a.py': asdict(a)}}, separators=(',', ':'), ensure_ascii=True)
    monkeypatch.setattr(ast_snapshot, 'MAX_CACHE_BYTES', len(only_a)+4)
    assert ast_snapshot.encode_summaries({'a.py': a, 'b.py': b, 'c.py': c}, 'snapshot') == only_a


def test_serializer_reduces_interpreted_call_work(tmp_path):
    # Break caught: a replacement preserves bytes but retains the original generator-call overhead.
    # Total cProfile calls include builtins; this is a work proxy, not a wall-time claim.
    value = FileAST('many.py', 'python', functions=[FunctionDef(f'fn{i}', i+1, i+2,
                    params=['value'], docstring='Example') for i in range(1000)])
    destination = Path(os.environ.get('ENCODING_CONTROL_EVIDENCE', str(tmp_path)))
    destination.mkdir(parents=True, exist_ok=True)
    rows, outputs = {}, []
    for label, function in [('baseline', reference_bounded), ('candidate', ast_snapshot._bounded_json)]:
        profiler = cProfile.Profile()
        outputs.append(profiler.runcall(function, value, 2**20))
        path = destination / (label + '.prof')
        profiler.dump_stats(str(path))
        rows[label] = pstats.Stats(str(path)).total_calls
    assert outputs[0] is not None and outputs[0] == outputs[1]
    (destination / 'work.json').write_text(json.dumps({'calls': rows,
        'wire_sha256': hashlib.sha256(outputs[0].encode()).hexdigest(), 'wire_bytes': len(outputs[0]),
        'candidate_to_baseline_call_ratio': rows['candidate']/rows['baseline']}, indent=2)+'\n')
    assert rows['candidate'] <= rows['baseline']*.5, 'bounded serialization still uses excessive interpreted work'
