"""Navigation regressions drawn from CommonJS, TSX and Rust workspace failures."""

import pytest
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.codebase_context import _resolve_rust_import
from attocode_intel._internal.integrations.context.syntax_evidence import symbol_position
from attocode_intel.gateway import OperationGateway


def project(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return OperationGateway(str(root), profile="daily", watch=False)


async def query(gateway, operation, **args):
    result = await gateway.execute(operation, args)
    assert not result.isError
    return result.structuredContent


@pytest.fixture(autouse=True)
def base_analysis(monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")


async def test_commonjs_navigation_and_import_edits(tmp_path):
    gateway = project(tmp_path, {
        "lib/response.js": "exports.json = function (value) { return value; };\n",
        "lib/other.js": "exports.other = () => true;\n",
        "test/response.js": "const res = require('../lib/response');\nres.json({});\n",
    })
    try:
        found = await query(gateway, "search_symbols", name="json")
        assert any(row["qualified_name"] == "exports.json" for row in found["data"])
        methods = await query(gateway, "search_symbols", name="json", kind="method")
        assert any(row["qualified_name"] == "exports.json" for row in methods["data"])
        refs = await query(gateway, "cross_references", symbol_name="json")
        assert any(row["file_path"] == "test/response.js" and row["line"] == 2 for row in refs["data"]["references"])
        deps = await query(gateway, "dependencies", path="lib/response.js")
        assert deps["data"]["imported_by"] == ["test/response.js"]
        (tmp_path / "test/response.js").write_text("const other = require('../lib/other');\nother.other();\n")
        deps = await query(gateway, "dependencies", path="lib/response.js")
        assert deps["data"]["imported_by"] == []
        deps = await query(gateway, "dependencies", path="lib/other.js")
        assert deps["data"]["imported_by"] == ["test/response.js"]
    finally:
        await gateway.close()


async def test_rust_workspace_aliases_calls_and_inline_tests(tmp_path):
    gateway = project(tmp_path, {
        "crates/ignore/src/lib.rs": "mod walk;\npub use crate::walk::WalkBuilder;\n",
        "crates/ignore/src/walk.rs": "pub struct WalkBuilder;\nimpl WalkBuilder { pub fn new() -> Self { Self } }\n#[test]\nfn test_walk() { WalkBuilder::new(); }\n",
        "crates/ignore/src/run.rs": "use crate::{walk::WalkBuilder as Builder};\nfn run() { Builder::new(); }\n",
    })
    try:
        refs = await query(gateway, "cross_references", symbol_name="WalkBuilder")
        assert any(r["file_path"].endswith("run.rs") and r["line"] == 2 for r in refs["data"]["references"])
        deps = await query(gateway, "dependencies", path="crates/ignore/src/walk.rs")
        assert set(deps["data"]["imported_by"]) == {"crates/ignore/src/lib.rs", "crates/ignore/src/run.rs"}
        tests = await query(gateway, "suggest_tests", files=["crates/ignore/src/walk.rs"])
        assert "inline test" in tests["result"]
        assert "not complete coverage" in tests["result"]
    finally:
        await gateway.close()


def test_nested_rust_module_resolution():
    files = {f: f for f in ["crates/a/src/lib.rs", "crates/a/src/outer.rs", "crates/a/src/outer/child.rs", "crates/a/src/helper.rs", "crates/b/src/helper.rs"]}
    assert _resolve_rust_import("mod:child", "crates/a/src/outer.rs", files) == "crates/a/src/outer/child.rs"
    assert _resolve_rust_import("super::helper::run", "crates/a/src/outer.rs", files) == "crates/a/src/helper.rs"
    assert _resolve_rust_import("crate::helper::run", "crates/a/src/outer/child.rs", files) == "crates/a/src/helper.rs"


def test_typescript_tsx_declarations_and_reexports(tmp_path):
    path = tmp_path / "view.tsx"
    source = '''export interface Props { title: string }
export type Status = "ready" | "loading";
export { helper } from './helper';
export const View = (props: Props) => <div>{props.title}</div>;
'''
    path.write_text(source)
    ast = parse_file(str(path))
    assert {c.name for c in ast.classes} == {"Props", "Status"}
    assert [f.name for f in ast.functions] == ["View"]
    assert [i.module for i in ast.imports] == ["./helper"]
    assert symbol_position(str(path), "View", 4, 4, "typescript") == (3, 13)


def test_multiline_assignment_uses_identifier_line_and_utf16_column(tmp_path):
    path = tmp_path / "response.js"
    source = 'const marker = "😀"; exports.json =\n    (value) => value;\n'
    path.write_text(source)
    function = parse_file(str(path)).functions[0]
    assert function.name == "json"
    assert function.start_line == 1
    prefix = source.split("json")[0]
    assert symbol_position(str(path), function.name, function.start_line,
                           function.end_line, "javascript") == (0, len(prefix.encode("utf-16-le")) // 2)


async def test_comments_strings_and_definitions_are_not_calls(tmp_path):
    gateway = project(tmp_path, {"main.py": 'def run():\n    return 1\n# run()\ns = "run()"\ndef caller():\n    return run()\n'})
    try:
        refs = await query(gateway, "cross_references", symbol_name="run")
        assert [(r["file_path"], r["line"]) for r in refs["data"]["references"]] == [("main.py", 6)]
        assert refs["metadata"]["analysis"]["absence_proven"] is False
        assert "partial" in refs["result"]
        impact = await query(gateway, "impact_analysis", changed_files=["main.py"])
        assert "No other files are impacted" not in impact["result"]
        assert impact["data"]["absence_proven"] is False
    finally:
        await gateway.close()


async def test_indirect_tests_and_stale_bootstrap(tmp_path):
    gateway = project(tmp_path, {
        "serialize.py": "def serialize_response(value):\n    return value\n",
        "routing.py": "from serialize import serialize_response\ndef request(v):\n    return serialize_response(v)\n",
        "tests/test_response.py": "from routing import request\ndef test_response():\n    assert request(1) == 1\n",
    })
    try:
        tests = await query(gateway, "suggest_tests", files=["serialize.py"])
        assert "tests/test_response.py" in tests["result"]
        assert "2 edges" in tests["result"]
        await query(gateway, "record_learning", type="gotcha", description="serialize_response USE_THE_OLD_FORMAT", scope="serialize.py")
    finally:
        await gateway.close()
    (tmp_path / "serialize.py").write_text("def serialize_response(value):\n    return str(value)\n")
    gateway = OperationGateway(str(tmp_path), profile="daily", watch=False)
    try:
        recall = await query(gateway, "recall", query="serialize_response")
        assert recall["data"][0]["stale"] is True
        bootstrap = await query(gateway, "bootstrap", task_hint="serialize_response", max_tokens=1500)
        assert "USE_THE_OLD_FORMAT" not in bootstrap["result"]
    finally:
        await gateway.close()


async def test_typescript_path_aliases_and_commonjs_directory_entry(tmp_path):
    gateway = project(tmp_path, {
        "tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        "src/helpers.ts": "export function helper() { return 1; }\n",
        "src/view.tsx": "import { helper } from '@/helpers';\nexport const View = () => <div>{helper()}</div>;\n",
        "index.js": "module.exports = require('./src/entry');\n",
        "src/entry.js": "exports.start = () => true;\n",
        "test/entry.js": "const app = require('..');\napp.start();\n",
    })
    try:
        deps = await query(gateway, "dependencies", path="src/helpers.ts")
        assert deps["data"]["imported_by"] == ["src/view.tsx"]
        deps = await query(gateway, "dependencies", path="index.js")
        assert deps["data"]["imported_by"] == ["test/entry.js"]
    finally:
        await gateway.close()


@pytest.mark.parametrize("options", [[], {"baseUrl": 42}, {"paths": []}])
async def test_invalid_tsconfig_options_do_not_break_relative_navigation(tmp_path, options):
    import json
    gateway = project(tmp_path, {
        "tsconfig.json": json.dumps({"compilerOptions": options}),
        "helper.ts": "export function helper() { return 1; }\n",
        "caller.ts": "import { helper } from './helper';\nhelper();\n",
    })
    try:
        deps = await query(gateway, "dependencies", path="helper.ts")
        assert deps["data"]["imported_by"] == ["caller.ts"]
    finally:
        await gateway.close()
