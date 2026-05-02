"""CLI entry point using Click."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click

from attocode import __version__
from attocode.config import infer_project_root_from_session_dir, load_config


def _config_project_root(config: Any) -> str:
    """Return the resolved project root for the active config."""
    project_root = getattr(config, "project_root", "") or ""
    if project_root:
        return str(project_root)

    inferred = infer_project_root_from_session_dir(getattr(config, "session_dir", "") or "")
    if inferred:
        return inferred

    return str(Path(config.working_directory).resolve())


async def _validate_staged_resume_for_tui(agent: Any, config: Any) -> list[str]:
    """Drop stale staged resume IDs that do not belong to the current project."""
    session_id = getattr(getattr(agent, "config", None), "resume_session", None)
    if not session_id:
        return []
    explicit_resume = bool(getattr(getattr(agent, "config", None), "resume_session_explicit", False))

    store = await agent.ensure_session_store()
    if not store:
        return []

    try:
        session = await store.get_session(session_id)
    except Exception:
        return []

    if session is None:
        agent.config.resume_session = None
        agent.config.resume_session_explicit = False
        return [f"Ignored staged resume '{session_id}' because it was not found in this project session store."]

    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    current_project_root = _config_project_root(config)
    current_session_dir = str(Path(config.session_dir).resolve()) if getattr(config, "session_dir", "") else ""

    stored_session_dir = str(metadata.get("session_dir", "") or "")
    if stored_session_dir and current_session_dir:
        try:
            if Path(stored_session_dir).resolve() != Path(current_session_dir):
                agent.config.resume_session = None
                agent.config.resume_session_explicit = False
                return [f"Ignored staged resume '{session_id}' because it belongs to a different project session store."]
        except OSError:
            pass
    elif not explicit_resume:
        agent.config.resume_session = None
        agent.config.resume_session_explicit = False
        return [f"Ignored staged resume '{session_id}' because it lacks trusted project metadata."]

    stored_project_root = str(metadata.get("project_root", "") or "")
    if stored_project_root and current_project_root:
        try:
            if Path(stored_project_root).resolve() != Path(current_project_root).resolve():
                agent.config.resume_session = None
                agent.config.resume_session_explicit = False
                return [f"Ignored staged resume '{session_id}' because it belongs to a different project root."]
        except OSError:
            pass

    return []


@click.command()
@click.argument("prompt", nargs=-1)
@click.option("--model", "-m", help="LLM model to use")
@click.option("--provider", help="LLM provider (anthropic, openrouter, openai)")
@click.option("--max-tokens", type=int, help="Maximum response tokens")
@click.option("--temperature", type=float, help="LLM temperature")
@click.option("--max-iterations", "-i", type=int, help="Maximum agent iterations")
@click.option("--timeout", type=float, help="Request timeout in seconds")
@click.option("--permission", "-p", type=click.Choice(["strict", "interactive", "auto-safe", "yolo"]),
              default=None, help="Permission mode for tool execution")
@click.option("--yolo", is_flag=True, help="Shorthand for --permission yolo (auto-approve all)")
@click.option("--resume", default=None, help="Resume a previous session by ID")
@click.option("--trace", is_flag=True, help="Save JSONL execution traces to .traces/")
@click.option("--tui/--no-tui", "use_tui", default=None, help="Force TUI or REPL mode")
@click.option("--theme", type=click.Choice(["dark", "light", "auto"]), default=None, help="TUI theme")
@click.option("--task", "-t", default=None, help="Task description (alternative to positional prompt)")
@click.option("--swarm", "swarm_config", default=None, help="Enable swarm mode with optional config path")
@click.option("--swarm-resume", default=None, help="Resume a swarm session")
@click.option("--hybrid", is_flag=True, help="Use standalone attoswarm hybrid orchestrator")
@click.option("--paid-only", is_flag=True, help="Only use paid models")
@click.option("--record", is_flag=True, help="Record session for visual debug replay")
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--version", is_flag=True, help="Show version and exit")
@click.option("--non-interactive", is_flag=True, help="Run in non-interactive mode")
def main(
    prompt: tuple[str, ...],
    model: str | None,
    provider: str | None,
    max_tokens: int | None,
    temperature: float | None,
    max_iterations: int | None,
    timeout: float | None,
    permission: str | None,
    yolo: bool,
    resume: str | None,
    trace: bool,
    use_tui: bool | None,
    theme: str | None,
    task: str | None,
    swarm_config: str | None,
    swarm_resume: str | None,
    hybrid: bool,
    paid_only: bool,
    record: bool,
    debug: bool,
    version: bool,
    non_interactive: bool,
) -> None:
    """Attocode - Production AI coding agent.

    Run with a prompt for single-turn mode, or without for interactive TUI.
    """
    if version:
        click.echo(f"attocode {__version__}")
        return

    if prompt and prompt[0] == "swarm":
        _dispatch_swarm_command(prompt[1:], debug=debug)
        return

    if swarm_config is not None or swarm_resume or hybrid:
        click.echo(
            "Top-level swarm mode was removed from `attocode`.\n"
            "Use the wrapper form instead:\n"
            "  attocode swarm start .attocode/swarm.hybrid.yaml \"<goal>\"\n"
            "  attocode swarm tui <run_dir>",
            err=True,
        )
        sys.exit(2)

    # Build CLI args dict
    cli_args: dict[str, Any] = {}
    if model:
        cli_args["model"] = model
    if provider:
        cli_args["provider"] = provider
    if max_tokens is not None:
        cli_args["max_tokens"] = max_tokens
    if temperature is not None:
        cli_args["temperature"] = temperature
    if max_iterations is not None:
        cli_args["max_iterations"] = max_iterations
    if timeout is not None:
        cli_args["timeout"] = timeout
    if debug:
        cli_args["debug"] = True
    if trace:
        cli_args["trace"] = True
    if paid_only:
        cli_args["paid_only"] = True
    if record:
        cli_args["record"] = True
    if theme:
        cli_args["theme"] = theme

    # Permission mode: --yolo is shorthand for --permission yolo
    if yolo:
        cli_args["permission_mode"] = "yolo"
    elif permission:
        cli_args["permission_mode"] = permission

    # Session resume
    if resume:
        cli_args["resume_session"] = resume
        cli_args["resume_session_explicit"] = True

    # Load configuration
    config = load_config(cli_args=cli_args)

    # Validate configuration early
    from attocode.config_validator import validate_config
    try:
        validate_config(config)
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    # Join prompt parts (--task flag takes precedence over positional args)
    prompt_text = task or (" ".join(prompt) if prompt else "")

    if prompt_text or non_interactive:
        # Non-interactive single-turn mode
        _run_single_turn(config, prompt_text)
    elif use_tui is False:
        # Forced REPL mode (--no-tui)
        _run_single_turn(config, "")
    else:
        # Interactive TUI mode (default or --tui)
        _run_tui(config)


def _run_single_turn(config: Any, prompt: str) -> None:
    """Run the agent with the ReAct execution loop."""
    import asyncio

    from attocode.config import needs_setup

    if needs_setup(config):
        click.echo(
            "No API key configured.\n\n"
            "Run `attocode` interactively to set up,\n"
            "or set an env var:\n"
            "  export ANTHROPIC_API_KEY=sk-...\n"
            "  export OPENROUTER_API_KEY=sk-...\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "  export ZAI_API_KEY=...",
            err=True,
        )
        sys.exit(1)

    async def _run() -> None:
        from attocode.agent.builder import AgentBuilder
        from attocode.providers.model_cache import init_model_cache
        from attocode.tracing import TraceWriter
        from attocode.types.budget import ExecutionBudget
        from attocode.types.events import AgentEvent, EventType

        await init_model_cache()

        trace_writer: TraceWriter | None = None

        try:
            builder = (
                AgentBuilder()
                .with_provider(config.provider, api_key=config.api_key, timeout=config.timeout)
                .with_model(config.model)
                .with_working_dir(config.working_directory)
                .with_project_root(_config_project_root(config))
                .with_rules(config.rules)
                .with_budget(ExecutionBudget(
                    max_tokens=config.budget_max_tokens,
                    max_iterations=config.max_iterations,
                    max_cost=config.budget_max_cost,
                    max_duration_seconds=config.budget_max_duration,
                ))
                .with_max_tokens(config.max_tokens)
                .with_temperature(config.temperature)
                .with_sandbox(True)
                .with_spawn_agent(True)
                .with_compaction(
                    True,
                    warning_threshold=config.compaction_warning_threshold,
                    compaction_threshold=config.compaction_threshold,
                )
                .with_openrouter_preferences(config.openrouter_preferences)
            )

            if config.session_dir:
                builder = builder.with_session_dir(config.session_dir)
            if config.resume_session:
                builder = builder.with_resume_session(
                    config.resume_session,
                    explicit=bool(getattr(config, "resume_session_explicit", False)),
                )

            if config.system_prompt:
                builder = builder.with_system_prompt(config.system_prompt)

            if config.debug:
                builder = builder.with_debug(True)

            if config.record:
                from attocode.integrations.recording.recorder import RecordingConfig
                rec_dir = config.working_directory + "/.attocode/recordings"
                builder = builder.with_recording(RecordingConfig(output_dir=rec_dir))

            # Set up trace writer
            trace_writer = TraceWriter(
                trace_dir=config.working_directory + "/.attocode/traces",
            )
            trace_writer.start()

            # Event handler for non-interactive output
            def _on_event(event: AgentEvent) -> None:
                # Record to trace file
                if trace_writer:
                    trace_writer.record(event)
                # Debug output
                if config.debug:
                    if event.type == EventType.TOOL_START:
                        click.echo(f"  [Tool: {event.tool}]", err=True)
                    elif event.type == EventType.TOOL_ERROR:
                        click.echo(f"  [Error: {event.error}]", err=True)
                    elif event.type == EventType.ITERATION:
                        click.echo(f"  [Iteration {event.iteration}]", err=True)

            builder = builder.on_event(_on_event)
            agent = builder.build()

        except Exception as e:
            if trace_writer:
                trace_writer.close()
            click.echo(f"Error initializing agent: {e}", err=True)
            sys.exit(1)

        try:
            # Detect image paths in the prompt for single-turn mode
            images: list[str] | None = None
            effective_prompt = prompt
            if effective_prompt:
                from attocode.tools.image_utils import extract_image_paths
                remaining, detected = extract_image_paths(effective_prompt)
                if detected:
                    effective_prompt = remaining
                    images = detected

            result = await agent.run(effective_prompt, images=images)
            if result.response:
                click.echo(result.response)
            if not result.success and result.error:
                click.echo(f"\nAgent error: {result.error}", err=True)
            if config.debug and result.metrics:
                m = result.metrics
                click.echo(
                    f"\n[Metrics: {m.llm_calls} LLM calls, "
                    f"{m.tool_calls} tool calls, "
                    f"{m.total_tokens} tokens, "
                    f"${m.estimated_cost:.4f}]",
                    err=True,
                )
            if not result.success:
                sys.exit(1)
        except SystemExit:
            raise
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        finally:
            if trace_writer:
                trace_writer.close()

    asyncio.run(_run())


def _run_setup_wizard() -> Any:
    """Run the first-time setup wizard in a standalone Textual app."""
    from textual.app import App

    from attocode.tui.dialogs.setup import SetupResult, SetupWizard

    result_holder: list[SetupResult] = []

    class SetupApp(App[None]):
        CSS = """
        Screen { background: $surface; }
        """

        def on_mount(self) -> None:
            def _on_result(result: SetupResult) -> None:
                result_holder.append(result)
                self.exit()

            self.push_screen(SetupWizard(), callback=_on_result)

    SetupApp().run()
    return result_holder[0] if result_holder else None


def _run_tui(config: Any) -> None:
    """Run the interactive TUI with full agent integration."""
    import asyncio
    import subprocess

    from attocode.config import needs_setup, save_global_config

    if needs_setup(config):
        result = _run_setup_wizard()
        if result is None or not result.completed:
            click.echo("Setup cancelled. Run `attocode` again to retry.", err=True)
            sys.exit(0)
        config.provider = result.provider
        config.api_key = result.api_key
        config.model = result.model
        save_global_config({
            "provider": result.provider,
            "api_key": result.api_key,
            "model": result.model,
        })
        click.echo("Configuration saved to ~/.attocode/config.json", err=True)

    from attocode.agent.builder import AgentBuilder
    from attocode.providers.model_cache import init_model_cache
    from attocode.tracing import TraceWriter
    from attocode.tui.app import AttocodeApp
    from attocode.tui.events import (
        AgentCompleted,
        BudgetWarning,
        IterationUpdate,
        LLMCompleted,
        LLMRetry,
        LLMStarted,
        LLMStreamChunk,
        LLMStreamEnd,
        LLMStreamStart,
        StatusUpdate,
        ToolCompleted,
        ToolStarted,
    )
    from attocode.types.budget import ExecutionBudget
    from attocode.types.events import AgentEvent, EventType

    # Detect git branch
    git_branch = ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=config.working_directory or None,
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    # Populate dynamic model cache (pricing + context windows) before building
    # the agent.  No event loop is running yet so asyncio.run() is safe here.
    asyncio.run(init_model_cache())

    # Create TUI app first so we can wire approval bridge
    app: AttocodeApp | None = None
    agent_task: asyncio.Task[Any] | None = None

    # Build agent
    builder = (
        AgentBuilder()
        .with_provider(config.provider, api_key=config.api_key, timeout=config.timeout)
        .with_model(config.model)
        .with_working_dir(config.working_directory)
        .with_project_root(_config_project_root(config))
        .with_rules(config.rules)
        .with_budget(ExecutionBudget(
            max_tokens=config.budget_max_tokens,
            max_iterations=config.max_iterations,
            max_cost=config.budget_max_cost,
            max_duration_seconds=config.budget_max_duration,
        ))
        .with_max_tokens(config.max_tokens)
        .with_temperature(config.temperature)
        .with_sandbox(True)
        .with_spawn_agent(True)
        .with_compaction(
            True,
            warning_threshold=config.compaction_warning_threshold,
            compaction_threshold=config.compaction_threshold,
        )
        .with_openrouter_preferences(config.openrouter_preferences)
    )

    if config.session_dir:
        builder = builder.with_session_dir(config.session_dir)
    if config.resume_session:
        builder = builder.with_resume_session(
            config.resume_session,
            explicit=bool(getattr(config, "resume_session_explicit", False)),
        )

    # Set up trace writer for recording execution traces
    trace_writer = TraceWriter(
        trace_dir=config.working_directory + "/.attocode/traces",
    )
    trace_writer.start()
    builder = builder.with_trace_collector(trace_writer._collector)

    if config.system_prompt:
        builder = builder.with_system_prompt(config.system_prompt)
    if config.debug:
        builder = builder.with_debug(True)

    if config.record:
        from attocode.integrations.recording.recorder import RecordingConfig
        rec_dir = config.working_directory + "/.attocode/recordings"
        builder = builder.with_recording(RecordingConfig(output_dir=rec_dir))

    # Load MCP server configs from hierarchy and wire into builder
    from attocode.integrations.mcp.config import load_mcp_configs

    mcp_configs = load_mcp_configs(_config_project_root(config))
    if mcp_configs:
        mcp_dicts = [
            {
                "name": c.name,
                "command": c.command,
                "args": c.args,
                "env": c.env,
                "enabled": c.enabled,
                "lazy_load": c.lazy_load,
            }
            for c in mcp_configs
        ]
        builder = builder.with_mcp_servers(mcp_dicts)

    # Create approval bridge before building agent so we can wire it
    from attocode.tui.bridges.approval_bridge import ApprovalBridge
    approval_bridge = ApprovalBridge()
    builder = builder.with_approval_callback(approval_bridge.request_approval)

    agent = builder.build()

    async def _bootstrap_tui_agent() -> list[str]:
        messages = await _validate_staged_resume_for_tui(agent, config)
        try:
            await agent.ensure_command_context()
        except Exception:
            if config.debug:
                click.echo("Warning: command context bootstrap failed.", err=True)
        return messages

    startup_messages = asyncio.run(_bootstrap_tui_agent())

    async def _request_budget_extension(
        current_tokens: int,
        max_tokens: int,
        requested: int,
        reason: str = "",
    ) -> bool:
        if app is None:
            return False
        used_pct = (current_tokens / max_tokens) if max_tokens > 0 else 0.0
        return await app.budget_bridge.request_extension(
            current_tokens=current_tokens,
            used_pct=used_pct,
            requested_tokens=requested,
            reason=reason,
        )

    agent.set_extension_handler(
        lambda req: _request_budget_extension(
            int(req.get("current_tokens", 0)),
            int(req.get("max_tokens", 0)),
            int(req.get("requested_additional", 0)),
            str(req.get("reason", "")),
        )
    )

    def _post_event(msg: Any) -> None:
        """Thread-safe post of a Textual message to the app."""
        if app is not None and app.is_running:
            app.post_message(msg)

    def _on_agent_event(event: AgentEvent) -> None:
        """Bridge AgentEvent → TUI Textual messages."""
        # Record to trace file
        try:
            trace_writer.record(event)
        except Exception:
            pass

        if event.type == EventType.STATUS:
            msg = (event.metadata or {}).get("message", "")
            if msg:
                _post_event(StatusUpdate(msg, mode="info"))
        elif event.type == EventType.TOOL_START:
            tool_id = ((event.metadata or {}).get("tool_id") or event.tool or "unknown")
            _post_event(ToolStarted(
                tool_id=tool_id,
                name=event.tool or "unknown",
                args=event.args,
            ))
        elif event.type == EventType.TOOL_COMPLETE:
            tool_id = ((event.metadata or {}).get("tool_id") or event.tool or "unknown")
            _post_event(ToolCompleted(
                tool_id=tool_id,
                name=event.tool or "unknown",
                result=event.result,
            ))
        elif event.type == EventType.TOOL_ERROR:
            tool_id = ((event.metadata or {}).get("tool_id") or event.tool or "unknown")
            _post_event(ToolCompleted(
                tool_id=tool_id,
                name=event.tool or "unknown",
                error=event.error,
            ))
        elif event.type == EventType.LLM_START:
            _post_event(LLMStarted())
        elif event.type == EventType.LLM_COMPLETE:
            _post_event(LLMCompleted(
                tokens=event.tokens or 0,
                cost=event.cost or 0.0,
            ))
        elif event.type == EventType.LLM_RETRY:
            meta = event.metadata or {}
            _post_event(LLMRetry(
                attempt=meta.get("attempt", 0),
                max_retries=meta.get("max_retries", 3),
                delay=meta.get("delay", 0),
                error=meta.get("error", ""),
            ))
        elif event.type == EventType.LLM_STREAM_START:
            _post_event(LLMStreamStart())
        elif event.type == EventType.LLM_STREAM_CHUNK:
            meta = event.metadata or {}
            content = meta.get("content", "")
            chunk_type = meta.get("chunk_type", "text")
            if content:
                _post_event(LLMStreamChunk(content=content, chunk_type=chunk_type))
        elif event.type == EventType.LLM_STREAM_END:
            _post_event(LLMStreamEnd(
                tokens=event.tokens or 0,
                cost=event.cost or 0.0,
            ))
        elif event.type == EventType.ITERATION:
            _post_event(IterationUpdate(iteration=event.iteration or 0))
        elif event.type == EventType.BUDGET_WARNING:
            meta = event.metadata or {}
            _post_event(BudgetWarning(
                usage_fraction=meta.get("usage_fraction", 0.0),
                message=meta.get("message", ""),
            ))
        elif event.type == EventType.BUDGET_EXHAUSTED:
            meta = event.metadata or {}
            _post_event(BudgetWarning(
                message=meta.get("message", ""),
                usage_fraction=meta.get("usage_fraction", 1.0),
            ))
        elif event.type == EventType.BUDGET_EXTENSION_GRANTED:
            meta = event.metadata or {}
            new_max = int(meta.get("new_max_tokens", 0))
            _post_event(StatusUpdate(
                f"Budget extended. New max: {new_max:,} tokens" if new_max else "Budget extended.",
                mode="info",
            ))
        elif event.type == EventType.BUDGET_EXTENSION_DENIED:
            _post_event(StatusUpdate("Budget extension denied.", mode="info"))
        elif event.type == EventType.COMPACTION_START:
            _post_event(StatusUpdate("Compacting context...", mode="info"))
        elif event.type == EventType.COMPACTION_COMPLETE:
            meta = event.metadata or {}
            saved = meta.get("tokens_saved", 0)
            _post_event(StatusUpdate(
                f"Compaction complete ({saved:,} tokens saved)", mode="info",
            ))
        elif event.type == EventType.ERROR:
            error_msg = event.error or "unknown error"
            _post_event(StatusUpdate(f"Error: {error_msg}", mode="error"))
        elif event.type == EventType.SUSPICIOUS_TOOL_MARKUP:
            cmd = (event.metadata or {}).get("command", "")
            _post_event(StatusUpdate(
                f"Suspicious streamed tool markup detected: {cmd[:80]}",
                mode="warning",
            ))
        elif event.type == EventType.TOOL_CALL_MISMATCH:
            meta = event.metadata or {}
            expected = meta.get("expected", "")
            actual = meta.get("actual", "")
            _post_event(StatusUpdate(
                "Tool-call mismatch: streamed text and executed arguments diverged.\n"
                f"  expected: {expected[:80]}\n  actual:   {actual[:80]}",
                mode="warning",
            ))
        elif event.type == EventType.LOOP_GUARD_ACTIVATED:
            _post_event(StatusUpdate(
                (event.metadata or {}).get("message", "Loop guard activated."),
                mode="warning",
            ))
        elif event.type in (EventType.SESSION_RESUMED, EventType.SESSION_RESUME_REJECTED):
            meta = event.metadata or {}
            msg = meta.get("message") or (
                f"Resumed session {event.session_id}" if event.session_id else "Session resume update."
            )
            _post_event(StatusUpdate(msg, mode=meta.get("mode", "info")))

    agent.on_event(_on_agent_event)

    def on_submit(prompt: str, images: list[str] | None = None) -> None:
        """Called when user submits a prompt in the TUI."""
        nonlocal agent_task

        async def _run_agent() -> None:
            # NOTE: Do not post AgentStarted here — on_prompt_input_submitted
            # in app.py already handles the UI state transition.
            try:
                result = await agent.run(prompt, images=images)
                _post_event(AgentCompleted(
                    success=result.success,
                    response=result.response,
                    error=result.error,
                ))
            except Exception as e:
                _post_event(AgentCompleted(
                    success=False,
                    response="",
                    error=str(e),
                ))

        # Schedule agent in the running event loop
        agent_task = asyncio.ensure_future(_run_agent())

    def on_cancel() -> None:
        """Called when user presses ESC or Ctrl+C."""
        agent.cancel()
        if agent_task and not agent_task.done():
            agent_task.cancel()

    app = AttocodeApp(
        on_submit=on_submit,
        on_cancel=on_cancel,
        model_name=config.model,
        git_branch=git_branch,
        agent=agent,
        approval_bridge=approval_bridge,
        startup_messages=startup_messages,
    )
    try:
        app.run()
    finally:
        trace_writer.close()
def _dispatch_swarm_command(parts: tuple[str, ...], *, debug: bool = False) -> None:
    """Support `attocode swarm ...` as a convenience wrapper around attoswarm."""
    args = list(parts)
    if not args:
        args = ["--help"]
    elif args[0] == "monitor":
        args[0] = "tui"
    if debug and args and args[0] in ("start", "run", "continue"):
        args.append("--debug")
    _invoke_attoswarm(args)


def _invoke_attoswarm(args: list[str]) -> None:
    """Invoke attoswarm while marking attocode as the launcher surface."""
    from attoswarm.cli import main as attoswarm_main

    prev_started = os.environ.get("ATTO_SWARM_STARTED_VIA")
    prev_family = os.environ.get("ATTO_SWARM_COMMAND_FAMILY")
    os.environ["ATTO_SWARM_STARTED_VIA"] = "attocode"
    os.environ["ATTO_SWARM_COMMAND_FAMILY"] = "attocode swarm"
    try:
        attoswarm_main(args=args, standalone_mode=False)
    finally:
        if prev_started is None:
            os.environ.pop("ATTO_SWARM_STARTED_VIA", None)
        else:
            os.environ["ATTO_SWARM_STARTED_VIA"] = prev_started
        if prev_family is None:
            os.environ.pop("ATTO_SWARM_COMMAND_FAMILY", None)
        else:
            os.environ["ATTO_SWARM_COMMAND_FAMILY"] = prev_family


def _entry_point() -> None:
    """Entry point that pre-dispatches subcommands before Click.

    Click would reject subcommand-specific flags (e.g. ``--global``) as
    unknown top-level options.  By intercepting ``code-intel`` here we
    hand its arguments directly to ``dispatch_code_intel`` untouched.
    """
    args = sys.argv[1:]
    # Walk past top-level flags to find the first positional arg.
    i = 0
    debug = False
    while i < len(args):
        if args[i] == "--debug":
            debug = True
            i += 1
        elif args[i].startswith("-"):
            # Skip flag + potential value (e.g. --model foo)
            i += 1
            if i < len(args) and not args[i].startswith("-"):
                i += 1
        else:
            break

    if i < len(args) and args[i] == "code-intel":
        from attocode.code_intel.cli import dispatch_code_intel
        dispatch_code_intel(args[i + 1:], debug=debug)
        return

    main()


if __name__ == "__main__":
    _entry_point()
