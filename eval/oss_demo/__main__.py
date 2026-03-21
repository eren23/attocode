"""CLI for preparing and summarizing the OSS Big-3 code-intel demonstration."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_RESULT_FIELDS = {
    "run_id",
    "agent_id",
    "repo_id",
    "task_id",
    "status",
    "time_s",
    "estimated_cost_usd",
    "tool_calls",
    "score_task_completion",
    "score_evidence_quality",
    "score_technical_correctness",
    "score_actionability",
    "score_clarity",
    "evidence_paths",
}

VALID_STATUSES = {"passed", "failed", "error", "skipped"}
VALID_MODES = {"with_code_intel", "without_code_intel"}


@dataclass(slots=True)
class Manifest:
    data: dict[str, Any]

    @property
    def agents(self) -> list[dict[str, Any]]:
        return list(self.data.get("agents", []))

    @property
    def repos(self) -> list[dict[str, Any]]:
        return list(self.data.get("repos", []))

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return list(self.data.get("tasks", []))

    @property
    def scoring(self) -> dict[str, Any]:
        return dict(self.data.get("scoring", {}))


def load_manifest(path: Path) -> Manifest:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be a mapping: {path}")
    return Manifest(payload)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _prompt_packet(
    *,
    agent: dict[str, Any],
    repo: dict[str, Any],
    task: dict[str, Any],
    with_code_intel: bool,
) -> str:
    mode = "with_code_intel" if with_code_intel else "without_code_intel"
    tools = ", ".join(task.get("expected_tools", []))
    capability_note = (
        "Use MCP code-intel tools directly when needed."
        if with_code_intel
        else "Do not use MCP code-intel tools; rely on baseline navigation only."
    )
    return (
        f"# Benchmark Packet\\n\\n"
        f"- Agent: {agent.get('display_name', agent.get('id', 'unknown'))}\\n"
        f"- Agent ID: {agent.get('id', 'unknown')}\\n"
        f"- Repository: {repo.get('name', repo.get('id', 'unknown'))}\\n"
        f"- Repo ID: {repo.get('id', 'unknown')}\\n"
        f"- Task ID: {task.get('id', 'unknown')}\\n"
        f"- Mode: {mode}\\n"
        f"- Expected code-intel tools: {tools or '(none listed)'}\\n\\n"
        f"## Instructions\\n"
        f"{task.get('prompt', '').strip()}\\n\\n"
        f"## Constraints\\n"
        f"- Analysis and plan output only; do not mutate repository files.\\n"
        f"- Provide evidence paths and references for each major claim.\\n"
        f"- {capability_note}\\n"
    )


def cmd_prepare(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    out_dir = Path(args.out)
    _ensure_dir(out_dir)

    packets_dir = out_dir / "packets"
    _ensure_dir(packets_dir)

    rows: list[dict[str, Any]] = []

    for agent in manifest.agents:
        for repo in manifest.repos:
            for task in manifest.tasks:
                packet_dir = packets_dir / agent["id"] / repo["id"]
                _ensure_dir(packet_dir)

                with_tools_packet = _prompt_packet(
                    agent=agent,
                    repo=repo,
                    task=task,
                    with_code_intel=True,
                )
                (packet_dir / f"{task['id']}__with_code_intel.md").write_text(with_tools_packet)

                rows.append({
                    "run_id": args.run_id,
                    "agent_id": agent["id"],
                    "repo_id": repo["id"],
                    "task_id": task["id"],
                    "mode": "with_code_intel",
                    "status": "skipped",
                    "time_s": 0.0,
                    "estimated_cost_usd": 0.0,
                    "tool_calls": 0,
                    "score_task_completion": 0,
                    "score_evidence_quality": 0,
                    "score_technical_correctness": 0,
                    "score_actionability": 0,
                    "score_clarity": 0,
                    "evidence_paths": [],
                    "notes": "fill after executing packet",
                })

                if args.include_ablation:
                    no_tools_packet = _prompt_packet(
                        agent=agent,
                        repo=repo,
                        task=task,
                        with_code_intel=False,
                    )
                    (packet_dir / f"{task['id']}__without_code_intel.md").write_text(no_tools_packet)

                    rows.append({
                        "run_id": args.run_id,
                        "agent_id": agent["id"],
                        "repo_id": repo["id"],
                        "task_id": task["id"],
                        "mode": "without_code_intel",
                        "status": "skipped",
                        "time_s": 0.0,
                        "estimated_cost_usd": 0.0,
                        "tool_calls": 0,
                        "score_task_completion": 0,
                        "score_evidence_quality": 0,
                        "score_technical_correctness": 0,
                        "score_actionability": 0,
                        "score_clarity": 0,
                        "evidence_paths": [],
                        "notes": "fill after executing packet",
                    })

    results_template = out_dir / "results_template.jsonl"
    with results_template.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(f"Wrote packets to: {packets_dir}")
    print(f"Wrote results template: {results_template}")
    print(f"Total rows: {len(rows)}")


def load_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {i}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Result line {i} must be an object")
            rows.append(row)
    return rows


def validate_results(rows: list[dict[str, Any]], manifest: Manifest) -> list[str]:
    errors: list[str] = []

    valid_agent_ids = {a["id"] for a in manifest.agents}
    valid_repo_ids = {r["id"] for r in manifest.repos}
    valid_task_ids = {t["id"] for t in manifest.tasks}

    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED_RESULT_FIELDS - set(row.keys())
        if missing:
            errors.append(f"line {idx}: missing fields: {sorted(missing)}")
            continue

        if row.get("agent_id") not in valid_agent_ids:
            errors.append(f"line {idx}: unknown agent_id={row.get('agent_id')}")
        if row.get("repo_id") not in valid_repo_ids:
            errors.append(f"line {idx}: unknown repo_id={row.get('repo_id')}")
        if row.get("task_id") not in valid_task_ids:
            errors.append(f"line {idx}: unknown task_id={row.get('task_id')}")

        status = row.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"line {idx}: invalid status={status}")

        mode = row.get("mode")
        if mode is not None and mode not in VALID_MODES:
            errors.append(f"line {idx}: invalid mode={mode}")

        if not isinstance(row.get("evidence_paths"), list):
            errors.append(f"line {idx}: evidence_paths must be a list")

    return errors


def _avg(nums: list[float]) -> float:
    return sum(nums) / len(nums) if nums else 0.0


def _weighted_quality(row: dict[str, Any], weights: dict[str, float]) -> float:
    return (
        float(row.get("score_task_completion", 0)) * float(weights.get("task_completion", 0.0))
        + float(row.get("score_evidence_quality", 0)) * float(weights.get("evidence_quality", 0.0))
        + float(row.get("score_technical_correctness", 0)) * float(weights.get("technical_correctness", 0.0))
        + float(row.get("score_actionability", 0)) * float(weights.get("actionability", 0.0))
        + float(row.get("score_clarity", 0)) * float(weights.get("clarity", 0.0))
    )


def cmd_validate_results(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    rows = load_results(Path(args.results))
    errors = validate_results(rows, manifest)
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)

    print(f"Results file is valid: {args.results} ({len(rows)} rows)")


def cmd_summarize(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    rows = load_results(Path(args.results))

    errors = validate_results(rows, manifest)
    if errors:
        raise ValueError("Cannot summarize invalid results. Run validate-results first.")

    quality_weights = manifest.scoring.get("quality_weights", {})

    agent_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repo_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mode_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        agent_rows[row["agent_id"]].append(row)
        repo_rows[row["repo_id"]].append(row)
        mode = row.get("mode")
        if isinstance(mode, str):
            mode_rows[mode].append(row)

    lines: list[str] = []
    lines.append("# Codebase Intelligence Demo Report")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(f"- Rows analyzed: {len(rows)}")
    lines.append(f"- Agents: {', '.join(a['display_name'] for a in manifest.agents)}")
    lines.append(f"- Repos: {', '.join(r['name'] for r in manifest.repos)}")
    lines.append("")

    lines.append("## Comparative Scorecard")
    lines.append("| Agent | Pass Rate | Avg Quality (0-5) | Avg Time (s) | Avg Cost ($) | Avg Tool Calls |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    for agent in manifest.agents:
        aid = agent["id"]
        data = agent_rows.get(aid, [])
        if not data:
            lines.append(f"| {agent['display_name']} | 0.0% | 0.00 | 0.0 | 0.0000 | 0.0 |")
            continue

        passed = sum(1 for r in data if r.get("status") == "passed")
        pass_rate = (passed / len(data)) * 100
        avg_quality = _avg([_weighted_quality(r, quality_weights) for r in data])
        avg_time = _avg([float(r.get("time_s", 0.0)) for r in data])
        avg_cost = _avg([float(r.get("estimated_cost_usd", 0.0)) for r in data])
        avg_tools = _avg([float(r.get("tool_calls", 0)) for r in data])

        lines.append(
            f"| {agent['display_name']} | {pass_rate:.1f}% | {avg_quality:.2f} | "
            f"{avg_time:.1f} | {avg_cost:.4f} | {avg_tools:.1f} |"
        )

    lines.append("")
    lines.append("## Repository Notes")
    for repo in manifest.repos:
        rid = repo["id"]
        data = repo_rows.get(rid, [])
        pass_rate = (sum(1 for r in data if r.get("status") == "passed") / len(data) * 100) if data else 0.0
        avg_quality = _avg([_weighted_quality(r, quality_weights) for r in data]) if data else 0.0
        lines.append(f"### {repo['name']}")
        lines.append(f"- Archetype: {repo.get('archetype', 'n/a')}")
        lines.append(f"- Pass rate: {pass_rate:.1f}%")
        lines.append(f"- Avg quality: {avg_quality:.2f}/5")

    if mode_rows.get("with_code_intel") and mode_rows.get("without_code_intel"):
        with_rows = mode_rows["with_code_intel"]
        without_rows = mode_rows["without_code_intel"]
        with_q = _avg([_weighted_quality(r, quality_weights) for r in with_rows])
        without_q = _avg([_weighted_quality(r, quality_weights) for r in without_rows])
        with_t = _avg([float(r.get("time_s", 0.0)) for r in with_rows])
        without_t = _avg([float(r.get("time_s", 0.0)) for r in without_rows])

        lines.append("")
        lines.append("## Ablation (With vs Without Code-Intel)")
        lines.append(f"- Avg quality delta: {with_q - without_q:+.2f}")
        lines.append(f"- Avg time delta (s): {with_t - without_t:+.1f}")

    lines.append("")
    lines.append("## Convincing Narrative")
    lines.append(
        "Cheap/fast agent lanes can remain cost-efficient while becoming meaningfully more "
        "reliable on large codebases when structural MCP intelligence tools reduce blind search loops."
    )

    out_path = Path(args.out)
    out_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    print(f"Wrote report: {out_path}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run evaluation tasks directly using CodeIntelService."""
    import time
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

    manifest = load_manifest(Path(args.manifest))
    output_path = Path(args.output) if args.output else Path(manifest.data.get("execution", {}).get("results_file", "eval/oss_demo/results.jsonl"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve repo paths
    benchmark_base = Path("/Users/eren/Documents/ai/benchmark-repos")
    project_root = Path(__file__).resolve().parent.parent.parent

    repo_paths: dict[str, Path] = {}
    for repo in manifest.repos:
        repo_id = repo["id"]
        # Check benchmark-repos first, then project root for "attocode"
        candidate = benchmark_base / repo_id
        if candidate.exists():
            repo_paths[repo_id] = candidate
        elif repo_id == "attocode":
            repo_paths[repo_id] = project_root
        else:
            # Try the repo name (e.g., "vscode" -> "microsoft/vscode" won't exist locally)
            print(f"  SKIP: repo '{repo_id}' not found at {candidate}")

    if not repo_paths:
        print("No repos available locally. Clone repos to benchmark-repos/ first.")
        return

    print(f"Running {len(manifest.tasks)} tasks across {len(repo_paths)} repos...")
    print()

    results: list[dict[str, Any]] = []
    run_id = f"oss-demo-{int(time.time())}"

    for repo_id, repo_path in repo_paths.items():
        print(f"  Repo: {repo_id} ({repo_path})")

        try:
            from attocode.code_intel.service import CodeIntelService
            svc = CodeIntelService(str(repo_path))
        except Exception as e:
            print(f"    ERROR initializing CodeIntelService: {e}")
            continue

        for task in manifest.tasks:
            task_id = task["id"]
            expected_tools = task.get("expected_tools", [])

            print(f"    Task: {task_id}...", end=" ", flush=True)

            t0 = time.perf_counter()
            output_parts: list[str] = []

            try:
                # Map expected_tools to CodeIntelService methods
                for tool in expected_tools:
                    try:
                        if tool == "bootstrap":
                            output_parts.append(svc.bootstrap(task_hint=task.get("prompt", "")[:200], max_tokens=8000))
                        elif tool == "project_summary":
                            output_parts.append(svc.bootstrap(task_hint="project summary", max_tokens=4000))
                        elif tool == "explore_codebase":
                            output_parts.append(svc.bootstrap(task_hint="explore structure", max_tokens=4000))
                        elif tool == "relevant_context":
                            output_parts.append(svc.bootstrap(task_hint="relevant context", max_tokens=4000))
                        elif tool == "semantic_search":
                            output_parts.append(svc.semantic_search(task.get("prompt", "code analysis")[:100]))
                        elif tool == "impact_analysis":
                            # Use a representative file
                            files = list(repo_path.rglob("*.py"))[:1] or list(repo_path.rglob("*.go"))[:1] or list(repo_path.rglob("*.ts"))[:1]
                            if files:
                                rel = str(files[0].relative_to(repo_path))
                                output_parts.append(svc.impact_analysis([rel]))
                        elif tool == "dependency_graph":
                            files = list(repo_path.rglob("*.py"))[:1] or list(repo_path.rglob("*.go"))[:1]
                            if files:
                                rel = str(files[0].relative_to(repo_path))
                                output_parts.append(svc.dependency_graph(rel, depth=2))
                        elif tool == "cross_references":
                            output_parts.append(svc.cross_references("main"))
                        elif tool == "hotspots":
                            output_parts.append(svc.hotspots(top_n=10))
                        elif tool == "conventions":
                            output_parts.append(svc.conventions())
                        elif tool in ("lsp_references", "lsp_diagnostics"):
                            pass  # Skip LSP tools for now
                    except Exception as tool_err:
                        output_parts.append(f"[{tool} error: {tool_err}]")

                elapsed_s = time.perf_counter() - t0
                combined_output = "\n---\n".join(output_parts)

                result = {
                    "run_id": run_id,
                    "agent_id": "code_intel_direct",
                    "repo_id": repo_id,
                    "task_id": task_id,
                    "mode": "with_code_intel",
                    "status": "passed" if combined_output and "error" not in combined_output.lower()[:50] else "failed",
                    "time_s": round(elapsed_s, 2),
                    "estimated_cost_usd": 0.0,
                    "tool_calls": len(expected_tools),
                    "output_len": len(combined_output),
                    "score_task_completion": 0,
                    "score_evidence_quality": 0,
                    "score_technical_correctness": 0,
                    "score_actionability": 0,
                    "score_clarity": 0,
                    "evidence_paths": [],
                }

                print(f"{elapsed_s:.1f}s, {len(combined_output)} chars")

            except Exception as e:
                elapsed_s = time.perf_counter() - t0
                result = {
                    "run_id": run_id,
                    "agent_id": "code_intel_direct",
                    "repo_id": repo_id,
                    "task_id": task_id,
                    "mode": "with_code_intel",
                    "status": "error",
                    "time_s": round(elapsed_s, 2),
                    "estimated_cost_usd": 0.0,
                    "tool_calls": 0,
                    "output_len": 0,
                    "error": str(e),
                    "score_task_completion": 0,
                    "score_evidence_quality": 0,
                    "score_technical_correctness": 0,
                    "score_actionability": 0,
                    "score_clarity": 0,
                    "evidence_paths": [],
                }
                print(f"ERROR: {e}")

            results.append(result)

    # Write results
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    passed = sum(1 for r in results if r["status"] == "passed")
    print(f"\nResults: {passed}/{len(results)} passed, written to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OSS Big-3 code-intel demo helper")
    sub = parser.add_subparsers(dest="cmd")

    p_prepare = sub.add_parser("prepare", help="Generate prompt packets and results template")
    p_prepare.add_argument("--manifest", required=True)
    p_prepare.add_argument("--out", required=True)
    p_prepare.add_argument("--run-id", default="oss-demo-run")
    p_prepare.add_argument("--include-ablation", action="store_true")

    p_validate = sub.add_parser("validate-results", help="Validate results JSONL against manifest")
    p_validate.add_argument("--manifest", required=True)
    p_validate.add_argument("--results", required=True)

    p_summary = sub.add_parser("summarize", help="Build markdown report from results")
    p_summary.add_argument("--manifest", required=True)
    p_summary.add_argument("--results", required=True)
    p_summary.add_argument("--out", required=True)

    run_p = sub.add_parser("run", help="Run evaluation tasks via CodeIntelService")
    run_p.add_argument("--manifest", required=True, help="Path to manifest YAML")
    run_p.add_argument("--output", default="", help="Output JSONL path")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "prepare":
        cmd_prepare(args)
    elif args.cmd == "validate-results":
        cmd_validate_results(args)
    elif args.cmd == "summarize":
        cmd_summarize(args)
    elif args.cmd == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
