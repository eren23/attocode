"""Kotlin source-set boundaries shared by search and test discovery."""
import json
import subprocess
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.gateway import OperationGateway
from attocode_intel.query_ranking import demote_tests
from attocode_intel.test_ranking import is_test_path, rank_symbol_tests
from attocode_intel.tools import composite_tools


@pytest.mark.parametrize("source_set", [
    "commonTest", "jvmTest", "jsTest", "wasmJsTest", "wasmWasiTest",
    "nativeTest", "appleTest", "iosTest", "macosTest", "linuxTest", "mingwTest",
    "tvosTest", "watchosTest", "iosArm64Test", "iosX64Test", "iosSimulatorArm64Test",
    "macosArm64Test", "macosX64Test", "linuxArm64Test", "linuxX64Test", "mingwX64Test",
    "tvosArm64Test", "tvosX64Test", "tvosSimulatorArm64Test",
    "watchosArm32Test", "watchosArm64Test", "watchosDeviceArm64Test",
    "watchosX64Test", "watchosSimulatorArm64Test",
    "androidTest", "androidAndroidTest", "androidUnitTest", "androidInstrumentedTest",
    "androidHostTest", "androidDeviceTest",
])
def test_helper_in_conventional_source_set(source_set):
    assert is_test_path(f"library/src/{source_set}/kotlin/example/QueueFixture.kt")


@pytest.mark.parametrize("path", [
    "src/jvmMain/kotlin/Queue.kt", "src/commonMain/kotlin/Queue.kt",
    "src/androidMain/kotlin/Queue.kt", "src/commonJvmAndroid/kotlin/Queue.kt",
    "src/main/java/example/Queue.java", "src/main/kotlin/jvmTest/Queue.kt",
    "src/commonMain/kotlin/androidHostTest/Queue.kt", "jvmTest/kotlin/Queue.kt",
    "src/jvmTest", "src/customTest/kotlin/Queue.kt",
    "src/contest/kotlin/Queue.kt", "src/SomeTest/kotlin/Queue.kt",
    "src/jvmTestSupport/kotlin/Queue.kt", "src/JvmTest/kotlin/Queue.kt",
    "okhttp-testing-support/src/main/kotlin/okhttp3/FakeDns.kt",
    "src/main/kotlin/Inspection.kt", "", "src/TestData/Queue.kt",
])
def test_production_and_ambiguous_names_are_not_inferred_as_tests(path):
    assert not is_test_path(path)


@pytest.mark.parametrize("path", [
    "src/jvmTest.kt", "src/test/kotlin/Fixture.kt", "src/androidTest/java/Fixture.java",
    "src/jvmTest/resources/fixture.txt", "lib.Tests/Fixture.cs",
    "test_parser.py", "parser_test.go", "src/__tests__/fixture.ts", "spec/fixture.rb",
])
def test_existing_conventions_and_source_set_contents(path):
    assert is_test_path(path)


def test_search_stably_moves_helpers_without_dropping_or_rescoring():
    paths = ["src/jvmTest/kotlin/QueueFixture.kt", "src/commonMain/kotlin/Queue.kt",
             "src/commonTest/kotlin/QueueRegression.kt", "src/jvmMain/kotlin/Queue.kt"]
    rows = [SemanticSearchResult(p, "file", "queue", "", 1 - i / 10) for i, p in enumerate(paths)]
    ranked = demote_tests("queue scheduling", rows)
    assert [id(r) for r in ranked] == [id(rows[i]) for i in (1, 3, 0, 2)]
    assert [r.score for r in ranked] == [.9, .7, 1, .8]
    assert demote_tests("queue scheduling tests", rows) is rows


def test_search_and_task_scores_use_different_test_policy(tmp_path):
    production = "src/commonMain/kotlin/Queue.kt"
    helper = "src/jvmTest/kotlin/QueueFixture.kt"
    for path in (production, helper):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fun queueScheduling() = Unit\n")
    mgr = SemanticSearchManager(str(tmp_path))
    try:
        mgr.search_candidates("queue scheduling")
        assert mgr.wait_for_body_index(timeout=30)
        ordinary = mgr.search_candidates("queue scheduling", top_k=10)
        assert ordinary[0].file_path == production
        assert {r.file_path for r in ordinary} == {production, helper}
        explicit = mgr.search_candidates("queue scheduling tests", top_k=10)
        task = mgr.search_candidates("queue scheduling tests", top_k=10, tests_last=False)
        assert explicit == task
    finally:
        mgr.close()


def test_tracked_test_discovery_includes_helpers_but_not_data(tmp_path):
    paths = ["src/androidHostTest/kotlin/QueueFixture.kt", "src/commonTest/kotlin/QueueFixture.kt",
             "src/jvmTest/resources/data.json", "src/jvmMain/kotlin/Queue.kt"]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert set(composite_tools._test_paths(str(tmp_path))) == set(paths[:2])


def test_reverse_imports_use_same_classifier_and_preserve_distance(tmp_path, monkeypatch):
    source = "src/commonMain/kotlin/Queue.kt"
    middle = "src/jvmMain/kotlin/Inspection.kt"  # contains 'spec', but is production
    helper = "src/jvmTest/kotlin/QueueFixture.kt"
    graph = SimpleNamespace(get_importers=lambda path: {source: [middle], middle: [helper]}.get(path, []))
    monkeypatch.setattr(composite_tools, "_get_project_dir", lambda: str(tmp_path))
    monkeypatch.setattr(composite_tools, "_get_context_mgr", lambda: SimpleNamespace(dependency_graph=graph))
    monkeypatch.setattr(composite_tools, "_test_paths", lambda _: [])
    paths = [source, middle, helper]
    ast = SimpleNamespace(index=SimpleNamespace(file_symbols=dict.fromkeys(paths, [])),
                          get_file_symbols=lambda _: [])
    import attocode_intel._shared as shared
    monkeypatch.setattr(shared, "_get_ast_service", lambda: ast)
    monkeypatch.setattr(shared, "_get_service", lambda: SimpleNamespace())
    result = composite_tools.suggest_tests_data([source], task_hint="queue")
    assert [r["file_path"] for r in result["candidates"]] == [helper]
    assert result["candidates"][0]["evidence"]["import_distance"] == 2
    assert not result["absence_proven"]
    # The file-only API must not leak production importers into test suggestions.
    result = composite_tools.suggest_tests_data([source])
    assert [r["file_path"] for r in result["candidates"]] == [helper]


def test_linked_helper_remains_evidence_backed_candidate():
    helper = "src/jvmTest/kotlin/QueueFixture.kt"
    ast = SimpleNamespace(index=SimpleNamespace(file_symbols={helper: []}), get_file_symbols=lambda _: [])
    rows = rank_symbol_tests(ast, {}, ["src/jvmMain/kotlin/Queue.kt"], "schedule", None, {},
                             linked_reference_files=[helper])
    assert rows[0]["file_path"] == helper
    assert rows[0]["evidence"]["selected_symbol_reference"]


@pytest.mark.parametrize("source_set", ["commonTest", "jvmTest", "androidHostTest"])
async def test_gateway_suggests_kotlin_regressions_without_test_filename(tmp_path, monkeypatch, source_set):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    source = "src/commonMain/kotlin/Queue.kt"
    helper = f"src/{source_set}/kotlin/QueueRegression.kt"
    for path in (source, helper):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fun queueScheduling() = Unit\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        response = await gateway.execute_mcp("suggest_tests", {"files": [source], "task_hint": "queue regression"})
        assert not response.isError
        result = json.loads(response.content[0].text)["data"]
        assert [r["file_path"] for r in result["candidates"]] == [helper]
        assert not result["absence_proven"]
    finally:
        await gateway.close()
