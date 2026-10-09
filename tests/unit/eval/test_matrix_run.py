import hashlib
import json
import sys

import pytest

from eval.matrix.run import import_legacy, main

ISSUE = "Crash on load\nDetails"


def _locbench_run(root, pool_sha256=None, ranked=("b.py", "a.py")):
    """Two instances: one issue with a title, one one-line issue. One failed request on a title."""
    (root / "pools").mkdir(parents=True)
    (root / "trials").mkdir()
    rows = [{"instance_id": native, "repo": repo, "base_commit": "c", "category": "Bug Report", "created_at": 0,
             "problem_statement": issue, "edit_functions": ["b.py:f"]}
            for native, repo, issue in (("o__r-1", "o/r", ISSUE), ("o__s-2", "o/s", "One line"))]
    (root / "all.json").write_text(json.dumps(rows))
    for native, queries in (("o__r-1", [ISSUE, "Crash on load"]), ("o__s-2", ["One line"])):
        pool = json.dumps({"repos": [{"repo": native, "queries": [
            {"query": q, "arms": {"prior": {"files": ["a.py", "b.py", "c.py"], "ms": 5}}} for q in queries]}]})
        (root / "pools" / f"{native}.json").write_text(pool)
        cases = [{"repo": native, "query": q, "baseline_files": ["a.py", "b.py"], "failures": int(failed),
                  "ranked_files": ["a.py", "b.py"] if failed else list(ranked),  # a failure keeps the pool order
                  "fallback_reason": None, "inference_ms": 9, "evidence_sha256": "e"}
                 for q in queries for failed in [q == "Crash on load"]]
        sha = pool_sha256 or hashlib.sha256(pool.encode()).hexdigest()
        (root / "trials" / f"{native}-jev2.json").write_text(json.dumps({"pool_sha256": sha, "cases": cases}))


def test_import_legacy_locbench_rows(tmp_path):
    _locbench_run(tmp_path / "run")
    import_legacy(tmp_path / "out", [str(tmp_path / "run")], [])
    rows = {(r["instance_id"], r["variant"], r["cell"]): r
            for r in map(json.loads, (tmp_path / "out" / "results.jsonl").read_text().splitlines())}
    assert len(rows) == 12  # 2 instances x 2 variants x (lexical, lexpy, jev2)
    assert rows["locbench/o__r-1", "full", "jev2"]["files"] == ["b.py", "a.py", "c.py"]  # the pool tail follows
    failed = rows["locbench/o__r-1", "title", "jev2"]
    assert failed["status"] == "request_failed" and failed["files"] == ["a.py", "b.py", "c.py"]
    one_line = rows["locbench/o__s-2", "title", "jev2"]  # a one-line issue: the title rows are the full rows
    assert one_line["files"] == rows["locbench/o__s-2", "full", "jev2"]["files"]


def test_import_legacy_refuses_a_trial_on_another_pool(tmp_path):
    _locbench_run(tmp_path / "other", pool_sha256="0" * 64)
    with pytest.raises(ValueError, match="pool that is not in"):
        import_legacy(tmp_path / "out", [str(tmp_path / "other")], [])
    _locbench_run(tmp_path / "bad", ranked=("c.py", "a.py"))
    with pytest.raises(ValueError, match="not the first 2 files"):
        import_legacy(tmp_path / "out", [str(tmp_path / "bad")], [])


def test_report_cli(tmp_path, monkeypatch):
    _locbench_run(tmp_path / "run")
    import_legacy(tmp_path / "out", [f"old={tmp_path / 'run'}", str(tmp_path / "run")], [])
    monkeypatch.setattr(sys, "argv", ["run", "report", str(tmp_path / "out"), "--cells", "jev2,old.jev2",
                                      "--baseline", "lexical", "--pair", "jev2:old.jev2"])
    main()
    report = (tmp_path / "out" / "report.md").read_text()
    assert "| jev2@title | lexical@title | locbench |" in report and "1 request_failed" in report
    assert "| jev2@full | old.jev2@full | locbench |" in report
    argv, ids = sys.argv, tmp_path / "ids.txt"
    ids.write_text("o__r-1\n")  # a native id, as in the old Loc-Bench id files
    monkeypatch.setattr(sys, "argv", argv + ["--ids", str(ids)])
    main()
    assert "on 1 instances from" in (tmp_path / "out" / "report.md").read_text()
    ids.write_text("o__r-1\no__x-9\n")
    with pytest.raises(SystemExit, match="1 ids in .* match no instance, such as o__x-9"):
        main()
    monkeypatch.setattr(sys, "argv", argv)
    results = tmp_path / "out" / "results.jsonl"
    results.write_text("".join(line + "\n" for line in results.read_text().splitlines()
                               if not ('"cell": "jev2"' in line and '"full"' in line and "o__r-1" in line)))
    with pytest.raises(SystemExit, match="jev2@full on locbench: 1 of 2 instances have no row"):
        main()
