"""Slash commands for the TUI interactive mode.

Provides ~30 slash commands organized into groups:
- Core: /help, /status, /budget, /model, /compact, /save, /clear, /quit
- Session: /sessions, /load, /resume, /checkpoint, /checkpoints
- Mode: /mode, /plan, /approve, /reject
- Agent: /agents, /spawn
- MCP: /mcp
- Skills: /skills
- Context: /context
- Debug: /trace, /grants
- Config: /init, /theme
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CommandResult:
    """Result of a slash command."""

    output: str
    handled: bool = True


def is_command(text: str) -> bool:
    """Check if text is a slash command."""
    return text.strip().startswith("/")


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
        return CommandResult(output="Screen cleared.")

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

    # --- Mode commands ---
    if cmd == "/mode":
        return _mode_command(agent, arg)

    if cmd == "/plan":
        return _plan_command(agent, arg)

    if cmd in ("/approve",):
        return _approve_command(agent, arg)

    if cmd in ("/reject",):
        return _reject_command(agent, arg)

    # --- Agent commands ---
    if cmd == "/agents":
        return _agents_command(agent)

    if cmd == "/spawn":
        return _spawn_command(agent, arg)

    # --- MCP commands ---
    if cmd == "/mcp":
        return _mcp_command(agent, arg)

    # --- Skills commands ---
    if cmd == "/skills":
        return _skills_command(agent, arg)

    # --- Context commands ---
    if cmd == "/context":
        return _context_command(agent, arg)

    # --- Debug commands ---
    if cmd == "/trace":
        return _trace_command(agent, arg)

    if cmd == "/grants":
        return _grants_command(agent)

    if cmd == "/undo":
        return _undo_command(agent, arg)

    if cmd == "/diff":
        return _diff_command(agent, arg)

    # --- Config commands ---
    if cmd == "/init":
        return await _init_command(agent)

    if cmd == "/theme":
        return _theme_command(app, arg)

    if cmd == "/config":
        return await _config_command(agent, arg, app)

    if cmd == "/setup":
        return await _setup_command(agent, app)

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
        "\n"
        "Mode:\n"
        "  /mode [name]      Show or switch mode (build/plan/review/debug)\n"
        "  /plan             Show the current plan\n"
        "  /approve [n|all]  Approve proposed change(s)\n"
        "  /reject [n|all]   Reject proposed change(s)\n"
        "\n"
        "Agent:\n"
        "  /agents           List registered agents\n"
        "  /spawn <task>     Spawn a subagent for a task\n"
        "\n"
        "Tools:\n"
        "  /mcp [subcmd]     MCP server management (list/connect/disconnect)\n"
        "  /skills [subcmd]  List or manage skills (list/info <name>)\n"
        "  /undo [path]      Undo last file change (or specific file)\n"
        "\n"
        "Context:\n"
        "  /context [sub]    Show context info (breakdown for token details)\n"
        "\n"
        "Debug:\n"
        "  /trace [subcmd]   Trace inspection (list/analyze/export)\n"
        "  /grants           Show remembered permissions\n"
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

    ctx.budget = ctx.budget.__class__(
        max_tokens=ctx.budget.max_tokens + amount,
        max_iterations=ctx.budget.max_iterations,
        max_cost=ctx.budget.max_cost,
    )
    return CommandResult(output=f"Budget extended by {amount:,} tokens. New max: {ctx.budget.max_tokens:,}")


def _model_command(agent: Any, arg: str) -> CommandResult:
    if agent is None:
        return CommandResult(output="No agent running.")

    if not arg:
        model = "unknown"
        if agent and hasattr(agent, "config"):
            model = agent.config.model or "default"
        return CommandResult(output=f"Model: {model}")

    # Switch model
    if hasattr(agent, "_config"):
        agent._config.model = arg
        return CommandResult(output=f"Switched model to: {arg}")
    return CommandResult(output="Cannot switch model on this agent.")


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
    ctx = getattr(agent, "context", None) if agent else None
    store = getattr(ctx, "session_store", None) if ctx else None

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

    ctx = getattr(agent, "context", None) if agent else None
    store = getattr(ctx, "session_store", None) if ctx else None

    if not store:
        return CommandResult(output="Session persistence not configured.")

    try:
        session = await store.get_session(session_id)
        if not session:
            return CommandResult(output=f"Session '{session_id}' not found.")

        checkpoint = await store.load_checkpoint(session_id)
        if not checkpoint:
            return CommandResult(output=f"No checkpoint found for session '{session_id}'.")

        return CommandResult(
            output=f"Loaded session {session_id}: {session.task}\n"
            f"  Status: {session.status}\n"
            f"  Messages: {len(checkpoint.messages)}\n"
            f"  Tokens: {session.total_tokens:,}\n"
            f"  Note: Full resume requires agent restart with --resume flag."
        )
    except Exception as e:
        return CommandResult(output=f"Error loading session: {e}")


async def _resume_command(agent: Any, session_id: str) -> CommandResult:
    if not session_id:
        return CommandResult(
            output="Usage: /resume <session_id>\n"
            "Tip: Use /sessions to see available sessions."
        )
    return CommandResult(
        output=f"Session resume for '{session_id}' requires restarting with:\n"
        f"  attocode --resume {session_id}"
    )


async def _checkpoint_command(agent: Any) -> CommandResult:
    return await _save_command(agent)


async def _checkpoints_command(agent: Any, session_id: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    store = getattr(ctx, "session_store", None) if ctx else None

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


# ============================================================
# Mode command handlers
# ============================================================

def _mode_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return CommandResult(output="Mode system not available. Running in default build mode.")

    if not arg:
        return CommandResult(output=f"Current mode: {mode_mgr.mode.value}")

    result = mode_mgr.switch_mode(arg)
    return CommandResult(output=result)


def _plan_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if mode_mgr:
        summary = mode_mgr.format_changes_summary()
        return CommandResult(output=f"Mode: {mode_mgr.mode.value}\n{summary}")

    return CommandResult(output="No plan mode manager available.")


def _approve_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return CommandResult(output="Mode system not available.")

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
        idx = mode_mgr.proposed_changes.index(pending[0])
        return CommandResult(output=mode_mgr.approve_change(idx))
    return CommandResult(output="No pending changes to approve.")


def _reject_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    mode_mgr = getattr(ctx, "mode_manager", None) if ctx else None

    if not mode_mgr:
        return CommandResult(output="Mode system not available.")

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
        idx = mode_mgr.proposed_changes.index(pending[0])
        return CommandResult(output=mode_mgr.reject_change(idx))
    return CommandResult(output="No pending changes to reject.")


# ============================================================
# Agent command handlers
# ============================================================

def _agents_command(agent: Any) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    registry = getattr(ctx, "registry", None) if ctx else None

    if not registry:
        return CommandResult(output="No agent registry available.")

    # Check for agent-tagged tools
    try:
        all_tools = registry.list_tools()
        agent_tools = [t for t in all_tools if "agent" in getattr(t, "tags", [])]
        if not agent_tools:
            return CommandResult(output="No agent tools registered.")

        lines = ["Registered agent tools:"]
        for t in agent_tools:
            lines.append(f"  {t.spec.name}: {t.spec.description[:80]}")
        return CommandResult(output="\n".join(lines))
    except Exception:
        return CommandResult(output="Error listing agents.")


def _spawn_command(agent: Any, task: str) -> CommandResult:
    if not task:
        return CommandResult(output="Usage: /spawn <task description>")
    return CommandResult(
        output=f"Subagent spawning from commands not yet supported.\n"
        f"Use the spawn_agent tool within your prompt instead."
    )


# ============================================================
# MCP command handlers
# ============================================================

def _mcp_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None

    if not arg or arg == "list":
        # List MCP servers
        configs = getattr(ctx, "mcp_server_configs", []) if ctx else []
        if not configs:
            return CommandResult(output="No MCP servers configured.")

        lines = ["MCP servers:"]
        for i, cfg in enumerate(configs):
            name = cfg.get("name", cfg.get("command", "unknown"))
            status = "configured"
            lines.append(f"  [{i}] {name} ({status})")
        return CommandResult(output="\n".join(lines))

    if arg == "tools":
        # List all MCP tools
        registry = getattr(ctx, "registry", None) if ctx else None
        if not registry:
            return CommandResult(output="No tool registry available.")

        tools = registry.list_tools()
        mcp_tools = [t for t in tools if "mcp" in getattr(t, "tags", [])]
        if not mcp_tools:
            return CommandResult(output="No MCP tools registered.")

        lines = [f"MCP tools ({len(mcp_tools)}):"]
        for t in mcp_tools[:30]:
            lines.append(f"  {t.spec.name}: {t.spec.description[:60]}")
        if len(mcp_tools) > 30:
            lines.append(f"  ... and {len(mcp_tools) - 30} more")
        return CommandResult(output="\n".join(lines))

    return CommandResult(output="MCP subcommands: list, tools")


# ============================================================
# Skills command handlers
# ============================================================

def _skills_command(agent: Any, arg: str) -> CommandResult:
    if not arg or arg == "list":
        # Try to load skills
        try:
            from attocode.integrations.skills.loader import SkillLoader
            ctx = getattr(agent, "context", None) if agent else None
            wd = getattr(ctx, "working_dir", None) or getattr(agent, "_working_dir", "")
            if not wd:
                return CommandResult(output="No working directory set for skill discovery.")
            loader = SkillLoader(wd)
            loader.load()
            skills = loader.list_skills()
            if not skills:
                return CommandResult(output="No skills found.")

            lines = ["Available skills:"]
            for s in skills:
                name = getattr(s, "name", str(s))
                desc = getattr(s, "description", "")[:60]
                lines.append(f"  {name}: {desc}")
            return CommandResult(output="\n".join(lines))
        except Exception as e:
            return CommandResult(output=f"Error loading skills: {e}")

    parts = arg.split(maxsplit=1)
    subcmd = parts[0]
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "info" and subarg:
        return CommandResult(output=f"Skill info for '{subarg}' not yet implemented.")

    return CommandResult(output="Skills subcommands: list, info <name>")


# ============================================================
# Context command handlers
# ============================================================

def _context_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
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
    return CommandResult(output="\n".join(l for l in lines if l))


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


# ============================================================
# Debug command handlers
# ============================================================

def _trace_command(agent: Any, arg: str) -> CommandResult:
    if not arg or arg == "list":
        return CommandResult(output="Trace dashboard not yet implemented in Python port.\nUse the TS trace-dashboard for now.")

    if arg == "analyze":
        ctx = getattr(agent, "context", None) if agent else None
        if not ctx:
            return CommandResult(output="No active context for analysis.")

        lines = [
            "Session analysis:",
            f"  Iterations: {ctx.iteration}",
            f"  LLM calls: {ctx.metrics.llm_calls}",
            f"  Tool calls: {ctx.metrics.tool_calls}",
            f"  Tokens: {ctx.metrics.total_tokens:,}",
            f"  Cost: ${ctx.metrics.estimated_cost:.4f}",
            f"  Duration: {ctx.metrics.duration_ms / 1000:.1f}s",
        ]
        return CommandResult(output="\n".join(lines))

    return CommandResult(output="Trace subcommands: list, analyze")


def _grants_command(agent: Any) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    policy = getattr(ctx, "policy_engine", None) if ctx else None

    if not policy:
        return CommandResult(output="No policy engine configured (all tools auto-approved).")

    approved = getattr(policy, "_approved_commands", set())
    if not approved:
        return CommandResult(output="No remembered permissions.")

    lines = ["Remembered permissions:"]
    for cmd in sorted(approved):
        lines.append(f"  {cmd}")
    return CommandResult(output="\n".join(lines))


def _undo_command(agent: Any, arg: str) -> CommandResult:
    ctx = getattr(agent, "context", None) if agent else None
    tracker = getattr(ctx, "file_change_tracker", None) if ctx else None

    if not tracker:
        return CommandResult(output="Undo system not available (no file change tracker).")

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
    ctx = getattr(agent, "context", None) if agent else None
    tracker = getattr(ctx, "file_change_tracker", None) if ctx else None

    if not tracker:
        return CommandResult(output="File change tracking not available.")

    history = tracker.format_history()
    if not history or history == "No changes":
        return CommandResult(output="No file changes in this session.")

    return CommandResult(output=history)


# ============================================================
# Config command handlers
# ============================================================

async def _init_command(agent: Any) -> CommandResult:
    """Initialize .attocode/ directory structure."""
    import os
    from pathlib import Path

    ctx = getattr(agent, "context", None) if agent else None
    wd = getattr(ctx, "working_dir", None) or os.getcwd()

    base = Path(wd) / ".attocode"
    dirs = ["skills", "agents"]
    files = {
        "config.json": '{\n  "model": null,\n  "sandbox": { "mode": "auto" }\n}\n',
        "rules.md": "# Project Rules\n\nAdd project-specific rules here.\n",
    }

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

    return CommandResult(output=f"Initialized .attocode/ with:\n" + "\n".join(f"  {c}" for c in created))


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
        current = getattr(app, "current_theme", "default")
        return CommandResult(output=f"Current theme: {current}")

    # Try to switch theme
    if hasattr(app, "set_theme"):
        app.set_theme(arg)
        return CommandResult(output=f"Theme switched to: {arg}")

    return CommandResult(output="Theme switching not supported by this app.")
