"""Tool base types and abstractions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from attocode.types.messages import DangerLevel, ToolDefinition


class ToolParam(BaseModel):
    """Pydantic model for tool parameter validation."""

    model_config = {"extra": "forbid"}


@dataclass(slots=True)
class ToolSpec:
    """Specification for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    danger_level: DangerLevel = DangerLevel.SAFE

    def to_definition(self) -> ToolDefinition:
        """Convert to ToolDefinition for LLM consumption."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            danger_level=self.danger_level,
        )


@dataclass
class Tool:
    """A registered tool with its execute function."""

    spec: ToolSpec
    execute: Callable[[dict[str, Any]], Awaitable[Any]]
    tags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def danger_level(self) -> DangerLevel:
        return self.spec.danger_level

    def to_definition(self) -> ToolDefinition:
        return self.spec.to_definition()
