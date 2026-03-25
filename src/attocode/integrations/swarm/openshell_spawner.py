"""OpenShell sandbox spawner for swarm workers.

Spawns swarm workers inside NVIDIA OpenShell sandboxes with policy-governed
isolation. Each worker gets its own sandbox session with configurable
filesystem, network, and process policies.

Supports two-phase execution: network ON during setup (install deps),
then hot-reload to restricted network during agent work.

Security: Uses ``asyncio.create_subprocess_exec`` (not shell=True) for all
subprocess calls. Arguments are passed as safe argv lists.
"""

from __future__ import annotations

import logging
import shutil
import time
from typing import Any

from attocode.integrations.swarm.types import (
    SpawnResult,
    SwarmConfig,
    SwarmTask,
    SwarmWorkerSpec,
)

logger = logging.getLogger(__name__)


def _find_openshell_binary() -> str | None:
    """Locate the ``openshell`` CLI binary on PATH."""
    return shutil.which("openshell")


def _resolve_sandbox_policy(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    config: SwarmConfig,
) -> dict[str, Any] | None:
    """Resolve effective sandbox policy using cascade: task > worker > swarm.

    For network_policies, lists are concatenated (a task might need
    additional endpoints beyond the base set).
    """
    base = config.sandbox_policy
    worker_override = worker.sandbox_policy
    task_override = task.sandbox_policy

    if not base and not worker_override and not task_override:
        return None

    # Start with swarm-level defaults
    effective = dict(base or {})

    # Merge worker-level overrides (shallow merge)
    if worker_override:
        for key, val in worker_override.items():
            if key == "network_policies" and key in effective:
                # Concatenate network policy blocks
                merged = dict(effective.get(key, {}))
                merged.update(val)
                effective[key] = merged
            else:
                effective[key] = val

    # Merge task-level overrides (highest priority)
    if task_override:
        for key, val in task_override.items():
            if key == "network_policies" and key in effective:
                merged = dict(effective.get(key, {}))
                merged.update(val)
                effective[key] = merged
            else:
                effective[key] = val

    return effective


def _map_agent_type(worker: SwarmWorkerSpec) -> str:
    """Map worker policy_profile to OpenShell agent type."""
    profile = (worker.policy_profile or "").lower()
    if profile in ("cc", "claude", "claude-code"):
        return "claude"
    if profile in ("opencode", "oc"):
        return "opencode"
    if profile in ("codex",):
        return "codex"
    # Default based on model name
    model = (worker.model or "").lower()
    if "claude" in model or "anthropic" in model:
        return "claude"
    if "gpt" in model or "openai" in model:
        return "codex"
    return "claude"  # safe default


async def spawn_openshell_worker(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    system_prompt: str,
    *,
    working_dir: str = "",
    max_iterations: int = 15,
    timeout_ms: int = 120_000,
    config: SwarmConfig | None = None,
) -> SpawnResult:
    """Spawn a swarm worker inside an OpenShell sandbox.

    Lifecycle:
    1. Create sandbox session with effective policy
    2. Setup phase: network ON, run setup commands if needed
    3. Hot-reload network policy to restricted
    4. Agent phase: spawn agent CLI inside sandbox
    5. Parse output into SpawnResult
    6. Destroy sandbox session

    Args:
        task: The swarm task to execute.
        worker: Worker specification.
        system_prompt: System prompt for the agent.
        working_dir: Working directory for the sandbox.
        max_iterations: Max agent turns.
        timeout_ms: Timeout in milliseconds.
        config: Swarm config for sandbox settings.

    Returns:
        SpawnResult from the agent execution.
    """
    from attocode.integrations.safety.sandbox.openshell import (
        OpenShellOptions,
        OpenShellSandbox,
    )

    if not _find_openshell_binary():
        return SpawnResult(
            success=False,
            output="OpenShell CLI not found on PATH. Install: pip install openshell",
        )

    effective_config = config or SwarmConfig()
    effective_policy = _resolve_sandbox_policy(task, worker, effective_config)
    agent_type = _map_agent_type(worker)
    sandbox_name = f"swarm-{task.id[:8]}-{worker.name}"

    # Build sandbox options
    options = OpenShellOptions(
        gateway_url=effective_config.sandbox_gateway_url,
        policy=effective_policy,
        policy_path=effective_config.sandbox_policy_path,
        network_allowed=True,  # Start with network ON (setup phase)
        agent_type=agent_type,
        timeout=timeout_ms / 1000.0,
        credential_env=dict(effective_config.sandbox_credentials or {}),
    )

    sandbox = OpenShellSandbox(options=options)
    start_time = time.monotonic()

    try:
        # 1. Create sandbox session
        session = await sandbox.create_session(
            name=sandbox_name,
            working_dir=working_dir,
        )
    except Exception as e:
        logger.error("Failed to create OpenShell sandbox for task %s: %s", task.id, e)
        return SpawnResult(
            success=False,
            output=f"Failed to create sandbox: {e}",
        )

    try:
        # 2. Setup phase (network ON) - install deps if needed
        if task.type in ("implement", "test", "integrate", "deploy"):
            # Auto-detect and install dependencies
            setup_out, setup_code = await session.exec_command(
                "test -f requirements.txt && pip install -q -r requirements.txt 2>/dev/null; "
                "test -f package.json && npm install --silent 2>/dev/null; "
                "true",
                timeout=60.0,
            )
            if setup_code != 0:
                logger.debug("Setup phase had issues for %s: %s", task.id, setup_out[:200])

        # 3. Hot-reload to restricted network (agent phase)
        restricted_policy = sandbox.build_restricted_network_policy()
        await session.update_network_policy(restricted_policy)

        # 4. Agent phase - spawn the actual agent inside sandbox
        prompt_parts = [system_prompt, "", task.description]
        if task.target_files:
            prompt_parts.append(f"\n\nTarget files: {', '.join(task.target_files)}")
        if task.read_files:
            prompt_parts.append(f"\nReference files: {', '.join(task.read_files)}")
        if task.dependency_context:
            prompt_parts.append(f"\n\nContext from completed dependencies:\n{task.dependency_context}")

        full_prompt = "\n".join(prompt_parts)
        max_turns = max(5, max_iterations)

        if agent_type == "claude":
            agent_cmd = (
                f"claude -p {_shell_quote(full_prompt)} "
                f"--output-format json "
                f"--max-turns {max_turns} "
                f"--dangerously-skip-permissions"
            )
            if worker.model:
                agent_cmd += f" --model {worker.model}"
        elif agent_type == "opencode":
            agent_cmd = (
                f"opencode run "
                f"--format json "
                f"{_shell_quote(full_prompt)}"
            )
            if worker.model:
                agent_cmd += f" --model {worker.model}"
        else:
            agent_cmd = (
                f"claude -p {_shell_quote(full_prompt)} "
                f"--output-format json "
                f"--max-turns {max_turns} "
                f"--dangerously-skip-permissions"
            )

        raw_output, exit_code = await session.exec_command(
            agent_cmd,
            timeout=timeout_ms / 1000.0,
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # 5. Parse output using appropriate parser
        if agent_type in ("claude", "codex"):
            from attocode.integrations.swarm.cc_spawner import _parse_cc_output
            result = _parse_cc_output(raw_output)
        elif agent_type == "opencode":
            from attocode.integrations.swarm.opencode_spawner import _parse_opencode_output
            result = _parse_opencode_output(raw_output)
        else:
            from attocode.integrations.swarm.cc_spawner import _parse_cc_output
            result = _parse_cc_output(raw_output)

        # Augment metrics with sandbox info
        if result.metrics is None:
            result.metrics = {}
        result.metrics["sandbox"] = "openshell"
        result.metrics["sandbox_name"] = sandbox_name
        result.metrics["duration"] = duration_ms

        if exit_code != 0 and not result.success:
            result.output = f"Agent exited with code {exit_code}.\n{result.output}"

        return result

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("OpenShell worker failed for task %s: %s", task.id, e, exc_info=True)
        return SpawnResult(
            success=False,
            output=f"OpenShell worker error: {e}",
            metrics={"sandbox": "openshell", "duration": duration_ms},
        )
    finally:
        # 6. Always destroy sandbox
        try:
            await session.destroy()
        except Exception:
            logger.debug("Failed to destroy sandbox %s", sandbox_name, exc_info=True)


def _shell_quote(s: str) -> str:
    """Quote a string for safe use in a shell command within the sandbox.

    Uses single quotes with proper escaping of embedded single quotes.
    """
    return "'" + s.replace("'", "'\\''") + "'"


def create_openshell_spawn_fn(
    working_dir: str,
    config: SwarmConfig | None = None,
):
    """Create a spawn function for OpenShell-sandboxed workers.

    Returns an async callable matching the SpawnAgentFn signature used
    by SwarmWorkerPool.

    Args:
        working_dir: Default working directory for sandboxes.
        config: Swarm config with sandbox settings.
    """
    effective_config = config or SwarmConfig()

    async def _spawn(
        task: SwarmTask,
        worker: SwarmWorkerSpec,
        system_prompt: str,
        *,
        max_iterations: int = 15,
        timeout_ms: int = 120_000,
        **_kwargs: Any,
    ) -> SpawnResult:
        return await spawn_openshell_worker(
            task,
            worker,
            system_prompt,
            working_dir=working_dir,
            max_iterations=max_iterations,
            timeout_ms=timeout_ms,
            config=effective_config,
        )

    return _spawn
