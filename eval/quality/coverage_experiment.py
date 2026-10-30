"""Temporary bounded causal coverage controls; no paid or scored workload."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / "eval/quality/experiments/coverage.json").read_bytes())
    tests = list(dict.fromkeys([*TESTS, "test_search_budget_repair.py", "test_search_evidence.py",
                              "test_search_coverage.py", "test_search_coverage_scale.py"]))
    xml = root / "evidence/coverage-controls.xml"
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", "packages/code-intel/pyproject.toml",
                             "--confcutdir=packages/code-intel/tests", "-q", "-p", "eval.quality.experiment_origin",
                             "--basetemp=" + str(root / "work/pytest"), "-o", "cache_dir=" + str(root / "work/cache"),
                             "--junitxml=" + str(xml), *["packages/code-intel/tests/" + p for p in tests]], cwd=REPO)
    tree = ET.fromstring(xml.read_bytes())
    cases = list(tree.iter("testcase"))
    failed = [c for c in cases if c.find("failure") is not None]
    assert len(cases) == design["expected_cases"]
    assert not list(tree.iter("error")) and not list(tree.iter("skipped"))
    assert len({(c.attrib["classname"], c.attrib["name"]) for c in cases}) == len(cases)
    expected = set(design["expected_failures"])
    assert {c.attrib["name"] for c in failed} == expected
    assert all("coverage boundary:" in "".join(c.find("failure").itertext()) for c in failed)
    assert result.returncode == (1 if expected else 0)
    write_json(root / "evidence/coverage-control-verdict.json", {
        "expected": design["expected"], "cases": len(cases), "failed": len(failed),
        "exit_code": result.returncode, "failures": sorted(expected)})
