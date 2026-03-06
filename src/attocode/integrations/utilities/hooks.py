"""Hook manager for lifecycle events.

Hooks are shell commands that run in response to agent events.
They are configured in .attocode/config.json under the "hooks" key.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HookDefinition:
    """A hook configuration."""

    event: str
    command: str
    timeout: float = 30.0
    enabled: bool = True


@dataclass(slots=True)
class HookResult:
    """Result of running a hook."""

    event: str
    command: str
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0


@dataclass
class HookManager:
    """Manages and executes lifecycle hooks.

    Hooks are shell commands triggered by specific events like
    tool.before, tool.after, run.before, run.after, etc.
    """

    hooks: list[HookDefinition] = field(default_factory=list)
    _results: list[HookResult] = field(default_factory=list, repr=False)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> HookManager:
        """Create from config dict.

        Expected format:
        {
            "hooks": [
                {"event": "tool.before", "command": "echo starting"},
                {"event": "run.after", "command": "./cleanup.sh", "timeout": 60}
            ]
        }
        """
        hooks_config = config.get("hooks", [])
        hooks = []
        for h in hooks_config:
            if isinstance(h, dict) and "event" in h and "command" in h:
                hooks.append(HookDefinition(
                    event=h["event"],
                    command=h["command"],
                    timeout=h.get("timeout", 30.0),
                    enabled=h.get("enabled", True),
                ))
        return cls(hooks=hooks)

    def get_hooks(self, event: str) -> list[HookDefinition]:
        """Get all enabled hooks for a specific event."""
        return [h for h in self.hooks if h.event == event and h.enabled]

    async def run_hooks(
        self,
        event: str,
        *,
        env: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[HookResult]:
        """Run all hooks for an event.

        Args:
            event: The event name (e.g., "tool.before").
            env: Extra environment variables.
            context: Context data passed as ATTOCODE_CONTEXT env var (JSON).

        Returns:
            List of HookResults.
        """
        matching = self.get_hooks(event)
        if not matching:
            return []

        results = []
        for hook in matching:
            result = await self._execute_hook(hook, env=env, context=context)
            results.append(result)
            self._results.append(result)

        return results

    async def _execute_hook(
        self,
        hook: HookDefinition,
        *,
        env: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> HookResult:
        """Execute a single hook."""
        full_env = dict(env or {})
        if context:
            full_env["ATTOCODE_CONTEXT"] = json.dumps(context, default=str)

        try:
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env if full_env else None,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=hook.timeout,
            )
            return HookResult(
                event=hook.event,
                command=hook.command,
                success=proc.returncode == 0,
                output=stdout.decode(errors="replace").strip(),
                error=stderr.decode(errors="replace").strip(),
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            return HookResult(
                event=hook.event,
                command=hook.command,
                success=False,
                error=f"Hook timed out after {hook.timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return HookResult(
                event=hook.event,
                command=hook.command,
                success=False,
                error=str(e),
                exit_code=-1,
            )

    @property
    def results(self) -> list[HookResult]:
        return list(self._results)
