import yaml

from eval.matrix.datasets import PACKS, case_pack, locbench


def test_case_pack_parses_list_and_graded_gold(tmp_path):
    pack = tmp_path / "pack.yaml"
    pack.write_text(yaml.safe_dump({"repos": {
        "svc": [{"query": "load config", "relevant_files": ["a.py", "b.py", "a.py"]}],
        "owner__repo-1": [{"query": "fix it", "intent": "source", "source_repo": "owner/repo",
                           "base_commit": "abc", "relevant_files": {"good.py": 3, "ok.py": 1, "bad.py": 0}}]}},
                                    sort_keys=False))
    binary, graded = case_pack("p", pack)
    assert (binary.id, binary.repo, binary.gold, binary.grades) == ("p/svc::load config", "svc", ["a.py", "b.py"], None)
    assert (graded.repo, graded.base_commit, graded.category) == ("owner/repo", "abc", "source")
    assert graded.gold == ["good.py", "ok.py"] and graded.grades == {"good.py": 3, "ok.py": 1, "bad.py": 0}
    assert binary.dataset == "p" and {binary.split, graded.split} <= {"dev", "holdout"}


def test_every_known_pack_parses():
    for name in PACKS:
        instances = case_pack(name)
        assert instances and len({inst.id for inst in instances}) == len(instances)
    blind = case_pack("graded_blind")
    assert len(blind) == 36 and len({inst.repo for inst in blind}) == 6 and all(inst.grades for inst in blind)
    titles = case_pack("locbench_title")  # one key per instance. The cluster is the source repository.
    assert len(titles) == 42 and len({inst.repo for inst in titles}) == 6


def test_locbench_rows():
    row = {"instance_id": "o__r-1", "repo": "o/r", "base_commit": "abc", "category": "Bug Report",
           "created_at": 1734798627000, "problem_statement": "## [Bug] Crash on load\nDetails",
           "edit_functions": ["b.py:f", "a.py:g", "b.py:h"]}
    issue, one_line = locbench([row, {**row, "instance_id": "o__r-2", "problem_statement": "Crash on load"}])
    assert (issue.id, issue.repo, issue.gold, issue.grades) == ("locbench/o__r-1", "o/r", ["a.py", "b.py"], None)
    assert issue.queries == {"full": "## [Bug] Crash on load\nDetails", "title": "Crash on load"}
    assert one_line.queries == {"full": "Crash on load", "title": "Crash on load"}
    assert issue.created_at == "2024-12-21T16:30:27Z"
