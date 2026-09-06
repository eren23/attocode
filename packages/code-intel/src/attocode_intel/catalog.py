"""One catalog for protocol schemas, profiles, and documentation."""

from __future__ import annotations

from copy import deepcopy

from mcp.types import Tool, ToolAnnotations

INSTRUCTIONS = (
    "Use Attocode Intelligence to understand the selected codebase. Start unfamiliar tasks with "
    "bootstrap(task_hint=...). Locate code with search_symbols or semantic_search; inspect relevant_context "
    "and cross_references before changes. Use impact_analysis and suggest_tests to select verification. "
    "Check source, revision, and coverage; incomplete indexes are not proof of no dependencies. "
    "After edits notify_file_changed. Keep uncommitted code local."
)
DAILY = frozenset(
    {
        "bootstrap",
        "project_summary",
        "explore_codebase",
        "search_symbols",
        "semantic_search",
        "fast_search",
        "symbols",
        "relevant_context",
        "cross_references",
        "dependencies",
        "call_graph",
        "impact_analysis",
        "suggest_tests",
        "review_change",
        "notify_file_changed",
        "hydration_status",
        "recall",
        "record_learning",
        "list_learnings",
        "learning_feedback",
    }
)
WRITES = frozenset(
    [
        "notify_file_changed",
        "record_adr",
        "update_adr_status",
        "pin_current",
        "pin_delete",
        "track_file_access",
        "clear_frecency",
        "record_learning",
        "learning_feedback",
        "update_learning",
        "reindex",
        "track_query_result",
        "clear_query_history",
        "migrate_cache",
        "clear_symbols",
        "clear_embeddings",
        "clear_trigrams",
        "clear_kw_index",
        "clear_learnings",
        "clear_adrs",
        "clear_all",
        "cas_clear",
        "export_learnings",
        "import_learnings",
        "export_adrs_markdown",
        "import_adrs_markdown",
        "gc_run",
        "embeddings_rotate_start",
        "embeddings_rotate_step",
        "embeddings_rotate_cutover",
        "embeddings_rotate_gc_old",
        "embeddings_rotate_abort",
        "snapshot_create",
        "snapshot_delete",
        "snapshot_restore",
        "overlay_create",
        "overlay_activate",
        "overlay_delete",
        "install_pack",
        "register_rule",
        "rule_feedback",
        "evolve_rules",
        "synthesize_rule",
        "rule_hygiene",
        "install_community_pack",
        "import_rules",
    ]
)
REMOTE_WRITES = frozenset(
    {"record_learning", "learning_feedback", "record_adr", "update_adr_status", "update_learning"}
)


def remote_available(name):
    return not is_write(name) or name in REMOTE_WRITES


def registered_tools():
    from attocode_intel.server import mcp

    return mcp._tool_manager._tools


def is_write(name: str) -> bool:
    return name in WRITES


def tool_catalog(profile: str = "full", *, remote: bool = False) -> list[Tool]:
    if profile not in ("daily", "full"):
        raise ValueError("profile must be daily or full")
    result = []
    for name, tool in registered_tools().items():
        if profile == "daily" and name not in DAILY:
            continue
        if remote and not remote_available(name):
            continue
        schema = deepcopy(tool.parameters)
        schema.setdefault("properties", {}).update(
            {
                "workspace": {
                    "type": "string",
                    "description": "Local project path or authorized remote repository ID.",
                },
                "revision": {
                    "type": "string",
                    "description": "Remote branch or commit; omitted uses the default branch.",
                },
            }
        )
        schema["properties"]["max_tokens"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 32000,
            "default": 8000,
            "description": "Maximum tokens in the complete readable response, including provenance.",
        }
        result.append(
            Tool(
                name=name,
                description=tool.description,
                inputSchema=schema,
                annotations=ToolAnnotations(
                    readOnlyHint=not is_write(name),
                    destructiveHint=name.startswith(("clear_", "delete_"))
                    or name
                    in {"snapshot_delete", "snapshot_restore", "overlay_delete", "pin_delete"},
                ),
            )
        )
    result.extend(
        [
            Tool(
                name="update_learning",
                description="Edit or archive a repository learning.",
                inputSchema={
                    "type": "object",
                    "required": ["learning_id"],
                    "properties": {
                        "learning_id": {"type": "integer"},
                        "description": {"type": "string"},
                        "details": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "archived"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "workspace": {"type": "string"},
                        "revision": {"type": "string"},
                    },
                },
                annotations=ToolAnnotations(readOnlyHint=False),
            ),
            Tool(
                name="cross_repo_search",
                description="Search explicitly selected authorized repositories; results retain repository and commit provenance.",
                inputSchema={
                    "type": "object",
                    "required": ["query", "workspaces"],
                    "properties": {
                        "query": {"type": "string"},
                        "workspaces": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
                annotations=ToolAnnotations(readOnlyHint=True),
            ),
        ]
    )
    result.append(
        Tool(
            name="capabilities",
            description="Available tools, profiles, workspace selection, and optional enhancements.",
            inputSchema={
                "type": "object",
                "properties": {"workspace": {"type": "string"}, "revision": {"type": "string"}},
            },
            annotations=ToolAnnotations(readOnlyHint=True),
        )
    )
    return result
