"""Localize study with a stub client: one row end to end, resume, interruption, orphans and grading. No model calls."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

EVALS = Path(__file__).parents[1] / "evals"
PROJECT = Path(__file__).resolve().parents[3]
STUB = r'''#!PYTHON
import json, os, re, subprocess, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    sys.exit(print("9.9.9 (Claude Code)"))
if args[:2] == ["auth", "status"]:
    sys.exit(print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"})))
with open(os.environ["STUB_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
if os.environ.get("STUB_SLEEPER"):
    # A child that leaves the process group, as a server that calls setsid does.
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", os.getcwd()], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def emit(event):
    print(json.dumps(event), flush=True)
emit({"type": "system", "subtype": "init", "tools": args[args.index("--tools") + 1].split(",") + ["StructuredOutput"]})
if "wiring check" in args[-1]:
    token = re.search(r"Readiness token: (\w+)", open("CLAUDE.md").read()).group(1)
    call = {"id": "m1", "name": "mcp__attocode-code-intel__semantic_search", "input": {"query": "benchmark value"}}
    content = "{}"
    answer = {"readiness_token": token, "user_instructions": "none", "search_called": True}
else:
    call, content = {"id": "g1", "name": "Grep", "input": {"pattern": "target"}}, "pkg/b.py:1:def target():"
    answer = {"files": ["./pkg/b.py:1", os.getcwd() + "/pkg/a.py", "missing.py"]}
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", **call}]}})
time.sleep(.2)
emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call["id"], "content": content}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.0123,
      "usage": {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 20},
      "structured_output": answer, "permission_denials": []})
'''


@pytest.fixture
def localize(monkeypatch):
    monkeypatch.syspath_prepend(str(EVALS))
    import localize_study
    return localize_study


@pytest.fixture
def stub(monkeypatch, tmp_path):
    """A `claude` on PATH that emits stream-json, and an isolated home folder."""
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "claude").write_text(STUB.replace("PYTHON", sys.executable))
    (folder / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return tmp_path / "calls.jsonl"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def matrix(name, repo, base_commit, queries, gold):
    """One line of a matrix instances.jsonl: asdict(eval.matrix.datasets.Instance)."""
    return {"id": name, "repo": repo, "base_commit": base_commit, "language": "python", "category": "",
            "created_at": "", "queries": queries, "gold": gold, "grades": None, "split": "dev", "tags": []}


def freeze(localize, tmp_path, name, instances, ids, setups):
    (tmp_path / "instances.jsonl").write_text("".join(json.dumps(instance) + "\n" for instance in instances))
    (tmp_path / "ids.txt").write_text("".join(f"{name}\n" for name in ids))
    study = tmp_path / name
    localize.freeze(SimpleNamespace(project=PROJECT, study=study, instances=tmp_path / "instances.jsonl",
                                    ids=tmp_path / "ids.txt", model="stub-model-1", trials=1, setups=list(setups),
                                    config_id="product"))
    return study


def case_repo():
    """A case-pack clone under the (test) home folder. Its last commit is the fix, after the base commit."""
    source = Path.home() / "Documents/ai/benchmark-repos/fixture-repo"
    if not source.exists():
        (source / "pkg").mkdir(parents=True)
        (source / "pkg/a.py").write_text("def helper():\n    return 1\n")
        (source / "pkg/b.py").write_text("def target():\n    return helper()\n")
        git(source, "init", "-q")
        git(source, "add", ".")
        git(source, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        (source / "pkg/b.py").write_text("def target():\n    return helper() + 1\n")
        git(source, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "fix")
    return source, git(source, "rev-parse", "HEAD~1")


def frozen(localize, tmp_path, name="study", setups=("native", "intel")):
    _, base = case_repo()
    instance = matrix("fixture/fix-1", "fixture-repo", base, {"full": "Fix {target} in b.\nIt fails.",
                                                             "title": "Fix target"}, ["pkg/b.py"])
    return freeze(localize, tmp_path, name, [instance], ["fixture/fix-1"], setups)


def test_one_row_end_to_end_with_resume_and_no_orphans(localize, stub, tmp_path, monkeypatch):
    study = frozen(localize, tmp_path)
    source, _ = case_repo()
    before = {path: path.stat().st_mtime_ns for path in source.rglob("*")}
    localize.prepare(SimpleNamespace(study=study))
    assert {path: path.stat().st_mtime_ns for path in source.rglob("*")} == before, "prepare wrote to the clone"
    prepared = json.loads((study / "preparation.json").read_text())["tasks"]["fixture_fix-1"]
    assert prepared["status"] == "ready" and prepared["index"]["ready"]
    assert prepared["index"]["search"]["status"] == "ready"
    # The snapshot has one commit (the base, not the fix), so the history cannot show the fix.
    assert git(study / "sources/fixture_fix-1", "log", "--all", "--oneline").count("\n") == 0
    assert "+ 1" not in (study / "sources/fixture_fix-1/pkg/b.py").read_text()
    quota = tmp_path / "quota.json"
    quota.write_text(json.dumps({"claude": {"subscription_only": True, "extra_usage_disabled": True,
                                            "remaining": True, "checked_at": time.time()}}))
    localize.wiring(SimpleNamespace(study=study, quota=quota))
    assert json.loads((study / "wiring/result.json").read_text())["passed"]
    monkeypatch.setenv("STUB_SLEEPER", "1")
    arguments = SimpleNamespace(study=study, quota=quota, tasks=None, max_runs=None, jobs=1, deadline_minutes=100)
    localize.run(arguments)
    assert not localize.processes(str(study)), "a client child survived the run"
    assert len(stub.read_text().splitlines()) == 3
    localize.run(arguments)
    assert len(stub.read_text().splitlines()) == 3, "a finished trial ran again"
    argv = json.loads(stub.read_text().splitlines()[1])
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob" and "--strict-mcp-config" in argv
    assert argv[argv.index("--model") + 1] == "stub-model-1"

    localize.summary(SimpleNamespace(study=study))
    rows = {row["setup"]: row for row in map(json.loads, (study / "runs.jsonl").read_text().splitlines())}
    native, intel = rows["native"], rows["intel"]
    assert native["status"] == intel["status"] == "completed"
    assert native["files"] == ["pkg/b.py", "pkg/a.py", "missing.py"] and native["invalid_paths"] == 1
    assert (native["acc1"], native["acc5"], native["recall10"], native["mrr5"]) == (1.0, 1.0, 1.0, 1.0)
    assert (native["cost_usd"], native["turns"], native["tokens"]["cache_read_input_tokens"]) == (0.0123, 3, 100)
    assert native["tool_calls"] == {"Grep": 1} and native["gold_seen_s"] > 0
    assert (native["dataset"], native["instance_id"], native["config_id"]) == ("fixture", "fixture/fix-1", "product")
    assert intel["index_reused"] is True and native["index_reused"] is False
    assert "| native | 1 | 1 | 1.00 |" in (study / "summary.md").read_text()
    assert "Five random runs" in (study / "review.md").read_text()


def test_native_only_study_prepares_without_an_index(localize, stub, tmp_path, monkeypatch):
    study = frozen(localize, tmp_path, setups=("native",))
    monkeypatch.setattr(localize, "warm", lambda *args: pytest.fail("a study without intel setups needs no index"))
    localize.prepare(SimpleNamespace(study=study))
    prepared = json.loads((study / "preparation.json").read_text())["tasks"]["fixture_fix-1"]
    assert prepared["status"] == "ready" and prepared["index"] is None
    assert not (study / "sources/fixture_fix-1/.attocode").exists()


def test_unsafe_snapshot_excludes_its_task_and_prepare_goes_on(localize, stub, tmp_path):
    _, base = case_repo()
    # This repository sorts first, so prepare must go on to the next one.
    unsafe = Path.home() / "Documents/ai/benchmark-repos/absolute-link-repo"
    (unsafe / "pkg").mkdir(parents=True)
    (unsafe / "pkg/b.py").write_text("def target():\n    return 1\n")
    (unsafe / "pkg/link.py").symlink_to("/etc/hosts")
    git(unsafe, "init", "-q")
    git(unsafe, "add", ".")
    git(unsafe, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    queries = {"full": "Fix {target} in b.\nIt fails.", "title": "Fix target"}
    instances = [matrix("fixture/fix-1", "fixture-repo", base, queries, ["pkg/b.py"]),
                 matrix("fixture/unsafe-1", "absolute-link-repo", git(unsafe, "rev-parse", "HEAD"), queries, ["pkg/b.py"])]
    study = freeze(localize, tmp_path, "study", instances, ["fixture/fix-1", "fixture/unsafe-1"], ("native",))
    localize.prepare(SimpleNamespace(study=study))
    prepared = json.loads((study / "preparation.json").read_text())["tasks"]
    assert prepared["fixture_unsafe-1"]["status"] == "excluded"
    assert prepared["fixture_unsafe-1"]["reason"].startswith("Unsafe snapshot")
    assert prepared["fixture_fix-1"]["status"] == "ready"
    assert not (study / "sources/fixture_unsafe-1").exists()


def test_warm_waits_until_search_has_its_indexes(localize, monkeypatch, tmp_path):
    import warm_cache
    requests = []

    class Worker:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, task):
            requests.append(task["operation"])
            if task["operation"] == "bootstrap":
                return {"ready_coverage": {"phase": "ready"}}
            status = "warming" if len(requests) < 4 else "ready"
            return {"payload": {"metadata": {"ranking": {"index": {"status": status}}}}}

        def close(self, force=False):
            pass

    monkeypatch.setattr(warm_cache, "Worker", Worker)
    monkeypatch.setattr(localize.time, "sleep", lambda seconds: None)
    result = localize.warm(tmp_path, tmp_path, tmp_path / "warm", {"server_env": {}})
    assert result["ready"] and requests == ["bootstrap"] + 3 * ["semantic_search"]


def test_started_trial_without_result_is_kept_as_interrupted(localize, monkeypatch, tmp_path):
    row = {"id": "d.x:claude:0:native", "task": "d.x", "client": "claude", "repeat": 0, "lane": "native"}
    manifest = {"study_id": "frozen", "setups": ["native"], "schedule": [row], "tasks": [{"id": "d.x"}]}
    monkeypatch.setattr(localize, "load", lambda study: manifest)
    monkeypatch.setattr(localize, "trial", lambda *args: pytest.fail("An interrupted trial must not run again"))
    (tmp_path / "preparation.json").write_text(json.dumps({"study_id": "frozen", "tasks": {"d.x": {"status": "ready"}}}))
    folder = localize.run_dir(tmp_path, row)
    folder.mkdir(parents=True)
    (folder / "started.json").write_text("{}")
    localize.run(SimpleNamespace(study=tmp_path, quota=None, tasks=None, max_runs=None, jobs=1, deadline_minutes=1))
    assert json.loads((folder / "result.json").read_text())["status"] == "interrupted"


@pytest.mark.parametrize("raw, expected", [
    (["./a.py", "a.py:12", "/ws/root/b.py", "b.py:3:7", "./c.py:10-20", " ", "a.py"], ["a.py", "b.py", "c.py"]),
    ([f"f{n}.py" for n in range(12)], [f"f{n}.py" for n in range(10)]),
    (["/elsewhere/x.py", "dir\\y.py"], ["/elsewhere/x.py", "dir/y.py"]),
])
def test_answer_paths_become_repository_relative(localize, raw, expected):
    assert localize.clean_paths(raw, "/ws/root") == expected


def test_grading_uses_shared_metrics_and_scores_failures_as_zero(localize, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT))
    from eval import metrics
    manifest = {"config_id": "product", "model": "m", "timeout": 600}
    task = {"id": "d_x", "dataset": "d", "instance_id": "d/x", "gold": ["src/a.py", "src/b.py"]}
    record = {"id": "d_x:claude:0:native", "lane": "native", "repeat": 0, "workspace": "/ws", "status": "completed",
              "stage": {"output": {"files": ["docs/x.md", "src/a.py", "/ws/src/b.py:4"]}, "seconds": 42.0,
                        "cost_usd": 0.5, "turns": 5}}
    good = localize.grade(tmp_path, manifest, task, record, metrics, {"src/a.py", "src/b.py"})
    assert (good["acc1"], good["acc5"], good["recall10"], good["mrr5"]) == (0.0, 1.0, 1.0, 0.5)
    assert (good["invalid_paths"], good["seconds"], good["failed"]) == (1, 42.0, False)
    record.update(status="failed", stage={**record["stage"], "timed_out": True, "exit_code": -9})
    bad = localize.grade(tmp_path, manifest, task, record, metrics, None)
    assert (bad["acc5"], bad["mrr5"], bad["seconds"], bad["failure"]) == (0.0, 0.0, 600, "timed_out")
    assert localize.gold_seen([{"event_index": 1, "received_seconds": 3.0, "content": "src/a.pyc"},
                               {"event_index": 2, "received_seconds": 5.0, "content": [{"text": "/ws/src/b.py:1"}]}],
                              {"src/a.py", "src/b.py"}) == 5.0


def test_prompt_text_is_part_of_the_study_id(localize, stub, tmp_path, monkeypatch):
    first = frozen(localize, tmp_path, "first", setups=["native", "intel_first"])
    monkeypatch.setattr(localize, "PROMPT_V1", localize.PROMPT_V1.replace("most likely first", "best first"))
    second = frozen(localize, tmp_path, "second", setups=["native", "intel_first"])
    manifests = [json.loads((study / "manifest.json").read_text()) for study in (first, second)]
    assert manifests[0]["study_id"] != manifests[1]["study_id"]
    prompts = manifests[0]["tasks"][0]["prompts"]
    assert prompts["native"].startswith("Fix {target} in b.\nIt fails.\n\nFind the files")
    assert prompts["intel_first"] == prompts["native"] + localize.FIRST


def test_matrix_instances_become_tasks(localize, stub, tmp_path):
    commit = "a" * 40
    github = matrix("locbench/o__r-1", "o/r", commit, {"full": "Crash in x\nDetails", "title": "Crash in x"}, ["x.py"])
    pack = matrix("graded_blind/okhttp::follow redirects", "okhttp", commit, {"full": "follow redirects"}, ["a.kt"])
    with pytest.raises(ValueError, match="exactly one instance"):
        freeze(localize, tmp_path, "unknown", [github], ["o__r-1"], ["native"])
    study = freeze(localize, tmp_path, "study", [github, pack, {**pack, "id": "graded_blind/other"}],
                   [github["id"], pack["id"]], ["native"])
    tasks = {task["instance_id"]: task for task in json.loads((study / "manifest.json").read_text())["tasks"]}
    assert set(tasks) == {github["id"], pack["id"]}
    assert tasks[github["id"]]["id"] == "locbench_o__r-1" and tasks[github["id"]]["dataset"] == "locbench"
    assert tasks[github["id"]]["source"] == "https://github.com/o/r.git"
    assert (tasks[github["id"]]["issue"], tasks[github["id"]]["title"]) == ("Crash in x\nDetails", "Crash in x")
    assert tasks[pack["id"]]["id"] == "graded_blind_okhttp_follow_redirects"
    assert tasks[pack["id"]]["source"] == str(Path.home() / "Documents/ai/benchmark-repos/okhttp")
    assert tasks[pack["id"]]["title"] == tasks[pack["id"]]["issue"] == "follow redirects"
    assert tasks[pack["id"]]["gold"] == ["a.kt"]
