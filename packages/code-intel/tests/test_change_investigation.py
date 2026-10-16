"""Real Git/MCP/CLI workflow cases, including source-identity and stale-report traps."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from attocode_intel.change_evidence import GitWorkspace, check_report
from attocode_intel.gateway import OperationGateway


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=root,
        text=True,
    ).strip()


def repository(root, files):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for name, content in {".gitignore": ".attocode/\n", **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")


@pytest.fixture(autouse=True)
def structural_only(monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")


async def query(gateway, name="change_context", **arguments):
    response = await gateway.execute(name, arguments)
    assert not response.isError, response.content
    return response.structuredContent["data"]


LANGUAGES = {
    "python": (
        "worker.py",
        "caller.py",
        "test_worker.py",
        "def work():\n    return 1\n",
        "def work():\n    return 2\n",
        "from worker import work\ndef run():\n    return work()\n",
        "from caller import run\ndef test_run():\n    assert run() == 2\n",
    ),
    "typescript": (
        "worker.ts",
        "caller.ts",
        "worker.test.ts",
        "export function work() { return 1; }\n",
        "export function work() { return 2; }\n",
        "import {work} from './worker';\nexport function run() { return work(); }\n",
        "import {run} from './caller';\nfunction test_run() { return run(); }\n",
    ),
    "go": (
        "worker/worker.go",
        "caller/caller.go",
        "caller/caller_test.go",
        "package worker\nfunc Work() int { return 1 }\n",
        "package worker\nfunc Work() int { return 2 }\n",
        'package caller\nimport "example.test/app/worker"\nfunc Run() int { return worker.Work() }\n',
        "package caller\nfunc TestRun() { Run() }\n",
    ),
    "rust": (
        "src/worker.rs",
        "src/caller.rs",
        "src/caller_test.rs",
        "pub fn work() -> i32 { 1 }\n",
        "pub fn work() -> i32 { 2 }\n",
        "use crate::worker::work;\npub fn run() -> i32 { work() }\n",
        "use crate::caller::run;\n#[test]\nfn test_run() { run(); }\n",
    ),
}


@pytest.mark.parametrize("language", LANGUAGES)
async def test_real_diff_flow_tests_refresh_branch_and_restart(tmp_path, language):
    target, caller, test, old, new, caller_source, test_source = LANGUAGES[language]
    files = {target: old, caller: caller_source, test: test_source}
    if language == "go":
        files["go.mod"] = "module example.test/app\n\ngo 1.22\n"
    if language == "rust":
        files["src/lib.rs"] = "mod worker;\nmod caller;\nmod caller_test;\n"
    repository(tmp_path, files)
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        assert (await query(gateway))["status"] == "no_changes"
        (tmp_path / target).write_text(new)
        report = await query(gateway)
        changed = [r for r in report["symbols"] if r["change"] == "modified"]
        assert len(changed) == 1
        symbol = changed[0]["after"]
        edges = changed[0]["flow"]["edges"]
        assert any(
            e["site"]["file_path"] == caller and e["callee"]["file_path"] == target for e in edges
        )
        assert any(e["site"]["file_path"] == test for e in edges)
        assert test in {c["file_path"] for c in report["tests"]["candidates"]}
        assert report["analysis"] == "partial" and report["absence_proven"] is False
        assert check_report(str(tmp_path), report)["status"] == "current"
        trace = await query(
            gateway,
            "trace_flow",
            symbol_name=symbol["qualified_name"],
            file_path=target,
            line=symbol["start_line"],
            depth=2,
        )
        assert any(e["site"]["file_path"] == test for e in trace["flow"]["edges"])
        await gateway.close()
        gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
        restarted = await query(gateway)
        assert restarted["report_id"] == report["report_id"]
        git(tmp_path, "switch", "-qc", "feature")
        git(tmp_path, "add", target)
        git(tmp_path, "commit", "-qm", "change")
        assert check_report(str(tmp_path), report)["status"] == "stale"
        branch = await query(gateway, mode="branch", base="main")
        assert branch["comparison_revision"] == report["snapshot"]["head"]
        assert branch["symbols"]
        git(tmp_path, "switch", "-q", "main")
        assert (await query(gateway))["status"] == "no_changes"
    finally:
        await gateway.close()


async def test_staged_and_unstaged_sources_are_never_confused(tmp_path):
    repository(tmp_path, {"worker.py": "def work():\n    return 1\n"})
    (tmp_path / "worker.py").write_text("def work():\n    return 2\n")
    git(tmp_path, "add", "worker.py")
    (tmp_path / "worker.py").write_text("def other():\n    return 3\n")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        staged = await query(gateway, mode="staged")
        assert staged["symbols"][0]["after"]["name"] == "work"
        assert staged["symbols"][0]["current_source_matches"] is False
        assert staged["symbols"][0]["flow"]["status"] == "unavailable"
        unstaged = await query(gateway, mode="unstaged")
        assert {r["change"] for r in unstaged["symbols"]} == {"added", "removed"}
        assert {r["after"]["name"] for r in unstaged["symbols"] if r["after"]} == {"other"}
    finally:
        await gateway.close()


async def test_rename_delete_untracked_and_non_symbol_changes(tmp_path):
    repository(
        tmp_path, {"old.py": "def work():\n    return 1\n", "settings.json": '{"limit": 1}\n'}
    )
    git(tmp_path, "mv", "old.py", "renamed file.py")
    (tmp_path / "new.py").write_text("def added():\n    return 1\n")
    (tmp_path / "settings.json").write_text('{"limit": 2}\n')
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway)
        moved = next(r for r in report["symbols"] if r["change"] == "moved")
        assert (
            moved["before"]["file_path"] == "old.py"
            and moved["after"]["file_path"] == "renamed file.py"
        )
        assert any(r["change"] == "added" for r in report["symbols"])
        assert any(r["file_path"] == "settings.json" for r in report["files"])
        (tmp_path / "renamed file.py").unlink()
        deleted = await query(gateway)
        removed = next(r for r in deleted["symbols"] if r["change"] == "removed")
        assert removed["before"]["name"] == "work" and removed["flow"]["status"] == "unavailable"
    finally:
        await gateway.close()


async def test_ambiguity_cycles_depth_and_caps(tmp_path):
    repository(
        tmp_path,
        {
            "one.py": "def a():\n    return b()\ndef b():\n    return a()\n",
            "two.py": "def a():\n    return 1\n",
        },
    )
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        ambiguous = await query(gateway, "trace_flow", symbol_name="a")
        assert ambiguous["status"] == "ambiguous" and ambiguous["total_definitions"] == 2
        flow = (
            await query(gateway, "trace_flow", symbol_name="a", file_path="one.py", line=1, depth=3)
        )["flow"]
        assert len(flow["nodes"]) == 2 and len(flow["edges"]) == 2
        assert all(e["site"]["file_path"] == "one.py" for e in flow["edges"])
        shallow = (
            await query(gateway, "trace_flow", symbol_name="a", file_path="one.py", depth=1)
        )["flow"]
        assert len(shallow["edges"]) == 1
        capped = (
            await query(gateway, "trace_flow", symbol_name="a", file_path="one.py", max_nodes=1)
        )["flow"]
        assert capped["bounded"] and capped["omitted"]["nodes"]
        assert len(capped["nodes"]) == 1
    finally:
        await gateway.close()


async def test_changed_symbol_caps_and_unchanged_line_moves(tmp_path):
    repository(tmp_path, {"a.py": "def unchanged():\n    return 1\ndef changed():\n    return 1\n"})
    (tmp_path / "a.py").write_text(
        "# header\ndef unchanged():\n    return 1\ndef changed():\n    return 2\ndef added():\n    return 3\n"
    )
    (tmp_path / "b.py").write_text("def extra():\n    return 1\n")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway, max_files=1, max_symbols=1)
        assert report["bounded"] and report["omitted"] == {"files": 1, "symbols": 1}
        assert report["symbols"][0]["after"]["name"] != "unchanged"
    finally:
        await gateway.close()


def test_freshness_detects_same_size_edits_untracked_index_and_report_tampering(tmp_path):
    repository(tmp_path, {"a.py": "def a():\n    return 1\n"})
    workspace = GitWorkspace(tmp_path)
    (tmp_path / "a.py").write_text("def a():\n    return 2\n")
    before = workspace.snapshot()
    (tmp_path / "a.py").write_text("def a():\n    return 3\n")
    assert before != workspace.snapshot()
    before = workspace.snapshot()
    (tmp_path / "new.py").write_text("# new\n")
    assert before != workspace.snapshot()
    before = workspace.snapshot()
    git(tmp_path, "add", "a.py")
    assert before != workspace.snapshot()


@pytest.mark.parametrize("failure", ["outside", "symlink", "large", "revision", "output"])
def test_input_and_git_output_bounds(tmp_path, failure):
    repository(tmp_path, {"a.py": "def a(): pass\n"})
    workspace = GitWorkspace(tmp_path)
    with pytest.raises(ValueError):
        if failure == "outside":
            workspace.read("../outside.py")
        elif failure == "symlink":
            (tmp_path / "link.py").symlink_to(tmp_path / "a.py")
            workspace.read("link.py")
        elif failure == "large":
            (tmp_path / "large.py").write_bytes(b"x" * (512 * 1024 + 1))
            workspace.snapshot()
        elif failure == "revision":
            workspace.revision("--help")
        else:
            workspace.git("ls-files", limit=1)


async def test_compact_delivery_preserves_provenance_and_rejects_trimmed_exports(tmp_path):
    repository(tmp_path, {"a.py": "def a():\n    return 1\n"})
    (tmp_path / "a.py").write_text("def a():\n    return 2\n")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway)
        damaged = {**report, "status": "changed"}
        with pytest.raises(ValueError, match="integrity"):
            check_report(str(tmp_path), damaged)
        compact = await gateway.execute("change_context", {"max_tokens": 1500}, compact=True)
        assert not compact.isError
        data = json.loads(compact.content[0].text)
        assert data["metadata"]["workspace"] == str(tmp_path)
        assert data["data"]["absence_proven"] is False
        assert len(compact.content) == 1
    finally:
        await gateway.close()


def test_full_local_only_catalog_does_not_expand_daily_or_lean():
    from attocode_intel.catalog import tool_catalog

    names = {"change_context", "trace_flow"}
    assert names <= {t.name for t in tool_catalog("full")}
    for profile, remote in [("daily", False), ("lean", False), ("full", True)]:
        assert not names & {t.name for t in tool_catalog(profile, remote=remote)}


def cli(root, *args, check=True):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from attocode_intel.entrypoint import main; main()",
            *args,
            "--project",
            str(root),
        ],
        text=True,
        capture_output=True,
        check=check,
    )


def test_cli_export_check_refresh_markdown_and_no_overwrite(tmp_path):
    root = tmp_path / "repo"
    repository(root, {"a.py": "def a():\n    return 1\n"})
    (root / "a.py").write_text("def a():\n    return 2\n")
    saved = tmp_path / "report.json"
    cli(root, "changes", "--output", str(saved))
    assert json.loads(cli(root, "changes", "--check", str(saved)).stdout)["status"] == "current"
    (root / "a.py").write_text("def a():\n    return 3\n")
    stale = cli(root, "changes", "--check", str(saved), check=False)
    assert stale.returncode == 1 and json.loads(stale.stdout)["status"] == "stale"
    refreshed = json.loads(cli(root, "changes", "--refresh", str(saved)).stdout)
    assert refreshed["report_id"] != json.loads(saved.read_text())["report_id"]
    markdown = cli(root, "trace", "a", "--file", "a.py", "--format", "markdown")
    assert "# Change investigation" in markdown.stdout and "partial" in markdown.stdout
    assert cli(root, "changes", "--output", str(saved), check=False).returncode == 2


async def test_rename_delete_and_staged_only_workflows_across_languages(tmp_path):
    for language, (target, _, _, old, new, _, _) in LANGUAGES.items():
        root = tmp_path / language
        repository(root, {target: old})
        (root / target).write_text(new)
        git(root, "add", target)
        gateway = OperationGateway(str(root), profile="full", watch=False)
        try:
            assert (await query(gateway, mode="staged"))["symbols"][0]["change"] == "modified"
            assert (await query(gateway, mode="unstaged"))["status"] == "no_changes"
            git(root, "commit", "-qm", "edit")
            renamed = str(Path(target).with_name("renamed" + Path(target).suffix))
            git(root, "mv", target, renamed)
            report = await query(gateway)
            assert report["symbols"][0]["change"] == "moved"
            (root / renamed).unlink()
            report = await query(gateway)
            assert report["symbols"][0]["change"] == "removed"
            assert report["symbols"][0]["flow"]["status"] == "unavailable"
        finally:
            await gateway.close()


async def test_unbound_receivers_and_go_other_packages_are_never_followed(tmp_path):
    repository(
        tmp_path,
        {
            "worker.go": "package worker\nfunc Work() int { return 1 }\n",
            "same.go": "package worker\nfunc Same() int { return Work() }\n",
            "other.go": "package worker_test\nfunc Other() int { return Work() }\n",
            "different/worker.go": "package worker\nfunc Other() int { return Work() }\n",
            "one.py": "class One:\n    def close(self): pass\ndef wrong(store):\n    store.close()\n",
        },
    )
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        flow = (await query(gateway, "trace_flow", symbol_name="Work", file_path="worker.go"))[
            "flow"
        ]
        assert {e["site"]["file_path"] for e in flow["edges"]} == {"same.go"}
        assert {r["file_path"] for r in flow["unresolved"]} >= {"other.go", "different/worker.go"}
        flow = (await query(gateway, "trace_flow", symbol_name="One.close", file_path="one.py"))[
            "flow"
        ]
        assert flow["edges"] == []
        assert flow["unresolved"]
    finally:
        await gateway.close()


async def test_overload_dispatch_is_not_invented(tmp_path):
    repository(
        tmp_path,
        {
            "Parser.java": 'class Parser {\n void parse(String x) {}\n void parse(byte[] x) {}\n void run() { parse("x"); }\n}\n'
        },
    )
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        flow = (
            await query(
                gateway, "trace_flow", symbol_name="Parser.parse", file_path="Parser.java", line=2
            )
        )["flow"]
        assert flow["edges"] == []
        assert "Overload" in flow["unresolved"][0]["reason"]
    finally:
        await gateway.close()


async def test_branch_name_only_switch_invalidates_report(tmp_path):
    repository(tmp_path, {"a.py": "def a(): pass\n"})
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway)
        git(tmp_path, "switch", "-qc", "same-content")
        result = check_report(str(tmp_path), report)
        assert result["status"] == "stale" and "branch" in result["reasons"]
    finally:
        await gateway.close()


def test_configured_workspace_code_is_not_executed(tmp_path):
    repository(tmp_path, {"a.py": "def a(): pass\n", ".gitattributes": "*.py filter=unsafe\n"})
    marker = tmp_path / "filter-ran"
    git(tmp_path, "config", "filter.unsafe.clean", "touch " + str(marker))
    workspace = GitWorkspace(tmp_path)
    workspace.snapshot()
    assert "filter.unsafe" in workspace.disabled_filters
    assert not marker.exists()


async def test_source_changed_during_collection_is_rejected(tmp_path, monkeypatch):
    from attocode_intel import change_investigation

    repository(tmp_path, {"a.py": "def a():\n    return 1\n"})
    (tmp_path / "a.py").write_text("def a():\n    return 2\n")
    original = change_investigation._finish

    def edited(*args, **kwargs):
        (tmp_path / "a.py").write_text("def a():\n    return 3\n")
        return original(*args, **kwargs)

    monkeypatch.setattr(change_investigation, "_finish", edited)
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        with pytest.raises(ValueError, match="changed during"):
            await gateway.execute("change_context", {})
    finally:
        await gateway.close()


@pytest.mark.parametrize("case", ["dirty_count", "collection_time", "unborn", "invalid_mode"])
def test_collection_admission_limits(tmp_path, case):
    repository(tmp_path, {"a.py": "def a(): pass\n"})
    workspace = GitWorkspace(tmp_path)
    with pytest.raises(ValueError):
        if case == "dirty_count":
            for i in range(257):
                (tmp_path / f"new{i}.txt").write_text("fixture")
            workspace.snapshot()
        elif case == "collection_time":
            workspace.deadline = 0
            workspace.snapshot()
        elif case == "unborn":
            git(tmp_path, "checkout", "--orphan", "empty")
            workspace.snapshot()
        else:
            workspace.changes("staged", "main")


async def test_real_full_stdio_restart_preserves_complete_report(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repository(
        tmp_path,
        {
            "worker.py": "def work():\n    return 1\n",
            "caller.py": "from worker import work\ndef run():\n    return work()\n",
        },
    )
    (tmp_path / "worker.py").write_text("def work():\n    return 2\n")
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "attocode_intel.entrypoint",
            "--project",
            str(tmp_path),
            "--profile",
            "full",
            "--no-watch",
        ],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    reports = []
    for _ in range(2):
        async with asyncio.timeout(30), stdio_client(params) as streams:  # noqa: SIM117
            async with ClientSession(*streams) as session:
                await session.initialize()
                assert {"change_context", "trace_flow"} <= {
                    t.name for t in (await session.list_tools()).tools
                }
                result = await session.call_tool("change_context", {})
                assert not result.isError
                report = result.structuredContent["data"]
                assert report["symbols"][0]["flow"]["edges"][0]["site"]["file_path"] == "caller.py"
                assert check_report(str(tmp_path), report)["status"] == "current"
                reports.append(report["report_id"])
    assert reports[0] == reports[1]


def test_authenticated_http_returns_report_and_rejects_bad_requests(tmp_path, monkeypatch):
    from attocode_intel.api.app import create_app
    from attocode_intel.config import CodeIntelConfig
    from starlette.testclient import TestClient

    repository(tmp_path, {"a.py": "def a(): return 1\n"})
    (tmp_path / "a.py").write_text("def a(): return 2\n")
    monkeypatch.setenv("ATTOCODE_MCP_PROFILE", "full")
    app = create_app(CodeIntelConfig(project_dir=str(tmp_path), api_key="test-secret"))
    headers = {"Authorization": "Bearer test-secret"}
    with TestClient(app) as client:
        route = "/api/v2/operations/change_context"
        assert client.post(route, json={}).status_code == 401
        result = client.post(route, headers=headers, json={})
        assert result.status_code == 200, result.text
        report = result.json()["data"]
        assert check_report(str(tmp_path), report)["status"] == "current"
        assert client.post(route, headers=headers, json={"depth": 99}).status_code == 422
        assert (
            client.post(
                "/api/v2/operations/trace_flow",
                headers=headers,
                json={"symbol_name": "a", "file_path": "../outside.py"},
            ).status_code
            == 422
        )
