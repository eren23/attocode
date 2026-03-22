"""Dynamic tool creation with sandboxed execution.

Allows the agent to define new tools at runtime. Tools are
validated, sandboxed, and optionally persisted for session reload.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Builtins that are blocked in dynamic tool code
_BLOCKED_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "breakpoint", "exit", "quit", "input",
    "globals", "locals", "vars",
})

# Safe subset of builtins for dynamic tools
_SAFE_BUILTINS: dict[str, Any] = {
    k: v for k, v in __builtins__.items()  # type: ignore[union-attr]
    if k not in _BLOCKED_BUILTINS
} if isinstance(__builtins__, dict) else {
    k: getattr(__builtins__, k) for k in dir(__builtins__)
    if k not in _BLOCKED_BUILTINS and not k.startswith("_")
}


@dataclass(slots=True)
class DynamicToolSpec:
    """Specification for a dynamically defined tool."""
    name: str
    description: str
    parameters_schema: dict[str, Any]
    python_code: str
    created_by: str = "agent"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": self.parameters_schema,
            "python_code": self.python_code,
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DynamicToolSpec:
        return cls(
            name=data["name"],
            description=data["description"],
            parameters_schema=data["parameters_schema"],
            python_code=data["python_code"],
            created_by=data.get("created_by", "agent"),
            version=data.get("version", 1),
        )


class DynamicToolError(Exception):
    """Error in dynamic tool definition or execution."""


class DynamicToolRegistry:
    """Registry for dynamically defined tools.

    Handles validation, sandboxed execution, and persistence
    of tools defined at runtime by the agent.
    """

    def __init__(self, *, persist_dir: Path | None = None) -> None:
        self._tools: dict[str, DynamicToolSpec] = {}
        self._compiled: dict[str, Any] = {}
        self._persist_dir = persist_dir

    @property
    def tools(self) -> dict[str, DynamicToolSpec]:
        return dict(self._tools)

    def define(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        python_code: str,
        *,
        persist: bool = True,
    ) -> DynamicToolSpec:
        """Define a new dynamic tool.

        Args:
            name: Tool name (must be valid identifier).
            description: Human-readable description.
            parameters_schema: JSON Schema for parameters.
            python_code: Python code defining a `run(**kwargs)` function.
            persist: Whether to save to disk.

        Returns:
            The created tool spec.

        Raises:
            DynamicToolError: If validation or compilation fails.
        """
        self._validate_name(name)
        self._validate_schema(parameters_schema)
        compiled = self._compile(name, python_code)

        spec = DynamicToolSpec(
            name=name,
            description=description,
            parameters_schema=parameters_schema,
            python_code=python_code,
        )
        self._tools[name] = spec
        self._compiled[name] = compiled

        if persist and self._persist_dir:
            self._save(spec)

        logger.info("Defined dynamic tool: %s", name)
        return spec

    def execute(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a dynamic tool.

        Args:
            tool_name: Tool name.
            **kwargs: Tool parameters.

        Returns:
            Tool result.

        Raises:
            DynamicToolError: If tool not found or execution fails.
        """
        if tool_name not in self._tools:
            raise DynamicToolError(f"Unknown dynamic tool: {tool_name}")

        compiled = self._compiled[tool_name]
        sandbox = dict(_SAFE_BUILTINS)
        sandbox["__builtins__"] = _SAFE_BUILTINS

        try:
            # Execute the compiled code in a sandboxed namespace
            _sandbox_exec(compiled, sandbox)
            run_fn = sandbox.get("run")
            if not callable(run_fn):
                raise DynamicToolError(f"Tool {tool_name} does not define a 'run' function")
            return run_fn(**kwargs)
        except DynamicToolError:
            raise
        except Exception as exc:
            raise DynamicToolError(f"Tool {tool_name} execution failed: {exc}") from exc

    def unregister(self, name: str) -> bool:
        """Remove a dynamic tool."""
        if name not in self._tools:
            return False
        del self._tools[name]
        self._compiled.pop(name, None)
        if self._persist_dir:
            path = self._persist_dir / f"{name}.json"
            path.unlink(missing_ok=True)
        return True

    def load_persisted(self) -> int:
        """Load all persisted tools from disk.

        Returns:
            Number of tools loaded.
        """
        if not self._persist_dir or not self._persist_dir.exists():
            return 0

        count = 0
        for path in sorted(self._persist_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                spec = DynamicToolSpec.from_dict(data)
                compiled = self._compile(spec.name, spec.python_code)
                self._tools[spec.name] = spec
                self._compiled[spec.name] = compiled
                count += 1
            except Exception as exc:
                logger.warning("Failed to load dynamic tool %s: %s", path.name, exc)
        return count

    def list_tools(self) -> list[dict[str, Any]]:
        """List all dynamic tools with their metadata."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters_schema,
                "version": spec.version,
            }
            for spec in self._tools.values()
        ]

    def _validate_name(self, name: str) -> None:
        if not name.isidentifier():
            raise DynamicToolError(f"Invalid tool name: {name!r} (must be a valid Python identifier)")
        if name.startswith("_"):
            raise DynamicToolError(f"Tool name cannot start with underscore: {name!r}")

    def _validate_schema(self, schema: dict[str, Any]) -> None:
        if not isinstance(schema, dict):
            raise DynamicToolError("parameters_schema must be a dict")
        if "type" not in schema:
            raise DynamicToolError("parameters_schema must have a 'type' field")

    def _compile(self, name: str, code: str) -> Any:
        # Check for blocked patterns
        for blocked in _BLOCKED_BUILTINS:
            if blocked + "(" in code:
                raise DynamicToolError(
                    f"Tool {name} uses blocked builtin: {blocked}"
                )
        try:
            return compile(code, f"<dynamic-tool:{name}>", "exec")
        except SyntaxError as exc:
            raise DynamicToolError(f"Syntax error in tool {name}: {exc}") from exc

    def _save(self, spec: DynamicToolSpec) -> None:
        if not self._persist_dir:
            return
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        path = self._persist_dir / f"{spec.name}.json"
        path.write_text(
            json.dumps(spec.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )


def _sandbox_exec(compiled: Any, sandbox: dict[str, Any]) -> None:  # noqa: S102
    """Execute compiled code in a sandbox namespace.

    This is intentionally using exec() in a controlled sandbox
    environment with restricted builtins for dynamic tool execution.
    """
    exec(compiled, sandbox)  # noqa: S102
