"""Offline checks for the reproducible demo and scrubbed benchmark evidence."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from eval.rule_accuracy.demo.scan import HERE, reconcile, write_json
from eval.rule_accuracy.runner import _strip_annotations


def test_all_sample_rows_have_reviewed_evidence():
    rows = json.loads((HERE / "data/real.json").read_text())
    decisions = json.loads((HERE / "triage.json").read_text())
    assert len(rows) == len(decisions) == 82
    assert {r["sample_index"] for r in decisions} == set(range(82))
    for decision in decisions:
        assert decision["status"] in {"confirmed", "false_positive", "unresolved"}
        assert decision["rationale"] and decision["evidence"] and decision["acceptance"]


def test_annotation_scrubbing_covers_positive_and_negative_context():
    markers = ["expect: rule", "no-expect:", "ok: rule", "ruleid: rule", "todoruleid: rule", "nosec B307"]
    for marker in markers:
        f = SimpleNamespace(code_snippet=f"eval(x) # {marker}", description=f"bad # {marker}",
                            context_before=[f"safe() // {marker}"], context_after=[f"next() # {marker}"])
        _strip_annotations([f])
        assert f.code_snippet == "eval(x)" and f.description == "bad"
        assert f.context_before == ["safe()"] and f.context_after == ["next()"]


def test_reconciliation_does_not_guess_ambiguous_moves(tmp_path):
    (tmp_path / "x.py").write_text("changed()\nmatch()\nmatch()\n")
    row = {"file": "x.py", "line": 1, "snippet": "match()"}
    assert reconcile(tmp_path, row) == (None, "ambiguous_or_changed")
    (tmp_path / "x.py").write_text("changed()\nmatch()\n")
    assert reconcile(tmp_path, row) == (2, "relocated_match")


def test_refresh_redacts_nested_source_before_writing(tmp_path):
    secret = "abcdef" * 800
    path = tmp_path / "fresh.json"
    write_json(path, {"rows": [{"source": f'api_key = "{secret}"', "score": .8}]})
    content = path.read_text()
    assert "abcdef" not in content and "[REDACTED:" in content
    assert json.loads(content)["rows"][0]["score"] == .8


def test_benchmark_enriches_then_scrubs_before_provider(monkeypatch):
    from attocode_intel.confidence import jev

    from eval.rule_accuracy.runner import run_accuracy_benchmark

    seen = []

    def estimate(findings, **kwargs):
        seen.extend(findings)
        for f in findings:
            text = "\n".join([f.description, f.code_snippet, *f.context_before, *f.context_after])
            assert not any(marker in text for marker in ("# expect:", "# ok:", "# nosec", "// ruleid:"))
        return [.8] * len(findings)

    monkeypatch.setattr(jev, "available", lambda: True)
    monkeypatch.setattr(jev, "estimate", estimate)
    run_accuracy_benchmark(scorer="jev")
    assert seen and any(f.context_before or f.context_after for f in seen)


def test_historical_page_builds_without_scoring(tmp_path):
    subprocess.run([sys.executable, "-m", "eval.rule_accuracy.demo.build", "--output-dir", str(tmp_path)],
                   check=True, capture_output=True)
    page = (tmp_path / "calibration.html").read_text()
    assert '<meta charset="utf-8">' in page
    assert 'preload="none"' in page
    assert "legacy calibration proxy" in page
    assert "r.j >= .5 && r.m < .5" in page
    assert "__REAL__" not in page and "__DATA__" not in page
    assert "/private/tmp/" not in page


def test_archived_asset_checksums():
    import hashlib
    manifest = json.loads((HERE / "manifest.json").read_text())
    root = Path(__file__).resolve().parents[3]
    for item in manifest["assets"]:
        path = root / item["path"]
        if item["kind"] == "media" and not path.is_file():
            continue  # Media deliberately is not included in a checkout.
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
