"""Small mixed-language workspace contracts; no claim of precise call resolution."""
import json

import pytest
from attocode_intel.gateway import OperationGateway


async def call(gateway, operation, **arguments):
    result = await gateway.execute(operation, arguments, compact=True)
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("restart", [False, True], ids=["live", "reopened"])
async def test_mixed_workspace_selects_sources_and_recovers_after_changes(tmp_path, monkeypatch, restart):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    root = tmp_path / "project with spaces"
    root.mkdir()
    sources = {
        "src café/helper.py": "# café\ndef route():\n    return 'python'\n",
        "web/helper.ts": "export function route(): string { return 'typescript'; }\n",
        "web/helper.js": "export function route() { return 'javascript'; }\n",
        "backend/helper.go": 'package backend\nfunc route() string { return "go" }\n',
        "native/helper.rs": 'pub fn route() -> i32 { 1 }\n',
        "java/Helper.java": 'class Helper { public int route() { return 1; } }\n',
    }
    for path, source in sources.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    (root / "web/caller.ts").write_text("import { route } from './helper';\nexport function caller() { return route(); }\n")
    (root / "broken.py").write_text("def unfinished(\n")
    (root / ".gitignore").write_text("generated/\n")
    for folder in ("generated", "node_modules"):
        (root / folder).mkdir()
        (root / folder / "hidden.py").write_text("def route(): return 'hidden'\n")
    outside = tmp_path / "outside.py"
    outside.write_text("def outside_only(): return 'not project source'\n")
    (root / "outside_link.py").symlink_to(outside)

    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        matches = await call(gateway, "search_symbols", name="route", limit=20)
        assert {row["file_path"] for row in matches["data"]} == set(sources)
        assert matches["metadata"]["absence_proven"] is False
        ambiguous = await call(gateway, "inspect_symbol", symbol_name="route")
        assert ambiguous["data"]["status"] == "ambiguous"
        for path, source in sources.items():
            inspected = await call(gateway, "inspect_symbol", symbol_name="route", file_path=path)
            assert inspected["data"]["definition"]["file_path"] == path
            snippet = inspected["data"]["source"]
            assert snippet["text"] == "\n".join(source.splitlines()[snippet["start_line"] - 1:snippet["end_line"]])
        outside_matches = await call(gateway, "search_symbols", name="outside_only")
        assert all(row["name"] != "outside_only" for row in outside_matches["data"])
        dependencies = await call(gateway, "dependencies", path="web/caller.ts")
        assert "web/helper.ts" in dependencies["data"]["imports"]
        if restart:
            await gateway.close()
        (root / "web/helper.ts").rename(root / "web/moved.ts")
        (root / "web/caller.ts").write_text("import { route } from './moved';\nexport function caller() { return route(); }\n")
        (root / "broken.py").write_text("def repaired():\n    return 1\n")
        if restart:
            gateway = OperationGateway(str(root), "daily", watch=False)
        matches = await call(gateway, "search_symbols", name="route", limit=20)
        assert {row["file_path"] for row in matches["data"]} == (set(sources) - {"web/helper.ts"}) | {"web/moved.ts"}
        assert (await call(gateway, "search_symbols", name="repaired"))["data"][0]["file_path"] == "broken.py"
        dependencies = await call(gateway, "dependencies", path="web/caller.ts")
        assert "web/moved.ts" in dependencies["data"]["imports"]
        assert "web/helper.ts" not in dependencies["data"]["imports"]
    finally:
        await gateway.close()


@pytest.mark.parametrize("restart", [False, True], ids=["live", "reopened"])
async def test_retargeted_symlink_discards_old_index_and_preserves_internal_alias(tmp_path, restart):
    root = tmp_path / "workspace"
    root.mkdir()
    inside = root / "inside.py"
    inside.write_text("def inside_only(): return 1\n")
    outside = tmp_path / "outside.py"
    outside.write_text("def outside_only(): return 2\n")
    link = root / "alias.py"
    link.symlink_to(inside)
    (root / "dangling.py").symlink_to(root / "missing.py")
    (root / "loop.py").symlink_to(root / "loop.py")
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        matches = await call(gateway, "search_symbols", name="inside_only")
        assert {r["file_path"] for r in matches["data"]} == {"inside.py", "alias.py"}
        if restart:
            await gateway.close()
        link.unlink()
        link.symlink_to(outside)
        if restart:
            gateway = OperationGateway(str(root), "daily", watch=False)
        matches = await call(gateway, "search_symbols", name="inside_only")
        assert {r["file_path"] for r in matches["data"]} == {"inside.py"}
        outside_matches = await call(gateway, "search_symbols", name="outside_only")
        assert all(row["name"] != "outside_only" and row["file_path"] != "alias.py"
                   for row in outside_matches["data"])
        link.unlink()
        link.symlink_to(inside)
        matches = await call(gateway, "search_symbols", name="inside_only")
        assert {r["file_path"] for r in matches["data"]} == {"inside.py", "alias.py"}
    finally:
        await gateway.close()
