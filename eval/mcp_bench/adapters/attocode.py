"""attocode-code-intel adapter — full coverage of all task categories."""

from __future__ import annotations

from dataclasses import dataclass, field

from eval.mcp_bench.schema import BenchTask


@dataclass
class AttocodeAdapter:
    """Maps benchmark tasks to attocode-code-intel MCP tools."""

    name: str = "attocode-code-intel"
    server_command: list[str] = field(
        default_factory=lambda: ["uvx", "attocode-code-intel"],
    )

    def map_task_to_tool_calls(
        self, task: BenchTask, repo_dir: str,
    ) -> list[tuple[str, dict]]:
        category = task.category
        calls: list[tuple[str, dict]] = []

        if category == "orientation":
            calls.append(("project_summary", {}))

        elif category == "symbol_search":
            name = task.target_symbol or task.query
            calls.append(("search_symbols", {"name": name}))
            calls.append(("cross_references", {"symbol_name": name}))

        elif category == "semantic_search":
            calls.append(("semantic_search", {
                "query": task.search_query or task.query,
            }))

        elif category == "dependency_tracing":
            path = task.target_file or task.query
            calls.append(("dependencies", {"path": path}))

        elif category == "impact_analysis":
            target = task.target_file or task.target_symbol or task.query
            calls.append(("impact_analysis", {
                "changed_files": [target],
            }))

        elif category == "architecture":
            calls.append(("community_detection", {}))
            calls.append(("hotspots", {}))

        elif category == "security_scanning":
            calls.append(("analyze", {"category": "security"}))
            calls.append(("security_scan", {}))

        elif category == "dead_code":
            calls.append(("dead_code", {}))

        return calls
