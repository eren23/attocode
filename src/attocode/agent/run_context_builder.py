"""Run-context building logic for ProductionAgent.run().

Extracted from agent.py.  The ``build_run_context`` function sets up
the AgentContext, wires integrations, initializes features, loads
skills and learnings, connects MCP servers, builds messages, and
pre-seeds the repo map -- everything that used to live inline inside
``run()`` before the execution loop is invoked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.agent.agent import ProductionAgent

from attocode.agent.context import AgentContext
from attocode.agent.message_builder import build_initial_messages
from attocode.config import infer_project_root_from_session_dir
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import Message, Role, ToolCall

logger = logging.getLogger(__name__)


def _effective_rules(agent: ProductionAgent, ctx: AgentContext) -> list[str]:
    """Resolve prompt rules from config, falling back to loaded context rules."""
    config_rules = list(getattr(agent._config, "rules", []) or [])
    if config_rules:
        return [rule for rule in config_rules if isinstance(rule, str) and rule.strip()]

    loaded_rules = getattr(ctx, "_loaded_rules", [])
    if isinstance(loaded_rules, list):
        return [rule for rule in loaded_rules if isinstance(rule, str) and rule.strip()]
    if isinstance(loaded_rules, str) and loaded_rules.strip():
        return [loaded_rules.strip()]
    return []


def _session_metadata(agent: ProductionAgent) -> dict[str, str]:
    """Build session metadata used for future isolation checks."""
    working_dir = getattr(agent, "_working_dir", "") or ""
    session_dir = getattr(agent, "_session_dir", None) or ""
    project_root = getattr(agent, "_project_root", "") or ""

    if not project_root and session_dir:
        inferred = infer_project_root_from_session_dir(session_dir)
        if inferred:
            project_root = inferred

    if not project_root and working_dir:
        project_root = str(Path(working_dir).resolve())

    return {
        "working_dir": working_dir,
        "session_dir": session_dir,
        "project_root": project_root,
    }


async def build_run_context(
    agent: ProductionAgent,
    prompt: str,
    *,
    images: list[str] | None = None,
) -> tuple[AgentContext, list[Any]]:
    """Build and fully initialize the execution context for a single run.

    Returns ``(ctx, mcp_clients)`` where *mcp_clients* is the list of
    connected MCP clients that must be disconnected in the ``finally``
    block of ``run()``.
    """
    # --- Build the AgentContext -----------------------------------------
    ctx = AgentContext(
        provider=agent._provider,
        registry=agent._registry,
        config=agent._config,
        budget=agent._budget,
        working_dir=agent._working_dir,
        project_root=agent._project_root,
        system_prompt=agent._system_prompt,
        policy_engine=agent._policy_engine,
        approval_callback=agent._approval_callback,
        economics=agent._economics,
        compaction_manager=agent._compaction_manager,
        recitation_manager=agent._recitation_manager,
        failure_tracker=agent._failure_tracker,
        learning_store=agent._learning_store,
        auto_checkpoint=agent._auto_checkpoint,
        mcp_server_configs=agent._mcp_server_configs or [],
        goal=prompt[:500],
    )

    # Wire extension handler into context
    if agent._extension_handler:
        ctx.extension_handler = agent._extension_handler  # type: ignore[attr-defined]

    # Wire additional integrations
    if agent._safety_manager:
        ctx.safety_manager = agent._safety_manager  # type: ignore[attr-defined]
    if agent._task_manager:
        ctx.task_manager = agent._task_manager  # type: ignore[attr-defined]
    if agent._interactive_planner:
        ctx.interactive_planner = agent._interactive_planner  # type: ignore[attr-defined]
    if agent._codebase_context:
        ctx.codebase_context = agent._codebase_context  # type: ignore[attr-defined]
    if agent._multi_agent_manager:
        ctx.multi_agent_manager = agent._multi_agent_manager  # type: ignore[attr-defined]
    if agent._cancellation_manager:
        ctx.cancellation_manager = agent._cancellation_manager  # type: ignore[attr-defined]
    if agent._thread_manager:
        ctx.thread_manager = agent._thread_manager
    if agent._trace_collector:
        ctx.trace_collector = agent._trace_collector
    if agent._mode_manager:
        ctx.mode_manager = agent._mode_manager
    if agent._file_change_tracker:
        ctx.file_change_tracker = agent._file_change_tracker

    # Initialize recording if configured
    if agent._recording_config is not None:
        try:
            from attocode.integrations.recording.recorder import RecordingSessionManager
            agent._recorder = RecordingSessionManager(agent._recording_config)
            rec_session_id = str(uuid.uuid4())[:8]
            agent._recorder.start(rec_session_id)
        except Exception:
            logger.warning("recorder_init_failed", exc_info=True)
            agent._recorder = None  # Non-fatal

    # Register event handlers
    for handler in agent._event_handlers:
        ctx.on_event(handler)

    # Wire recorder as an event handler so it captures all agent events
    if agent._recorder is not None:
        ctx.on_event(agent._recorder.handle_event)

    agent._ctx = ctx

    # --- Session persistence --------------------------------------------
    await agent.ensure_session_store()

    # Handle session resume if requested
    resume_session_id = getattr(agent._config, "resume_session", None)
    if resume_session_id and agent._run_count == 0:
        if not agent._session_store:
            ctx.emit(AgentEvent(
                type=EventType.SESSION_RESUME_REJECTED,
                session_id=resume_session_id,
                metadata={
                    "message": (
                        f"Ignored staged resume '{resume_session_id}' because "
                        "session persistence is not available (no session directory or store failed to initialize)."
                    ),
                    "mode": "warning",
                },
            ))
            agent._config.resume_session = None
            agent._config.resume_session_explicit = False
        else:
            try:
                resume_data = await agent._session_store.resume_session(resume_session_id)
                if resume_data and resume_data.get("messages"):
                    for msg_dict in resume_data["messages"]:
                        role = msg_dict.get("role", "user")
                        content = msg_dict.get("content", "")
                        ctx.messages.append(Message(role=Role(role), content=content))
                    agent._session_id = resume_session_id
                    agent._conversation_messages = []
                    ctx.emit(AgentEvent(
                        type=EventType.SESSION_RESUMED,
                        session_id=resume_session_id,
                        metadata={
                            "message": (
                                f"Resumed session {resume_session_id} "
                                f"({len(resume_data['messages'])} messages)"
                            ),
                            "mode": "info",
                        },
                    ))
                else:
                    ctx.emit(AgentEvent(
                        type=EventType.SESSION_RESUME_REJECTED,
                        session_id=resume_session_id,
                        metadata={
                            "message": (
                                f"Ignored staged resume '{resume_session_id}' because "
                                "it was not found in the current project session store."
                            ),
                            "mode": "warning",
                        },
                    ))
            except Exception:
                logger.warning("session_resume_failed", exc_info=True)
            finally:
                agent._config.resume_session = None
                agent._config.resume_session_explicit = False

    # Create a new session record for this run (skip if resuming)
    if agent._session_store and not agent._session_id:
        try:
            session_id = str(uuid.uuid4())[:8]
            await agent._session_store.create_session(
                session_id,
                prompt[:200],
                model=agent._config.model or "",
                metadata=_session_metadata(agent),
            )
            agent._session_id = session_id
        except Exception:
            logger.warning("session_create_failed", exc_info=True)

    # Attach to context (always, even on subsequent runs)
    if agent._session_store:
        ctx.session_store = agent._session_store
        ctx.session_id = agent._session_id

    # Load persisted grants from DB into policy engine
    if (agent._session_store and agent._session_id
            and agent._policy_engine and hasattr(agent._policy_engine, "approve_command")):
        try:
            perms = await agent._session_store.list_permissions(agent._session_id)
            for p in perms:
                if p.permission_type == "allow":
                    if p.tool_name == "bash" and (p.pattern or "*") == "*":
                        continue
                    agent._policy_engine.approve_command(p.tool_name, pattern=p.pattern or "*")
        except Exception:
            logger.debug("permission_grants_load_failed", exc_info=True)

    # --- File change tracker --------------------------------------------
    if agent._file_change_tracker is None:
        try:
            from attocode.integrations.utilities.undo import FileChangeTracker
            agent._file_change_tracker = FileChangeTracker()
        except Exception:
            logger.debug("file_change_tracker_init_failed", exc_info=True)
    if agent._file_change_tracker is not None:
        ctx.file_change_tracker = agent._file_change_tracker

    # --- Feature initialization (first run only) --------------------------
    if agent._run_count == 0:
        ctx.emit_simple(EventType.STATUS, metadata={"message": "Initializing features..."})
        try:
            from attocode.agent.feature_initializer import initialize_features
            await asyncio.to_thread(
                initialize_features,
                ctx,
                project_root=agent._project_root,
                working_dir=agent._working_dir,
                session_dir=agent._session_dir,
            )
        except Exception:
            logger.warning("feature_init_failed", exc_info=True)

        # Persist managers for reuse across runs.
        if getattr(ctx, "mode_manager", None) is not None:
            agent._mode_manager = ctx.mode_manager
        if getattr(ctx, "file_change_tracker", None) is not None:
            agent._file_change_tracker = ctx.file_change_tracker
        if getattr(ctx, "thread_manager", None) is not None:
            agent._thread_manager = ctx.thread_manager
        if getattr(ctx, "codebase_context", None) is not None:
            agent._codebase_context = ctx.codebase_context
        if getattr(ctx, "economics", None) is not None:
            agent._economics = ctx.economics
        if getattr(ctx, "compaction_manager", None) is not None:
            agent._compaction_manager = ctx.compaction_manager
        if getattr(ctx, "_semantic_search", None) is not None:
            agent._semantic_search = ctx._semantic_search
        if getattr(ctx, "_lsp_manager", None) is not None:
            agent._lsp_manager = ctx._lsp_manager
        if getattr(ctx, "learning_store", None) is not None:
            agent._learning_store = ctx.learning_store

        ctx.emit_simple(EventType.STATUS, metadata={"message": "Loading skills and tools..."})
    else:
        # Re-use managers from first run — no re-init needed
        if agent._mode_manager is not None:
            ctx.mode_manager = agent._mode_manager
        if agent._file_change_tracker is not None:
            ctx.file_change_tracker = agent._file_change_tracker
        if agent._thread_manager is not None:
            ctx.thread_manager = agent._thread_manager
        if agent._codebase_context is not None:
            ctx.codebase_context = agent._codebase_context
        if getattr(agent, "_economics", None) is not None:
            ctx.economics = agent._economics
        if getattr(agent, "_compaction_manager", None) is not None:
            ctx.compaction_manager = agent._compaction_manager
        if getattr(agent, "_semantic_search", None) is not None:
            ctx._semantic_search = agent._semantic_search
        if getattr(agent, "_lsp_manager", None) is not None:
            ctx._lsp_manager = agent._lsp_manager
        if agent._learning_store is not None:
            ctx.learning_store = agent._learning_store

    # --- Sync setup (skills, learnings, tools) — first run only -----------
    if agent._run_count == 0:
        def _sync_setup() -> tuple[list[Any] | None, str]:
            """Load skills, learnings, register tools.

            Returns (loaded_skills, learning_context).
            """
            loaded_skills = None
            project_root = agent._project_root or agent._working_dir
            if project_root:
                try:
                    from attocode.integrations.skills.loader import SkillLoader
                    loader = SkillLoader(project_root)
                    loader.load()
                    all_skills = loader.list_skills()
                    if all_skills:
                        loaded_skills = all_skills
                except Exception:
                    logger.debug("skills_load_failed", exc_info=True)

            learning_context = ""
            if agent._learning_store:
                try:
                    learning_context = agent._learning_store.get_learning_context(
                        query=prompt[:200],
                        max_learnings=5,
                    )
                except Exception:
                    logger.debug("learnings_load_failed", exc_info=True)

            if agent._codebase_context or getattr(ctx, "codebase_context", None):
                try:
                    from attocode.tools.codebase import create_codebase_tools
                    mgr = agent._codebase_context or ctx.codebase_context
                    for tool in create_codebase_tools(mgr):
                        agent._registry.register(tool)
                except Exception:
                    logger.debug("codebase_tools_register_failed", exc_info=True)

            return loaded_skills, learning_context

        loaded_skills, learning_context = await asyncio.to_thread(_sync_setup)
        # Cache for subsequent runs
        agent._cached_skills = loaded_skills
        agent._cached_learning_context = learning_context
    else:
        loaded_skills = getattr(agent, "_cached_skills", None)
        learning_context = getattr(agent, "_cached_learning_context", "") or ""

    # --- MCP servers (truly async — network I/O) -------------------------
    mcp_clients: list[Any] = []
    if agent._mcp_server_configs:
        mcp_clients = await agent._connect_mcp_servers()

    # --- Build messages (fast, but keep on event loop for ctx.add_messages) ---
    rules = _effective_rules(agent, ctx)
    if agent._conversation_messages and not ctx.messages:
        from attocode.agent.message_builder import build_system_prompt, build_user_message
        sys_prompt = agent._system_prompt or build_system_prompt(
            rules=rules,
            working_dir=agent._working_dir,
            skills=loaded_skills,
            extra_context=learning_context or None,
        )
        carried = list(agent._conversation_messages)
        if carried and carried[0].role == Role.SYSTEM:
            carried[0] = Message(role=Role.SYSTEM, content=sys_prompt)
        else:
            carried.insert(0, Message(role=Role.SYSTEM, content=sys_prompt))
        carried.append(build_user_message(prompt, images=images, working_dir=agent._working_dir))
        ctx.add_messages(carried)
    else:
        messages = build_initial_messages(
            prompt,
            images=images,
            system_prompt=agent._system_prompt,
            rules=rules,
            working_dir=agent._working_dir,
            skills=loaded_skills,
            learning_context=learning_context,
        )
        ctx.add_messages(messages)

    # --- Pre-seed repo map (with disk cache) ------------------------------
    _cbc_mgr = agent._codebase_context or getattr(ctx, "codebase_context", None)
    if _cbc_mgr and agent._run_count == 0:
        ctx.emit_simple(EventType.STATUS, metadata={"message": "Indexing codebase..."})
        try:
            preseed_content = await asyncio.to_thread(
                _get_or_build_preseed, _cbc_mgr, agent._working_dir,
            )
            if preseed_content:
                # Inject as a system-context user message, NOT as a fake
                # tool_call/tool_result pair.  MiniMax (and other strict
                # OpenAI-compatible providers) reject tool results that
                # don't follow an actual assistant tool_call.
                ctx.add_messages([
                    Message(
                        role=Role.USER,
                        content=f"<system-context>\n{preseed_content}\n</system-context>",
                    ),
                ])
        except Exception:
            logger.debug("preseed_repo_map_failed", exc_info=True)

    return ctx, mcp_clients


# ---------------------------------------------------------------------------
# Preseed map caching
# ---------------------------------------------------------------------------

def _get_git_fingerprint(working_dir: str) -> str | None:
    """Get a fingerprint of the current repo state (HEAD + dirty file list).

    Combines ``git rev-parse HEAD`` with ``git status --porcelain`` so the
    cache invalidates on uncommitted edits, not just commits.  The porcelain
    output is hashed to keep the fingerprint short.
    """
    try:
        import hashlib
        import subprocess

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=working_dir,
        )
        if head.returncode != 0:
            return None
        head_sha = head.stdout.strip()

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=working_dir,
        )
        dirty_hash = hashlib.sha1(status.stdout.encode()).hexdigest()[:12]
        return f"{head_sha}:{dirty_hash}"
    except Exception:
        return None


def _get_or_build_preseed(cbc_mgr: Any, working_dir: str) -> str | None:
    """Return cached preseed content if repo unchanged, else rebuild.

    Cache is stored at ``.attocode/cache/preseed_map.json`` keyed by a
    git fingerprint (HEAD + dirty files).  Invalidates on any edit, not
    just commits.  Cache hit = ~10ms vs ~6s rebuild.
    """
    import json

    cache_dir = Path(working_dir) / ".attocode" / "cache"
    cache_file = cache_dir / "preseed_map.json"

    fingerprint = _get_git_fingerprint(working_dir)

    # Try loading cache
    if cache_file.exists() and fingerprint:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                logger.debug("preseed_map_cache_hit (fp=%s)", fingerprint[:20])
                return cached.get("content", "")
        except Exception:
            pass  # Cache corrupt — rebuild

    # Cache miss — build fresh
    logger.debug("preseed_map_cache_miss — rebuilding")
    repo_map = cbc_mgr.get_preseed_map(max_tokens=6000)

    parts = [
        "## Relevant Code (Pre-Analyzed AST Data)",
        "This section contains the repository structure with exported "
        "symbols, extracted by static analysis.",
        "For broad exploration, read this first before calling "
        "glob/read_file.",
        "Use the `codebase_overview` tool to get a refreshed or "
        "filtered view at any time.",
        "",
        f"Files: {repo_map.total_files} | "
        f"Lines: {repo_map.total_lines} | "
        f"Languages: {', '.join(sorted(repo_map.languages.keys()))}",
        "",
        "```",
        repo_map.tree,
        "```",
    ]
    if repo_map.symbols:
        parts.append("")
        parts.append("## Key Symbols")
        for rel_path, syms in list(repo_map.symbols.items())[:10]:
            parts.append(f"- `{rel_path}`: {', '.join(syms)}")

    content = "\n".join(parts)

    # Save cache
    if fingerprint:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"fingerprint": fingerprint, "content": content}),
                encoding="utf-8",
            )
        except Exception:
            pass  # Non-critical

    return content
