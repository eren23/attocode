"""Temporary causal ocamlcapture-binding controls; no corpus retrieval or scored study."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / "eval/quality/experiments/ocamlcapture.json").read_bytes())
    if design.get("stage") == "smoke":
        return run_smoke(root, design)
    tests = list(dict.fromkeys([*TESTS, "test_native_capture.py"]))
    xml = root / "evidence/ocamlcapture-controls.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "packages/code-intel/pyproject.toml",
            "--confcutdir=packages/code-intel/tests",
            *["packages/code-intel/tests/" + p for p in tests],
            "-p",
            "eval.quality.experiment_origin",
            "-q",
            "--basetemp=" + str(root / "work/pytest"),
            "-o",
            "cache_dir=" + str(root / "work/cache"),
            "--junitxml=" + str(xml),
        ],
        cwd=REPO,
    )
    tree = ET.fromstring(xml.read_bytes())
    cases = list(tree.iter("testcase"))
    failures = [c for c in cases if c.find("failure") is not None]
    assert (
        len(cases) == design["expected_cases"]
        and not list(tree.iter("error"))
        and not list(tree.iter("skipped"))
    )
    assert len({(c.attrib["classname"], c.attrib["name"]) for c in cases}) == len(cases)
    expected = set(design["expected_failures"])
    assert {c.attrib["name"] for c in failures} == expected
    assert all("OCaml capture:" in "".join(c.find("failure").itertext()) for c in failures)
    assert result.returncode == (1 if expected else 0)
    write_json(
        root / "evidence/ocamlcapture-control-verdict.json",
        {
            "expected_failures": design["expected_failures"],
            "cases": len(cases),
            "failed": len(failures),
            "exit_code": result.returncode,
        },
    )


def run_smoke(root, design):
    """One pinned routine worker; no retrieval questions or study verdict."""
    import hashlib
    import os
    import platform
    import shutil
    import time
    from collections import Counter

    import yaml

    from eval.quality.corpus import materialize
    from eval.quality.corpus_capture import admit_worker
    from eval.quality.experiment_evidence import Journal, assert_engine
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.native_experiment import grammar_identity

    for name, expected in design['capture_source_sha256'].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == expected
    smoke = design['smoke']
    assert smoke['worker_seconds'] == 180 and smoke['routine_worker_processes'] == 1
    assert smoke['max_trace_bytes'] == 4 * 2**20 and smoke['fixture']['queries'] == []
    pack_bytes = (REPO / 'eval/quality/workflows.yaml').read_bytes()
    assert hashlib.sha256(pack_bytes).hexdigest() == smoke['source_manifest_sha256']
    original = next(s for s in yaml.safe_load(pack_bytes)['repositories'] if s['id'] == 'ocaml')
    spec = smoke['fixture']
    assert spec == {**original, 'queries': []}
    target = {'runner': 'ubuntu-latest', 'sys_platform': 'linux', 'machine': 'x86_64',
              'scope': 'One pinned OCaml routine-worker capture smoke; no breadth/relevance/performance verdict'}
    actual = {'sys_platform': sys.platform, 'machine': platform.machine(), 'platform': platform.platform()}
    assert all(actual[k] == target[k] for k in ('sys_platform', 'machine'))
    write_json(root / 'evidence/runtime-platform.json', {'target': target, 'actual': actual})
    write_json(root / 'evidence/smoke-design.json', design)
    selected = os.environ['ATTOCODE_EXPERIMENT_ENGINE']
    captures = root / 'evidence/broad'
    control = Journal(captures / 'controller', 2 * 2**20)
    control.response({'event': 'origin_start'}, {'pid': os.getpid(), 'origins': assert_engine(selected)})
    workspace = root / 'work/ocaml'
    workspace.mkdir()
    cache = root / 'cache/grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), cache)
    before = grammar_identity(cache)
    write_json(root / 'evidence/grammar-before.json', before)
    report = {'status': 'incomplete', 'decision': None, 'scope': smoke['scope'], 'worker_launched': False}
    write_json(root / 'evidence/smoke-verdict.json', report)
    try:
        receipt = {}
        started = time.monotonic()
        tree = materialize(spec, workspace, root / 'cache/source', receipt=receipt)
        assert source_manifest(workspace) == receipt and not (workspace / '.attocode').exists()
        fixture = Journal(captures / 'ocaml/fixture', 8 * 2**20)
        ref = fixture.response({'event': 'fixture_pinned', 'repo': spec['repo'],
                               'commit': spec['commit'], 'tree': tree}, receipt)
        setup_seconds = time.monotonic() - started
        source_spec = root / 'work/spec.json'
        write_json(source_spec, spec)
        output = root / 'evidence/worker.json'
        environment = {**os.environ, 'ATTOCODE_CORPUS_EVIDENCE': str(captures),
                       'QUALITY_GRAMMAR_CACHE': str(cache)}
        command = [sys.executable, '-m', 'eval.quality.corpus', '--worker', str(workspace),
                   '--spec', str(source_spec), '--output', str(output)]
        report.update(worker_launched=True, workspace=str(workspace), worker_command=command)
        write_json(root / 'evidence/smoke-verdict.json', report)
        with (root / 'evidence/worker.log').open('xb') as log:
            child = subprocess.run(command,
                                   cwd=REPO, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=180, check=False)
        report['worker_exit_code'] = child.returncode
        assert child.returncode == 0 and output.is_file()
        result = json.loads(output.read_bytes())
        assert not result.get('worker_error') and result['retrieval'] == []
        assert [c['name'] for c in result['checks']] == [
            'definition', 'source', 'scoped_search', 'caller_syntax', 'dependencies', 'impact', 'tests', 'restart']
        assert all(c['outcome'] in {'passed', 'limited'} for c in result['checks'])
        row = {**result, 'id': 'ocaml', 'revision': spec['commit'], 'language': 'ocaml',
               'tree': tree, 'fixture_ref': ref, 'status': 'passed', 'phase': 'finished',
               'passed': True, 'expected_questions': [], 'setup_seconds': setup_seconds}
        row['admission'] = admit_worker(workspace, spec, captures / 'ocaml', row, Path(selected))
        native = row['admission']['native_capture']
        assert native['selected_source_parses'] > 0 and native['parse_calls'] > 0
        assert native['worker_pid'] != os.getpid() and native['bytes'] <= 4 * 2**20
        after = grammar_identity(cache)
        write_json(root / 'evidence/grammar-after.json', after)
        assert before == after
        shutil.rmtree(workspace)
        row['cleanup_verified'] = not workspace.exists()
        assert row['cleanup_verified']
        counts = Counter(c['outcome'] for c in row['checks'])
        workflows = {'passed': True, 'complete': True, 'cleanup_verified': True,
                     'pack_sha256': smoke['source_manifest_sha256'], 'model_runs': 0,
                     'selected_packs': ['ocaml'], 'manifest_packs': ['ocaml'], 'repositories': [row],
                     'outcomes': {n: counts.get(n, 0) for n in ('passed', 'failed', 'limited', 'unsupported', 'incomplete')},
                     'retrieval': {'observed_questions': 0, 'missing_questions': [],
                                   'labeled_hit_at_5': 0, 'labeled_hit_at_24': 0}}
        write_json(root / 'evidence/workflows.json', workflows)
        report.update(status='complete', admission=row['admission'], grammar_identity_unchanged=True,
                      fixture_entries=len(receipt), worker_processes=1, issued_retrieval_questions=0,
                      workflow_checks=8, native_capture=native, fixture_removed=True)
    finally:
        control.response({'event': 'origin_end'}, {'pid': os.getpid(), 'origins': assert_engine(selected)})
        write_json(root / 'evidence/smoke-verdict.json', report)
