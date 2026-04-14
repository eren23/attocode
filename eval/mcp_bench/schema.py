"""Data models for code-intel-bench.

All benchmark data flows through these dataclasses:
RepoSpec → BenchTask → (mcp_runner) → TaskResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RepoSpec:
    """A repository used in the benchmark, pinned at a specific commit."""

    name: str
    url: str  # GitHub clone URL
    commit: str  # pinned SHA for reproducibility
    language: str  # primary language
    size_mb: int = 0  # approximate, for CI planning


@dataclass(slots=True)
class BenchTask:
    """A single benchmark task to evaluate a code intelligence tool."""

    task_id: str  # e.g. "orientation-fastapi-001"
    category: str  # orientation|symbol_search|semantic_search|...
    repo: str  # repo name from repos.yaml
    query: str  # natural-language intent or specific symbol/file
    tools_required: list[str] = field(default_factory=list)  # MCP tool names
    ground_truth: dict[str, Any] = field(default_factory=dict)
    difficulty: str = "medium"  # easy|medium|hard
    scoring_rubric: dict[str, float] = field(default_factory=dict)

    # Optional task-specific fields
    target_symbol: str = ""  # for symbol_search tasks
    target_file: str = ""  # for dependency/navigation tasks
    search_query: str = ""  # for semantic_search tasks


@dataclass(slots=True)
class ToolCallRecord:
    """Record of a single MCP tool call during task execution."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_preview: str = ""  # first 500 chars
    latency_ms: float = 0.0
    success: bool = True


@dataclass(slots=True)
class TaskResult:
    """Result of running a single benchmark task."""

    task_id: str
    category: str = ""
    repo: str = ""
    score: float = 0.0  # 0.0-5.0 final weighted score
    deterministic_score: float = 0.0
    llm_judge_score: float | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    total_latency_ms: float = 0.0
    output_text: str = ""  # full tool output
    ground_truth_match: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(slots=True)
class BenchConfig:
    """Configuration for a benchmark run."""

    server_command: list[str] = field(default_factory=list)
    adapter: str = "attocode"  # attocode|ripgrep|ast_grep
    repos_filter: list[str] = field(default_factory=list)  # empty = all
    categories_filter: list[str] = field(default_factory=list)  # empty = all
    timeout_per_task: float = 60.0  # seconds
    use_llm_judge: bool = False
    output_path: str = ""


@dataclass(slots=True)
class BenchSuiteResult:
    """Aggregated results from a full benchmark run."""

    config: BenchConfig = field(default_factory=BenchConfig)
    task_results: list[TaskResult] = field(default_factory=list)
    total_tasks: int = 0
    completed_tasks: int = 0
    errored_tasks: int = 0
    mean_score: float = 0.0
    median_score: float = 0.0
    mean_latency_ms: float = 0.0
    per_category: dict[str, dict[str, float]] = field(default_factory=dict)

    def compute_aggregates(self) -> None:
        """Compute aggregate metrics from task results."""
        if not self.task_results:
            return

        self.total_tasks = len(self.task_results)
        scores = [r.score for r in self.task_results if not r.error]
        self.completed_tasks = len(scores)
        self.errored_tasks = self.total_tasks - self.completed_tasks

        if scores:
            self.mean_score = sum(scores) / len(scores)
            sorted_scores = sorted(scores)
            mid = len(sorted_scores) // 2
            self.median_score = (
                sorted_scores[mid] if len(sorted_scores) % 2
                else (sorted_scores[mid - 1] + sorted_scores[mid]) / 2
            )

        latencies = [r.total_latency_ms for r in self.task_results if not r.error]
        if latencies:
            self.mean_latency_ms = sum(latencies) / len(latencies)

        # Per-category breakdown
        by_cat: dict[str, list[float]] = {}
        for r in self.task_results:
            if not r.error:
                by_cat.setdefault(r.category, []).append(r.score)

        for cat, cat_scores in by_cat.items():
            self.per_category[cat] = {
                "mean_score": sum(cat_scores) / len(cat_scores),
                "count": len(cat_scores),
                "perfect": sum(1 for s in cat_scores if s >= 4.5),
            }
