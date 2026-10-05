"""The audit measures candidate recall without treating cold indexes as misses."""

from eval.broad_candidate_audit import score_pool, summarize


def test_score_pool_uses_first_distinct_file_occurrence():
    files = ["a.py", "a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
    row = score_pool(files, ["c.py", "missing.py"])
    assert row["first_labeled_rank"] == 3
    assert row["labeled_ranks"] == {"c.py": 3}
    assert row["top_5"] == ["a.py", "b.py", "c.py", "d.py", "e.py"]
    assert row["next_3"] == ["f.py"]
    assert row["labeled_at_5"] is True
    assert row["labeled_at_24"] is True


def test_summary_separates_page_misses_from_pool_misses():
    reports = [{"queries": [
        {**score_pool([f"f{i}.py" for i in range(24)], ["f7.py"]), "search_ms": 2.0,
         "intent": "source", "source_view_labeled_at_5": False},
        {**score_pool([f"f{i}.py" for i in range(24)], ["absent.py"]), "search_ms": 4.0,
         "intent": "source", "source_view_labeled_at_5": False},
    ]}]
    summary = summarize(reports)
    assert summary["labeled_at_5"] == 0
    assert summary["labeled_at_8"] == 1
    assert summary["labeled_at_24"] == 1
    assert summary["missed_at_5_but_in_24"] == 1
    assert summary["missing_from_24"] == 1


def test_source_view_uses_source_paths_without_changing_test_intent():
    from types import SimpleNamespace

    from eval.broad_candidate_audit import score_source_view

    pool = [SimpleNamespace(file_path=path) for path in (
        "tests/test_handler.py", "docs/example.py", "src/handler.py", "src/handler.py",
        "src/router.py", "benchmarks/bench.py", "src/server.py",
    )]
    source = score_source_view("request routing", pool, ["src/router.py"])
    assert source["source_view"] == ["src/handler.py", "src/router.py", "src/server.py"]
    assert source["source_view_labeled_at_5"] is True
    assert source["baseline_labeled_count_5"] == 1
    tests = score_source_view("request routing tests", pool, ["tests/test_handler.py"], "tests")
    assert tests["source_view"] == [hit.file_path for hit in pool[:5]]
    assert tests["source_view_unchanged"] is True
