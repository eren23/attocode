"""CLI entry point using Click."""

from __future__ import annotations

import sys
from typing import Any

import click

from attocode import __version__
from attocode.config import load_config


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

    if swarm_config is not None:
        cli_args["swarm"] = True
        cli_args["swarm_config"] = swarm_config if swarm_config != "true" else None
    if swarm_resume:
        cli_args["swarm"] = True
        cli_args["swarm_resume"] = swarm_resume
    if hybrid:
        cli_args["swarm_hybrid"] = True

    # Load configuration
    config = load_config(cli_args=cli_args)

    # Join prompt parts (--task flag takes precedence over positional args)
    prompt_text = task or (" ".join(prompt) if prompt else "")

    if config.swarm and (prompt_text or config.swarm_resume):
        # Swarm multi-agent mode
        if getattr(config, "record", False):
            click.echo("Warning: --record is not supported in swarm mode (ignored)", err=True)
        _run_swarm(config, prompt_text)
    elif prompt_text or non_interactive:
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
            )

            if config.session_dir:
                builder = builder.with_session_dir(config.session_dir)

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
            result = await agent.run(prompt)
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
        AgentStarted,
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
    except Exception:
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
    )

    if config.session_dir:
        builder = builder.with_session_dir(config.session_dir)

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

    mcp_configs = load_mcp_configs(config.working_directory)
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

        if event.type == EventType.TOOL_START:
            _post_event(ToolStarted(
                tool_id=event.tool or "unknown",
                name=event.tool or "unknown",
                args=event.args,
            ))
        elif event.type == EventType.TOOL_COMPLETE:
            _post_event(ToolCompleted(
                tool_id=event.tool or "unknown",
                name=event.tool or "unknown",
                result=event.result,
            ))
        elif event.type == EventType.TOOL_ERROR:
            _post_event(ToolCompleted(
                tool_id=event.tool or "unknown",
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
            _post_event(BudgetWarning(
                message=event.metadata.get("message", "") if event.metadata else "",
                usage_fraction=1.0,
            ))
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

    agent.on_event(_on_agent_event)

    def on_submit(prompt: str) -> None:
        """Called when user submits a prompt in the TUI."""
        nonlocal agent_task

        async def _run_agent() -> None:
            # NOTE: Do not post AgentStarted here — on_prompt_input_submitted
            # in app.py already handles the UI state transition.
            try:
                result = await agent.run(prompt)
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
    )
    try:
        app.run()
    finally:
        trace_writer.close()


def _run_swarm(config: Any, prompt: str) -> None:
    """Run in swarm multi-agent mode."""
    if getattr(config, "swarm_hybrid", False):
        from attoswarm.cli import main as attoswarm_main

        args: list[str] = ["start"]
        if config.swarm_config:
            args.append(config.swarm_config)
        else:
            args.append(".attocode/swarm.hybrid.yaml")
        args.append(prompt)
        attoswarm_main(args=args, standalone_mode=False)
        return

    import asyncio

    async def _run() -> None:
        from attocode.integrations.swarm import (
            SwarmOrchestrator,
            create_swarm_orchestrator,
            load_swarm_yaml_config,
            yaml_to_swarm_config,
        )
        from attocode.integrations.swarm.types import DEFAULT_SWARM_CONFIG, SwarmConfig
        from attocode.providers.model_cache import init_model_cache
        from attocode.providers.registry import create_provider

        await init_model_cache()

        # Create the LLM provider
        provider = create_provider(config.provider, api_key=config.api_key, model=config.model, timeout=config.timeout)

        # Load swarm config from YAML or use defaults
        swarm_cfg_overrides: dict = {}
        if config.swarm_config:
            # Explicit config path
            raw = load_swarm_yaml_config(config.swarm_config)
            if raw:
                swarm_cfg_overrides = yaml_to_swarm_config(raw, config.model)
        else:
            # Auto-detect from working directory
            raw = load_swarm_yaml_config(config.working_directory)
            if raw:
                swarm_cfg_overrides = yaml_to_swarm_config(raw, config.model)

        # Build SwarmConfig from overrides
        safe_overrides = {
            k: v for k, v in swarm_cfg_overrides.items()
            if k != "orchestrator_model" and hasattr(SwarmConfig, k)
        }
        swarm_config = SwarmConfig(
            orchestrator_model=swarm_cfg_overrides.get("orchestrator_model", config.model),
            **safe_overrides,
        )

        # Optionally force paid-only throttle
        if config.paid_only:
            swarm_config.throttle = "paid"

        # Create orchestrator
        orchestrator = create_swarm_orchestrator(
            config=swarm_config,
            provider=provider,
        )

        # Wire event listener for CLI output
        def _on_swarm_event(event: Any) -> None:
            event_type = getattr(event, "type", "")
            if config.debug:
                click.echo(f"  [Swarm: {event_type}]", err=True)
            if event_type == "task.completed":
                task_desc = getattr(event, "description", "")
                click.echo(f"  Task completed: {task_desc}", err=True)
            elif event_type == "wave.completed":
                click.echo(f"  Wave completed", err=True)
            elif event_type == "swarm.error":
                error = getattr(event, "error", "")
                click.echo(f"  Swarm error: {error}", err=True)

        orchestrator.subscribe(_on_swarm_event)

        # Execute
        click.echo(f"Starting swarm execution with model: {config.model}", err=True)
        click.echo(f"Task: {prompt[:200]}", err=True)
        click.echo("---", err=True)

        try:
            result = await orchestrator.execute(prompt)

            # Display result
            if result.success:
                click.echo("\n--- Swarm Completed ---")
                if result.summary:
                    click.echo(result.summary)
                click.echo(f"\nStats: {result.stats.total_tasks} tasks, "
                           f"{result.stats.total_tokens} tokens, "
                           f"${result.stats.total_cost:.4f}")
            else:
                errors_str = "; ".join(
                    e.get("error", str(e)) for e in (result.errors or [])
                ) or "Unknown error"
                click.echo(f"\nSwarm failed: {errors_str}", err=True)
                sys.exit(1)
        except Exception as e:
            click.echo(f"Swarm error: {e}", err=True)
            sys.exit(1)

    asyncio.run(_run())


def _dispatch_swarm_command(parts: tuple[str, ...], *, debug: bool = False) -> None:
    """Support `attocode swarm ...` as a convenience wrapper around attoswarm."""
    from attoswarm.cli import main as attoswarm_main

    args = list(parts)
    if not args:
        args = ["--help"]
    elif args[0] == "monitor":
        args[0] = "tui"
    if debug and args and args[0] in ("start", "run"):
        args.insert(1, "--debug")
    attoswarm_main(args=args, standalone_mode=False)


if __name__ == "__main__":
    main()
