"""Temporary causal controls: expected feature absence is retained as successful data."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    design = json.loads((REPO / "eval/quality/experiments/context_control.json").read_bytes())
    from eval.quality.experiments import TESTS

    tests = ["packages/code-intel/tests/test_context_search.py"]
    if design["expected"] != "feature_absent":
        tests += ["packages/code-intel/tests/" + name for name in TESTS]
    if design.get("include_trial_guards"):
        tests.append("packages/code-intel/tests/test_context_experiment.py")
    xml = root / "evidence/context-controls.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "packages/code-intel/pyproject.toml",
            "--confcutdir=packages/code-intel/tests",
            *tests,
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
    assert cases and not list(tree.iter("error"))
    failures = [c for c in cases if c.find("failure") is not None]
    if design["expected"] == "feature_absent":
        assert result.returncode == 1 and len(cases) == 20 and len(failures) == 19
        assert {c.attrib["name"] for c in cases if c.find("failure") is None} == {
            "test_ordinary_search_needs_no_structural_initialization"
        }
        for c in failures:
            text = "".join(c.find("failure").itertext())
            assert any(
                t in text for t in ("context_file", "allowed_paths", "KeyError: 'context'")
            ), (c.attrib, text)
    elif design["expected"] == "compact_provenance_absent":
        assert len(cases) == design["expected_cases"] and result.returncode == 1
        assert (
            len(failures) == 1
            and failures[0].attrib["name"]
            == "test_compact_context_metadata_preserves_budget_with_long_neighbor_names"
        )
        assert "max_tokens is too small" in "".join(failures[0].find("failure").itertext())
    elif design["expected"] == "trial_guards_absent":
        assert (
            len(cases) == design["expected_cases"]
            and result.returncode == 1
            and len(failures) == 14
        )
        assert all(
            "test_context_experiment" in c.attrib["classname"]
            and "eval.quality.context_experiment" in "".join(c.find("failure").itertext())
            for c in failures
        )
    elif design["expected"] == "http_vector_absent":
        assert (
            len(cases) == design["expected_cases"] and result.returncode == 1 and len(failures) == 2
        )
        assert all(
            c.attrib["name"].startswith("test_http_context_vector_is_rejected_instead_of_ignored")
            and "200 == 422" in "".join(c.find("failure").itertext())
            for c in failures
        )
    else:
        assert (
            design["expected"] == "all_pass"
            and result.returncode == 0
            and not failures
            and len(cases) == design["expected_cases"]
        )
    write_json(
        root / "evidence/context-control-verdict.json",
        {
            "expected": design["expected"],
            "cases": len(cases),
            "failed": len(failures),
            "exit_code": result.returncode,
        },
    )
