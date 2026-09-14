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
        assert "linked to selected symbol" in bundle["tests"][0]["reasons"][0]
        changed = decode(await gateway.execute_mcp("inspect_symbol", {**args, "symbol_name": other}))
        assert changed["tests"][0]["file_path"] != "test_regression.py"
        assert not suggestions["absence_proven"]
    finally:
        await gateway.close()

async def test_selected_definition_separates_same_name_references_and_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "backend.ts").write_text(
        'export function getAncestryChain(){ return ["backend"] }\n')
    (tmp_path / "frontend.ts").write_text(
        'export function getAncestryChain(){ return ["frontend"] }\n')
    (tmp_path / "backend.test.ts").write_text(
        'import {getAncestryChain} from "./backend";\n'
        'test("backend", () => getAncestryChain());\n'
        'test("unrelated member", () => other.getAncestryChain());\n')
    (tmp_path / "frontend.test.ts").write_text(
        'import {getAncestryChain} from "./frontend";\n'
        'test("frontend", () => getAncestryChain());\n')
    (tmp_path / "noise.test.ts").write_text(
        'function getAncestryChain(){ return [] }\n'
        'test("noise", () => getAncestryChain());\n')
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        selected = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "getAncestryChain", "file_path": "backend.ts", "line": 1}))
        assert {ref["file_path"] for ref in selected["references"]} == {"backend.test.ts"}
        assert all(ref["resolution"] == "import_binding" for ref in selected["references"])
        assert {ref["file_path"] for ref in selected["reference_candidates"]} == {
            "backend.test.ts", "frontend.test.ts", "noise.test.ts"}
        assert any(ref.get("syntax") == "other.getAncestryChain"
                   for ref in selected["reference_candidates"])
        assert selected["tests"][0]["file_path"] == "backend.test.ts"
        assert selected["tests"][0]["evidence"]["selected_symbol_reference"]
        assert all(not row["evidence"]["selected_symbol_reference"]
                   for row in selected["tests"][1:])
        assert "get" not in selected["tests"][-1]["evidence"]["symbol_terms"]
    finally:
        await gateway.close()

    # The written member expression must survive the persistent-index path;
    # otherwise restart would turn it back into a linked bare-name call.
    reopened = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        selected = decode(await reopened.execute_mcp("inspect_symbol", {
            "symbol_name": "getAncestryChain", "file_path": "backend.ts", "line": 1}))
        assert any(ref.get("syntax") == "other.getAncestryChain"
                   for ref in selected["reference_candidates"])
    finally:
        await reopened.close()


@pytest.mark.parametrize("language", ["python", "typescript"])
async def test_alias_reexports_link_calls_to_original_definition(tmp_path, monkeypatch, language):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    if language == "python":
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "impl.py").write_text("def calculate(): return 1\n")
        (package / "__init__.py").write_text("from .impl import calculate as compute\n")
        (tmp_path / "test_calc.py").write_text(
            "from pkg import compute as run\ndef test_calc(): assert run() == 1\n")
        file_path, test_path = "pkg/impl.py", "test_calc.py"
    else:
        (tmp_path / "impl.ts").write_text("export function calculate(){ return 1 }\n")
        (tmp_path / "barrel.ts").write_text(
            'export {calculate as compute} from "./impl";\n')
        (tmp_path / "calc.test.ts").write_text(
            'import {compute as run} from "./barrel";\n'
            'test("calculate", () => run());\n')
        file_path, test_path = "impl.ts", "calc.test.ts"
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        selected = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "calculate", "file_path": file_path, "line": 1}))
        test_refs = [ref for ref in selected["references"] if ref["file_path"] == test_path]
        assert any(ref["ref_kind"] == "call" for ref in test_refs)
        assert not selected["reference_candidates"]
        assert selected["tests"][0]["file_path"] == test_path
        assert selected["tests"][0]["evidence"] == {
            "selected_symbol_reference": True,
            "reference_resolution": "linked",
            "symbol_terms": [],
            "task_terms": [],
            "import_distance": 2,
        }
    finally:
        await gateway.close()


async def test_typescript_wildcard_and_namespace_reexports_link_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "impl.ts").write_text("export function calculate(){ return 1 }\n")
    (tmp_path / "wildcard.ts").write_text('export * from "./impl";\n')
    (tmp_path / "namespace.ts").write_text('export * as math from "./impl";\n')
    (tmp_path / "wildcard.test.ts").write_text(
        'import {calculate as execute} from "./wildcard";\n'
        'test("wildcard", () => execute());\n')
    (tmp_path / "namespace.test.ts").write_text(
        'import {math} from "./namespace";\n'
        'test("namespace", () => math.calculate());\n')
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        selected = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "calculate", "file_path": "impl.ts", "line": 1}))
        calls = {(ref["file_path"], ref["symbol"]) for ref in selected["references"]
                 if ref["ref_kind"] == "call"}
        assert calls == {("wildcard.test.ts", "execute"),
                         ("namespace.test.ts", "math.calculate")}
        assert not selected["reference_candidates"]
        assert {row["file_path"] for row in selected["tests"][:2]} == {
            "wildcard.test.ts", "namespace.test.ts"}
        assert all(row["evidence"]["selected_symbol_reference"] for row in selected["tests"][:2])
    finally:
        await gateway.close()


async def test_same_file_methods_use_enclosing_class_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "models.ts").write_text(
        "class Backend {\n"
        "  run(){ return 1 }\n"
        "  invoke(){ return this.run() }\n"
        "}\n"
        "class Frontend {\n"
        "  run(){ return 2 }\n"
        "  invoke(){ return this.run() }\n"
        "}\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        selected = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "Backend.run", "file_path": "models.ts", "line": 2}))
        assert [(ref["line"], ref["resolution"]) for ref in selected["references"]] == [
            (3, "same_file")]
        assert any(ref["line"] == 7 and ref["resolution"] == "same_name_candidate"
                   for ref in selected["reference_candidates"])
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
