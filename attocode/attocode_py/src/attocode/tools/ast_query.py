"""AST Query Tool — exposes shared AST index to agents.

Registered as ``codebase_ast_query`` so swarm workers and external agents
can query the shared AST index via the tool registry.
"""

from __future__ import annotations

import json
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


def create_ast_query_tool(ast_service: Any) -> Tool:
    """Create the codebase_ast_query tool bound to an ASTService.

    Args:
        ast_service: ASTService instance.

    Returns:
        A Tool for the LLM to query the AST index.
    """

    async def _execute(args: dict[str, Any]) -> Any:
        action = args.get("action", "")

        if action == "symbols":
            file_path = args.get("file", "")
            if not file_path:
                return "Error: 'file' parameter required for 'symbols' action"
            locations = ast_service.get_file_symbols(file_path)
            return "\n".join(
                f"{loc.kind} {loc.qualified_name} ({loc.file_path}:{loc.start_line}-{loc.end_line})"
                for loc in locations
            ) or "No symbols found"

        elif action == "cross_refs":
            symbol = args.get("symbol", "")
            if not symbol:
                return "Error: 'symbol' parameter required for 'cross_refs' action"
            refs = ast_service.get_callers(symbol)
            return "\n".join(
                f"{ref.ref_kind} in {ref.file_path}:{ref.line}"
                for ref in refs
            ) or "No references found"

        elif action == "impact":
            files_str = args.get("files", "")
            if not files_str:
                return "Error: 'files' parameter required for 'impact' action"
            files = [f.strip() for f in files_str.split(",") if f.strip()]
            impact = ast_service.get_impact(files)
            return "\n".join(sorted(impact)) or "No transitive impact"

        elif action == "search":
            query = args.get("query", "")
            if not query:
                return "Error: 'query' parameter required for 'search' action"
            locations = ast_service.find_symbol(query)
            return "\n".join(
                f"{loc.kind} {loc.qualified_name} ({loc.file_path}:{loc.start_line})"
                for loc in locations
            ) or "No matching symbols"

        elif action == "file_tree":
            cache = getattr(ast_service, "_ast_cache", {})
            index = getattr(ast_service, "_index", None)
            lines = []
            for rel_path in sorted(cache.keys()):
                sym_count = len(index.file_symbols.get(rel_path, set())) if index else 0
                lines.append(f"{rel_path} ({sym_count} symbols)")
            return "\n".join(lines) or "No files indexed"

        elif action == "dependencies":
            file_path = args.get("file", "")
            if not file_path:
                return "Error: 'file' parameter required for 'dependencies' action"
            deps = ast_service.get_dependencies(file_path)
            return "\n".join(sorted(deps)) or "No dependencies found"

        elif action == "dependents":
            file_path = args.get("file", "")
            if not file_path:
                return "Error: 'file' parameter required for 'dependents' action"
            dependents = ast_service.get_dependents(file_path)
            return "\n".join(sorted(dependents)) or "No dependents found"

        elif action == "conflicts":
            a_files_str = args.get("a_files", "")
            b_files_str = args.get("b_files", "")
            if not a_files_str or not b_files_str:
                return "Error: 'a_files' and 'b_files' parameters required for 'conflicts' action"
            a_files = [f.strip() for f in a_files_str.split(",") if f.strip()]
            b_files = [f.strip() for f in b_files_str.split(",") if f.strip()]
            conflicts = ast_service.detect_conflicts(a_files, b_files)
            if not conflicts:
                return "No conflicts detected"
            return json.dumps(conflicts, indent=2)

        else:
            return (
                f"Error: Unknown action '{action}'. "
                "Available: symbols, cross_refs, impact, search, file_tree, "
                "dependencies, dependents, conflicts"
            )

    return Tool(
        spec=ToolSpec(
            name="codebase_ast_query",
            description=(
                "Query the shared AST index for structural code intelligence. "
                "Use this to understand code structure, find symbol definitions, "
                "trace cross-references, and analyze change impact WITHOUT reading "
                "the actual file contents.\n"
                "\n"
                "Actions:\n"
                "- 'symbols': List all symbols in a file (functions, classes, methods)\n"
                "- 'cross_refs': Find all call sites / references for a symbol\n"
                "- 'impact': Compute transitive impact set for changed files\n"
                "- 'search': Find symbol definitions by name (exact or suffix match)\n"
                "- 'file_tree': List all indexed files with symbol counts\n"
                "- 'dependencies': Files that a given file imports from\n"
                "- 'dependents': Files that import a given file\n"
                "- 'conflicts': Detect potential conflicts between two parallel task file sets"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "symbols", "cross_refs", "impact", "search",
                            "file_tree", "dependencies", "dependents", "conflicts",
                        ],
                        "description": "The query action to perform.",
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "File path (relative to repo root). "
                            "Used by: symbols, dependencies, dependents."
                        ),
                    },
                    "symbol": {
                        "type": "string",
                        "description": (
                            "Symbol name to look up. Used by: cross_refs."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query for fuzzy symbol search. Used by: search."
                        ),
                    },
                    "files": {
                        "type": "string",
                        "description": (
                            "Comma-separated file paths for impact analysis. Used by: impact."
                        ),
                    },
                    "a_files": {
                        "type": "string",
                        "description": (
                            "Comma-separated file set A for conflict detection. Used by: conflicts."
                        ),
                    },
                    "b_files": {
                        "type": "string",
                        "description": (
                            "Comma-separated file set B for conflict detection. Used by: conflicts."
                        ),
                    },
                },
                "required": ["action"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_execute,
        tags=["codebase", "ast", "context"],
    )
