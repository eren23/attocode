from types import SimpleNamespace

import pytest
from attocode_intel.focused_evidence import source_excerpts


def excerpts(text, hint, path='example.py'):
    lines = text.splitlines()
    definition = SimpleNamespace(file_path=path, start_line=1, end_line=len(lines))
    result = source_excerpts(lines, definition, hint)
    for group in result:
        for item in [group, *group['context_ranges']]:
            assert item['text'] == '\n'.join(lines[item['start_line']-1:item['end_line']])
    return result


def test_separated_multiline_guard_stays_with_effect():
    source = 'def redirect(status, body):\n    if (status != 307\n            and status != 308):\n' + '\n'.join(
        '        unrelated = 1' for _ in range(25)) + '\n        body.clear()\n'
    rows = excerpts(source, 'body clear')
    row = next(r for r in rows if 'body.clear()' in r['text'])
    assert row['context_ranges'][0]['text'] == '    if (status != 307\n            and status != 308):'
    assert not row['context_incomplete']


def test_else_includes_preceding_alternatives_and_nested_guard():
    source = 'def parse(flag, mode):\n    if flag:\n        pass\n    elif mode:\n        pass\n    else:\n        if mode is None:\n' + '\n'.join(
        '            unrelated = 1' for _ in range(20)) + '\n            deliver()\n'
    rows = excerpts(source, 'deliver')
    context = '\n'.join(r['text'] for r in rows[0]['context_ranges'])
    assert 'if flag:' in context and 'elif mode:' in context and 'else:' in context and 'if mode is None:' in context


@pytest.mark.parametrize('suffix', ['.js', '.ts', '.tsx'])
def test_javascript_multiline_conditions_and_literal_delimiter(suffix):
    source = "function parse(arg, enabled) {\n  if (arg === '--' &&\n      enabled) {\n" + '\n'.join(
        '    other();' for _ in range(20)) + '\n    deliver();\n  }\n}\n'
    groups = excerpts(source, 'deliver', 'source' + suffix)
    assert "enabled) {" in groups[0]['context_ranges'][0]['text']
    delimiter = excerpts(source, '--', 'source' + suffix)
    assert "arg === '--'" in delimiter[0]['text']


def test_comment_and_docstring_are_not_executable_literals():
    text = 'def f():\n    """needle -- 308"""\n    # needle -- 308\n    unrelated()\n'
    assert excerpts(text, 'needle -- 308') == []


def test_unparseable_source_marks_context_unavailable():
    rows = excerpts('def broken(:\n    deliver()\n', 'deliver')
    assert rows and rows[0]['context_incomplete']


@pytest.mark.parametrize('budget', [800, 1000, 2000])
async def test_budget_drops_effect_and_distant_context_together(tmp_path, monkeypatch, budget):
    import json

    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    text = 'def process(status, body):\n' + '\n'.join('    setup = 1' for _ in range(15))
    text += '\n    if status not in (307, 308):\n' + '\n'.join('        setup = 1' for _ in range(65))
    text += '\n        body.clear()\n'
    (tmp_path / 'source.py').write_text(text)
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        result = await gateway.execute_mcp('inspect_symbol', {'symbol_name':'process','task_hint':'body clear','max_tokens':budget})
        assert not result.isError and response_tokens(result) <= budget
        data = json.loads(result.content[0].text)['data']
        for row in data.get('source_excerpts', []):
            if 'body.clear()' in row['text']:
                assert any('status not in (307, 308)' in c['text'] for c in row['context_ranges'])
    finally:
        await gateway.close()
