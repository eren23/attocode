"""Slash commands for the TUI interactive mode.

Provides ~55 slash commands organized into groups:
- Core: /help, /status, /budget, /model, /compact, /save, /clear, /quit
- Session: /sessions, /load, /resume, /checkpoint, /checkpoints, /reset, /handoff
- Mode: /mode, /plan, /show-plan, /approve, /reject
- Agent: /agents, /spawn, /find, /suggest, /auto
- Thread: /fork, /threads, /switch, /tree, /rollback, /restore
- Goals: /goals
- MCP: /mcp
- Skills: /skills
- Swarm: /swarm (init/start/status/stop/dashboard/config)
- Context: /context, /repomap
- Debug: /trace, /grants, /audit
- Capabilities: /powers
- Info: /sandbox, /lsp, /tui
- Config: /init, /theme, /config, /setup
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    """Result of a slash command."""

    output: str
    handled: bool = True


def is_command(text: str) -> bool:
    """Check if text is a slash command."""
    return text.strip().startswith("/")


# ============================================================
# Helpers: get infrastructure instances
# ============================================================

def _get_ctx(agent: Any) -> Any:
    return getattr(agent, "context", None) if agent else None


def _feature_unavailable(name: str, enable_hint: str = "") -> CommandResult:
    """Return a consistent 'feature not available' message."""
    msg = f"{name} is not available."
    if enable_hint:
        msg += f" Enable with: {enable_hint}"
    return CommandResult(output=msg)


async def _get_or_init_session_store(agent: Any) -> Any:
    """Get session store from context/agent or lazily initialize via agent."""
    ctx = _get_ctx(agent)
    if ctx and getattr(ctx, "session_store", None):
        return ctx.session_store

    store = getattr(agent, "session_store", None) if agent else None
    if store:
        return store

    if agent and hasattr(agent, "ensure_session_store"):
        try:
            return await agent.ensure_session_store()
        except Exception:
            return None
    return None


def _get_working_dir(agent: Any) -> str:
    ctx = _get_ctx(agent)
    wd = getattr(ctx, "working_dir", None) if ctx else None
    return wd or getattr(agent, "_working_dir", "") or ""


def _get_project_root(agent: Any) -> str:
    ctx = _get_ctx(agent)
    project_root = getattr(ctx, "project_root", None) if ctx else None
    return project_root or getattr(agent, "_project_root", "") or _get_working_dir(agent)


def _get_skill_loader(agent: Any) -> Any:
    """Create and load a SkillLoader for the agent's resolved project root."""
    from attocode.integrations.skills.loader import SkillLoader
    project_root = _get_project_root(agent)
    if not project_root:
        return None
    loader = SkillLoader(project_root)
    loader.load()
    return loader


def _get_agent_registry(agent: Any) -> Any:
    """Create and load an AgentRegistry for the agent's resolved project root."""
    from attocode.integrations.agents.registry import AgentRegistry
    project_root = _get_project_root(agent)
    registry = AgentRegistry(project_root or None)
    registry.load()
    return registry


# ============================================================
# Command router
# ============================================================

async def handle_command(
    text: str,
    *,
    agent: Any = None,
    app: Any = None,
) -> CommandResult:
    """Handle a slash command.

    Routes to the appropriate handler based on command prefix.
    """
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # Bootstrap lightweight context so command features work before first prompt.
    if agent and not getattr(agent, "context", None) and hasattr(agent, "ensure_command_context"):
        try:
            await agent.ensure_command_context()
        except Exception:
            pass

    # --- Core commands ---
    if cmd in ("/help", "/h", "/?"):
        return CommandResult(output=_help_text())

    if cmd == "/status":
        return _status_command(agent)

    if cmd == "/budget":
        return _budget_command(agent)

    if cmd in ("/extend",):
        return await _extend_budget_command(agent, arg)

    if cmd == "/model":
        return _model_command(agent, arg)

    if cmd == "/compact":
        return await _compact_command(agent)

    if cmd == "/save":
        return await _save_command(agent)

    if cmd in ("/clear", "/cls"):
        if app:
            app.action_clear_screen()
        if agent and hasattr(agent, "reset_conversation"):
            agent.reset_conversation()
        return CommandResult(output="Screen and conversation history cleared.")

    if cmd in ("/quit", "/exit", "/q"):
        if app:
            app.exit()
        return CommandResult(output="Goodbye.")

    # --- Session commands ---
    if cmd == "/sessions":
        return await _sessions_command(agent, arg)

    if cmd == "/load":
        return await _load_command(agent, arg)

    if cmd == "/resume":
        return await _resume_command(agent, arg)

    if cmd == "/checkpoint":
        return await _checkpoint_command(agent)

    if cmd == "/checkpoints":
        return await _checkpoints_command(agent, arg)

    if cmd == "/reset":
        return _reset_command(agent)

    if cmd == "/handoff":
        return _handoff_command(agent, arg)

    if cmd == "/export":
        return _export_command(agent, arg)

    # --- Mode commands ---
    if cmd == "/mode":
        return _mode_command(agent, arg)

    if cmd in ("/code", "/architect", "/ask", "/orchestrate"):
        return _mode_command(agent, cmd[1:])

    if cmd == "/plan":
        return _plan_command(agent, arg, app=app)

    if cmd == "/show-plan":
        return _show_plan_command(agent)

    if cmd in ("/approve",):
        return _approve_command(agent, arg)

    if cmd in ("/reject",):
        return _reject_command(agent, arg)

    # --- Agent commands ---
    if cmd == "/agents":
        return _agents_command(agent, arg)

    if cmd == "/spawn":
        return await _spawn_command(agent, arg)

    if cmd == "/find":
        return _find_command(agent, arg)

    if cmd == "/suggest":
        return _suggest_command(agent, arg)

    if cmd == "/auto":
        return _auto_command(agent, arg)

    # --- Thread commands ---
    if cmd == "/fork":
        return _fork_command(agent, arg)

    if cmd == "/threads":
        return _threads_command(agent)

    if cmd == "/switch":
        return _switch_command(agent, arg)

    if cmd == "/tree":
        return _tree_command(agent)

    if cmd == "/rollback":
        return _rollback_command(agent, arg)

    if cmd == "/restore":
        return await _restore_command(agent, arg)

    # --- Goals ---
    if cmd == "/goals":
        return await _goals_command(agent, arg)

    # --- MCP commands ---
    if cmd == "/mcp":
        return await _mcp_command(agent, arg)

    # --- Skills commands ---
    if cmd == "/skills":
        return _skills_command(agent, arg)

    # --- Context commands ---
    if cmd == "/context":
        return _context_command(agent, arg)

    if cmd == "/repomap":
        return _repomap_command(agent, arg)

    # --- Graph visualization commands ---
    if cmd == "/deps":
        return _deps_command(agent, arg, app=app)

    if cmd == "/impact":
        return _impact_command(agent, arg, app=app)

    if cmd == "/graph":
        return _graph_command(agent, app=app)

    # --- Debug commands ---
    if cmd == "/trace":
        return _trace_command(agent, arg)

    if cmd == "/grants":
        return await _grants_command(agent)

    if cmd == "/audit":
        return await _audit_command(agent)

    if cmd == "/tasks":
        return _tasks_command(app)

    if cmd == "/debug":
        return _debug_command(app)

    if cmd == "/undo":
        return _undo_command(agent, arg)

    if cmd == "/diff":
        return _diff_command(agent, arg)

    # --- Capabilities ---
    if cmd == "/powers":
        return _powers_command(agent, arg)

    # --- Info commands ---
    if cmd == "/sandbox":
        return _sandbox_command(agent)

    if cmd == "/lsp":
        return _lsp_command(agent)

    if cmd == "/tui":
        return _tui_command()

    if cmd == "/dashboard":
        return _dashboard_command(app)

    if cmd == "/swarm":
        return await _swarm_command(agent, arg, app)

    if cmd == "/swarm-monitor":
        return _swarm_monitor_command(app, arg)

    # --- Config commands ---
    if cmd == "/init":
        return await _init_command(agent)

    if cmd == "/theme":
        return _theme_command(app, arg)

    if cmd == "/config":
        return await _config_command(agent, arg, app)

    if cmd == "/setup":
        return await _setup_command(agent, app)

    # --- New feature commands ---
    if cmd == "/define-tool":
        return _define_tool_command(agent, arg)

    if cmd == "/scaffold-mcp":
        return _scaffold_mcp_command(agent, arg)

    if cmd == "/parallel":
        return _parallel_command(agent, arg)

    if cmd == "/bugfind":
        return _bugfind_command(agent, arg)

    if cmd in ("/orchestrate", "/orch"):
        return _orchestrate_command(agent, arg)

    if cmd == "/watch":
        return _watch_command(agent, arg)

    if cmd == "/project-state":
        return _project_state_command(agent, arg)

    return CommandResult(output=f"Unknown command: {cmd}. Type /help for available commands.")


# ============================================================
# Help text
# ============================================================

def _help_text() -> str:
    return (
        "Available commands:\n"
        "\n"
        "Core:\n"
        "  /help             Show this help\n"
        "  /status           Show agent status and metrics\n"
        "  /budget           Show budget usage\n"
        "  /extend [amount]  Request budget extension\n"
        "  /model [name]     Show or switch model\n"
        "  /compact          Force context compaction\n"
        "  /save             Save current session checkpoint\n"
        "  /clear            Clear message log\n"
        "  /quit             Exit the application\n"
        "\n"
        "Session:\n"
        "  /sessions         List recent sessions\n"
        "  /load <id>        Load a session\n"
        "  /resume [id]      Resume most recent (or specific) session\n"
        "  /checkpoint       Create a named checkpoint\n"
        "  /checkpoints [id] List checkpoints for a session\n"
        "  /reset            Reset conversation (clear messages & metrics)\n"
        "  /handoff [fmt]    Export session handoff summary (markdown)\n"
        "  /export [html|md] Export session as HTML or markdown file\n"
        "\n"
        "Mode:\n"
        "  /mode [name]      Show or switch mode (build/plan/review/debug/code/architect/ask/orchestrate)\n"
        "  /code             Switch to code mode (full access, implementation focus)\n"
        "  /architect        Switch to architect mode (read + markdown write only)\n"
        "  /ask              Switch to ask mode (read-only, Q&A focus)\n"
        "  /orchestrate      Switch to orchestrate mode (full access, delegation focus)\n"
        "  /plan [desc]      Enter plan mode (or show current plan)\n"
        "  /show-plan        Show detailed plan with pending diffs\n"
        "  /approve [n|all]  Approve proposed change(s)\n"
        "  /reject [n|all]   Reject proposed change(s)\n"
        "\n"
        "Agent:\n"
        "  /agents [subcmd]  List or manage agents (list/info/new/edit/reload)\n"
        "  /spawn [--model <model>] <task>\n"
        "  /find <query>     Search agents by keyword\n"
        "  /suggest <task>   Suggest best agent for a task\n"
        "  /auto <task>      Auto-select and confirm agent for a task\n"
        "\n"
        "Threads:\n"
        "  /fork [label]     Fork conversation into a new thread\n"
        "  /threads          List all conversation threads\n"
        "  /switch <id>      Switch to a different thread\n"
        "  /tree             Show thread/fork tree visualization\n"
        "  /rollback [n]     Remove last N messages (default: 1 turn)\n"
        "  /restore <id>     Restore from a checkpoint\n"
        "\n"
        "Goals:\n"
        "  /goals [subcmd]   Manage goals (list/add/done/all)\n"
        "\n"
        "Tools:\n"
        "  /mcp [subcmd]     MCP management (list/tools/connect/disconnect/search/stats)\n"
        "  /skills [subcmd]  Skill management (list/info/new/edit/enable/disable/reload)\n"
        "  /define-tool      List dynamic tools (or describe one to create)\n"
        "  /scaffold-mcp <n> Scaffold a local MCP server\n"
        "  /undo [path]      Undo last file change (or specific file)\n"
        "  /diff             Show recent file changes\n"
        "\n"
        "Context:\n"
        "  /context [sub]    Show context info (breakdown for token details)\n"
        "  /repomap          Show repository tree view\n"
        "  /repomap symbols  Tree with function/class annotations\n"
        "  /repomap deps     Dependency graph stats\n"
        "  /repomap analyze  Force re-discovery (clear caches)\n"
        "\n"
        "Graph:\n"
        "  /deps <file>      Show dependency graph for a file\n"
        "  /impact <file>    Show blast radius / impact analysis\n"
        "  /graph            Show repo overview (overview/deps/impact/hotspots)\n"
        "\n"
        "Debug:\n"
        "  /trace [subcmd]   Trace inspection (summary/analyze/issues/export)\n"
        "  /grants           Show remembered permissions\n"
        "  /audit            Show recent tool call audit log\n"
        "  /tasks            Toggle tasks panel\n"
        "  /debug            Toggle debug panel\n"
        "\n"
        "Capabilities:\n"
        "  /powers [model]   Show capabilities (or model-specific caps)\n"
        "\n"
        "Swarm:\n"
        "  /swarm              Show swarm status or help\n"
        "  /swarm init         Initialize swarm config (auto-detects your model)\n"
        "  /swarm start <task> Start a swarm execution\n"
        "  /swarm status       Show running swarm state\n"
        "  /swarm stop         Cancel running swarm\n"
        "  /swarm dashboard    Open swarm dashboard (Ctrl+S)\n"
        "  /swarm config       Show swarm configuration\n"
        "\n"
        "Info:\n"
        "  /sandbox          Show sandbox configuration\n"
        "  /lsp              Show LSP integration status\n"
        "  /tui              Show TUI feature list\n"
        "  /dashboard        Open the trace analysis dashboard (Ctrl+D)\n"
        "  /swarm-monitor    Open multi-run swarm monitor (Ctrl+M)\n"
        "\n"
        "Analysis:\n"
        "  /bugfind [branch] Scan diff for potential bugs (default: main)\n"
        "  /watch            Scan for inline AI trigger comments (# AI: ...)\n"
        "  /parallel t1|t2   Spawn parallel agents in isolated worktrees\n"
        "  /project-state    Show or update file-driven project state\n"
        "\n"
        "Config:\n"
        "  /init             Initialize .attocode/ directory\n"
        "  /theme [name]     Show or switch theme\n"
        "  /config           Show current config (provider, model, key)\n"
        "  /config provider <name>  Switch provider (persists globally)\n"
        "  /config model <name>     Switch model (persists globally)\n"
        "  /config api-key          Re-enter API key (TUI dialog)\n"
        "  /config save             Persist full runtime config globally\n"
        "  /setup                   Run the first-time setup wizard"
    )


# ============================================================
# Core command handlers
# ============================================================

def _status_command(agent: Any) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    ctx = getattr(agent, "context", None)
    status = getattr(agent, "status", "unknown")

    lines = [f"Status: {status}"]

    if ctx:
        m = ctx.metrics
        lines.append(f"Iteration: {ctx.iteration}")
        lines.append(f"LLM calls: {m.llm_calls}")
        lines.append(f"Tool calls: {m.tool_calls}")
        lines.append(f"Total tokens: {m.total_tokens:,}")
        lines.append(f"Estimated cost: ${m.estimated_cost:.4f}")
        lines.append(f"Messages: {len(ctx.messages)}")

        # Mode info
        mode_mgr = getattr(ctx, "mode_manager", None)
        if mode_mgr:
            lines.append(f"Mode: {mode_mgr.mode.value}")

    return CommandResult(output="\n".join(lines))


def _budget_command(agent: Any) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    ctx = getattr(agent, "context", None)
    if not ctx:
        return CommandResult(output="No active context.")

    lines = ["Budget:"]
    budget = ctx.budget
    lines.append(f"  Max tokens: {budget.max_tokens:,}")
    lines.append(f"  Max iterations: {budget.max_iterations or 'unlimited'}")
    lines.append(f"  Max cost: ${budget.max_cost or 0:.2f}")
    lines.append(f"  Used: {ctx.metrics.total_tokens:,} tokens ({agent.get_budget_usage():.0%})")

    if ctx.economics:
        econ = ctx.economics
        lines.append(f"  Economics status: {econ.check_budget().status}")
        lines.append(f"  LLM calls: {econ.llm_calls}")

    return CommandResult(output="\n".join(lines))


async def _extend_budget_command(agent: Any, arg: str) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    try:
        amount = int(arg) if arg else 100_000
    except ValueError:
        return CommandResult(output="Usage: /extend [token_amount]")

    ctx = getattr(agent, "context", None)
    if not ctx:
        return CommandResult(output="No active context.")

    if hasattr(agent, "apply_budget_extension"):
        new_max = agent.apply_budget_extension(amount)
    else:
        # Fallback for legacy test doubles.
        ctx.budget = ctx.budget.__class__(
            max_tokens=ctx.budget.max_tokens + amount,
            max_iterations=ctx.budget.max_iterations,
            max_cost=ctx.budget.max_cost,
        )
        new_max = ctx.budget.max_tokens
    return CommandResult(output=f"Budget extended by {amount:,} tokens. New max: {new_max:,}")


def _model_command(agent: Any, arg: str) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    current_model = "unknown"
    if agent and hasattr(agent, "config"):
        current_model = agent.config.model or "default"

    if not arg:
        # Show current model + list available
        from attocode.providers.catalog import format_model_table, get_catalog
        catalog = get_catalog()
        provider = agent.config.provider if hasattr(agent, "config") else None
        entries = catalog.list_models(provider=provider, limit=15)
        table = format_model_table(entries, current_model=current_model)
        return CommandResult(
            output=f"Current model: {current_model}\n\n"
            f"Available models ({catalog.count} total, showing {provider or 'all'}):\n{table}\n\n"
            "Use /model <query> to search, /model set <model_id> to switch."
        )

    # Handle subcommands
    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower()

    if subcmd == "set" and len(parts) > 1:
        # Direct model switch
        new_model = parts[1].strip()
        if hasattr(agent, "_config"):
            agent._config.model = new_model
            return CommandResult(output=f"Switched model to: {new_model}")
        return CommandResult(output="Cannot switch model on this agent.")

    if subcmd == "list":
        # List all models (optionally filtered by provider)
        from attocode.providers.catalog import format_model_table, get_catalog
        catalog = get_catalog()
        provider_filter = parts[1].strip() if len(parts) > 1 else None
        entries = catalog.list_models(provider=provider_filter, limit=50)
        table = format_model_table(entries, current_model=current_model)
        return CommandResult(
            output=f"Models ({len(entries)} shown):\n{table}"
        )

    if subcmd == "refresh":
        from attocode.providers.catalog import get_catalog
        catalog = get_catalog()
        catalog.refresh()
        return CommandResult(output=f"Model catalog refreshed: {catalog.count} models loaded.")

    # Fuzzy search — treat entire arg as search query
    from attocode.providers.catalog import format_model_table, get_catalog
    catalog = get_catalog()
    results = catalog.search(arg, limit=10)
    if not results:
        return CommandResult(output=f"No models matching '{arg}'. Try /model list to see all.")

    table = format_model_table(results, show_score=True, current_model=current_model)

    # If there's a strong match, offer to switch
    top_entry, top_score = results[0]
    hint = ""
    if top_score > 0.8:
        hint = f"\nTop match: {top_entry.model_id} — use /model set {top_entry.model_id} to switch."

    return CommandResult(
        output=f"Search results for '{arg}':\n{table}{hint}"
    )


async def _compact_command(agent: Any) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    ctx = getattr(agent, "context", None)
    if not ctx or not ctx.compaction_manager:
        return CommandResult(output="Compaction not available.")

    check = ctx.compaction_manager.check(ctx.messages)
    return CommandResult(
        output=f"Context usage: {check.usage_fraction:.0%}\n"
        f"Status: {check.status}\n"
        f"Messages: {len(ctx.messages)}\n"
        "Use in-agent compaction to compact (triggered automatically at threshold)."
    )


async def _save_command(agent: Any) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    ctx = getattr(agent, "context", None)
    if not ctx or not ctx.session_store or not ctx.session_id:
        return CommandResult(output="Session persistence not configured.")

    try:
        messages_data = []
        for msg in ctx.messages:
            messages_data.append({
                "role": str(msg.role),
                "content": getattr(msg, "content", ""),
            })
        await ctx.session_store.save_checkpoint(
            ctx.session_id,
            messages_data,
            metrics={
                "total_tokens": ctx.metrics.total_tokens,
                "llm_calls": ctx.metrics.llm_calls,
                "tool_calls": ctx.metrics.tool_calls,
                "cost": ctx.metrics.estimated_cost,
            },
        )
        return CommandResult(output=f"Session {ctx.session_id} checkpoint saved.")
    except Exception as e:
        return CommandResult(output=f"Save failed: {e}")


# ============================================================
# Session command handlers
# ============================================================

async def _sessions_command(agent: Any, arg: str) -> CommandResult:
    store = await _get_or_init_session_store(agent)

    if not store:
        return CommandResult(output="Session persistence not configured.")

    try:
        limit = int(arg) if arg else 10
    except ValueError:
        limit = 10

    try:
        sessions = await store.list_sessions(limit=limit)
        if not sessions:
            return CommandResult(output="No sessions found.")

        lines = ["Recent sessions:"]
        for s in sessions:
            lines.append(
                f"  [{s.id}] {s.task[:60]} ({s.status}, "
                f"{s.total_tokens:,} tokens, ${s.total_cost:.4f})"
            )
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error listing sessions: {e}")


async def _load_command(agent: Any, session_id: str) -> CommandResult:
    if not session_id:
        return CommandResult(output="Usage: /load <session_id>")

    if session_id.startswith("trace-"):
        return CommandResult(
            output=(
                f"'{session_id}' is a trace session from Dashboard analysis, not a resumable DB session.\n"
                "Use /sessions to list resumable session IDs from SQLite."
            )
        )

    ctx = _get_ctx(agent)
    store = await _get_or_init_session_store(agent)

    if not store:
        return CommandResult(output="Session persistence not configured.")

    try:
        session = await store.get_session(session_id)
        if not session:
            return CommandResult(output=f"Session '{session_id}' not found.")

        checkpoint = await store.load_checkpoint(session_id)
        if not checkpoint:
            return CommandResult(output=f"No checkpoint found for session '{session_id}'.")

        if not ctx:
            if agent and hasattr(agent, "config"):
                agent.config.resume_session = session_id
                agent.config.resume_session_explicit = True
            if agent and hasattr(agent, "_conversation_messages"):
                agent._conversation_messages = []
            return CommandResult(
                output=f"Session {session_id} staged for resume: {session.task}\n"
                f"  Messages: {len(checkpoint.messages)}\n"
                "  Send your next prompt to continue this session."
            )

        return CommandResult(
            output=f"Loaded session {session_id}: {session.task}\n"
            f"  Status: {session.status}\n"
            f"  Messages: {len(checkpoint.messages)}\n"
            f"  Tokens: {session.total_tokens:,}\n"
            "  Note: Use /resume <session_id> to restore messages now."
        )
    except Exception as e:
        return CommandResult(output=f"Error loading session: {e}")


async def _resume_command(agent: Any, session_id: str) -> CommandResult:
    if not session_id:
        store = await _get_or_init_session_store(agent)
        if not store:
            return CommandResult(
                output="Usage: /resume <session_id>\n"
                "Tip: Use /sessions to see available sessions."
            )
        try:
            recent = await store.list_sessions(limit=1)
            if not recent:
                return CommandResult(output="No sessions found. Use /sessions to list available IDs.")
            session_id = recent[0].id
        except Exception as e:
            return CommandResult(output=f"Error listing sessions: {e}")

    if session_id.startswith("trace-"):
        return CommandResult(
            output=(
                f"'{session_id}' is a trace session from Dashboard analysis, not a resumable DB session.\n"
                "Use /sessions to list resumable session IDs from SQLite."
            )
        )

    ctx = _get_ctx(agent)
    store = await _get_or_init_session_store(agent)

    if not store:
        return CommandResult(
            output=f"Session resume for '{session_id}' requires restarting with:\n"
            f"  attocode --resume {session_id}"
        )

    if not ctx:
        try:
            session = await store.get_session(session_id)
            if not session:
                return CommandResult(output=f"Session '{session_id}' not found.")
            if agent and hasattr(agent, "config"):
                agent.config.resume_session = session_id
                agent.config.resume_session_explicit = True
            if agent and hasattr(agent, "_conversation_messages"):
                agent._conversation_messages = []
            return CommandResult(
                output=f"Session {session_id} staged for resume: {session.task}\n"
                "Send your next prompt to continue this session."
            )
        except Exception as e:
            return CommandResult(output=f"Error resuming session: {e}")

    try:
        resume_data = await store.resume_session(session_id)
        if not resume_data:
            return CommandResult(output=f"Session '{session_id}' not found.")

        messages = resume_data.get("messages", [])
        if not messages:
            return CommandResult(output=f"Session '{session_id}' has no messages to restore.")

        # Restore messages into the current context
        from attocode.types.messages import Message, Role
        ctx.messages.clear()
        restored = 0
        for msg_dict in messages:
            role = msg_dict.get("role", "user")
            content = msg_dict.get("content", "")
            ctx.messages.append(Message(role=Role(role), content=content))
            restored += 1

        # Update session tracking
        ctx.session_id = session_id
        if agent is not None:
            try:
                agent._session_id = session_id
                agent._conversation_messages = list(ctx.messages)
                if hasattr(agent, "config"):
                    agent.config.resume_session = None
                    agent.config.resume_session_explicit = False
            except Exception:
                logger.debug("resume_agent_state_sync_failed", exc_info=True)
        session_info = resume_data.get("session", {})
        task = session_info.get("task", "unknown")

        return CommandResult(
            output=f"Resumed session {session_id}: {task}\n"
            f"  Messages restored: {restored}\n"
            f"  Previous tokens: {session_info.get('total_tokens', 0):,}\n"
            f"  Previous cost: ${session_info.get('total_cost', 0.0):.4f}"
        )
    except Exception as e:
        return CommandResult(output=f"Error resuming session: {e}")


async def _checkpoint_command(agent: Any) -> CommandResult:
    return await _save_command(agent)


async def _checkpoints_command(agent: Any, session_id: str) -> CommandResult:
    ctx = _get_ctx(agent)
    store = await _get_or_init_session_store(agent)

    if not store:
        return CommandResult(output="Session persistence not configured.")

    sid = session_id or (ctx.session_id if ctx else None)
    if not sid:
        return CommandResult(output="Usage: /checkpoints <session_id>")

    try:
        checkpoints = await store.list_checkpoints(sid)
        if not checkpoints:
            return CommandResult(output=f"No checkpoints for session '{sid}'.")

        lines = [f"Checkpoints for session {sid}:"]
        for cp in checkpoints:
            import datetime
            ts = datetime.datetime.fromtimestamp(cp.created_at).strftime("%H:%M:%S")
            msgs = len(cp.messages)
            lines.append(f"  [{cp.id}] {ts} ({msgs} messages)")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error listing checkpoints: {e}")


def _reset_command(agent: Any) -> CommandResult:
    """Clear messages, metrics, and iteration counter."""
    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="No active context.")

    msg_count = len(ctx.messages)
    if agent and hasattr(agent, "reset_conversation"):
        agent.reset_conversation()
    else:
        ctx.messages.clear()
        ctx.session_id = None
    ctx.iteration = 0
    from attocode.types.agent import AgentMetrics
    ctx.metrics = AgentMetrics()

    return CommandResult(output=f"Session reset. Cleared {msg_count} messages, metrics zeroed.")


def _handoff_command(agent: Any, arg: str) -> CommandResult:
    """Export session summary for handoff."""
    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="No active context.")

    m = ctx.metrics
    lines = [
        "# Session Handoff",
        "",
        f"- Messages: {len(ctx.messages)}",
        f"- Iterations: {ctx.iteration}",
        f"- LLM calls: {m.llm_calls}",
        f"- Tool calls: {m.tool_calls}",
        f"- Total tokens: {m.total_tokens:,}",
        f"- Estimated cost: ${m.estimated_cost:.4f}",
    ]

    if ctx.goal:
        lines.insert(2, f"- Goal: {ctx.goal}")

    mode_mgr = getattr(ctx, "mode_manager", None)
    if mode_mgr:
        lines.append(f"- Mode: {mode_mgr.mode.value}")
        summary = mode_mgr.format_changes_summary()
        if summary and summary != "No changes":
            lines.append(f"- Changes:\n{summary}")

    return CommandResult(output="\n".join(lines))


def _export_command(agent: Any, arg: str) -> CommandResult:
    """Export session as HTML or markdown."""
    import datetime as _dt
    from pathlib import Path

    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="No active context.")

    fmt = (arg.split()[0] if arg else "html").lower()
    if fmt == "md" or fmt == "markdown":
        return _handoff_command(agent, arg)

    # HTML export
    m = ctx.metrics
    model = "unknown"
    if agent and hasattr(agent, "config"):
        model = agent.config.model or "unknown"

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_id = ctx.session_id or "unsaved"

    # Build message HTML
    msg_html_parts: list[str] = []
    for msg in ctx.messages:
        role = getattr(msg, "role", "unknown")
        content = getattr(msg, "content", "")
        if not content or not isinstance(content, str):
            continue

        role_class = role.replace(" ", "-")
        # Escape HTML
        import html as _html
        safe_content = _html.escape(str(content))
        # Preserve newlines and code blocks
        safe_content = safe_content.replace("\n", "<br>")

        msg_html_parts.append(
            f'<div class="message {role_class}">'
            f'<div class="role">{role}</div>'
            f'<div class="content">{safe_content}</div>'
            f"</div>"
        )

    messages_html = "\n".join(msg_html_parts)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Attocode Session: {session_id}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
         background: #0d1117; color: #c9d1d9; padding: 20px; max-width: 900px; margin: 0 auto; }}
  h1 {{ color: #58a6ff; margin-bottom: 10px; font-size: 1.4em; }}
  .meta {{ color: #8b949e; margin-bottom: 20px; font-size: 0.85em; }}
  .meta span {{ margin-right: 16px; }}
  .stats {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px;
            padding: 12px 16px; margin-bottom: 20px; display: flex; gap: 24px; flex-wrap: wrap; }}
  .stat {{ text-align: center; }}
  .stat-value {{ color: #58a6ff; font-size: 1.2em; font-weight: bold; }}
  .stat-label {{ color: #8b949e; font-size: 0.75em; }}
  .messages {{ display: flex; flex-direction: column; gap: 8px; }}
  .message {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; }}
  .message.user {{ border-left: 3px solid #58a6ff; }}
  .message.assistant {{ border-left: 3px solid #3fb950; }}
  .message.system {{ border-left: 3px solid #8b949e; opacity: 0.7; }}
  .message.tool {{ border-left: 3px solid #d29922; }}
  .role {{ color: #8b949e; font-size: 0.75em; text-transform: uppercase; margin-bottom: 6px; }}
  .content {{ white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; line-height: 1.5; }}
  .footer {{ margin-top: 20px; color: #484f58; font-size: 0.75em; text-align: center; }}
</style>
</head>
<body>
<h1>Attocode Session Export</h1>
<div class="meta">
  <span>Session: {session_id}</span>
  <span>Model: {model}</span>
  <span>Exported: {now}</span>
</div>
<div class="stats">
  <div class="stat"><div class="stat-value">{len(ctx.messages)}</div><div class="stat-label">Messages</div></div>
  <div class="stat"><div class="stat-value">{ctx.iteration}</div><div class="stat-label">Iterations</div></div>
  <div class="stat"><div class="stat-value">{m.llm_calls}</div><div class="stat-label">LLM Calls</div></div>
  <div class="stat"><div class="stat-value">{m.tool_calls}</div><div class="stat-label">Tool Calls</div></div>
  <div class="stat"><div class="stat-value">{m.total_tokens:,}</div><div class="stat-label">Tokens</div></div>
  <div class="stat"><div class="stat-value">${m.estimated_cost:.4f}</div><div class="stat-label">Cost</div></div>
</div>
<div class="messages">
{messages_html}
</div>
<div class="footer">Generated by Attocode v0.2.4</div>
</body>
</html>"""

    # Write to file
    export_dir = Path(".attocode/exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    export_path = export_dir / f"session-{ts}.html"
    export_path.write_text(html)

    return CommandResult(
        output=f"Session exported to: {export_path}\n"
        f"  Messages: {len(ctx.messages)}, Tokens: {m.total_tokens:,}, Cost: ${m.estimated_cost:.4f}"
    )


# ============================================================
# Mode command handlers
# ============================================================

def _mode_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return CommandResult(output="Mode system not available. Running in default build mode.")

    if not arg:
        return CommandResult(output=f"Current mode: {mode_mgr.mode.value}")

    result = mode_mgr.switch_mode(arg)
    return CommandResult(output=result)


def _plan_command(agent: Any, arg: str, *, app: Any = None) -> CommandResult:
    ctx = _get_ctx(agent)
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return _feature_unavailable("Plan mode")

    if arg:
        # /plan <description> — enter plan mode and set goal
        mode_mgr.switch_mode("plan")
        if ctx and hasattr(ctx, "goal"):
            ctx.goal = arg

        # Emit plan event to TUI so PlanPanel shows data
        if app and hasattr(app, "post_message"):
            try:
                from attocode.tui.events import PlanUpdated
                from attocode.types.agent import AgentPlan, PlanTask, TaskStatus
                plan = AgentPlan(
                    goal=arg,
                    tasks=[PlanTask(id="plan-0", description=arg, status=TaskStatus.IN_PROGRESS)],
                )
                app.post_message(PlanUpdated(plan=plan))
            except Exception:
                pass

        return CommandResult(
            output=f"Entered plan mode. Goal: {arg}\n"
            "Use /show-plan to see proposed changes, /approve to apply them."
        )

    # No arg — show current plan state
    if mode_mgr.mode.value == "plan":
        summary = mode_mgr.format_changes_summary()
        return CommandResult(output=f"Mode: plan\n{summary}")

    # Check interactive planner
    planner = getattr(ctx, "interactive_planner", None) if ctx else None
    if planner and hasattr(planner, "current_plan") and planner.current_plan:
        plan = planner.current_plan
        lines = [f"Interactive plan: {getattr(plan, 'title', 'untitled')}"]
        steps = getattr(plan, "steps", [])
        for i, step in enumerate(steps):
            status = getattr(step, "status", "pending")
            desc = getattr(step, "description", str(step))
            lines.append(f"  [{i}] [{status}] {desc}")
        return CommandResult(output="\n".join(lines))

    # Show current mode + summary
    summary = mode_mgr.format_changes_summary()
    return CommandResult(
        output=f"Mode: {mode_mgr.mode.value}\n{summary}\n"
        "Tip: /plan <description> enters plan mode with a goal."
    )


def _show_plan_command(agent: Any) -> CommandResult:
    """Show detailed plan with pending diffs."""
    ctx = _get_ctx(agent)
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return _feature_unavailable("Plan mode")

    lines = [f"Mode: {mode_mgr.mode.value}"]

    pending = getattr(mode_mgr, "get_pending_changes", lambda: [])()
    if pending:
        lines.append(f"\nPending changes ({len(pending)}):")
        for i, change in enumerate(pending):
            path = getattr(change, "path", getattr(change, "file_path", "?"))
            action = getattr(change, "action", "modify")
            lines.append(f"  [{i}] {action}: {path}")
            diff = getattr(change, "diff", None) or getattr(change, "preview", None)
            if diff:
                for dl in str(diff).splitlines()[:5]:
                    lines.append(f"      {dl}")
    else:
        lines.append("\nNo pending changes.")

    summary = mode_mgr.format_changes_summary()
    if summary and summary not in ("No changes", ""):
        lines.append(f"\nSummary:\n{summary}")

    return CommandResult(output="\n".join(lines))


def _approve_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        # Fallback: try pending plan manager
        pending = getattr(ctx, "_pending_plan", None) if ctx else None
        if pending and hasattr(pending, "approve"):
            try:
                result = pending.approve(arg or "all")
                return CommandResult(output=result)
            except Exception as e:
                return CommandResult(output=f"Approve failed: {e}")
        return _feature_unavailable("Mode system")

    if arg == "all":
        return CommandResult(output=mode_mgr.approve_all_changes())

    if arg:
        try:
            index = int(arg)
            return CommandResult(output=mode_mgr.approve_change(index))
        except ValueError:
            return CommandResult(output="Usage: /approve <index|all>")

    # Approve the first pending change
    pending = mode_mgr.get_pending_changes()
    if pending:
        try:
            idx = mode_mgr.proposed_changes.index(pending[0])
            return CommandResult(output=mode_mgr.approve_change(idx))
        except (ValueError, IndexError):
            return CommandResult(output="Could not find pending change to approve.")
    return CommandResult(output="No pending changes to approve.")


def _reject_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        pending = getattr(ctx, "_pending_plan", None) if ctx else None
        if pending and hasattr(pending, "reject"):
            try:
                result = pending.reject(arg or "all")
                return CommandResult(output=result)
            except Exception as e:
                return CommandResult(output=f"Reject failed: {e}")
        return _feature_unavailable("Mode system")

    if arg == "all":
        return CommandResult(output=mode_mgr.reject_all_changes())

    if arg:
        try:
            index = int(arg)
            return CommandResult(output=mode_mgr.reject_change(index))
        except ValueError:
            return CommandResult(output="Usage: /reject <index|all>")

    pending = mode_mgr.get_pending_changes()
    if pending:
        try:
            idx = mode_mgr.proposed_changes.index(pending[0])
            return CommandResult(output=mode_mgr.reject_change(idx))
        except (ValueError, IndexError):
            return CommandResult(output="Could not find pending change to reject.")
    return CommandResult(output="No pending changes to reject.")


# ============================================================
# Agent command handlers (rewritten with AgentRegistry)
# ============================================================

def _agents_command(agent: Any, arg: str) -> CommandResult:
    if not arg or arg == "list":
        try:
            registry = _get_agent_registry(agent)
            agents = registry.list_agents()
            if not agents:
                return CommandResult(output="No agents found.")

            # Group by source
            by_source: dict[str, list[Any]] = {}
            for a in agents:
                src = getattr(a, "source", "unknown")
                by_source.setdefault(src, []).append(a)

            lines = [f"Registered agents ({len(agents)}):"]
            for source, group in sorted(by_source.items()):
                lines.append(f"\n  [{source}]")
                for a in group:
                    model = getattr(a, "model", None) or "default"
                    desc = (getattr(a, "description", "") or "")[:50]
                    lines.append(f"    {a.name}: {desc} (model: {model})")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error listing agents: {e}")

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "info":
        return _agents_info_command(agent, subarg)
    if subcmd == "new":
        return _agents_new_command(agent, subarg)
    if subcmd == "edit":
        return _agents_edit_command(agent, subarg)
    if subcmd == "reload":
        return _agents_reload_command(agent)

    return CommandResult(output="Agents subcommands: list, info <name>, new <name>, edit <name>, reload")


def _agents_info_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /agents info <name>")
    try:
        registry = _get_agent_registry(agent)
        defn = registry.get(name)
        if not defn:
            return CommandResult(output=f"Agent '{name}' not found.")

        lines = [
            f"Agent: {defn.name}",
            f"  Description: {defn.description}",
            f"  Model: {defn.model or 'default'}",
            f"  Max iterations: {defn.max_iterations}",
            f"  Source: {defn.source}",
        ]
        if defn.tools:
            lines.append(f"  Tools: {', '.join(defn.tools)}")
        if defn.temperature is not None:
            lines.append(f"  Temperature: {defn.temperature}")
        if defn.system_prompt:
            preview = defn.system_prompt[:120].replace("\n", " ")
            lines.append(f"  System prompt: {preview}...")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _agents_new_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /agents new <name>")

    wd = _get_working_dir(agent)
    if not wd:
        return CommandResult(output="No working directory set.")

    agent_dir = Path(wd) / ".attocode" / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_file = agent_dir / "AGENT.yaml"
    if agent_file.exists():
        return CommandResult(output=f"Agent '{name}' already exists at {agent_file}")

    scaffold = (
        f"name: {name}\n"
        f"description: A custom agent\n"
        f"model: null  # Uses default model\n"
        f"max_iterations: 50\n"
        f"temperature: null\n"
        f"tools:\n"
        f"  - read_file\n"
        f"  - write_file\n"
        f"  - edit_file\n"
        f"  - bash\n"
        f"  - glob\n"
        f"  - grep\n"
        f"system_prompt: |\n"
        f"  You are a helpful coding assistant.\n"
    )
    agent_file.write_text(scaffold)
    return CommandResult(output=f"Created agent scaffold at {agent_file}\nEdit it to customize.")


def _agents_edit_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /agents edit <name>")

    wd = _get_working_dir(agent)
    if not wd:
        return CommandResult(output="No working directory set.")

    agent_file = Path(wd) / ".attocode" / "agents" / name / "AGENT.yaml"
    if not agent_file.exists():
        return CommandResult(output=f"Agent '{name}' not found at {agent_file}")

    editor = os.environ.get("EDITOR", "")
    if editor:
        return CommandResult(output=f"Open with: {editor} {agent_file}")
    return CommandResult(output=f"Agent file: {agent_file}")


def _agents_reload_command(agent: Any) -> CommandResult:
    try:
        registry = _get_agent_registry(agent)
        count = len(registry.list_agents())
        return CommandResult(output=f"Agent registry reloaded. {count} agents found.")
    except Exception as e:
        return CommandResult(output=f"Error reloading agents: {e}")


async def _spawn_command(agent: Any, task: str) -> CommandResult:
    if not task:
        return CommandResult(output="Usage: /spawn [--model <model>] <task description>")

    # Parse optional --model flag
    model: str | None = None
    if task.startswith("--model "):
        parts = task.split(maxsplit=2)
        if len(parts) >= 3:
            model = parts[1]
            task = parts[2]
        else:
            return CommandResult(output="Usage: /spawn --model <model> <task description>")

    if not agent or not hasattr(agent, "spawn_agent"):
        return _feature_unavailable("Subagent spawning")

    try:
        import time as _time
        agent_name = f"command_spawn_{int(_time.time() * 1000)}"
        result = await agent.spawn_agent(
            agent_name=agent_name,
            task=task,
            model=model,
        )
        success = result.get("success", False)
        response = result.get("response", "")
        tokens = result.get("tokens_used", 0)

        if success:
            lines = [
                f"Subagent completed ({tokens:,} tokens):",
                response[:2000] if len(response) > 2000 else response,
            ]
        else:
            error = result.get("error", "")
            detail = error or response or "No error details returned."
            lines = [f"Subagent failed: {str(detail)[:500]}"]
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Spawn error: {e}")


def _find_command(agent: Any, query: str) -> CommandResult:
    """Search agents by keyword in name + description."""
    if not query:
        return CommandResult(output="Usage: /find <query>")

    try:
        registry = _get_agent_registry(agent)
        agents = registry.list_agents()
        query_lower = query.lower()
        matches = []
        for a in agents:
            name = (getattr(a, "name", "") or "").lower()
            desc = (getattr(a, "description", "") or "").lower()
            if query_lower in name or query_lower in desc:
                matches.append(a)

        if not matches:
            return CommandResult(output=f"No agents matching '{query}'.")

        lines = [f"Agents matching '{query}':"]
        for a in matches:
            desc = (getattr(a, "description", "") or "")[:60]
            lines.append(f"  {a.name}: {desc}")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _suggest_command(agent: Any, task: str) -> CommandResult:
    """Suggest agents ranked by keyword overlap with task."""
    if not task:
        return CommandResult(output="Usage: /suggest <task description>")

    try:
        registry = _get_agent_registry(agent)
        agents = registry.list_agents()
        task_words = set(task.lower().split())

        scored: list[tuple[Any, float]] = []
        for a in agents:
            desc_words = set((getattr(a, "description", "") or "").lower().split())
            name_words = set((getattr(a, "name", "") or "").lower().replace("-", " ").split())
            overlap = len(task_words & (desc_words | name_words))
            if overlap > 0:
                score = overlap / max(len(task_words), 1)
                scored.append((a, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            return CommandResult(output="No agents match this task. Consider using the main agent.")

        lines = ["Suggested agents (by relevance):"]
        for a, score in scored[:5]:
            desc = (getattr(a, "description", "") or "")[:50]
            lines.append(f"  {a.name} ({score:.0%}): {desc}")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _auto_command(agent: Any, task: str) -> CommandResult:
    """Auto-select best agent for a task."""
    if not task:
        return CommandResult(output="Usage: /auto <task description>")

    try:
        registry = _get_agent_registry(agent)
        agents = registry.list_agents()
        task_words = set(task.lower().split())

        best_agent = None
        best_score = 0.0
        for a in agents:
            desc_words = set((getattr(a, "description", "") or "").lower().split())
            name_words = set((getattr(a, "name", "") or "").lower().replace("-", " ").split())
            overlap = len(task_words & (desc_words | name_words))
            score = overlap / max(len(task_words), 1)
            if score > best_score:
                best_score = score
                best_agent = a

        if not best_agent or best_score < 0.05:
            return CommandResult(output="No suitable agent found. Use the main agent for this task.")

        return CommandResult(
            output=f"Best match: {best_agent.name} ({best_score:.0%} relevance)\n"
            f"  {getattr(best_agent, 'description', '')}\n"
            f"Use: /spawn with agent '{best_agent.name}' to delegate."
        )
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


# ============================================================
# Thread command handlers
# ============================================================

def _fork_command(agent: Any, label: str) -> CommandResult:
    """Fork conversation into a new thread."""
    ctx = _get_ctx(agent)
    mgr = getattr(ctx, "thread_manager", None) if ctx else None

    if not mgr:
        # Try to create one on the fly
        try:
            from attocode.integrations.utilities.thread_manager import ThreadManager
            sid = getattr(ctx, "session_id", "") if ctx else ""
            mgr = ThreadManager(session_id=sid)
            if ctx:
                ctx.thread_manager = mgr
        except Exception:
            return CommandResult(output="Thread management not available.")

    try:
        messages = ctx.messages if ctx else None
        info = mgr.create_fork(label=label or "", messages=messages)
        return CommandResult(
            output=f"Forked to thread '{info.thread_id}'"
            + (f" ({info.label})" if info.label else "")
            + f"\n  Messages copied: {info.message_count}"
        )
    except Exception as e:
        return CommandResult(output=f"Fork failed: {e}")


def _threads_command(agent: Any) -> CommandResult:
    """List all conversation threads."""
    ctx = _get_ctx(agent)
    mgr = getattr(ctx, "thread_manager", None) if ctx else None

    if not mgr:
        return _feature_unavailable("Thread management", "/fork to create the first thread")

    try:
        threads = mgr.list_threads()
        if not threads:
            return CommandResult(output="No threads.")

        active_id = mgr.active_thread_id
        lines = [f"Threads ({len(threads)}):"]
        for t in threads:
            marker = " *" if t.thread_id == active_id else ""
            label = f" ({t.label})" if t.label else ""
            parent = f" [parent: {t.parent_id}]" if t.parent_id else ""
            lines.append(
                f"  {t.thread_id}{label}: {t.message_count} msgs"
                f"{'  (active)' if t.is_active else '  (closed)'}{marker}{parent}"
            )
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _switch_command(agent: Any, thread_id: str) -> CommandResult:
    """Switch to a different thread."""
    if not thread_id:
        return CommandResult(output="Usage: /switch <thread_id>")

    ctx = _get_ctx(agent)
    mgr = getattr(ctx, "thread_manager", None) if ctx else None

    if not mgr:
        return _feature_unavailable("Thread management")

    try:
        info = mgr.switch_thread(thread_id)
        # Load thread messages into context
        if ctx:
            thread_msgs = mgr.get_messages(thread_id)
            ctx.messages.clear()
            ctx.messages.extend(thread_msgs)
        return CommandResult(
            output=f"Switched to thread '{info.thread_id}'"
            + (f" ({info.label})" if info.label else "")
            + f"\n  Messages: {info.message_count}"
        )
    except Exception as e:
        return CommandResult(output=f"Switch failed: {e}")


def render_thread_tree(mgr: Any) -> str:
    """Build an ASCII tree visualization of thread/fork structure."""
    tree = mgr.get_thread_tree()
    active_id = mgr.active_thread_id
    threads = {t.thread_id: t for t in mgr.list_threads()}

    def _format_node(tid: str) -> str:
        info = threads.get(tid)
        if not info:
            return tid
        label_part = f': "{info.label}"' if info.label else ""
        msg_part = f" ({info.message_count} messages)"
        active_part = " [active]" if tid == active_id else ""
        return f"{tid}{label_part}{msg_part}{active_part}"

    lines: list[str] = []

    def _walk(parent_id: str, prefix: str, is_last: bool, is_root: bool) -> None:
        if not is_root:
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            lines.append(f"{prefix}{connector}{_format_node(parent_id)}")
            child_prefix = prefix + ("    " if is_last else "\u2502   ")
        else:
            lines.append(_format_node(parent_id))
            child_prefix = ""

        children = tree.get(parent_id, [])
        for i, child_id in enumerate(children):
            _walk(child_id, child_prefix, i == len(children) - 1, False)

    root_children = tree.get("root", [])
    if not root_children:
        return _format_node("main")

    for i, root_id in enumerate(root_children):
        _walk(root_id, "", i == len(root_children) - 1, True)

    return "\n".join(lines)


def _tree_command(agent: Any) -> CommandResult:
    """Show thread/fork tree visualization."""
    ctx = _get_ctx(agent)
    mgr = getattr(ctx, "thread_manager", None) if ctx else None

    if not mgr:
        return _feature_unavailable("Thread management", "/fork to create the first thread")

    try:
        output = render_thread_tree(mgr)
        return CommandResult(output=output)
    except Exception as e:
        return CommandResult(output=f"Error rendering tree: {e}")


def _rollback_command(agent: Any, arg: str) -> CommandResult:
    """Remove last N messages (default: remove last assistant turn + tool messages)."""
    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="No active context.")

    if not ctx.messages:
        return CommandResult(output="No messages to rollback.")

    try:
        n = int(arg) if arg else 0
    except ValueError:
        return CommandResult(output="Usage: /rollback [n]")

    if n > 0:
        # Remove exactly N messages
        removed = min(n, len(ctx.messages))
        del ctx.messages[-removed:]
        return CommandResult(output=f"Rolled back {removed} message(s). {len(ctx.messages)} remaining.")

    # Default: remove last turn (trailing assistant + tool messages)
    removed = 0
    while ctx.messages and str(getattr(ctx.messages[-1], "role", "")) in ("assistant", "tool"):
        ctx.messages.pop()
        removed += 1

    if removed == 0 and ctx.messages:
        # If last message is user, remove it
        ctx.messages.pop()
        removed = 1

    return CommandResult(output=f"Rolled back {removed} message(s). {len(ctx.messages)} remaining.")


async def _restore_command(agent: Any, checkpoint_id: str) -> CommandResult:
    """Restore from a checkpoint."""
    if not checkpoint_id:
        return CommandResult(output="Usage: /restore <checkpoint_id>")

    if agent and hasattr(agent, "restore_checkpoint"):
        success = await agent.restore_checkpoint(checkpoint_id)
        if success:
            ctx = _get_ctx(agent)
            msg_count = len(ctx.messages) if ctx else 0
            return CommandResult(output=f"Restored checkpoint '{checkpoint_id}'. Messages: {msg_count}")
        return CommandResult(output=f"Failed to restore checkpoint '{checkpoint_id}'.")

    return CommandResult(output="Checkpoint restore not available.")


# ============================================================
# Goals command handlers
# ============================================================

async def _goals_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="Goals require an active agent context.")
    store = getattr(ctx, "session_store", None)
    sid = getattr(ctx, "session_id", None)

    # In-memory fallback goals when no session store
    _mem_goals: list[dict[str, Any]] = getattr(ctx, "_memory_goals", [])
    use_memory = not store or not sid

    if use_memory and not hasattr(ctx, "_memory_goals"):
        ctx._memory_goals = []  # type: ignore[attr-defined]
        _mem_goals = ctx._memory_goals  # type: ignore[attr-defined]

    if not arg or arg == "list":
        if use_memory:
            active = [g for g in _mem_goals if g.get("status") == "active"]
            if not active:
                return CommandResult(output="No active goals. Use /goals add <description> to create one.")
            lines = ["Active goals (in-memory):"]
            for g in active:
                lines.append(f"  [{g['id']}] {g['description']}")
            return CommandResult(output="\n".join(lines))
        try:
            goals = await store.list_goals(sid, status="active")
            if not goals:
                return CommandResult(output="No active goals. Use /goals add <description> to create one.")

            lines = ["Active goals:"]
            for g in goals:
                lines.append(f"  [{g.id}] {g.description}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error: {e}")

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "add":
        if not subarg:
            return CommandResult(output="Usage: /goals add <description>")
        if use_memory:
            gid = len(_mem_goals) + 1
            _mem_goals.append({"id": gid, "description": subarg, "status": "active"})
            return CommandResult(output=f"Goal #{gid} created (in-memory): {subarg}")
        try:
            goal_id = await store.create_goal(sid, subarg)
            return CommandResult(output=f"Goal #{goal_id} created: {subarg}")
        except Exception as e:
            return CommandResult(output=f"Error creating goal: {e}")

    if subcmd == "done":
        if not subarg:
            return CommandResult(output="Usage: /goals done <id>")
        try:
            goal_id = int(subarg)
        except ValueError:
            return CommandResult(output="Usage: /goals done <id> (id must be a number)")
        if use_memory:
            for g in _mem_goals:
                if g["id"] == goal_id:
                    g["status"] = "done"
                    return CommandResult(output=f"Goal #{goal_id} marked complete.")
            return CommandResult(output=f"Goal #{goal_id} not found.")
        try:
            await store.complete_goal(goal_id)
            return CommandResult(output=f"Goal #{goal_id} marked complete.")
        except Exception as e:
            return CommandResult(output=f"Error: {e}")

    if subcmd == "all":
        if use_memory:
            if not _mem_goals:
                return CommandResult(output="No goals found.")
            lines = ["All goals (in-memory):"]
            for g in _mem_goals:
                status_mark = "+" if g["status"] == "active" else "x"
                lines.append(f"  [{status_mark}] #{g['id']} {g['description']}")
            return CommandResult(output="\n".join(lines))
        try:
            goals = await store.list_goals(sid)
            if not goals:
                return CommandResult(output="No goals found.")

            lines = ["All goals:"]
            for g in goals:
                status_mark = "+" if g.status == "active" else "x"
                lines.append(f"  [{status_mark}] #{g.id} {g.description}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error: {e}")

    return CommandResult(output="Goals subcommands: list, add <description>, done <id>, all")


# ============================================================
# MCP command handlers
# ============================================================

async def _mcp_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)

    if not arg or arg == "list":
        # Try ctx first, fall back to agent-level configs (ctx is None before first prompt)
        configs = getattr(ctx, "mcp_server_configs", []) if ctx else []
        if not configs:
            configs = getattr(agent, "_mcp_server_configs", []) or []
        if not configs:
            return CommandResult(output="No MCP servers configured.")

        mgr = getattr(agent, "_mcp_client_manager", None)
        lines = ["MCP servers:"]
        for i, cfg in enumerate(configs):
            name = cfg.get("name", cfg.get("command", "unknown"))
            if mgr:
                state = mgr.get_state(name)
                status = str(state) if state else "configured"
            else:
                status = "configured"
            lines.append(f"  [{i}] {name} ({status})")
            # Show error details for failed servers
            if mgr and status == "failed":
                entry = mgr._servers.get(name)
                if entry and entry.error:
                    lines.append(f"       Error: {entry.error}")
        return CommandResult(output="\n".join(lines))

    if arg == "tools":
        registry = getattr(ctx, "registry", None) if ctx else None
        if not registry:
            registry = getattr(agent, "_registry", None)
        if not registry:
            return CommandResult(output="No tool registry available.")

        tools = list(getattr(registry, "_tools", {}).values())
        mcp_tools = [t for t in tools if "mcp" in getattr(t, "tags", [])]
        if not mcp_tools:
            return CommandResult(output="No MCP tools registered.")

        lines = [f"MCP tools ({len(mcp_tools)}):"]
        for t in mcp_tools[:30]:
            lines.append(f"  {t.spec.name}: {t.spec.description[:60]}")
        if len(mcp_tools) > 30:
            lines.append(f"  ... and {len(mcp_tools) - 30} more")
        return CommandResult(output="\n".join(lines))

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "connect":
        if not subarg:
            return CommandResult(output="Usage: /mcp connect <server_name>")
        mgr = getattr(agent, "_mcp_client_manager", None)
        if not mgr:
            return CommandResult(output="MCP client manager not available.")
        try:
            success = await mgr.ensure_connected(subarg)
            if success:
                return CommandResult(output=f"Connected to MCP server '{subarg}'.")
            return CommandResult(output=f"Failed to connect to '{subarg}'.")
        except Exception as e:
            return CommandResult(output=f"Connection error: {e}")

    if subcmd == "disconnect":
        if not subarg:
            return CommandResult(output="Usage: /mcp disconnect <server_name>")
        mgr = getattr(agent, "_mcp_client_manager", None)
        if not mgr:
            return CommandResult(output="MCP client manager not available.")
        try:
            await mgr.disconnect(subarg)
            return CommandResult(output=f"Disconnected from '{subarg}'.")
        except Exception as e:
            return CommandResult(output=f"Disconnect error: {e}")

    if subcmd == "search":
        if not subarg:
            return CommandResult(output="Usage: /mcp search <query>")
        meta = getattr(agent, "_mcp_meta_tools", None) or getattr(agent, "_mcp_meta", None)
        registry = getattr(ctx, "registry", None) if ctx else None
        if not registry:
            registry = getattr(agent, "_registry", None)
        if not meta or not registry:
            # Fallback: simple name-based search
            if registry:
                tools = list(getattr(registry, "_tools", {}).values())
                mcp_tools = [t for t in tools if "mcp" in getattr(t, "tags", [])]
                query_lower = subarg.lower()
                matches = [
                    t for t in mcp_tools
                    if query_lower in t.spec.name.lower() or query_lower in (t.spec.description or "").lower()
                ]
                if not matches:
                    return CommandResult(output=f"No MCP tools matching '{subarg}'.")
                lines = [f"MCP tools matching '{subarg}':"]
                for t in matches[:15]:
                    lines.append(f"  {t.spec.name}: {t.spec.description[:60]}")
                return CommandResult(output="\n".join(lines))
            return CommandResult(output="MCP meta tools not available.")
        try:
            all_tools = list(getattr(registry, "_tools", {}).values())
            mcp_tools_raw = [t for t in all_tools if "mcp" in getattr(t, "tags", [])]
            results = meta.search_tools(subarg, mcp_tools_raw)
            if not results:
                return CommandResult(output=f"No MCP tools matching '{subarg}'.")
            lines = [f"MCP tools matching '{subarg}':"]
            for t in results[:15]:
                name = getattr(t, "name", str(t))
                desc = (getattr(t, "description", "") or "")[:60]
                lines.append(f"  {name}: {desc}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Search error: {e}")

    if subcmd == "stats":
        meta = getattr(agent, "_mcp_meta_tools", None) or getattr(agent, "_mcp_meta", None)
        if not meta:
            # Fallback: basic stats from configs (ctx may be None before first prompt)
            configs = getattr(ctx, "mcp_server_configs", []) if ctx else []
            if not configs:
                configs = getattr(agent, "_mcp_server_configs", []) or []
            registry = getattr(ctx, "registry", None) if ctx else None
            if not registry:
                registry = getattr(agent, "_registry", None)
            tools = list(getattr(registry, "_tools", {}).values()) if registry else []
            mcp_tools = [t for t in tools if "mcp" in getattr(t, "tags", [])]
            lines = [
                "MCP stats:",
                f"  Configured servers: {len(configs)}",
                f"  Registered MCP tools: {len(mcp_tools)}",
            ]
            return CommandResult(output="\n".join(lines))
        try:
            stats = meta.get_context_stats()
            lines = [
                "MCP stats:",
                f"  Total servers: {stats.total_servers}",
                f"  Connected: {stats.connected_servers}",
                f"  Total tools: {stats.total_tools}",
                f"  Total calls: {stats.total_calls}",
            ]
            for s in stats.servers:
                status = "connected" if s.connected else "disconnected"
                lines.append(
                    f"  [{s.server_name}] {status}, {s.tool_count} tools, "
                    f"{s.total_calls} calls, {s.avg_latency_ms:.0f}ms avg"
                )
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error: {e}")

    return CommandResult(output="MCP subcommands: list, tools, connect <name>, disconnect <name>, search <query>, stats")


# ============================================================
# Skills command handlers (full implementation)
# ============================================================

def _skills_command(agent: Any, arg: str) -> CommandResult:
    if not arg or arg == "list":
        try:
            loader = _get_skill_loader(agent)
            if not loader:
                return CommandResult(output="No working directory set for skill discovery.")
            skills = loader.list_skills()
            if not skills:
                return CommandResult(output="No skills found.")

            lines = ["Available skills:"]
            for s in skills:
                name = getattr(s, "name", str(s))
                desc = (getattr(s, "description", "") or "")[:50]
                source = getattr(s, "source", "")
                invokable = "invokable" if getattr(s, "metadata", {}).get("invokable", True) else ""
                parts_info = [name]
                if desc:
                    parts_info.append(desc)
                tag = f"[{source}]" if source else ""
                inv = f" ({invokable})" if invokable else ""
                lines.append(f"  {tag} {name}: {desc}{inv}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error loading skills: {e}")

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "info":
        return _skills_info_command(agent, subarg)
    if subcmd == "new":
        return _skills_new_command(agent, subarg)
    if subcmd == "edit":
        return _skills_edit_command(agent, subarg)
    if subcmd in ("enable", "disable"):
        return _skills_toggle_command(agent, subarg, enable=(subcmd == "enable"))
    if subcmd == "reload":
        return _skills_reload_command(agent)

    return CommandResult(
        output="Skills subcommands: list, info <name>, new <name>, edit <name>, enable <name>, disable <name>, reload"
    )


def _skills_info_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /skills info <name>")
    try:
        loader = _get_skill_loader(agent)
        if not loader:
            return CommandResult(output="No working directory set.")
        skill = loader.get(name)
        if not skill:
            return CommandResult(output=f"Skill '{name}' not found.")

        lines = [
            f"Skill: {skill.name}",
            f"  Description: {skill.description}",
            f"  Source: {skill.source}",
            f"  Path: {skill.path}",
        ]
        if skill.metadata:
            for k, v in skill.metadata.items():
                lines.append(f"  {k}: {v}")
        if skill.content:
            preview = skill.content[:200].replace("\n", "\n    ")
            lines.append(f"  Content preview:\n    {preview}")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _skills_new_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /skills new <name>")

    wd = _get_working_dir(agent)
    if not wd:
        return CommandResult(output="No working directory set.")

    skill_dir = Path(wd) / ".attocode" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        return CommandResult(output=f"Skill '{name}' already exists at {skill_file}")

    scaffold = (
        f"---\n"
        f"name: {name}\n"
        f"description: A custom skill\n"
        f"invokable: true\n"
        f"---\n"
        f"\n"
        f"# {name}\n"
        f"\n"
        f"Describe what this skill does and how the agent should use it.\n"
    )
    skill_file.write_text(scaffold)
    return CommandResult(output=f"Created skill scaffold at {skill_file}\nEdit it to customize.")


def _skills_edit_command(agent: Any, name: str) -> CommandResult:
    if not name:
        return CommandResult(output="Usage: /skills edit <name>")
    try:
        loader = _get_skill_loader(agent)
        if not loader:
            return CommandResult(output="No working directory set.")
        skill = loader.get(name)
        if not skill:
            return CommandResult(output=f"Skill '{name}' not found.")

        editor = os.environ.get("EDITOR", "")
        if editor:
            return CommandResult(output=f"Open with: {editor} {skill.path}")
        return CommandResult(output=f"Skill file: {skill.path}")
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _skills_toggle_command(agent: Any, name: str, *, enable: bool) -> CommandResult:
    if not name:
        action = "enable" if enable else "disable"
        return CommandResult(output=f"Usage: /skills {action} <name>")

    try:
        loader = _get_skill_loader(agent)
        if not loader:
            return CommandResult(output="No working directory set.")
        skill = loader.get(name)
        if not skill:
            return CommandResult(output=f"Skill '{name}' not found.")

        action = "enabled" if enable else "disabled"
        return CommandResult(
            output=f"Skill '{name}' {action}.\n"
            f"Note: Skills are always loaded when present. "
            f"To truly disable, move the SKILL.md file."
        )
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _skills_reload_command(agent: Any) -> CommandResult:
    try:
        loader = _get_skill_loader(agent)
        if not loader:
            return CommandResult(output="No working directory set.")
        count = len(loader.list_skills())
        return CommandResult(output=f"Skills reloaded. {count} skills found.")
    except Exception as e:
        return CommandResult(output=f"Error reloading skills: {e}")


# ============================================================
# Context command handlers
# ============================================================

def _context_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    if not ctx:
        return CommandResult(output="No active context.")

    if arg == "breakdown":
        return _context_breakdown(ctx)

    # Default: basic context info
    msgs = len(ctx.messages)
    tokens = ctx.metrics.total_tokens
    lines = [
        "Context info:",
        f"  Messages: {msgs}",
        f"  Total tokens used: {tokens:,}",
        f"  Budget: {ctx.budget.max_tokens:,} tokens",
        f"  Usage: {agent.get_budget_usage():.0%}" if agent else "",
    ]
    return CommandResult(output="\n".join(line for line in lines if line))


def _context_breakdown(ctx: Any) -> CommandResult:
    """Show token usage breakdown by category."""
    from attocode.integrations.utilities.token_estimate import estimate_tokens

    system_tokens = 0
    user_tokens = 0
    assistant_tokens = 0
    tool_result_tokens = 0

    for msg in ctx.messages:
        content = getattr(msg, "content", "")
        est = estimate_tokens(content) if isinstance(content, str) else 0

        role = str(getattr(msg, "role", ""))
        if role == "system":
            system_tokens += est
        elif role == "user":
            user_tokens += est
        elif role == "assistant":
            assistant_tokens += est
        elif role == "tool":
            tool_result_tokens += est

    total = system_tokens + user_tokens + assistant_tokens + tool_result_tokens

    lines = [
        "Context token breakdown (estimated):",
        f"  System:      {system_tokens:>8,} ({system_tokens / total * 100:.0f}%)" if total else "  System: 0",
        f"  User:        {user_tokens:>8,} ({user_tokens / total * 100:.0f}%)" if total else "  User: 0",
        f"  Assistant:   {assistant_tokens:>8,} ({assistant_tokens / total * 100:.0f}%)" if total else "  Assistant: 0",
        f"  Tool results:{tool_result_tokens:>8,} ({tool_result_tokens / total * 100:.0f}%)" if total else "  Tool results: 0",
        f"  Total:       {total:>8,}",
    ]
    return CommandResult(output="\n".join(lines))


def _repomap_command(agent: Any, arg: str) -> CommandResult:
    """Show repository map, symbols, or dependency info."""
    # Get or create codebase context manager
    ctx_mgr = None
    if agent:
        ctx_mgr = getattr(agent, "get_codebase_context", lambda: None)()
    if not ctx_mgr:
        wd = _get_working_dir(agent)
        if not wd:
            return CommandResult(output="No working directory set.")
        try:
            from attocode.integrations.context.codebase_context import CodebaseContextManager
            ctx_mgr = CodebaseContextManager(root_dir=wd)
        except Exception as e:
            return CommandResult(output=f"Failed to create context manager: {e}")

    # Ensure files are discovered
    if not ctx_mgr._files:
        try:
            ctx_mgr.discover_files()
        except Exception as e:
            return CommandResult(output=f"File discovery failed: {e}")

    subcmd = arg.strip().lower()

    if subcmd == "analyze":
        # Force re-discovery: clear caches and re-scan
        ctx_mgr._files = []
        ctx_mgr._repo_map = None
        ctx_mgr._dep_graph = None
        try:
            ctx_mgr.discover_files()
        except Exception as e:
            return CommandResult(output=f"Re-discovery failed: {e}")
        return CommandResult(
            output=f"Re-scanned {len(ctx_mgr._files)} files in {ctx_mgr.root_dir}"
        )

    if subcmd == "symbols":
        try:
            repo_map = ctx_mgr.get_repo_map(include_symbols=True)
            lines = [f"Repository map ({repo_map.total_files} files, {repo_map.total_lines:,} lines):"]
            lines.append(repo_map.tree)
            if repo_map.symbols:
                lines.append("\nSymbols:")
                for rel_path, syms in sorted(repo_map.symbols.items()):
                    if syms:
                        lines.append(f"  {rel_path}: {', '.join(syms[:10])}")
                        if len(syms) > 10:
                            lines.append(f"    ... and {len(syms) - 10} more")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Symbol extraction failed: {e}")

    if subcmd == "deps":
        try:
            from attocode.integrations.context.codebase_context import build_dependency_graph
            graph = ctx_mgr._dep_graph
            if graph is None:
                graph = build_dependency_graph(ctx_mgr._files, ctx_mgr.root_dir)
                ctx_mgr._dep_graph = graph

            total_edges = sum(len(targets) for targets in graph.forward.values())
            lines = [
                "Dependency graph:",
                f"  Files with imports: {len(graph.forward)}",
                f"  Files imported: {len(graph.reverse)}",
                f"  Total edges: {total_edges}",
            ]
            # Top imported files (hubs)
            if graph.reverse:
                hubs = sorted(graph.reverse.items(), key=lambda x: len(x[1]), reverse=True)[:10]
                lines.append("\n  Most imported (hub files):")
                for path, importers in hubs:
                    lines.append(f"    {path}: {len(importers)} importers")
            # Top importing files
            if graph.forward:
                heavy = sorted(graph.forward.items(), key=lambda x: len(x[1]), reverse=True)[:10]
                lines.append("\n  Most imports (heavy files):")
                for path, targets in heavy:
                    lines.append(f"    {path}: {len(targets)} imports")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Dependency analysis failed: {e}")

    # Default: tree view
    try:
        tree = ctx_mgr.get_tree_view()
        file_count = len(ctx_mgr._files)
        langs = {}
        for f in ctx_mgr._files:
            if f.language:
                langs[f.language] = langs.get(f.language, 0) + 1
        lines = [f"Repository: {ctx_mgr.root_dir} ({file_count} files)"]
        if langs:
            top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append("Languages: " + ", ".join(f"{line} ({c})" for line, c in top))
        lines.append("")
        lines.append(tree)
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Tree generation failed: {e}")


# ============================================================
# Graph visualization command handlers
# ============================================================


def _get_ast_svc(agent: Any) -> Any:
    """Get or create an ASTService for graph commands."""
    wd = _get_working_dir(agent)
    if not wd:
        return None
    try:
        from attocode.integrations.context.ast_service import ASTService
        svc = ASTService.get_instance(wd)
        if not svc.initialized:
            svc.initialize()
        return svc
    except Exception:
        return None


def _deps_command(agent: Any, arg: str, *, app: Any = None) -> CommandResult:
    """Show dependency graph for a file. Opens GraphScreen in TUI mode."""
    if not arg:
        return CommandResult(output="Usage: /deps <file_path>")

    wd = _get_working_dir(agent) or "."

    # TUI mode: push GraphScreen
    if app and hasattr(app, "push_screen"):
        try:
            from attocode.tui.screens.graph_screen import GraphScreen
            app.push_screen(GraphScreen(mode="deps", file=arg.strip(), working_dir=wd))
            return CommandResult(output="")
        except Exception as e:
            return CommandResult(output=f"Failed to open graph screen: {e}")

    # REPL fallback: text output
    svc = _get_ast_svc(agent)
    if not svc:
        return CommandResult(output="AST service not available.")

    rel = svc._to_rel(arg.strip())
    deps = sorted(svc.get_dependencies(rel))
    importers = sorted(svc.get_dependents(rel))
    lines = [f"Dependencies for {rel}:"]
    lines.append(f"\n  Imports ({len(deps)}):")
    for d in deps[:20]:
        lines.append(f"    -> {d}")
    lines.append(f"\n  Imported by ({len(importers)}):")
    for i in importers[:20]:
        lines.append(f"    <- {i}")
    return CommandResult(output="\n".join(lines))


def _impact_command(agent: Any, arg: str, *, app: Any = None) -> CommandResult:
    """Show impact analysis for a file. Opens GraphScreen in TUI mode."""
    if not arg:
        return CommandResult(output="Usage: /impact <file_path>")

    wd = _get_working_dir(agent) or "."

    # TUI mode: push GraphScreen
    if app and hasattr(app, "push_screen"):
        try:
            from attocode.tui.screens.graph_screen import GraphScreen
            app.push_screen(GraphScreen(mode="impact", file=arg.strip(), working_dir=wd))
            return CommandResult(output="")
        except Exception as e:
            return CommandResult(output=f"Failed to open graph screen: {e}")

    # REPL fallback: text output
    svc = _get_ast_svc(agent)
    if not svc:
        return CommandResult(output="AST service not available.")

    rel = svc._to_rel(arg.strip())
    affected = svc.get_impact([rel])
    lines = [f"Impact analysis for {rel}: {len(affected)} files affected"]
    for f in sorted(affected)[:30]:
        lines.append(f"    > {f}")
    if len(affected) > 30:
        lines.append(f"    ... and {len(affected) - 30} more")
    return CommandResult(output="\n".join(lines))


def _graph_command(agent: Any, *, app: Any = None) -> CommandResult:
    """Show repo overview. Opens GraphScreen in TUI mode."""
    wd = _get_working_dir(agent) or "."

    # TUI mode: push GraphScreen
    if app and hasattr(app, "push_screen"):
        try:
            from attocode.tui.screens.graph_screen import GraphScreen
            app.push_screen(GraphScreen(mode="overview", working_dir=wd))
            return CommandResult(output="")
        except Exception as e:
            return CommandResult(output=f"Failed to open graph screen: {e}")

    # REPL fallback: text output
    svc = _get_ast_svc(agent)
    if not svc:
        return CommandResult(output="AST service not available.")

    idx = svc._index
    hotspots: list[tuple[str, int]] = []
    for f in idx.file_symbols:
        fan_in = len(idx.get_dependents(f))
        fan_out = len(idx.get_dependencies(f))
        symbol_count = len(idx.file_symbols.get(f, set()))
        score = fan_in * 2 + fan_out + symbol_count
        hotspots.append((f, score))

    hotspots.sort(key=lambda h: h[1], reverse=True)
    lines = ["Hotspot heatmap (top 15):"]
    for f, score in hotspots[:15]:
        lines.append(f"  [{score:>4}] {f}")
    return CommandResult(output="\n".join(lines))


# ============================================================
# Debug command handlers
# ============================================================

def _trace_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    collector = getattr(ctx, "trace_collector", None) if ctx else None
    collector = collector or getattr(agent, "_trace_collector", None)

    if not arg or arg == "summary":
        if collector:
            try:
                summary = collector.get_summary()
                lines = [
                    "Trace summary:",
                    f"  Session: {getattr(summary, 'session_id', collector.session_id)}",
                    f"  Events: {getattr(summary, 'total_events', collector.event_count)}",
                    f"  LLM calls: {getattr(summary, 'llm_calls', 0)}",
                    f"  Tool calls: {getattr(summary, 'tool_calls', 0)}",
                    f"  Tokens: {getattr(summary, 'total_tokens', 0):,}",
                    f"  Cost: ${getattr(summary, 'total_cost', 0):.4f}",
                    f"  Duration: {getattr(summary, 'duration_seconds', 0):.1f}s",
                    f"  Errors: {getattr(summary, 'error_count', 0)}",
                ]
                return CommandResult(output="\n".join(lines))
            except Exception as e:
                return CommandResult(output=f"Error reading trace: {e}")

        # Fallback to metrics
        if ctx:
            m = ctx.metrics
            lines = [
                "Trace summary (from metrics, no TraceCollector):",
                f"  Iterations: {ctx.iteration}",
                f"  LLM calls: {m.llm_calls}",
                f"  Tool calls: {m.tool_calls}",
                f"  Tokens: {m.total_tokens:,}",
                f"  Cost: ${m.estimated_cost:.4f}",
            ]
            return CommandResult(output="\n".join(lines))
        return CommandResult(output="No trace data available.")

    if arg == "analyze":
        if not ctx:
            return CommandResult(output="No active context for analysis.")

        m = ctx.metrics
        lines = [
            "Session analysis:",
            f"  Iterations: {ctx.iteration}",
            f"  LLM calls: {m.llm_calls}",
            f"  Tool calls: {m.tool_calls}",
            f"  Tokens: {m.total_tokens:,}",
            f"  Cost: ${m.estimated_cost:.4f}",
            f"  Duration: {m.duration_ms / 1000:.1f}s",
        ]

        # Efficiency ratios
        if ctx.iteration > 0:
            lines.append("\n  Efficiency:")
            lines.append(f"    Tokens/iteration: {m.total_tokens / ctx.iteration:,.0f}")
            lines.append(f"    LLM calls/iteration: {m.llm_calls / ctx.iteration:.1f}")
            if m.tool_calls > 0:
                lines.append(f"    Cost/tool call: ${m.estimated_cost / m.tool_calls:.4f}")
        return CommandResult(output="\n".join(lines))

    if arg == "issues":
        if not ctx:
            return CommandResult(output="No active context for issue detection.")

        m = ctx.metrics
        issues: list[str] = []

        # Check for common problems
        if ctx.iteration > 0 and m.total_tokens / ctx.iteration > 5000:
            issues.append("High token usage per iteration (>5000 avg)")
        if m.llm_calls > 0 and m.tool_calls > 0:
            ratio = m.llm_calls / m.tool_calls
            if ratio > 2.0:
                issues.append(f"LLM-to-tool ratio is high ({ratio:.1f}x)")
        if m.tool_calls > 0 and m.estimated_cost / m.tool_calls > 0.05:
            issues.append("High cost per tool call (>$0.05)")
        err_count = getattr(m, "error_count", 0)
        if err_count > 3:
            issues.append(f"Many errors ({err_count})")

        if not issues:
            return CommandResult(output="No issues detected. Session looks healthy.")

        lines = ["Detected issues:"]
        for issue in issues:
            lines.append(f"  - {issue}")
        return CommandResult(output="\n".join(lines))

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "export":
        if not ctx:
            return CommandResult(output="No active context.")

        import json
        import time as _time

        data: dict[str, Any] = {
            "iteration": ctx.iteration,
            "metrics": {
                "total_tokens": ctx.metrics.total_tokens,
                "llm_calls": ctx.metrics.llm_calls,
                "tool_calls": ctx.metrics.tool_calls,
                "estimated_cost": ctx.metrics.estimated_cost,
                "duration_ms": ctx.metrics.duration_ms,
            },
            "message_count": len(ctx.messages),
        }

        if collector:
            try:
                summary = collector.get_summary()
                data["trace_summary"] = {
                    "session_id": getattr(summary, "session_id", ""),
                    "total_events": getattr(summary, "total_events", 0),
                    "error_count": getattr(summary, "error_count", 0),
                }
            except Exception:
                pass

        export_path = subarg or f".attocode/traces/export-{int(_time.time())}.json"
        try:
            p = Path(export_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2))
            return CommandResult(output=f"Trace exported to {export_path}")
        except Exception as e:
            return CommandResult(output=f"Export failed: {e}")

    return CommandResult(output="Trace subcommands: summary, analyze, issues, export [path]")


async def _grants_command(agent: Any) -> CommandResult:
    ctx = _get_ctx(agent)
    policy = getattr(ctx, "policy_engine", None) if ctx else None

    lines: list[str] = []

    # In-memory grants from policy engine
    if policy:
        approved = getattr(policy, "_approved_commands", set())
        if approved:
            lines.append("In-memory permissions:")
            for cmd in sorted(approved):
                lines.append(f"  {cmd}")

    # DB-persisted grants from session store
    store = getattr(ctx, "session_store", None) if ctx else None
    sid = getattr(ctx, "session_id", None) if ctx else None
    if store and sid:
        try:
            perms = await store.list_permissions(sid)
            if perms:
                lines.append("\nPersisted permissions:" if lines else "Persisted permissions:")
                for p in perms:
                    expires = " (expires)" if p.expires_at else ""
                    lines.append(f"  {p.tool_name} [{p.permission_type}] pattern={p.pattern}{expires}")
        except Exception:
            pass

    if not lines:
        if not policy:
            return CommandResult(output="No policy engine configured (all tools auto-approved).")
        return CommandResult(output="No remembered permissions.")

    return CommandResult(output="\n".join(lines))


async def _audit_command(agent: Any) -> CommandResult:
    """Show recent tool call audit log."""
    ctx = _get_ctx(agent)
    store = getattr(ctx, "session_store", None) if ctx else None
    sid = getattr(ctx, "session_id", None) if ctx else None

    if not store or not sid:
        return CommandResult(output="Session persistence not configured (audit requires a session store).")

    try:
        calls = await store.list_tool_calls(sid)
        if not calls:
            return CommandResult(output="No tool calls recorded in this session.")

        # Show most recent 20
        recent = calls[-20:] if len(calls) > 20 else calls
        lines = [f"Recent tool calls ({len(recent)} of {len(calls)}):"]
        for tc in recent:
            import datetime
            ts = datetime.datetime.fromtimestamp(tc.timestamp).strftime("%H:%M:%S") if tc.timestamp else "?"
            status = "ok" if tc.approved else "denied"
            danger = f" [{tc.danger_level}]" if tc.danger_level != "safe" else ""
            dur = f" {tc.duration_ms}ms" if tc.duration_ms else ""
            lines.append(f"  {ts} {tc.tool_name}{danger} ({status}){dur}")
        return CommandResult(output="\n".join(lines))
    except Exception as e:
        return CommandResult(output=f"Error: {e}")


def _tasks_command(app: Any) -> CommandResult:
    """Toggle tasks panel visibility in TUI."""
    if not app:
        return CommandResult(output="Tasks panel requires TUI mode.")
    if hasattr(app, "action_toggle_tasks"):
        try:
            app.action_toggle_tasks()
            return CommandResult(output="Tasks panel toggled.")
        except Exception as e:
            return CommandResult(output=f"Failed to toggle tasks panel: {e}")
    return CommandResult(output="Tasks panel is not supported by this app.")


def _debug_command(app: Any) -> CommandResult:
    """Toggle debug/internals panel visibility in TUI."""
    if not app:
        return CommandResult(output="Debug panel requires TUI mode.")
    if hasattr(app, "action_toggle_debug"):
        try:
            app.action_toggle_debug()
            return CommandResult(output="Debug panel toggled.")
        except Exception as e:
            return CommandResult(output=f"Failed to toggle debug panel: {e}")
    if hasattr(app, "action_toggle_internals"):
        try:
            app.action_toggle_internals()
            return CommandResult(output="Debug panel toggled.")
        except Exception as e:
            return CommandResult(output=f"Failed to toggle debug panel: {e}")
    return CommandResult(output="Debug panel is not supported by this app.")


def _undo_command(agent: Any, arg: str) -> CommandResult:
    ctx = _get_ctx(agent)
    tracker = getattr(ctx, "file_change_tracker", None) if ctx else None

    if not tracker:
        return _feature_unavailable("Undo system")

    if not arg:
        result = tracker.undo_last_change()
        return CommandResult(output=result)

    if arg == "history":
        return CommandResult(output=tracker.format_history())

    if arg == "turn":
        result = tracker.undo_current_turn()
        return CommandResult(output=result)

    # Treat arg as a file path
    result = tracker.undo_file(arg)
    return CommandResult(output=result)


def _diff_command(agent: Any, arg: str) -> CommandResult:
    """Show recent file changes."""
    ctx = _get_ctx(agent)
    tracker = getattr(ctx, "file_change_tracker", None) if ctx else None

    if not tracker:
        return _feature_unavailable("File change tracking")

    history = tracker.format_history()
    if not history or history == "No changes":
        return CommandResult(output="No file changes in this session.")

    return CommandResult(output=history)


# ============================================================
# Capabilities command handler
# ============================================================

def _powers_command(agent: Any, arg: str) -> CommandResult:
    """Show capabilities summary or model-specific capabilities."""
    if arg:
        # Model-specific capabilities
        try:
            from attocode.integrations.utilities.capabilities import get_capabilities
            caps = get_capabilities(arg)
            lines = [
                f"Model: {caps.model_id}",
                f"  Max input tokens: {caps.max_input_tokens:,}",
                f"  Max output tokens: {caps.max_output_tokens:,}",
                f"  System prompt: {'yes' if caps.supports_system_prompt else 'no'}",
                f"  Tool use: {'yes' if caps.can_use_tools else 'no'}",
                f"  Vision: {'yes' if caps.can_see_images else 'no'}",
                f"  Streaming: {'yes' if caps.can_stream else 'no'}",
                f"  Extended thinking: {'yes' if caps.can_think else 'no'}",
            ]
            if caps.capabilities:
                lines.append(f"  All capabilities: {', '.join(sorted(str(c) for c in caps.capabilities))}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error getting capabilities for '{arg}': {e}")

    # General overview
    ctx = _get_ctx(agent)
    lines = ["Agent capabilities:"]

    # Count tools
    registry = getattr(ctx, "registry", None) if ctx else None
    if registry:
        all_tools = registry.list_tools()
        mcp_tools = [t for t in all_tools if "mcp" in getattr(t, "tags", [])]
        builtin_tools = len(all_tools) - len(mcp_tools)
        lines.append(f"  Built-in tools: {builtin_tools}")
        lines.append(f"  MCP tools: {len(mcp_tools)}")
    else:
        lines.append("  Tools: (no registry)")

    # Count skills
    try:
        loader = _get_skill_loader(agent)
        if loader:
            skills = loader.list_skills()
            lines.append(f"  Skills: {len(skills)}")
        else:
            lines.append("  Skills: (no working dir)")
    except Exception:
        lines.append("  Skills: (load error)")

    # Count agents
    try:
        agent_reg = _get_agent_registry(agent)
        agents = agent_reg.list_agents()
        lines.append(f"  Agents: {len(agents)}")
    except Exception:
        lines.append("  Agents: (load error)")

    # Known models
    try:
        from attocode.integrations.utilities.capabilities import list_known_models
        models = list_known_models()
        lines.append(f"  Known models: {len(models)}")
    except Exception:
        pass

    return CommandResult(output="\n".join(lines))


# ============================================================
# Info command handlers
# ============================================================

def _sandbox_command(agent: Any) -> CommandResult:
    """Show sandbox configuration."""
    config = getattr(agent, "_config", None) if agent else None
    sandbox_cfg = getattr(config, "sandbox", None) if config else None

    lines = ["Sandbox:"]
    if sandbox_cfg:
        mode = getattr(sandbox_cfg, "mode", "unknown")
        lines.append(f"  Mode: {mode}")
        network = getattr(sandbox_cfg, "network_allowed", False)
        lines.append(f"  Network: {'allowed' if network else 'blocked'}")
        timeout = getattr(sandbox_cfg, "timeout", 60000)
        lines.append(f"  Timeout: {timeout}ms")
    else:
        lines.append("  Mode: auto (default)")

    lines.append("\n  Available implementations:")
    import platform
    system = platform.system()
    if system == "Darwin":
        lines.append("    - Seatbelt (macOS sandbox-exec)")
    elif system == "Linux":
        lines.append("    - Landlock (Linux LSM)")
    lines.append("    - Docker (cross-platform)")
    lines.append("    - Basic (allowlist fallback)")

    return CommandResult(output="\n".join(lines))


def _lsp_command(agent: Any) -> CommandResult:
    """Show LSP integration status."""
    lines = ["LSP integration:"]
    try:
        from attocode.integrations.lsp import lsp  # noqa: F401
        lines.append("  Module: available")
    except ImportError:
        lines.append("  Module: not available")

    lines.append("  Status: LSP integration provides:")
    lines.append("    - Go-to-definition")
    lines.append("    - Find references")
    lines.append("    - Hover information")
    lines.append("    - Diagnostics")
    lines.append("    - Symbol search")
    return CommandResult(output="\n".join(lines))


def _tui_command() -> CommandResult:
    """Show TUI feature list."""
    return CommandResult(output=(
        "TUI features:\n"
        "\n"
        "Panels:\n"
        "  - Chat panel (main interaction)\n"
        "  - Status bar (context %, budget %, model)\n"
        "  - Tool call display (expandable)\n"
        "  - Thinking display (toggle with Alt+O)\n"
        "  - Dashboard (Ctrl+D) — live monitoring, session browser, analysis\n"
        "\n"
        "Dialogs:\n"
        "  - Tool approval dialog\n"
        "  - Budget extension dialog\n"
        "  - Learning validation dialog\n"
        "  - Setup wizard\n"
        "  - API key dialog\n"
        "  - Command palette (Ctrl+P)\n"
        "\n"
        "Keyboard shortcuts:\n"
        "  Ctrl+C    Exit\n"
        "  Ctrl+D    Toggle dashboard (live metrics, sessions, analysis)\n"
        "  Ctrl+L    Clear screen\n"
        "  Ctrl+P    Command palette\n"
        "  Escape    Cancel current operation\n"
        "  Ctrl+T    Toggle tool details\n"
        "  Ctrl+I    Toggle debug panel"
    ))


def _dashboard_command(app: Any) -> CommandResult:
    """Open the dashboard screen."""
    if not app:
        return CommandResult(output="Dashboard requires TUI mode. Use Ctrl+D in TUI.")

    try:
        app.action_toggle_dashboard()
        return CommandResult(output="Dashboard opened. Press Escape to return to chat.")
    except Exception as e:
        return CommandResult(output=f"Failed to open dashboard: {e}")


# ============================================================
# Swarm command handlers
# ============================================================


async def _swarm_command(agent: Any, arg: str, app: Any) -> CommandResult:
    """Route /swarm subcommands."""
    if not arg:
        # No args: show status if swarm running, else show help
        orch = getattr(agent, "_swarm_orchestrator", None) if agent else None
        if orch:
            return _swarm_status(agent)
        return CommandResult(output=_swarm_help())

    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower()
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "init":
        return _swarm_init(agent)
    if subcmd == "start":
        return await _swarm_start(agent, subarg, app)
    if subcmd == "status":
        return _swarm_status(agent)
    if subcmd == "stop":
        return _swarm_stop(agent)
    if subcmd == "dashboard":
        return _swarm_dashboard(app)
    if subcmd == "config":
        return _swarm_config_show(agent)
    if subcmd == "help":
        return CommandResult(output=_swarm_help())

    return CommandResult(output=f"Unknown swarm subcommand: {subcmd}\n\n{_swarm_help()}")


def _swarm_help() -> str:
    """Return swarm command help text."""
    return (
        "Swarm commands:\n"
        "  /swarm              Show swarm status (or this help if idle)\n"
        "  /swarm init         Generate .attocode/swarm.yaml from your current model\n"
        "  /swarm start <task> Start a swarm execution with the given prompt\n"
        "  /swarm status       Show running swarm state\n"
        "  /swarm stop         Cancel running swarm\n"
        "  /swarm dashboard    Open swarm dashboard (Ctrl+S)\n"
        "  /swarm config       Show current swarm configuration\n"
        "\n"
        "Quick start:\n"
        "  /swarm start Build a REST API with tests\n"
        "\n"
        "The swarm works with zero config — it uses your current model\n"
        "for the orchestrator and all workers. Use /swarm init to\n"
        "customize worker count, models, or quality gates."
    )


def _swarm_init(agent: Any) -> CommandResult:
    """Generate .attocode/swarm.yaml using the user's current model."""
    wd = _get_working_dir(agent)
    if not wd:
        wd = os.getcwd()

    # Get model from agent config
    model = "anthropic/claude-sonnet-4-20250514"
    config = getattr(agent, "_config", None) if agent else None
    if config:
        model = getattr(config, "model", None) or model

    base = Path(wd) / ".attocode"
    base.mkdir(parents=True, exist_ok=True)

    yaml_path = base / "swarm.yaml"
    if yaml_path.exists():
        # Show existing config and ask about overwrite
        try:
            existing = yaml_path.read_text()
            return CommandResult(
                output=f"Swarm config already exists at {yaml_path}\n\n"
                f"Current contents:\n{existing}\n"
                "Delete the file and run /swarm init again to regenerate."
            )
        except Exception:
            pass

    yaml_content = (
        f"# Swarm configuration — auto-generated by /swarm init\n"
        f"# Model auto-detected from your current session: {model}\n"
        f"\n"
        f"models:\n"
        f"  orchestrator: {model}\n"
        f"\n"
        f"workers:\n"
        f"  - name: builder\n"
        f"    model: {model}\n"
        f"    capabilities: [code, test]\n"
        f"    count: 2\n"
        f"  - name: reviewer\n"
        f"    model: {model}\n"
        f"    capabilities: [review, research]\n"
        f"    count: 1\n"
        f"\n"
        f"budget:\n"
        f"  totalTokens: 5000000\n"
        f"  maxCost: 10.0\n"
        f"  maxConcurrency: 2\n"
        f"\n"
        f"quality:\n"
        f"  enabled: true\n"
        f"\n"
        f"features:\n"
        f"  planning: true\n"
        f"  verification: true\n"
    )
    yaml_path.write_text(yaml_content)

    return CommandResult(
        output=f"Created {yaml_path}\n"
        f"  Orchestrator: {model}\n"
        f"  Workers: 2 builders + 1 reviewer (all using {model})\n"
        f"  Budget: $10 / 5M tokens, concurrency 2\n"
        f"  Quality gates: enabled\n"
        f"\n"
        f"Start with: /swarm start <your task>"
    )


async def _swarm_start(agent: Any, prompt: str, app: Any) -> CommandResult:
    """Start a swarm execution with the given prompt."""
    if not prompt:
        return CommandResult(
            output="Usage: /swarm start <task description>\n"
            "Example: /swarm start Build a REST API with authentication and tests"
        )

    if agent is None:
        return CommandResult(output="No agent running.")

    # Check if swarm is already running
    orch = getattr(agent, "_swarm_orchestrator", None)
    if orch:
        phase = "unknown"
        try:
            state = orch.get_state()
            phase = getattr(state, "phase", "unknown")
        except Exception:
            pass
        if phase not in ("idle", "completed", "failed", "unknown"):
            return CommandResult(
                output=f"Swarm is already running (phase: {phase}).\n"
                "Use /swarm stop to cancel, or wait for completion."
            )

    # Enable swarm mode on the config
    config = getattr(agent, "_config", None)
    if config:
        config.swarm_enabled = True  # type: ignore[attr-defined]

    # Submit through the TUI callback (same path as regular prompt)
    if app and hasattr(app, "_on_submit") and app._on_submit:
        # Add as user message and trigger agent via the TUI's submit path
        try:
            log = app.query_one("#message-log")
            log.add_user_message(f"[swarm] {prompt}")
        except Exception:
            pass
        app._processing = True
        try:
            app.query_one("#input-area").set_enabled(False)
        except Exception:
            pass
        try:
            app.query_one("#status-bar").start_processing()
        except Exception:
            pass
        app._on_submit(prompt)
        return CommandResult(
            output=f"Swarm started: {prompt[:80]}{'...' if len(prompt) > 80 else ''}\n"
            "Use /swarm status to monitor progress, or Ctrl+S for the dashboard."
        )

    # Fallback: run directly if no TUI app
    try:
        result = await agent.run(prompt)
        success = "succeeded" if result.success else "failed"
        metrics = result.metrics
        tokens = metrics.total_tokens if metrics else 0
        cost = metrics.estimated_cost if metrics else 0.0
        return CommandResult(
            output=f"Swarm {success}.\n"
            f"  Tokens: {tokens:,}\n"
            f"  Cost: ${cost:.4f}\n"
            f"  Response: {result.response[:200] if result.response else '(none)'}"
        )
    except Exception as e:
        return CommandResult(output=f"Swarm execution failed: {e}")
    finally:
        # Reset swarm_enabled so the next regular prompt doesn't go to swarm
        if config:
            config.swarm_enabled = False  # type: ignore[attr-defined]


def _swarm_status(agent: Any) -> CommandResult:
    """Show current swarm state."""
    if agent is None:
        return CommandResult(output="No agent running.")

    orch = getattr(agent, "_swarm_orchestrator", None)
    if not orch:
        return CommandResult(
            output="No swarm session active.\n"
            "Use /swarm start <task> to begin."
        )

    lines = ["Swarm status:"]

    try:
        state = orch.get_state()

        phase = getattr(state, "phase", "unknown")
        lines.append(f"  Phase: {phase}")

        current_wave = getattr(state, "current_wave", None)
        if current_wave is not None:
            lines.append(f"  Wave: {current_wave}")

        active_workers = getattr(state, "active_workers", None)
        if active_workers is not None:
            lines.append(f"  Active workers: {active_workers}")

        # Queue stats
        queue = getattr(state, "queue", None)
        if queue:
            completed = getattr(queue, "completed", 0)
            total = getattr(queue, "total", 0)
            failed = getattr(queue, "failed", 0)
            lines.append(f"  Tasks: {completed}/{total} completed"
                         + (f", {failed} failed" if failed else ""))

        # Budget
        budget_info = getattr(state, "budget", None)
        if budget_info:
            tokens_used = getattr(budget_info, "tokens_used", 0)
            cost = getattr(budget_info, "cost", 0.0)
            lines.append(f"  Tokens: {tokens_used:,}")
            lines.append(f"  Cost: ${cost:.4f}")

        # Orchestrator status
        orch_status = getattr(state, "orchestrator_status", None)
        if orch_status:
            lines.append(f"  Orchestrator: {orch_status}")

    except Exception as e:
        lines.append(f"  (Error reading state: {e})")

    # Event bridge stats
    bridge = getattr(agent, "_event_bridge", None)
    if bridge:
        try:
            last_status = getattr(bridge, "last_status", None)
            if last_status:
                lines.append(f"  Last event: {getattr(last_status, 'phase', 'n/a')}")
        except Exception:
            pass

    return CommandResult(output="\n".join(lines))


def _swarm_stop(agent: Any) -> CommandResult:
    """Cancel a running swarm."""
    if agent is None:
        return CommandResult(output="No agent running.")

    orch = getattr(agent, "_swarm_orchestrator", None)
    if not orch:
        return CommandResult(output="No swarm session to stop.")

    try:
        if hasattr(orch, "cancel"):
            orch.cancel()
            return CommandResult(output="Swarm cancellation requested.")
        return CommandResult(output="Swarm orchestrator does not support cancel.")
    except Exception as e:
        return CommandResult(output=f"Failed to stop swarm: {e}")


def _swarm_dashboard(app: Any) -> CommandResult:
    """Open the swarm dashboard screen."""
    if not app:
        return CommandResult(output="Swarm dashboard requires TUI mode. Use Ctrl+S in TUI.")

    try:
        if hasattr(app, "action_swarm_dashboard"):
            app.action_swarm_dashboard()
        else:
            app.action_toggle_swarm_monitor()
        return CommandResult(output="Swarm dashboard opened. Press Escape to return.")
    except Exception as e:
        return CommandResult(output=f"Failed to open dashboard: {e}")


def _swarm_config_show(agent: Any) -> CommandResult:
    """Show current swarm configuration."""
    lines = ["Swarm configuration:"]

    # Check for YAML config file
    wd = _get_working_dir(agent) or os.getcwd()
    yaml_path = Path(wd) / ".attocode" / "swarm.yaml"
    if yaml_path.exists():
        lines.append(f"  Config file: {yaml_path}")
        try:
            from attocode.integrations.swarm.config_loader import load_swarm_yaml_config
            raw = load_swarm_yaml_config(wd)
            if raw:
                models = raw.get("models", {})
                if isinstance(models, dict):
                    lines.append(f"  Orchestrator model: {models.get('orchestrator', 'default')}")
                workers = raw.get("workers", [])
                if isinstance(workers, list):
                    total = sum(w.get("count", 1) for w in workers if isinstance(w, dict))
                    lines.append(f"  Workers: {total}")
                    for w in workers:
                        if isinstance(w, dict):
                            name = w.get("name", "worker")
                            model = w.get("model", "default")
                            caps = w.get("capabilities", [])
                            count = w.get("count", 1)
                            lines.append(
                                f"    {name} x{count}: {model} [{', '.join(caps)}]"
                            )
                budget = raw.get("budget", {})
                if isinstance(budget, dict):
                    cost = budget.get("maxCost", budget.get("max_cost", "?"))
                    conc = budget.get("maxConcurrency", budget.get("max_concurrency", "?"))
                    lines.append(f"  Max cost: ${cost}")
                    lines.append(f"  Concurrency: {conc}")
                quality = raw.get("quality", {})
                if isinstance(quality, dict):
                    lines.append(f"  Quality gates: {quality.get('enabled', False)}")
                elif isinstance(quality, bool):
                    lines.append(f"  Quality gates: {quality}")
        except Exception:
            lines.append("  (Could not parse config file)")
    else:
        lines.append("  Config file: not found (using defaults)")

    # Show runtime model info
    config = getattr(agent, "_config", None) if agent else None
    if config:
        model = getattr(config, "model", None) or "default"
        lines.append(f"  Runtime model: {model}")
        lines.append("  Defaults: 2 builders + 1 reviewer (all use runtime model)")

    return CommandResult(output="\n".join(lines))


def _swarm_monitor_command(app: Any, arg: str) -> CommandResult:
    """Open the swarm fleet monitor screen."""
    if not app:
        return CommandResult(output="Swarm Monitor requires TUI mode.")
    try:
        if arg.strip():
            from attocode.tui.screens.swarm_monitor import SwarmMonitorScreen

            app.push_screen(SwarmMonitorScreen(root=arg.strip()))
        else:
            app.action_toggle_swarm_monitor()
        return CommandResult(output="Swarm Monitor opened. Press Escape to return.")
    except Exception as e:
        return CommandResult(output=f"Failed to open Swarm Monitor: {e}")


# ============================================================
# Config command handlers
# ============================================================

async def _init_command(agent: Any) -> CommandResult:
    """Initialize .attocode/ directory structure."""
    ctx = _get_ctx(agent)
    wd = getattr(ctx, "working_dir", None) if ctx else None
    wd = wd or os.getcwd()

    base = Path(wd) / ".attocode"
    dirs = ["skills", "agents"]
    files: dict[str, str] = {
        "config.json": '{\n  "model": null,\n  "sandbox": { "mode": "auto" }\n}\n',
        "rules.md": "# Project Rules\n\nAdd project-specific rules here.\n",
    }

    # Auto-generate swarm.yaml with user's current model
    model = "anthropic/claude-sonnet-4-20250514"
    config = getattr(agent, "_config", None) if agent else None
    if config:
        model = getattr(config, "model", None) or model

    files["swarm.yaml"] = (
        f"# Swarm configuration — auto-generated by /init\n"
        f"# Model auto-detected from your current session: {model}\n"
        f"\n"
        f"models:\n"
        f"  orchestrator: {model}\n"
        f"\n"
        f"workers:\n"
        f"  - name: builder\n"
        f"    model: {model}\n"
        f"    capabilities: [code, test]\n"
        f"    count: 2\n"
        f"  - name: reviewer\n"
        f"    model: {model}\n"
        f"    capabilities: [review, research]\n"
        f"    count: 1\n"
        f"\n"
        f"budget:\n"
        f"  totalTokens: 5000000\n"
        f"  maxCost: 10.0\n"
        f"  maxConcurrency: 2\n"
        f"\n"
        f"quality:\n"
        f"  enabled: true\n"
        f"\n"
        f"features:\n"
        f"  planning: true\n"
        f"  verification: true\n"
    )

    created = []
    for d in dirs:
        p = base / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p.relative_to(wd)))

    for name, content in files.items():
        p = base / name
        if not p.exists():
            p.write_text(content)
            created.append(str(p.relative_to(wd)))

    if not created:
        return CommandResult(output=f".attocode/ already initialized at {base}")

    return CommandResult(output="Initialized .attocode/ with:\n" + "\n".join(f"  {c}" for c in created))


async def _config_command(agent: Any, arg: str, app: Any) -> CommandResult:
    """Route /config subcommands."""
    if not arg:
        return _config_show(agent)

    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower()
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "provider":
        return _config_set_provider(agent, subarg)
    if subcmd == "model":
        return _config_set_model(agent, subarg)
    if subcmd in ("api-key", "apikey", "key"):
        return await _config_api_key(agent, app)
    if subcmd == "save":
        return _config_save(agent)

    return CommandResult(
        output="Config subcommands: (none)=show, provider <name>, model <name>, api-key, save"
    )


def _config_show(agent: Any) -> CommandResult:
    """Display current config."""
    from attocode.config import get_user_config_dir

    config = getattr(agent, "_config", None) if agent else None
    if not config:
        return CommandResult(output="No config available (no agent running).")

    provider = getattr(config, "provider", "unknown")
    model = getattr(config, "model", "unknown")
    api_key = getattr(config, "api_key", None) or ""

    # Mask the key
    if len(api_key) > 8:
        masked = api_key[:4] + "..." + api_key[-4:]
    elif api_key:
        masked = "****"
    else:
        masked = "(not set)"

    config_path = get_user_config_dir() / "config.json"
    exists = config_path.exists()

    lines = [
        "Current configuration:",
        f"  Provider:    {provider}",
        f"  Model:       {model}",
        f"  API key:     {masked}",
        f"  Config file: {config_path} ({'exists' if exists else 'not created'})",
    ]
    return CommandResult(output="\n".join(lines))


def _config_set_provider(agent: Any, name: str) -> CommandResult:
    """Switch provider and persist globally."""
    from attocode.config import PROVIDER_MODEL_DEFAULTS, save_global_config

    if not name:
        return CommandResult(output="Usage: /config provider <anthropic|openrouter|openai|zai>")

    name = name.lower()
    valid = ("anthropic", "openrouter", "openai", "zai")
    if name not in valid:
        return CommandResult(output=f"Unknown provider '{name}'. Valid: {', '.join(valid)}")

    save_global_config({"provider": name})
    default_model = PROVIDER_MODEL_DEFAULTS.get(name, "")

    config = getattr(agent, "_config", None) if agent else None
    if config:
        config.provider = name

    return CommandResult(
        output=f"Provider set to: {name}\n"
        f"Default model for this provider: {default_model}\n"
        f"Note: Provider change may require restart to take effect for new LLM calls."
    )


def _config_set_model(agent: Any, name: str) -> CommandResult:
    """Switch model and persist globally."""
    from attocode.config import save_global_config

    if not name:
        return CommandResult(output="Usage: /config model <model-name>")

    save_global_config({"model": name})

    config = getattr(agent, "_config", None) if agent else None
    if config:
        config.model = name

    return CommandResult(output=f"Model set to: {name} (persisted globally)")


async def _config_api_key(agent: Any, app: Any) -> CommandResult:
    """Push ApiKeyDialog to re-enter API key."""
    if not app:
        return CommandResult(
            output="API key dialog requires TUI mode.\n"
            "Set manually: /config save or edit ~/.attocode/config.json"
        )

    from attocode.tui.dialogs.setup import ApiKeyDialog

    result_holder: list[str] = []

    def _on_result(key: str) -> None:
        result_holder.append(key)

    app.push_screen(ApiKeyDialog(), callback=_on_result)

    # The dialog saves the key itself on submit.
    # We can't await the modal from here, so just inform the user.
    return CommandResult(output="API key dialog opened. Enter your new key.")


def _config_save(agent: Any) -> CommandResult:
    """Persist full runtime config globally."""
    from attocode.config import save_global_config

    config = getattr(agent, "_config", None) if agent else None
    if not config:
        return CommandResult(output="No config available (no agent running).")

    data: dict[str, Any] = {}
    for attr in ("provider", "model", "api_key"):
        val = getattr(config, attr, None)
        if val:
            data[attr] = val

    if not data:
        return CommandResult(output="Nothing to save — no provider/model/key set in runtime.")

    path = save_global_config(data)
    return CommandResult(output=f"Runtime config saved to {path}")


async def _setup_command(agent: Any, app: Any) -> CommandResult:
    """Launch the setup wizard from within the TUI."""
    if not app:
        return CommandResult(output="Setup wizard requires TUI mode.")

    from attocode.config import save_global_config
    from attocode.tui.dialogs.setup import SetupResult, SetupWizard

    def _on_result(result: SetupResult) -> None:
        if not result.completed:
            return
        save_global_config({
            "provider": result.provider,
            "api_key": result.api_key,
            "model": result.model,
        })
        config = getattr(agent, "_config", None) if agent else None
        if config:
            config.provider = result.provider
            config.api_key = result.api_key
            config.model = result.model

    app.push_screen(SetupWizard(), callback=_on_result)
    return CommandResult(output="Setup wizard opened.")


def _theme_command(app: Any, arg: str) -> CommandResult:
    if not app:
        return CommandResult(output="Theme switching requires TUI mode.")

    if not arg:
        current = getattr(app, "active_theme_name", "default")
        return CommandResult(output=f"Current theme: {current}")

    # Try to switch theme
    if hasattr(app, "set_theme"):
        app.set_theme(arg)
        return CommandResult(output=f"Theme switched to: {arg}")

    return CommandResult(output="Theme switching not supported by this app.")


# ============================================================
# New feature command handlers (F2-F13 wiring)
# ============================================================


def _define_tool_command(agent: Any, arg: str) -> CommandResult:
    """Handle /define-tool — list or describe dynamic tool capabilities."""
    ctx = getattr(agent, "context", None)
    dynamic_reg = getattr(ctx, "dynamic_tools", None) if ctx else None

    if not arg:
        if dynamic_reg is None:
            return CommandResult(output="Dynamic tools not initialized.")
        tools = dynamic_reg.list_tools()
        if not tools:
            return CommandResult(output="No dynamic tools defined. Use /define-tool <name> to create one.")
        lines = ["Dynamic tools:"]
        for t in tools:
            lines.append(f"  {t['name']}: {t['description']}")
        return CommandResult(output="\n".join(lines))

    return CommandResult(
        output=(
            "To define a dynamic tool, describe it in your message and the agent "
            "will use the DynamicToolRegistry to create it.\n"
            f"Requested: {arg}"
        )
    )


def _scaffold_mcp_command(agent: Any, arg: str) -> CommandResult:
    """Handle /scaffold-mcp — scaffold a local MCP server."""
    if not arg:
        return CommandResult(output="Usage: /scaffold-mcp <server-name>\nScaffolds a local MCP server in .attocode/mcp-servers/")

    from attocode.integrations.mcp.scaffolder import MCPScaffolder

    ctx = getattr(agent, "context", None)
    project_root = getattr(ctx, "project_root", "") if ctx else ""
    if not project_root:
        return CommandResult(output="No project root found. Run from a project directory.")

    from pathlib import Path
    servers_dir = Path(project_root) / ".attocode" / "mcp-servers"
    scaffolder = MCPScaffolder(servers_dir=servers_dir)
    existing = scaffolder.list_servers()
    if existing:
        lines = ["Existing MCP servers:"]
        for s in existing:
            lines.append(f"  {s['name']}: {s['description']} ({s['tools']} tools)")
        lines.append(f"\nTo create '{arg}', describe the tools in your message.")
        return CommandResult(output="\n".join(lines))

    return CommandResult(
        output=f"Ready to scaffold MCP server '{arg}'. Describe the tools it should have."
    )


def _parallel_command(agent: Any, arg: str) -> CommandResult:
    """Handle /parallel — spawn parallel agents for independent tasks."""
    if not arg:
        return CommandResult(
            output="Usage: /parallel task1 | task2 | task3\nSpawns agents in isolated git worktrees."
        )

    from attocode.core.parallel_agents import ParallelAgentManager

    mgr = ParallelAgentManager()
    tasks = mgr.parse_tasks(arg)
    lines = [f"Parsed {len(tasks)} parallel tasks:"]
    for t in tasks:
        lines.append(f"  [{t.id}] {t.description}")
    lines.append("\nParallel execution would spawn each in an isolated git worktree.")
    return CommandResult(output="\n".join(lines))


def _bugfind_command(agent: Any, arg: str) -> CommandResult:
    """Handle /bugfind — scan diff for potential bugs."""
    import subprocess

    base_branch = arg.strip() or "main"
    try:
        result = subprocess.run(
            ["git", "diff", f"{base_branch}...HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff_text = result.stdout
    except Exception as e:
        return CommandResult(output=f"Failed to get diff: {e}")

    if not diff_text:
        return CommandResult(output=f"No diff found between {base_branch} and HEAD.")

    from attocode.code_intel.bug_finder import scan_diff

    report = scan_diff(diff_text)
    return CommandResult(output=report.format_report())


def _orchestrate_command(agent: Any, arg: str) -> CommandResult:
    """Handle /orchestrate — decompose task across agent modes."""
    if not arg:
        return CommandResult(
            output="Usage: /orchestrate <complex task>\nDecomposes into subtasks assigned to Code/Architect/Debug/Ask modes."
        )

    from attocode.core.orchestrator import Orchestrator

    orch = Orchestrator()
    prompt = orch.create_decomposition_prompt(arg)
    return CommandResult(
        output=f"Orchestrator ready. Decomposition prompt prepared for:\n{arg}\n\n"
        "The agent will break this into mode-specific subtasks."
    )


def _watch_command(agent: Any, arg: str) -> CommandResult:
    """Handle /watch — scan for inline AI trigger comments."""
    from pathlib import Path

    from attocode.agent.watch import FileWatcher, WatchConfig

    ctx = getattr(agent, "context", None)
    project_root = getattr(ctx, "project_root", ".") if ctx else "."

    config = WatchConfig(watch_dirs=[project_root])
    watcher = FileWatcher(config)
    matches = watcher.scan_all()

    if not matches:
        return CommandResult(output="No AI trigger comments found (# AI: ... or // AI: ...).")

    lines = [f"Found {len(matches)} trigger(s):"]
    for m in matches[:20]:
        lines.append(f"  {m.file_path}:{m.line_number} — {m.trigger_text}")
    if len(matches) > 20:
        lines.append(f"  ... and {len(matches) - 20} more")
    return CommandResult(output="\n".join(lines))


def _project_state_command(agent: Any, arg: str) -> CommandResult:
    """Handle /project-state — show or update file-driven project state."""
    ctx = getattr(agent, "context", None)
    project_state = getattr(ctx, "project_state", None) if ctx else None

    if project_state is None:
        # Try to create one on the fly
        project_root = getattr(ctx, "project_root", "") if ctx else ""
        if not project_root:
            return CommandResult(output="No project root found.")
        from pathlib import Path

        from attocode.integrations.persistence.project_state import ProjectStateManager
        project_state = ProjectStateManager(Path(project_root))

    state = project_state.load()
    if state.is_empty:
        return CommandResult(
            output="No project state found. Use '/project-state add <decision>' to record a decision."
        )

    if arg.startswith("add "):
        entry = arg[4:].strip()
        if entry:
            project_state.update_state(entry)
            return CommandResult(output=f"Added to project state: {entry}")

    return CommandResult(output=state.as_context_block() or "Project state is empty.")
