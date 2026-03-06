from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.oss_demo.__main__ import cmd_prepare, cmd_summarize, cmd_validate_results


def _write_manifest(path: Path) -> None:
    path.write_text(
        """
version: 1
repos:
  - id: repo_a
    name: owner/repo_a
agents:
  - id: codex
    display_name: Codex CLI
tasks:
  - id: orient
    title: Orientation
    expected_tools: [bootstrap]
    prompt: orient this repo
scoring:
  quality_weights:
    task_completion: 0.35
    evidence_quality: 0.25
    technical_correctness: 0.20
    actionability: 0.10
    clarity: 0.10
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_prepare_creates_packets_and_template(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    out_dir = tmp_path / "out"
    _write_manifest(manifest)

    args = argparse.Namespace(
        manifest=str(manifest),
        out=str(out_dir),
        run_id="run-1",
        include_ablation=True,
    )
    cmd_prepare(args)

    packet = out_dir / "packets" / "codex" / "repo_a" / "orient__with_code_intel.md"
    packet_ablation = out_dir / "packets" / "codex" / "repo_a" / "orient__without_code_intel.md"
    template = out_dir / "results_template.jsonl"

    assert packet.exists()
    assert packet_ablation.exists()
    assert template.exists()

    rows = [json.loads(line) for line in template.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    assert {row["mode"] for row in rows} == {"with_code_intel", "without_code_intel"}


def test_validate_and_summarize(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    results = tmp_path / "results.jsonl"
    report = tmp_path / "report.md"
    _write_manifest(manifest)

    row = {
        "run_id": "run-1",
        "agent_id": "codex",
        "repo_id": "repo_a",
        "task_id": "orient",
        "mode": "with_code_intel",
        "status": "passed",
        "time_s": 12.5,
        "estimated_cost_usd": 0.02,
        "tool_calls": 4,
        "score_task_completion": 5,
        "score_evidence_quality": 4,
        "score_technical_correctness": 5,
        "score_actionability": 4,
        "score_clarity": 4,
        "evidence_paths": ["notes/orient.md"],
    }
    results.write_text(json.dumps(row) + "\n", encoding="utf-8")

    validate_args = argparse.Namespace(manifest=str(manifest), results=str(results))
    cmd_validate_results(validate_args)

    summary_args = argparse.Namespace(
        manifest=str(manifest),
        results=str(results),
        out=str(report),
    )
    cmd_summarize(summary_args)

    output = report.read_text(encoding="utf-8")
    assert "Comparative Scorecard" in output
    assert "Codex CLI" in output
    assert "Pass Rate" in output
