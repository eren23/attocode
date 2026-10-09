import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from eval.matrix.datasets import (
    PACKS,
    Instance,
    _is_test,
    case_pack,
    core_mix,
    lca,
    lite,
    live,
    locbench,
    noise50,
    patch_files,
    patch_gold,
    polybench,
    search_coverage,
)
from eval.matrix.run import ingest


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


# One section per header kind. The first hunk removes "-- a/..." and adds "++ b/...": these lines
# look like headers, so the parser must stop at the first @@ line of a section.
PATCH = """diff --git a/m.py b/m.py
index 1..2 100644
--- a/m.py
+++ b/m.py
@@ -1,3 +1,3 @@
--- a/removed_sql_comment.py
+++ b/added_line.py
 context
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+x
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-x
diff --git a/old name.py b/new name.py
similarity index 90%
rename from old name.py
rename to new name.py
--- a/old name.py\t
+++ b/new name.py\t
@@ -1 +1 @@
-x
+y
diff --git a/a/moved.py b/b/moved.py
similarity index 100%
rename from a/moved.py
rename to b/moved.py
diff --git a/img.png b/img.png
index 1..2 100644
Binary files a/img.png and b/img.png differ
diff --git a/blob.bin b/blob.bin
new file mode 100644
GIT binary patch
literal 1
Icmd;J0000

diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"
--- "a/caf\\303\\251.py"
+++ "b/caf\\303\\251.py"
@@ -1 +1 @@
-x
+y
diff --git a/src.py b/copy.py
similarity index 100%
copy from src.py
copy to copy.py
diff --git a/run.sh b/run.sh
old mode 100644
new mode 100755
"""


def test_patch_files_and_gold():
    assert patch_files(PATCH) == [
        ("m.py", "m.py"), (None, "new.py"), ("gone.py", None), ("old name.py", "new name.py"),
        ("a/moved.py", "b/moved.py"), ("img.png", "img.png"), (None, "blob.bin"), ("café.py", "café.py"),
        (None, "copy.py"), ("run.sh", "run.sh")]
    # Gold is the base tree side: a renamed file by its old path. New files and copies are not gold.
    assert patch_gold(PATCH) == ["m.py", "gone.py", "old name.py", "a/moved.py", "img.png", "café.py", "run.sh"]
    only_new = PATCH.split("diff --git a/gone.py")[0].split("diff --git a/new.py")[1]
    assert patch_gold("diff --git a/new.py" + only_new) == [] and patch_gold("") == []


def test_lite_polybench_and_live_rows():
    patch = ("diff --git a/src/x.ts b/src/x.ts\n--- a/src/x.ts\n+++ b/src/x.ts\n@@ -1 +1 @@\n-a\n+b\n"
             "diff --git a/src/new.ts b/src/new.ts\nnew file mode 100644\n--- /dev/null\n+++ b/src/new.ts\n")
    [swe] = lite([{"instance_id": "o__r-1", "repo": "o/r", "base_commit": "c1", "created_at": "2022-03-03T15:14:54Z",
                   "problem_statement": "Crash\nDetails", "edit_functions": ["b.py:f", "a.py:C.g"]}])
    assert (swe.id, swe.gold, swe.language, swe.created_at) == ("lite/o__r-1", ["a.py", "b.py"], "python",
                                                                "2022-03-03T15:14:54Z")
    [poly] = polybench([{"instance_id": "o__r-2", "repo": "o/r", "base_commit": "c2", "language": "TypeScript",
                         "task_category": "Bug Fix", "created_at": "2023-03-06 15:40:50+00:00",
                         "problem_statement": "One line", "patch": patch}])
    assert (poly.language, poly.category, poly.created_at, poly.gold) == ("typescript", "Bug Fix",
                                                                          "2023-03-06T15:40:50Z", ["src/x.ts"])
    assert poly.queries == {"full": "One line", "title": "One line"}
    [multi] = live([{"_file": "data/cs-00000-of-00001.parquet", "instance_id": "o__r-3", "repo": "o/r",
                     "base_commit": "c3", "created_at": "2025-07-10T19:03:03Z",
                     "problem_statement": "[Bug] Leak\nmore", "patch": patch.split("diff --git a/src/new.ts")[0]}])
    assert (multi.id, multi.language, multi.gold, multi.queries["title"]) == ("live/o__r-3", "csharp", ["src/x.ts"],
                                                                              "Leak")


def test_lca_rows():
    diff = ("diff --git a/app/A.kt b/app/A.kt\n--- a/app/A.kt\n+++ b/app/A.kt\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/app/Old.kt b/app/New.kt\nsimilarity index 95%\nrename from app/Old.kt\nrename to app/New.kt\n"
            "diff --git a/app/Fresh.kt b/app/Fresh.kt\nnew file mode 100644\n--- /dev/null\n+++ b/app/Fresh.kt\n"
            "diff --git a/test/ATest.kt b/test/ATest.kt\n--- a/test/ATest.kt\n+++ b/test/ATest.kt\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n")
    row = {"_file": "kt/test-00000-of-00001.parquet", "text_id": "square/okhttp/1254/1158", "base_sha": "c",
           "pull_create_at": datetime(1970, 1, 1, 0, 23, 39), "issue_title": "Cache 307", "issue_body": "Details",
           "diff": diff, "changed_files": "['app/A.kt', 'app/New.kt', 'app/Fresh.kt', 'test/ATest.kt']"}
    inst, only_tests = lca([row, {**row, "text_id": "square/okhttp/1/2", "changed_files": "['test/ATest.kt']"}])
    assert (inst.id, inst.repo, inst.base_commit, inst.language) == ("lca/square__okhttp-1254-1158", "square/okhttp",
                                                                     "c", "kotlin")
    # The test file and the new file are not gold, and README.md is not in changed_files.
    assert inst.gold == ["app/A.kt", "app/Old.kt"] and only_tests.gold == []
    assert inst.created_at == "2014-12-19T14:40:00Z"  # 1,419,000,000 s, stored as 1,419,000 ms
    assert inst.queries == {"full": "Cache 307\nDetails", "title": "Cache 307"}


def test_is_test_is_a_frozen_path_rule():
    tests = ["pkg/test/a.py", "tests/a.py", "web/__tests__/a.js", "okhttp/src/jvmTest/kotlin/A.kt",
             "app/src/androidTest/java/B.java", "lib/src/commonTest/C.kt", "svc/src/integrationTest/D.java",
             "pkg/test_util.py", "pkg/util_test.py", "pkg/conftest.py", "src/main/java/FooTest.java",
             "src/main/java/FooTests.java", "src/main/kotlin/BarTest.kt", "src/main/kotlin/BarTests.kt"]
    sources = ["numpy/testing/utils.py", "src/testing/x.py", "src/main/java/Foo.java", "app/TestUtils.java",
               "pkg/contest.py", "pkg/testdata/a.py", "core/src/latest/A.kt", "lib/jvmTest/A.kt"]
    assert [path for path in tests if not _is_test(path)] == []
    assert [path for path in sources if _is_test(path)] == []


def test_search_coverage_follows_product_discovery():
    assert search_coverage("src/app.py") == "parsed"
    assert search_coverage("src/robot/output/conf.py") == "skipped"  # "output" is an ignored folder name
    assert search_coverage(".size-limit.js") == "skipped" and search_coverage("yarn.lock") == "skipped"
    assert search_coverage("src/compiler/parser.cr") == "text_only"


def _instance(iid: str, repo: str, language: str = "python", category: str = "") -> Instance:
    return Instance(id=iid, repo=repo, base_commit="", language=language, category=category, created_at="",
                    queries={"full": iid}, gold=["f.py"], grades=None)


def test_split_is_a_fixed_hash_of_the_id():
    assert _instance("lite/astropy__astropy-12907", "r").split == "dev"
    assert _instance("lite/astropy__astropy-14365", "r").split == "holdout"


CORE_SCRIPT = """
import json, sys
from eval.matrix.datasets import Instance, core_mix
insts = [Instance(id=f"{d}/{d}-{i}", repo=f"{d}-r{i % 7}", base_commit="", language="ab"[i % 2],
                  category="xyz"[i % 3], created_at="", queries={}, gold=["f"], grades=None)
         for d in ("lite", "live", "graded_blind") for i in range(90)]
print(json.dumps(core_mix(insts[::-1] if sys.argv[1] == "reverse" else insts, seed=7)))
"""


def test_core_mix_ignores_hash_seed_and_input_order():
    runs = []
    for hash_seed, order in (("1", "forward"), ("2", "reverse")):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": os.pathsep.join(sys.path)}
        # python -c puts the working folder first on sys.path, so run it from this checkout.
        done = subprocess.run([sys.executable, "-c", CORE_SCRIPT, order], env=env, capture_output=True, text=True,
                              check=True, cwd=Path(__file__).resolve().parents[3])
        runs.append(json.loads(done.stdout))
    assert runs[0] == runs[1] == sorted(runs[0]) and len(runs[0]) == 40 + 60 + 90  # graded_blind: every instance


def test_core_mix_strata_and_repository_cap():
    # 60 python instances in one repository, 30 java and 30 typescript ones in 6 small repositories.
    pool = ([_instance(f"polybench/big-{i}", "big") for i in range(60)]
            + [_instance(f"polybench/s-{i}", f"s{i % 6}", "java" if i % 6 < 3 else "typescript") for i in range(60)])
    core = core_mix(pool, quotas={"polybench": 60})
    repos = [inst.repo for inst in pool if inst.id in core]
    # The python stratum has 30 seats, but one repository gives at most ceil(2 * 60 / 7) = 18.
    # The 12 empty seats go to the java and typescript instances.
    assert len(core) == 60 and repos.count("big") == 18
    assert set(core_mix(pool[::-1], quotas={"polybench": 60})) == set(core)
    few = [_instance(f"lite/big-{i}", "big") for i in range(20)] + [_instance(f"lite/x-{i}", f"x{i}") for i in range(3)]
    with pytest.raises(ValueError, match="at most 5 instances per repository fill 8 of 10"):
        core_mix(few, quotas={"lite": 10})
    ids = [f"lite/{i}" for i in range(100)]
    assert noise50(ids) == noise50(ids[::-1]) == sorted(noise50(ids)) and len(set(noise50(ids)) & set(ids)) == 50


def test_ingest(tmp_path):
    out, config, core = tmp_path / "out", tmp_path / "full.yaml", tmp_path / "core_ids.txt"
    rows = [{"instance_id": f"o__r-{i}", "repo": f"o/r{i % 3}", "base_commit": "c", "created_at": "2022-03-03T15:14:54Z",
             "problem_statement": f"Issue {i}\nDetails", "edit_functions": [f"m{i}.py:f"]} for i in range(5)]
    lite_file = out / "datasets/lite@r1/rows.jsonl"
    lite_file.parent.mkdir(parents=True)
    lite_file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    poly_file = out / "datasets/polybench@r2/test.csv"
    poly_file.parent.mkdir(parents=True)
    with poly_file.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, ["instance_id", "repo", "base_commit", "language", "task_category",
                                         "created_at", "problem_statement", "patch"])
        writer.writeheader()
        for native, path, mode in (("o__p-1", "a.js", ""), ("o__p-new", "b.js", "new file mode 100644\n")):
            writer.writerow({"instance_id": native, "repo": "o/p", "base_commit": "c", "language": "JavaScript",
                             "task_category": "Feature", "created_at": "2023-03-06 15:40:50+00:00",
                             "problem_statement": "Add it", "patch": f"diff --git a/{path} b/{path}\n{mode}"})
    entry = {"hf": "x/y", "files": [], "primary": "acc5", "public": True}
    registry = {"run": {"budget_usd": 10, "seed": 7, "holdout": 0.3},
                "datasets": {"lite": {**entry, "revision": "r1", "files": ["rows.jsonl"]},
                             "polybench": {**entry, "revision": "r2", "files": ["test.csv"]}}}
    config.write_text(yaml.safe_dump(registry))
    ingest(out, config, core)
    written = [json.loads(line) for line in (out / "instances.jsonl").read_text().splitlines()]
    ids = [inst["id"] for inst in written]
    assert ids == sorted(ids) and len(ids) == 6 and "polybench/o__p-new" not in ids  # its patch only adds a file
    assert core.read_text().splitlines() == ids and all("core" in inst["tags"] for inst in written)
    report = (out / "ingest.md").read_text()
    assert "| lite | r1 | 5 | 0 | 5 | 3 |" in report and "- polybench: polybench/o__p-new" in report
    ingest(out, config, core)  # the same data gives the same core mix
    lite_file.write_text("".join(json.dumps(row) + "\n" for row in rows[:4]))
    with pytest.raises(SystemExit, match="core mix differs"):
        ingest(out, config, core)
    lite_file.write_text("".join(json.dumps(row) + "\n" for row in rows + rows[:1]))
    with pytest.raises(SystemExit, match="1 instance ids occur twice, such as lite/o__r-0"):
        ingest(out, config, core)
    registry["datasets"]["lite"]["primary"] = "gndcg5"
    config.write_text(yaml.safe_dump(registry))
    with pytest.raises(SystemExit, match="lite: the scorer uses acc5, but the config says gndcg5"):
        ingest(out, config, core)
