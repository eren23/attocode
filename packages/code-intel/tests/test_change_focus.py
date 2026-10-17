"""Selected real Git workflows retain caller/test evidence while removing class noise."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from attocode_intel.change_evidence import check_report
from attocode_intel.change_investigation import markdown_report
from attocode_intel.gateway import OperationGateway
from test_change_investigation import LANGUAGES, cli, git, query, repository


@pytest.fixture(autouse=True)
def syntax_only(monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")


@pytest.mark.parametrize("language", ["python", "typescript", "go"])
async def test_filtered_diff_before_caps_preserves_real_callers_tests_and_restart(tmp_path, language):
    target, caller, test, old, new, caller_source, test_source = LANGUAGES[language]
    noise = "aaa" + Path(target).suffix
    old_noise = old.replace("work", "other").replace("Work", "Other")
    files = {target: old, noise: old_noise, caller: caller_source, test: test_source}
    if language == "go":
        files["go.mod"] = "module example.test/app\n\ngo 1.22\n"
    repository(tmp_path, files)
    (tmp_path / target).write_text(new)
    (tmp_path / noise).write_text(old_noise.replace("1", "3"))
    symbol = "Work" if language == "go" else "work"
    arguments = {"files": [target], "symbols": [symbol], "max_files": 1, "max_symbols": 1}
    reports = []
    for _ in range(2):
        gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
        try:
            report = await query(gateway, **arguments)
            assert report["omitted"] == {"files": 0, "symbols": 0}
            assert report["selection"]["excluded_files"] == 1
            assert not report["selection"]["unmatched_symbols"]
            assert [r["file_path"] for r in report["files"]] == [target]
            assert report["symbols"][0]["after"]["name"] == symbol
            assert {caller, test} <= {e["site"]["file_path"]
                                      for e in report["symbols"][0]["flow"]["edges"]}
            assert test in {c["file_path"] for c in report["tests"]["candidates"]}
            assert check_report(str(tmp_path), report)["status"] == "current"
            reports.append(report)
            by_symbol = await query(gateway, symbols=[symbol], max_files=1, max_symbols=1)
            assert [r["file_path"] for r in by_symbol["files"]] == [target]
            assert by_symbol["omitted"] == {"files": 0, "symbols": 0}
        finally:
            await gateway.close()
    assert reports[0]["report_id"] == reports[1]["report_id"]
    # Scope is not a weaker freshness guarantee: an excluded dirty file still invalidates it.
    (tmp_path / noise).write_text(old_noise.replace("1", "4"))
    assert check_report(str(tmp_path), reports[0])["status"] == "stale"


CLASS_SOURCES = {
    "python": ("worker.py", "class Worker:\n    def work(self):\n        return 1\n",
               "def make():\n    return Worker()\n"),
    "typescript": ("worker.ts", "export class Worker {\n  work() { return 1; }\n}\n",
                   "export function make() { return new Worker(); }\n"),
}


@pytest.mark.parametrize("language", CLASS_SOURCES)
async def test_class_summary_keeps_methods_and_expand_restores_class_evidence(tmp_path, language):
    path, old, caller = CLASS_SOURCES[language]
    repository(tmp_path, {path: old + caller})
    (tmp_path / path).write_text(old.replace("1", "2") + caller)
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        summary = await query(gateway)
        expanded = await query(gateway, class_mode="expand")
        summarized_class = next(r for r in summary["symbols"] if r["after"]["kind"] == "class")
        expanded_class = next(r for r in expanded["symbols"] if r["after"]["kind"] == "class")
        assert summarized_class["flow"]["status"] == "summarized"
        assert summarized_class["class_summary"]["total_changed_members"] == 1
        assert summarized_class["class_summary"]["changed_members"][0]["after"]["qualified_name"] == "Worker.work"
        assert any(e["caller"]["name"] == "make" for e in expanded_class["flow"]["edges"])
        method = next(r for r in summary["symbols"] if r["after"]["qualified_name"] == "Worker.work")
        expanded_method = next(r for r in expanded["symbols"] if r["after"]["qualified_name"] == "Worker.work")
        assert method == expanded_method
        text = markdown_report(summary)
        assert "Class summary: 1 changed child" in text and "class-wide callers not collected" in text
        assert "class_summary" not in expanded_class
    finally:
        await gateway.close()


async def test_rename_old_and_new_file_and_definition_names_remain_selectable(tmp_path):
    repository(tmp_path, {"old.py": "def old(): return 1\n"})
    git(tmp_path, "mv", "old.py", "new.py")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        for path in ["old.py", "new.py"]:
            moved = await query(gateway, files=[path], symbols=["old"])
            assert len(moved["files"]) == 1
            assert moved["files"][0]["old_path"] == "old.py"
            assert moved["files"][0]["file_path"] == "new.py"
            assert moved["symbols"][0]["change"] == "moved"
        (tmp_path / "new.py").write_text("def new(): return 1\n")
        # A changed name may be represented as a remove/add, without guessing an identity pair.
        for path, name in [("old.py", "old"), ("new.py", "new")]:
            report = await query(gateway, files=[path], symbols=[name])
            assert report["symbols"]
            assert not report["selection"]["unmatched_files"]
            assert not report["selection"]["unmatched_symbols"]
        removed = await query(gateway, symbols=["old"])
        assert removed["symbols"][0]["flow"]["status"] == "unavailable"
    finally:
        await gateway.close()


async def test_class_index_only_summary_has_no_current_caller_follow_up(tmp_path):
    repository(tmp_path, {"worker.py": "class Worker:\n    def work(self): return 1\n"})
    (tmp_path / "worker.py").write_text("class Worker:\n    def work(self): return 2\n")
    git(tmp_path, "add", "worker.py")
    (tmp_path / "worker.py").write_text("class Worker:\n    def work(self): return 3\n")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway, mode="staged", symbols=["Worker"])
        row = report["symbols"][0]
        assert row["flow"]["status"] == "unavailable"
        assert row["class_summary"]["follow_up"] is None
        assert row["class_summary"]["total_changed_members"] == 1
    finally:
        await gateway.close()


async def test_symbol_filter_matches_simple_names_without_discarding_other_owners(tmp_path):
    old = "class One:\n    def work(self): return 1\nclass Two:\n    def work(self): return 1\n"
    repository(tmp_path, {"worker.py": old})
    (tmp_path / "worker.py").write_text(old.replace("return 1", "return 2"))
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        all_named = await query(gateway, symbols=["work"])
        assert {s["after"]["qualified_name"] for s in all_named["symbols"]} == {"One.work", "Two.work"}
        selected = await query(gateway, symbols=["Two.work"], max_symbols=1)
        assert [s["after"]["qualified_name"] for s in selected["symbols"]] == ["Two.work"]
        assert selected["omitted"]["symbols"] == 0
    finally:
        await gateway.close()


async def test_flow_caps_mark_whole_report_bounded_without_losing_file_counts(tmp_path):
    old = "def work(): return 1\n" + "".join(f"def use{i}(): return work()\n" for i in range(20))
    repository(tmp_path, {"worker.py": old})
    (tmp_path / "worker.py").write_text(old.replace("return 1", "return 2"))
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        result = await query(gateway)
        assert result["bounded"] and result["limits"]["capped_caller_flows"] == 1
        assert result["omitted"] == {"files": 0, "symbols": 0}
        text = markdown_report(result)
        assert "Caller evidence was capped" in text and "Some files or symbols were omitted" not in text
    finally:
        await gateway.close()


async def test_symbol_filter_refuses_incomplete_large_branch_scan(tmp_path):
    repository(tmp_path, {f"file{i}.py": "def work(): return 1\n" for i in range(257)})
    git(tmp_path, "switch", "-qc", "feature")
    for i in range(257):
        (tmp_path / f"file{i}.py").write_text("def work(): return 2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "large branch change")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        with pytest.raises(ValueError, match="256 changed files"):
            await gateway.execute("change_context", {"mode": "branch", "base": "main", "symbols": ["missing"]})
    finally:
        await gateway.close()


async def test_exact_names_no_match_and_duplicate_path_normalization(tmp_path):
    repository(tmp_path, {"worker.py": "def work(): return 1\n"})
    (tmp_path / "worker.py").write_text("def work(): return 2\n")
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway, files=["./worker.py", "worker.py"], symbols=["work", "missing"])
        assert report["request"]["files"] == ["worker.py"]
        assert report["selection"]["unmatched_symbols"] == ["missing"]
        for arguments in [{"files": ["*.py"]}, {"symbols": ["wor"]},
                          {"files": ["other.py"], "symbols": ["work"]}]:
            result = await query(gateway, **arguments)
            assert result["status"] == "no_matches" and not result["symbols"]
            assert result["omitted"] == {"files": 0, "symbols": 0}
            assert result["absence_proven"] is False and result["selection"]["excluded_files"] == 1
    finally:
        await gateway.close()


@pytest.mark.parametrize("arguments", [{"files": ["../outside.py"]}, {"files": ["."]},
                                      {"files": [""]}, {"files": ["a.py"] * 33},
                                      {"symbols": ["a"] * 49}, {"class_mode": "guess"}])
async def test_invalid_or_unbounded_selections_fail_explicitly(tmp_path, arguments):
    repository(tmp_path, {"a.py": "def a(): return 1\n"})
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        with pytest.raises(ValueError):
            await gateway.execute("change_context", arguments)
    finally:
        await gateway.close()


async def test_summary_preview_caps_do_not_hide_changed_method_rows(tmp_path):
    old = "class Worker:\n" + "".join(f"    def m{i}(self): return 1\n" for i in range(15))
    repository(tmp_path, {"worker.py": old})
    (tmp_path / "worker.py").write_text(old.replace("return 1", "return 2"))
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        result = await query(gateway)
        cls = next(r for r in result["symbols"] if r["after"]["kind"] == "class")
        assert len(result["symbols"]) == 16
        assert len(cls["class_summary"]["changed_members"]) == 12
        assert cls["class_summary"]["total_changed_members"] == 15
        assert cls["class_summary"]["omitted_members"] == result["limits"]["omitted_summary_members"] == 3
        assert result["bounded"] and result["omitted"] == {"files": 0, "symbols": 0}
    finally:
        await gateway.close()


async def test_repeated_class_names_do_not_mix_lexical_member_summaries(tmp_path):
    old = ("class Worker:\n    def work(self): return 1\n\n"
           "class Worker:\n    def work(self): return 1\n")
    repository(tmp_path, {"worker.py": old})
    (tmp_path / "worker.py").write_text(old.replace("return 1", "return 2"))
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        report = await query(gateway, symbols=["Worker"])
        assert len(report["symbols"]) == 2
        for cls in report["symbols"]:
            summary = cls["class_summary"]
            assert summary["total_changed_members"] == 1
            member = summary["changed_members"][0]["after"]
            assert cls["after"]["start_line"] < member["start_line"] <= cls["after"]["end_line"]
    finally:
        await gateway.close()


def test_cli_filtered_request_refresh_and_markdown_preserve_scope(tmp_path):
    root = tmp_path / "repo"
    repository(root, {"worker.py": "def work(): return 1\n", "other.py": "def work(): return 1\n"})
    for path in ["worker.py", "other.py"]:
        (root / path).write_text("def work(): return 2\n")
    saved = tmp_path / "focused.json"
    cli(root, "changes", "--file", "worker.py", "--symbol", "work", "--class-mode", "expand",
        "--output", str(saved))
    report = json.loads(saved.read_text())
    (root / "worker.py").write_text("def work(): return 3\n")
    assert cli(root, "changes", "--check", str(saved), check=False).returncode == 1
    refreshed = json.loads(cli(root, "changes", "--refresh", str(saved)).stdout)
    assert refreshed["request"] == report["request"]
    assert [r["file_path"] for r in refreshed["files"]] == ["worker.py"]
    for option in ["--file", "--fi", "--symbol", "--class-mode"]:
        assert cli(root, "changes", "--refresh", str(saved), option, "other", check=False).returncode == 2
    text = cli(root, "changes", "--file", "worker.py", "--symbol", "missing", "--format", "markdown").stdout
    assert "Selected changes" in text and "unmatched symbols: `missing`" in text


async def test_full_stdio_filters_and_summary_survive_real_process_restart(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repository(tmp_path, {"worker.py": "class Worker:\n    def work(self): return 1\n"})
    (tmp_path / "worker.py").write_text("class Worker:\n    def work(self): return 2\n")
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "attocode_intel.entrypoint", "--project", str(tmp_path), "--profile", "full", "--no-watch"],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")})
    ids = []
    for _ in range(2):
        async with asyncio.timeout(30), stdio_client(params) as streams:  # noqa: SIM117
            async with ClientSession(*streams) as session:
                await session.initialize()
                response = await session.call_tool("change_context", {"files": ["worker.py"], "symbols": ["Worker"]})
                assert not response.isError
                report = response.structuredContent["data"]
                assert report["symbols"][0]["flow"]["status"] == "summarized"
                assert check_report(str(tmp_path), report)["status"] == "current"
                ids.append(report["report_id"])
    assert ids[0] == ids[1]


def test_authenticated_http_accepts_focus_and_rejects_invalid_selection(tmp_path, monkeypatch):
    from attocode_intel.api.app import create_app
    from attocode_intel.config import CodeIntelConfig
    from starlette.testclient import TestClient

    repository(tmp_path, {"worker.py": "class Worker:\n    def work(self): return 1\n"})
    (tmp_path / "worker.py").write_text("class Worker:\n    def work(self): return 2\n")
    monkeypatch.setenv("ATTOCODE_MCP_PROFILE", "full")
    route = "/api/v2/operations/change_context"
    with TestClient(create_app(CodeIntelConfig(project_dir=str(tmp_path), api_key="test-secret"))) as client:
        headers = {"Authorization": "Bearer test-secret"}
        args = {"files": ["worker.py"], "symbols": ["Worker"]}
        assert client.post(route, json=args).status_code == 401
        response = client.post(route, headers=headers, json=args)
        assert response.status_code == 200, response.text
        report = response.json()["data"]
        assert report["symbols"][0]["class_summary"]["total_changed_members"] == 1
        for arguments in [{"files": ["../outside.py"]}, {"class_mode": "guess"}, {"symbols": ["x"] * 49}]:
            assert client.post(route, headers=headers, json=arguments).status_code == 422
