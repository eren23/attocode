"""Generic MCP client runner for code-intel-bench.

Connects to any MCP server via stdio, discovers tools, and executes
benchmark tasks. Does NOT import any attocode internal code — pure
MCP protocol for fairness.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from eval.mcp_bench.schema import (
    BenchConfig,
    BenchSuiteResult,
    BenchTask,
    ToolCallRecord,
    TaskResult,
)
from eval.mcp_bench.scoring import score_task

logger = logging.getLogger(__name__)


def _load_adapter(name: str):
    """Load a tool adapter by name."""
    if name == "attocode":
        from eval.mcp_bench.adapters.attocode import AttocodeAdapter
        return AttocodeAdapter()
    elif name == "ripgrep":
        from eval.mcp_bench.adapters.ripgrep import RipgrepAdapter
        return RipgrepAdapter()
    elif name == "ast_grep":
        from eval.mcp_bench.adapters.ast_grep import AstGrepAdapter
        return AstGrepAdapter()
    else:
        raise ValueError(f"Unknown adapter: {name}")


def _load_tasks(
    categories_filter: list[str] | None = None,
    repos_filter: list[str] | None = None,
) -> list[BenchTask]:
    """Load benchmark tasks from YAML files in tasks/ directory."""
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML required: pip install pyyaml")
        return []

    tasks_dir = Path(__file__).parent / "tasks"
    if not tasks_dir.is_dir():
        return []

    tasks: list[BenchTask] = []
    for yaml_file in sorted(tasks_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "tasks" not in data:
                continue
            for item in data["tasks"]:
                task = BenchTask(
                    task_id=str(item["task_id"]),
                    category=str(item["category"]),
                    repo=str(item["repo"]),
                    query=str(item.get("query", "")),
                    tools_required=list(item.get("tools_required", [])),
                    ground_truth=dict(item.get("ground_truth", {})),
                    difficulty=str(item.get("difficulty", "medium")),
                    scoring_rubric=dict(item.get("scoring_rubric", {})),
                    target_symbol=str(item.get("target_symbol", "")),
                    target_file=str(item.get("target_file", "")),
                    search_query=str(item.get("search_query", "")),
                )
                # Apply filters
                if categories_filter and task.category not in categories_filter:
                    continue
                if repos_filter and task.repo not in repos_filter:
                    continue
                tasks.append(task)
        except Exception as exc:
            logger.warning("Failed to load tasks from %s: %s", yaml_file.name, exc)

    return tasks


def _load_repos() -> dict[str, dict[str, str]]:
    """Load repos.yaml manifest."""
    try:
        import yaml
    except ImportError:
        return {}

    repos_file = Path(__file__).parent / "repos.yaml"
    if not repos_file.is_file():
        return {}

    data = yaml.safe_load(repos_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "repos" not in data:
        return {}

    return {
        r["name"]: r
        for r in data["repos"]
        if isinstance(r, dict) and "name" in r
    }


# ---------------------------------------------------------------------------
# Synchronous runner (no MCP SDK dependency — calls tools directly)
# ---------------------------------------------------------------------------


def run_task_direct(
    task: BenchTask,
    adapter,
    repo_dir: str,
    *,
    timeout: float = 60.0,
) -> TaskResult:
    """Run a single task by calling the adapter and scoring output.

    This is a direct-call runner that works without an MCP connection.
    It calls the adapter to get tool call specs, then for the attocode
    adapter, imports and calls the service directly. For other adapters,
    this would need the MCP SDK.
    """
    tool_calls_spec = adapter.map_task_to_tool_calls(task, repo_dir)

    if not tool_calls_spec:
        return TaskResult(
            task_id=task.task_id,
            category=task.category,
            repo=task.repo,
            error="No tool calls mapped for this category with this adapter",
        )

    all_output: list[str] = []
    tool_records: list[ToolCallRecord] = []

    for tool_name, args in tool_calls_spec:
        start = time.monotonic()
        try:
            output = _call_tool_direct(tool_name, args, repo_dir)
            elapsed = (time.monotonic() - start) * 1000
            tool_records.append(ToolCallRecord(
                tool_name=tool_name,
                arguments=args,
                result_preview=output[:500],
                latency_ms=elapsed,
            ))
            all_output.append(output)
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            tool_records.append(ToolCallRecord(
                tool_name=tool_name,
                arguments=args,
                result_preview=str(exc)[:500],
                latency_ms=elapsed,
                success=False,
            ))

    combined_output = "\n\n".join(all_output)
    total_latency = sum(r.latency_ms for r in tool_records)

    # Score the output
    result = score_task(task, combined_output)
    result.tool_calls = tool_records
    result.total_latency_ms = total_latency
    result.output_text = combined_output[:10000]  # cap stored output

    return result


def _call_tool_direct(tool_name: str, args: dict, repo_dir: str) -> str:
    """Call an attocode-code-intel tool directly (for local evaluation)."""
    # Lazy import to keep the runner generic
    try:
        from attocode.code_intel.service import CodeIntelService
    except ImportError:
        return f"[Error: CodeIntelService not available for direct call to {tool_name}]"

    svc = CodeIntelService(project_dir=repo_dir)
    method = getattr(svc, tool_name, None)
    if method is None:
        return f"[Error: Tool '{tool_name}' not found on CodeIntelService]"

    try:
        return str(method(**args))
    except Exception as exc:
        return f"[Error calling {tool_name}: {exc}]"


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------


def run_benchmark(config: BenchConfig) -> BenchSuiteResult:
    """Run the full benchmark suite.

    Args:
        config: Benchmark configuration.

    Returns:
        BenchSuiteResult with per-task results and aggregates.
    """
    adapter = _load_adapter(config.adapter)
    tasks = _load_tasks(
        categories_filter=config.categories_filter or None,
        repos_filter=config.repos_filter or None,
    )

    if not tasks:
        logger.warning("No tasks to run")
        return BenchSuiteResult(config=config)

    repos = _load_repos()
    # Determine repo directories
    import os
    repos_base = os.environ.get("BENCHMARK_REPOS_DIR", "")

    suite = BenchSuiteResult(config=config)

    for task in tasks:
        repo_info = repos.get(task.repo, {})
        repo_dir = repo_info.get("local_path", "")
        if not repo_dir and repos_base:
            repo_dir = os.path.join(repos_base, task.repo)
        if not repo_dir or not os.path.isdir(repo_dir):
            suite.task_results.append(TaskResult(
                task_id=task.task_id,
                category=task.category,
                repo=task.repo,
                error=f"Repo directory not found: {repo_dir or task.repo}",
            ))
            continue

        logger.info("Running %s on %s...", task.task_id, task.repo)
        result = run_task_direct(
            task, adapter, repo_dir, timeout=config.timeout_per_task,
        )
        suite.task_results.append(result)

    suite.compute_aggregates()
    return suite
