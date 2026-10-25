"""Temporary causal ocamlcapture-binding controls; no corpus retrieval or scored study."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from eval.quality.runner import REPO, write_json


def run(root):
    from eval.quality.experiments import TESTS

    design = json.loads((REPO / "eval/quality/experiments/ocamlcapture.json").read_bytes())
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
    assert all("ocamlcaptureer binding guard:" in "".join(c.find("failure").itertext()) for c in failures)
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
