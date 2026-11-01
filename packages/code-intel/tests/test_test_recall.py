"""Trial candidate: a test-only body search for short explicit test requests."""

from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.test_ranking import is_test_path

TEST_FILE = "tests/test_misc.py"


def _manager(tmp_path):
    # 70 short source chunks match both terms and fill the shared body slots.
    # The test file mentions one term once in a long body, so it ranks below them.
    for i in range(70):
        target = tmp_path / "src" / f"mod{i}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"def worker_{i}():\n    return 'queue scheduling queue scheduling'\n")
    filler = "".join(f"    step_{n} = {n}\n" for n in range(40))
    (tmp_path / "tests").mkdir()
    (tmp_path / TEST_FILE).write_text(f"def test_order():\n{filler}    assert 'queue'\n")
    mgr = SemanticSearchManager(str(tmp_path))
    mgr.search_candidates("queue scheduling")
    assert mgr.wait_for_body_index(timeout=30)
    return mgr


def _count_body_calls(monkeypatch):
    calls = []
    original = SemanticSearchManager._body_search

    def counted(self, *args, **kwargs):
        calls.append(kwargs.get("tests_only", False))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SemanticSearchManager, "_body_search", counted)
    return calls


def test_test_only_body_search_returns_only_test_paths(tmp_path):
    mgr = _manager(tmp_path)
    try:
        hits = mgr._body_search(["queue", "scheduling"], 60, "", tests_only=True)
        assert [hit.file_path for hit in hits] == [TEST_FILE]
        assert all(is_test_path(hit.file_path) for hit in hits)
    finally:
        mgr.close()


def test_flag_brings_a_crowded_out_test_file_into_the_pool(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    try:
        monkeypatch.delenv("ATTOCODE_INTEL_TEST_RECALL", raising=False)
        trace: dict = {}
        mgr.search_candidates("queue scheduling tests", top_k=5, trace=trace)
        assert TEST_FILE not in trace["fused"]
        monkeypatch.setenv("ATTOCODE_INTEL_TEST_RECALL", "1")
        trace = {}
        hits = mgr.search_candidates("queue scheduling tests", top_k=5, trace=trace)
        assert TEST_FILE in trace["fused"]
        assert hits[0].file_path == TEST_FILE
    finally:
        mgr.close()


def test_non_test_queries_and_test_scores_are_unchanged(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    try:
        calls = _count_body_calls(monkeypatch)
        monkeypatch.delenv("ATTOCODE_INTEL_TEST_RECALL", raising=False)
        off = [mgr.search_candidates("queue scheduling", top_k=5),
               mgr.search_candidates("queue scheduling tests", top_k=5, tests_last=False)]
        calls_off = list(calls)
        calls.clear()
        monkeypatch.setenv("ATTOCODE_INTEL_TEST_RECALL", "1")
        on = [mgr.search_candidates("queue scheduling", top_k=5),
              mgr.search_candidates("queue scheduling tests", top_k=5, tests_last=False)]
        assert on == off
        assert calls == calls_off == [False, False]
        mgr.search_candidates("queue scheduling tests", top_k=5)
        assert calls[-2:] == [False, True]
    finally:
        mgr.close()
