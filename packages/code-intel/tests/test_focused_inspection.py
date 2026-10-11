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


async def test_workspace_member_src_layout_links_its_tests(tmp_path, monkeypatch):
    # A monorepo: the root config names only its own package, and a member package uses src/.
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "pyproject.toml").write_text('[tool.hatch.build.targets.wheel]\npackages = ["src/app"]\n')
    (tmp_path / "src/app").mkdir(parents=True)
    (tmp_path / "src/app/__init__.py").write_text("")
    member = tmp_path / "packages/lib"
    (member / "src/mylib").mkdir(parents=True)
    (member / "src/mylib/__init__.py").write_text("")
    (member / "src/mylib/core.py").write_text("def target(): return 1\n")
    (member / "tests").mkdir()
    (member / "tests/test_core.py").write_text("from mylib.core import target\ndef test_core(): assert target() == 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_target_words.py").write_text("def test_target_words(): assert True\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        bundle = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "target", "file_path": "packages/lib/src/mylib/core.py"}))
        assert bundle["tests"][0]["file_path"] == "packages/lib/tests/test_core.py"
        assert bundle["tests"][0]["evidence"]["selected_symbol_reference"]
    finally:
        await gateway.close()


def test_name_matched_tests_prefer_the_nearest_test_for_the_file():
    from attocode_intel.test_ranking import is_test_path, name_matched_tests

    tests = ["lib/pkg/tests/test_figure.py", "lib/other/tests/test_figure.py", "lib/pkg/tests/test_figure_legend.py"]
    assert name_matched_tests("lib/pkg/figure.py", tests) == [
        ("lib/pkg/tests/test_figure.py", 1, "Test file named for `lib/pkg/figure.py`"),
        ("lib/other/tests/test_figure.py", 3, "Test file named for `lib/pkg/figure.py`"),
        ("lib/pkg/tests/test_figure_legend.py", 4, "Test file name contains `figure`"),
    ]
    # Java tests in another package or module, and .NET test projects.
    java = "core/src/main/java/org/x/Version.java"
    assert name_matched_tests(java, ["core-testing/src/test/java/org/x/v/VersionTest.java"])[0][1] == 1
    assert is_test_path("App.Tests/Parsing/ParserTests.cs")
    assert name_matched_tests("App/Parsing/Parser.cs", ["App.Tests/Parsing/ParserTests.cs"])[0][1] == 1
    # A word that ends in "test" is not a test affix.
    assert name_matched_tests("src/latest.py", ["tests/contest.py"]) == []
    # A fixture in a test folder has no test affix, and a test with no shared folder is far.
    assert [row[1] for row in name_matched_tests("lib/pkg/figure.py", ["lib/pkg/tests/data/figure.py"])] == [4]
    assert [row[1] for row in name_matched_tests("kernel/core.c", ["tools/selftests/test_core.c"])] == [3]
    # A two-letter name matches its test exactly, but a name that only contains it is noise.
    assert [row[0] for row in name_matched_tests("src/uu/cp/src/cp.rs", ["tests/test_cp.rs", "tests/test_scp.rs"])] == [
        "tests/test_cp.rs"]


async def test_lib_layout_links_tests_by_name_and_by_import(tmp_path, monkeypatch):
    # matplotlib keeps its package in lib/, and its tests in a tests/ folder next to the source.
    import subprocess

    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "lib/pkg/tests").mkdir(parents=True)
    (tmp_path / "lib/pkg/__init__.py").write_text("")
    (tmp_path / "lib/pkg/figure.py").write_text("class Figure:\n    pass\n")
    (tmp_path / "lib/pkg/tests/__init__.py").write_text("")
    (tmp_path / "lib/pkg/tests/test_figure.py").write_text("def test_figure(): assert True\n")
    (tmp_path / "lib/pkg/tests/test_layout.py").write_text(
        "from pkg.figure import Figure\ndef test_layout(): assert Figure()\n")
    (tmp_path / "lib/pkg/tests/test_text.py").write_text("def test_text(): assert True\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("suggest_tests", {"files": ["lib/pkg/figure.py"]})
        paths = [row["file_path"] for row in decode(result)["candidates"]]
        assert paths[:2] == ["lib/pkg/tests/test_figure.py", "lib/pkg/tests/test_layout.py"]
        assert "lib/pkg/tests/test_text.py" not in paths
    finally:
        await gateway.close()


async def test_tests_on_shorter_import_paths_rank_first(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("")
    (tmp_path / "pkg/a.py").write_text("def base(): return 1\n")
    (tmp_path / "pkg/b.py").write_text("from pkg.a import base\ndef mid(): return base()\n")
    (tmp_path / "pkg/c.py").write_text("from pkg.b import mid\ndef top(): return mid()\n")
    # Path order puts the farther test first; two import steps beat three.
    (tmp_path / "tests/test_aa_far.py").write_text("from pkg.c import top\ndef test_top(): assert top()\n")
    (tmp_path / "tests/test_zz_near.py").write_text("from pkg.b import mid\ndef test_mid(): assert mid()\n")
    # A shared folder name beats a shorter import path (pylint tests/config/ for pylint/config/).
    (tmp_path / "tests/pkg").mkdir()
    (tmp_path / "tests/pkg/test_deep.py").write_text("from pkg.c import top\ndef test_top(): assert top()\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("suggest_tests", {"files": ["pkg/a.py"]})
        paths = [row["file_path"] for row in decode(result)["candidates"]]
        assert paths == ["tests/pkg/test_deep.py", "tests/test_zz_near.py", "tests/test_aa_far.py"]
    finally:
        await gateway.close()
