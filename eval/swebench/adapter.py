"""AttoswarmSWEBenchFactory implementing AgentFactory protocol.

Bridges eval harness with SwarmOrchestrator for SWE-bench evaluation.
Uses subprocess-based spawn/decompose functions from attoswarm CLI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any

from eval.harness import AgentFactory, BenchInstance
from eval.swebench.config import SWEBenchEvalConfig, build_swarm_yaml_dict
from eval.swebench.prompt import build_custom_instructions, build_swarm_goal

logger = logging.getLogger(__name__)


class AttoswarmSWEBenchFactory:
    """Factory that creates Attoswarm orchestrator instances for SWE-bench.

    Implements the AgentFactory protocol so it can be used with EvalHarness.
    Supports binding an instance via set_instance() so run_instance callers
    (like EvalHarness) don't need to know about BenchInstance.
    """

    def __init__(
        self,
        config: SWEBenchEvalConfig | None = None,
        **kwargs: Any,
    ) -> None:
        self.config = config or SWEBenchEvalConfig(**kwargs)
        self._pending_instance: BenchInstance | None = None

    def set_instance(self, instance: BenchInstance) -> None:
        """Bind a BenchInstance so create_and_run receives it automatically."""
        self._pending_instance = instance

    async def create_and_run(
        self,
        working_dir: str,
        problem_statement: str,
        *,
        model: str | None = None,
        max_iterations: int = 50,
        timeout: float = 600.0,
        instance: BenchInstance | None = None,
    ) -> dict[str, Any]:
        """Create and run an Attoswarm orchestrator on the problem."""
        # Use pending instance if caller didn't pass one explicitly
        if instance is None and self._pending_instance is not None:
            instance = self._pending_instance
            self._pending_instance = None

        cfg = self.config
        if model:
            cfg = SWEBenchEvalConfig(
                **{**vars(cfg), "model": model}
            )

        # Build goal and instructions
        if instance:
            goal = build_swarm_goal(instance)
            custom_instructions = build_custom_instructions(instance)
        else:
            goal = f"Fix the following issue:\n\n{problem_statement}"
            custom_instructions = ""

        # Build YAML config
        run_dir = os.path.join(working_dir, ".swarm-run")
        yaml_dict = build_swarm_yaml_dict(cfg, working_dir, run_dir)
        yaml_dict["orchestration"]["custom_instructions"] = custom_instructions

        # Write config to a temp file outside working_dir to avoid polluting git diff
        import tempfile
        config_fd, config_path = tempfile.mkstemp(prefix="swarm-eval-", suffix=".json")
        with os.fdopen(config_fd, "w") as f:
            json.dump(yaml_dict, f, indent=2)

        start_time = time.monotonic()

        try:
            result = await self._run_swarm(
                working_dir=working_dir,
                run_dir=run_dir,
                goal=goal,
                config_path=config_path,
                timeout=min(timeout, cfg.max_runtime_seconds),
            )

            # Extract patch
            patch = self._get_patch(working_dir, instance)

            return {
                "success": result.get("completed", False),
                "output": result.get("summary", ""),
                "tokens_used": result.get("tokens_used", 0),
                "cost": result.get("cost_usd", 0.0),
                "iterations": result.get("tasks_completed", 0),
                "tool_calls": result.get("tool_calls", 0),
                "model": cfg.model,
                "patch": patch,
                "swarm_state": result,
            }

        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            logger.error("Swarm execution failed: %s", exc)
            return {
                "success": False,
                "output": str(exc),
                "tokens_used": 0,
                "cost": 0.0,
                "iterations": 0,
                "tool_calls": 0,
                "model": cfg.model,
                "patch": "",
            }

    async def _run_swarm(
        self,
        working_dir: str,
        run_dir: str,
        goal: str,
        config_path: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Run attoswarm as a subprocess."""
        cmd = [
            "attoswarm",
            "--config", config_path,
            "--goal", goal,
            "--non-interactive",
        ]

        # Keep model credentials so attoswarm can authenticate, while still
        # stripping unrelated high-risk automation tokens from child env.
        _STRIP_PREFIXES = ("CLAUDECODE", "AWS_")
        _STRIP_EXACT = {"GITHUB_TOKEN", "GH_TOKEN"}
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in _STRIP_EXACT and not any(k.startswith(p) for p in _STRIP_PREFIXES)
        }

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            output = stdout.decode("utf-8", errors="replace")

            # Try to load the persisted swarm state from configured run_dir.
            state_path = os.path.join(run_dir, "swarm.state.json")
            state: dict[str, Any] = {}
            if os.path.exists(state_path):
                with open(state_path) as f:
                    state = json.load(f)

            return {
                "completed": proc.returncode == 0,
                "summary": output[:5000],
                "tokens_used": state.get("budget", {}).get("tokens_used", 0),
                "cost_usd": state.get("budget", {}).get("cost_usd", 0.0),
                "tasks_completed": state.get("tasks_completed", 0),
                "tasks_total": state.get("tasks_total", 0),
                "tool_calls": 0,
                "phase": state.get("phase", "unknown"),
            }

        except asyncio.TimeoutError:
            if proc and proc.returncode is None:
                proc.kill()
            raise

    def _get_patch(
        self,
        working_dir: str,
        instance: BenchInstance | None = None,
    ) -> str:
        """Get the git diff of changes made by the swarm."""
        try:
            if instance and instance.base_commit:
                args = ["git", "diff", f"{instance.base_commit}..HEAD"]
            else:
                args = ["git", "diff"]
            result = subprocess.run(
                args,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout
        except Exception:
            return ""
