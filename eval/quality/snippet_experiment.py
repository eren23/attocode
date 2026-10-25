"""Temporary causal snippet controls; no corpus retrieval or scored study."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / "eval/quality/experiments/snippet.json").read_bytes())
    tests = list(
        dict.fromkeys(
            [
                *TESTS,
                "test_search_budget_repair.py",
                "test_search_evidence.py",
                "test_snippet_budget.py",
            ]
        )
    )
    xml = root / "evidence/snippet-controls.xml"
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
    if design["expected"] == "restoration_absent":
        assert result.returncode == 1 and len(failures) == 4
        assert all(
            c.attrib["name"].startswith(
                "test_small_overflow_preserves_more_than_three_quarters_of_source["
            )
            and "snippet restoration boundary: excessive source loss"
            in "".join(c.find("failure").itertext())
            for c in failures
        )
    else:
        assert design["expected"] == "all_pass" and result.returncode == 0 and not failures
    write_json(
        root / "evidence/snippet-control-verdict.json",
        {
            "expected": design["expected"],
            "cases": len(cases),
            "failed": len(failures),
            "exit_code": result.returncode,
        },
    )
