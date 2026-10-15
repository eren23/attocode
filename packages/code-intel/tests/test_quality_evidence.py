"""A broader matrix must not inflate coverage, mix versions or retain source copies."""
import copy
import json
import sys

import pytest

from eval.quality.evidence import merge_reports, reusable_rows, select_packs, summarize


def test_operation_inventory_requires_passing_teardown_and_keeps_unmapped_tools():
    from eval.quality.coverage import operation_inventory
    calls = {'ok': [('search', 'response'), ('search', 'error')], 'bad': [('delete', 'response')]}
    outcomes = {'ok': dict.fromkeys(('setup', 'call', 'teardown'), 'passed'),
                'bad': {'setup': 'passed', 'call': 'passed', 'teardown': 'failed'}}
    report = operation_inventory(['search', 'delete', 'unknown'], calls, outcomes)
    assert report['observed'] == 1 and report['total'] == 3
    search = next(r for r in report['operations'] if r['operation'] == 'search')
    assert search['tests'][0]['responses'] == search['tests'][0]['errors'] == 1
    assert all(r['status'] == 'unmapped' for r in report['operations'] if r['operation'] != 'search')


def evidence(name, outcome="passed"):
    return {"id": name, "status": "passed", "cleanup_verified": True,
            "checks": [{"name": "definition", "outcome": outcome}]}


def report(rows, *, packs=("one", "two")):
    return {"schema_version": 2, "identity": {"source": "frozen", "environment": "fixed"},
            "manifest_packs": list(packs), "repositories": rows, "cleanup_verified": True}


def test_shards_are_disjoint_complete_and_order_independent():
    specs = [{"id": str(i)} for i in range(36)]
    groups = [select_packs(specs, shard=f"{i}/3") for i in range(1, 4)]
    assert [len(g) for g in groups] == [12, 12, 12]
    assert len({s["id"] for g in groups for s in g}) == 36
    assert select_packs(specs[::-1], shard="2/3") == groups[1]
    assert select_packs(specs, packs=["2", "0"]) == [{"id": "0"}, {"id": "2"}]


@pytest.mark.parametrize("packs,shard", [(["missing"], None), ([], "0/3"), ([], "4/3"),
                                        ([], "1/4"), ([], "all"), ([], "1/0")])
def test_invalid_selection_never_runs_a_different_pack(packs, shard):
    with pytest.raises(ValueError):
        select_packs([{"id": "one"}, {"id": "two"}], packs, shard)


def test_missing_and_limited_evidence_do_not_become_successful_assertions():
    rows = [evidence("one", "limited"), evidence("two", "unsupported")]
    result = summarize(rows, ["one", "two", "three"])
    assert result["status"] == "incomplete" and not result["passed"]
    assert result["outcomes"] == {"passed": 0, "failed": 0, "limited": 1, "unsupported": 1, "incomplete": 0}
    assert result["missing_packs"] == ["three"]
    rows.append(evidence("three", "failed"))
    assert summarize(rows, ["one", "two", "three"])["status"] == "failed"


def test_shard_aggregation_requires_same_version_complete_union_and_cleanup():
    a, b = report([evidence("one")]), report([evidence("two")])
    assert merge_reports([a])["missing_packs"] == ["two"]
    assert merge_reports([a, b])["passed"]
    changed = copy.deepcopy(b)
    changed["identity"]["source"] = "new"
    with pytest.raises(ValueError, match="different candidate"):
        merge_reports([a, changed])
    changed = copy.deepcopy(b)
    changed["cleanup_verified"] = False
    with pytest.raises(ValueError, match="cleanup"):
        merge_reports([a, changed])
    conflict = report([evidence("one", "failed")])
    with pytest.raises(ValueError, match="Conflicting"):
        merge_reports([a, conflict])


def test_resume_cannot_hide_failed_incomplete_or_unclean_packs():
    previous = report([evidence("one"), evidence("two", "failed"), evidence("three")])
    previous["repositories"][-1]["cleanup_verified"] = False
    assert list(reusable_rows(previous, previous["identity"], ["one", "two", "three"])) == ["one"]
    with pytest.raises(ValueError, match="different inputs"):
        reusable_rows(previous, {"source": "changed"}, ["one"])


async def test_real_workflow_reports_unlabeled_relationships_as_limited(tmp_path, monkeypatch):
    from eval.quality.corpus import evaluate
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("def greeting():\n    return 'hello'\ngreeting()\n")
    rows = await evaluate(tmp_path, {"file": "main.py", "symbol": "greeting", "anchor": "def greeting(",
                                     "caller": "main.py", "importer": None, "test": None})
    outcomes = {row["name"]: row["outcome"] for row in rows}
    assert {name for name, value in outcomes.items() if value == "limited"} == {"dependencies", "impact", "tests"}
    assert sum(row["passed"] for row in rows) == 5
    assert all(row["contract_passed"] for row in rows)


def test_pack_storage_is_released_before_next_pack_and_resume_skips_execution(tmp_path, monkeypatch):
    import yaml

    from eval.quality import corpus
    manifest = tmp_path / "packs.yaml"
    specs = [{"id": name, "repo": "owner/" + name, "commit": "a" * 40, "language": "python"}
             for name in ("one", "two")]
    manifest.write_text(yaml.safe_dump({"repositories": specs}))
    monkeypatch.setattr(corpus, "PACK", manifest)
    monkeypatch.setattr(corpus, "evidence_identity", lambda: {"pack_sha256": "frozen"})
    previous = []
    def materialize(spec, root, cache):
        assert all(not p.exists() for p in previous)
        previous.extend([root, cache])
        (cache / "blob").write_bytes(b"source")
        (root / "source.py").write_text("pass\n")
        return "tree"
    def evaluate(root, spec, directory):
        return {"checks": [{"name": "source", "outcome": "passed", "passed": True}], "retrieval": []}
    monkeypatch.setattr(corpus, "materialize", materialize)
    monkeypatch.setattr(corpus, "evaluate_isolated", evaluate)
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["corpus", "--output", str(output)])
    assert corpus.main() == 0
    result = json.loads(output.read_text())
    assert result["cleanup_verified"] and result["outcomes"]["passed"] == 2
    assert all(not p.exists() for p in previous)
    monkeypatch.setattr(corpus, "materialize", lambda *a: pytest.fail("Resumed pack must not execute"))
    monkeypatch.setattr(sys, "argv", ["corpus", "--output", str(tmp_path / "resumed.json"), "--resume", str(output)])
    assert corpus.main() == 0


def test_frozen_breadth_manifest_has_complete_distinct_source_questions():
    import re

    import yaml

    from eval.quality.corpus import PACK
    specs = yaml.safe_load(PACK.read_text())["repositories"]
    assert len(specs) == 36 and len({s["id"] for s in specs}) == 36
    assert all(re.fullmatch(r"[a-f0-9]{40}", s["commit"]) for s in specs)
    assert sum(len(s["queries"]) for s in specs) == 144
    for spec in specs:
        assert len(spec["queries"]) == len({q["query"] for q in spec["queries"]}) == 4
        for q in spec["queries"]:
            assert q["evidence"]
            assert all(e["quote"] and e["line"] > 0 and len(e["source_sha256"]) == 64 for e in q["evidence"])


def test_source_scoping_copies_only_selected_git_blobs(tmp_path):
    import subprocess

    from eval.matrix import run as matrix
    from eval.quality.sources import read_tree
    source = tmp_path / "source"
    source.mkdir()
    for name, text in [("inside/main.py", "def inside(): pass\n"), ("outside/other.py", "def outside(): pass\n")]:
        path = source / name
        path.parent.mkdir()
        path.write_text(text)
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
            "-c", "user.name=Quality test", "-c", "user.email=quality@localhost", "-C", str(source), *args], text=True).strip()
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "Fixture")
    cache = tmp_path / "cache"
    tree = read_tree(source, git("rev-parse", "HEAD"), cache, {"include": ["inside"]})
    assert [e[0] for e in tree["entries"]] == ["inside/main.py"]
    assert not matrix._blob_file(cache, git("rev-parse", "HEAD:outside/other.py")).exists()
    tree = read_tree(source, git("rev-parse", "HEAD"), cache, {"subdir": "inside"})
    assert [e[0] for e in tree["entries"]] == ["main.py"]


@pytest.mark.parametrize("checkpointed", [False, True])
def test_worker_error_preserves_checkpoint_and_bounded_diagnostic(tmp_path, monkeypatch, checkpointed):
    from eval.quality import corpus

    spec, output = tmp_path / "spec.json", tmp_path / "worker.json"
    spec.write_text('{"id":"fixture"}')
    monkeypatch.setattr(sys, "argv", ["corpus", "--worker", str(tmp_path),
                                    "--spec", str(spec), "--output", str(output)])
    checks = [{"name": "definition", "outcome": "passed"}]
    async def fail(*args, observations, checkpoint):
        if checkpointed:
            observations.append({"id": "question"})
            checkpoint(checks, observations)
        raise TimeoutError("warming: " + "x" * 5000)
    monkeypatch.setattr(corpus, "evaluate", fail)
    with pytest.raises(TimeoutError, match="warming"):
        corpus.main()
    result = json.loads(output.read_text())
    assert result["checks"] == (checks if checkpointed else [])
    assert result["retrieval"] == ([{"id": "question"}] if checkpointed else [])
    assert result["worker_error"]["type"] == "TimeoutError"
    assert len(result["worker_error"]["message"]) == 4000


def test_interrupted_pack_preserves_completed_checks_and_stops_its_worker(tmp_path, monkeypatch):
    import subprocess

    from eval.quality import corpus
    original = subprocess.Popen
    child = None
    def launch(command, **kwargs):
        nonlocal child
        program = "import pathlib,json,time,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({'checks':[{'name':'source','outcome':'passed'}],'retrieval':[]})); time.sleep(30)"
        child = original([sys.executable, '-c', program, str(tmp_path / 'worker.json')], **kwargs)
        return child
    monkeypatch.setattr(corpus.subprocess, 'Popen', launch)
    monkeypatch.setattr(corpus, 'PACK_SECONDS', .5)
    result = corpus.evaluate_isolated(tmp_path, {'id':'fixture'}, tmp_path)
    assert result['status'] == 'incomplete'
    assert result['checks'][0]['name'] == 'source'
    assert child.poll() is not None


def test_resume_refuses_changed_inputs_and_missing_question_observations():
    previous = report([evidence('one')])
    previous['repositories'][0]['expected_questions'] = ['one:1']
    assert not reusable_rows(previous, previous['identity'], ['one'])
    result = summarize(previous['repositories'], ['one'])
    assert not result['complete'] and result['retrieval']['missing_questions'] == ['one:1']
    previous['reason'] = 'inputs_changed_during_run'
    with pytest.raises(ValueError, match='inputs changed'):
        reusable_rows(previous, previous['identity'], ['one'])
    assert not summarize([{'id':'one','status':'passed','cleanup_verified':True}], ['one'])['passed']


async def test_excluded_source_is_explicitly_unsupported_and_inclusion_restores_checks(tmp_path, monkeypatch):
    from eval.quality.corpus import evaluate
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist' / 'source.py').write_text('def helper(): return 1\n')
    spec = {'file':'dist/source.py', 'symbol':'helper', 'anchor':'def helper(', 'caller':None, 'importer':None, 'test':None}
    before = await evaluate(tmp_path, spec)
    assert {c['name'] for c in before if c['outcome'] == 'unsupported'} == {'definition','source','scoped_search','restart'}
    assert not any(c['passed'] for c in before if c['outcome'] == 'unsupported')
    (tmp_path / '.gitignore').write_text('!dist/\n')
    after = await evaluate(tmp_path, spec)
    assert all(c['outcome'] == 'passed' for c in after if c['name'] in {'definition','source','scoped_search','restart'})


async def test_fuzzy_same_file_definition_is_not_the_labeled_symbol(tmp_path, monkeypatch):
    from eval.quality.corpus import evaluate
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'source.py').write_text('# helper is planned\ndef helpers(): return 1\n')
    rows = await evaluate(tmp_path, {'file':'source.py','symbol':'helper','anchor':'# helper',
                                    'caller':None,'importer':None,'test':None})
    assert next(c for c in rows if c['name'] == 'definition')['outcome'] == 'failed'


def test_worker_grammar_acquisition_records_absent_artifact_without_downloading_it(tmp_path, monkeypatch):
    import runpy
    from pathlib import Path
    from types import SimpleNamespace
    names = ['haskell','erlang','clojure','perl','dart','ocaml','fsharp','julia','nim','r','objc']
    calls = []
    pack = SimpleNamespace(configure=lambda **kwargs: None, manifest_languages=lambda: names,
                           download=lambda selected: calls.append(selected), downloaded_languages=lambda: names)
    monkeypatch.setitem(sys.modules, 'tree_sitter_language_pack', pack)
    monkeypatch.setattr(pytest, 'main', lambda arguments: 0)
    monkeypatch.setenv('QUALITY_ALLOW_DOWNLOADS', '1')
    monkeypatch.setattr(sys, 'argv', ['check', '--cache', str(tmp_path / 'grammars')])
    main = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/check_optional_grammars.py'))['main']
    assert main() == 0
    assert calls == [names]
    monkeypatch.setattr(sys, 'argv', ['check', '--cache', str(tmp_path / 'unexpected')])
    pack.manifest_languages = lambda: names[:-1]
    with pytest.raises(RuntimeError, match='Unexpected unavailable'):
        main()
    assert calls == [names]


@pytest.mark.parametrize('name,expected,matched', [
    ('cmd.run_command','run_command',True), ('Phoenix.Endpoint','Phoenix.Endpoint',True),
    ('Endpoint','Phoenix.Endpoint',True), ('helpers','helper',False),
    ('Other.Endpoint','Phoenix.Endpoint',False),
])
def test_definition_identity_accepts_qualified_adapters_without_fuzzy_matches(name, expected, matched):
    from eval.quality.corpus import definition_matches
    spec = {'file':'source', 'symbol':expected}
    assert definition_matches({'file_path':'source','name':name}, spec) is matched
    assert not definition_matches({'file_path':'elsewhere','name':name}, spec)
