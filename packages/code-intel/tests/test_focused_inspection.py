import json

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens


def decode(result):
    assert not result.isError
    return json.loads(result.content[0].text)["data"]


@pytest.mark.parametrize("selected,other", [("retrieve", "purge"), ("assemble", "release")])
async def test_selected_symbol_beats_module_and_filename_matches(tmp_path, monkeypatch, selected, other):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "engine.py").write_text(f"def {selected}(): return 1\ndef {other}(): return 2\n")
    (tmp_path / "test_engine.py").write_text(f"from engine import {other}\ndef test_module(): assert {other}() == 2\n")
    (tmp_path / f"test_{selected}.py").write_text(f"from engine import {other}\ndef test_name_only(): assert {other}() == 2\n")
    (tmp_path / "test_regression.py").write_text(f"from engine import {selected}\ndef test_regression(): assert {selected}() == 1\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        args = {"symbol_name": selected, "file_path": "engine.py"}
        bundle = decode(await gateway.execute_mcp("inspect_symbol", args))
        suggestions = decode(await gateway.execute_mcp("suggest_tests", {
            "files": ["engine.py"], "symbol_name": selected}))
        assert bundle["tests"] == suggestions["candidates"][:5]
        assert bundle["tests"][0]["file_path"] == "test_regression.py"
        assert bundle["tests"][0]["evidence"]["selected_symbol_reference"]
        assert "verify same-name" in bundle["tests"][0]["reasons"][0]
        changed = decode(await gateway.execute_mcp("inspect_symbol", {**args, "symbol_name": other}))
        assert changed["tests"][0]["file_path"] != "test_regression.py"
        assert not suggestions["absence_proven"]
    finally:
        await gateway.close()


@pytest.fixture
def long_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    lines = ["def process(item, storage, policy, transport):",
             '    """storage storage storage policy policy transport transport"""',
             "    # storage policy transport " * 4,
             *(f"    item += {i}" for i in range(80)),
             "    if item in storage:",
             "        return storage[item]",
             *(f"    item += {i}" for i in range(15)),
             "    if item not in storage:",
             "        storage[item] = item",
             *(f"    item += {i}" for i in range(15)),
             "    if policy.allowed:",
             "        transport.send(item)",
             "    return item"]
    (tmp_path / "engine.py").write_text("\n".join(lines) + "\n")
    # No direct imports: the test's function name must supply lexical evidence.
    (tmp_path / "test_regression.py").write_text("def test_storage(): pass\n")
    (tmp_path / "contest.py").write_text("def storage(): pass\n")
    return tmp_path, lines


def assert_exact_excerpts(data, lines):
    occupied = set()
    for excerpt in data["source_excerpts"]:
        start, end = excerpt["start_line"], excerpt["end_line"]
        assert excerpt["file_path"] == "engine.py"
        assert 1 <= start <= end <= len(lines)
        assert end - start < 5
        assert excerpt["text"] == "\n".join(lines[start - 1:end])
        interval = set(range(start, end + 1))
        assert not occupied & interval
        occupied.update(interval)


async def test_task_focus_returns_deep_branches_and_exact_current_source(long_repository):
    root, lines = long_repository
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        args = {"symbol_name": "process", "task_hint": "storage reads writes"}
        result = await gateway.execute_mcp("inspect_symbol", args)
        assert response_tokens(result) <= 2000
        data = decode(result)
        assert_exact_excerpts(data, lines)
        text = "\n".join(e["text"] for e in data["source_excerpts"])
        assert "if item in storage:" in text
        assert "if item not in storage:" in text
        assert all(e["start_line"] > 3 for e in data["source_excerpts"])
        assert data["tests"][0]["file_path"] == "test_regression.py"
        assert not data["tests"][0]["evidence"]["selected_symbol_reference"]
        assert not any(t["file_path"] == "contest.py" for t in data["tests"])
        other = decode(await gateway.execute_mcp("inspect_symbol", {
            **args, "task_hint": "policy transport"}))
        assert "transport.send(item)" in other["source_excerpts"][0]["text"]
        assert other["source_excerpts"] != data["source_excerpts"]
        unknown = decode(await gateway.execute_mcp("inspect_symbol", {**args, "task_hint": "quasar"}))
        assert unknown["source_excerpts"] == []
        assert "not exhaustive" in data["excerpt_selection"]
        changed_lines = ["", "", *[line.replace("storage[item] = item", "storage[item] = item + 7") for line in lines]]
        (root / "engine.py").write_text("\n".join(changed_lines) + "\n")
        changed = decode(await gateway.execute_mcp("inspect_symbol", args))
        assert_exact_excerpts(changed, changed_lines)
        assert "storage[item] = item + 7" in "\n".join(e["text"] for e in changed["source_excerpts"])
    finally:
        await gateway.close()


@pytest.mark.parametrize("budget", [800, 1000, 2000])
async def test_focused_budget_keeps_whole_excerpts_and_source_continuation(long_repository, budget):
    root, lines = long_repository
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        args = {"symbol_name": "process", "task_hint": "storage", "max_tokens": budget}
        result = await gateway.execute_mcp("inspect_symbol", args)
        assert response_tokens(result) <= budget
        data = decode(result)
        assert_exact_excerpts(data, lines)
        received = data["source"]["text"].splitlines()
        for _ in range(150):
            continuation = data["follow_up"]["next_source"]
            if continuation is None:
                break
            assert continuation["source_start_line"] == len(received) + 1
            args = {k: v for k, v in continuation.items() if k != "tool"}
            result = await gateway.execute_mcp("inspect_symbol", {**args, "max_tokens": budget})
            assert response_tokens(result) <= budget
            data = decode(result)
            received.extend(data["source"]["text"].splitlines())
        assert received == lines
    finally:
        await gateway.close()


def test_rust_inline_tests_remain_candidates():
    from types import SimpleNamespace

    from attocode_intel.test_ranking import rank_symbol_tests
    ast = SimpleNamespace(index=SimpleNamespace(file_symbols={"src/lib.rs": []}),
                          get_file_symbols=lambda path: [], get_callers=lambda name: [])
    rows = rank_symbol_tests(ast, {"src/lib.rs": {"priority": 1, "reasons": ["Rust inline test module"]}},
                             ["src/lib.rs"], "parse", None, {})
    assert [row["file_path"] for row in rows] == ["src/lib.rs"]


async def test_hint_does_not_hide_the_tail_of_a_short_function(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    lines = ["def serialize(payload):", *(f"    payload += {i}" for i in range(20)), "    return payload"]
    (tmp_path / "engine.py").write_text("\n".join(lines) + "\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        data = decode(await gateway.execute_mcp("inspect_symbol", {"symbol_name": "serialize", "task_hint": "serialize"}))
        assert data["source"]["text"].splitlines() == lines
        assert data["follow_up"]["next_source"] is None
    finally:
        await gateway.close()
