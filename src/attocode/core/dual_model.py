"""Architect/Editor dual-model workflow.

Splits reasoning (architect) and editing (editor) into separate
LLM calls, using a powerful model for analysis and a faster/cheaper
model for mechanical edits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ArchitectPlan:
    """Plan produced by the architect model."""
    analysis: str
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class EditorResult:
    """Result from the editor model."""
    edits: list[dict[str, Any]] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class DualModelConfig:
    """Configuration for dual-model workflow."""
    architect_model: str = ""  # Empty = use default model
    editor_model: str = ""  # Empty = use default model
    enabled: bool = False
    architect_max_tokens: int = 4096
    editor_max_tokens: int = 8192


class DualModelWorkflow:
    """Orchestrates architect/editor model split.

    The architect model (typically more capable, like Opus/o1)
    analyzes the task and proposes a solution plan. The editor
    model (typically faster/cheaper, like Sonnet/Haiku) then
    generates the precise file edits.
    """

    def __init__(self, config: DualModelConfig) -> None:
        self._config = config
        self._last_plan: ArchitectPlan | None = None
        self._stats = DualModelStats()

    @property
    def config(self) -> DualModelConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._config.architect_model)

    @property
    def last_plan(self) -> ArchitectPlan | None:
        return self._last_plan

    @property
    def stats(self) -> DualModelStats:
        return self._stats

    def create_architect_prompt(self, task: str, context: str = "") -> str:
        """Create the prompt for the architect model.

        The architect should analyze the task and produce a
        detailed plan with specific changes needed.
        """
        parts = [
            "You are the ARCHITECT. Your job is to analyze and plan, NOT to write code.",
            "",
            "## Task",
            task,
        ]
        if context:
            parts.extend(["", "## Context", context])
        parts.extend([
            "",
            "## Instructions",
            "1. Analyze what needs to change and why",
            "2. List specific files to modify with exact changes needed",
            "3. Consider edge cases and potential issues",
            "4. Provide your confidence level (0-100%)",
            "",
            "Output a structured plan. Do NOT write implementation code.",
        ])
        return "\n".join(parts)

    def create_editor_prompt(self, plan: ArchitectPlan, file_contents: dict[str, str] | None = None) -> str:
        """Create the prompt for the editor model.

        The editor should implement the architect's plan with
        precise file edits.
        """
        parts = [
            "You are the EDITOR. Implement the following plan precisely.",
            "",
            "## Architect's Plan",
            plan.analysis,
        ]
        if plan.proposed_changes:
            parts.append("\n## Proposed Changes")
            for i, change in enumerate(plan.proposed_changes, 1):
                file_path = change.get("file", "unknown")
                description = change.get("description", "")
                parts.append(f"{i}. **{file_path}**: {description}")

        if file_contents:
            parts.append("\n## Current File Contents")
            for path, content in file_contents.items():
                parts.append(f"\n### {path}")
                parts.append(f"```\n{content}\n```")

        parts.extend([
            "",
            "## Instructions",
            "Generate precise edits. Follow the architect's plan exactly.",
            "Do not add features or changes not in the plan.",
        ])
        return "\n".join(parts)

    def parse_architect_response(self, response: str) -> ArchitectPlan:
        """Parse the architect model's response into a structured plan."""
        # Extract confidence if mentioned
        confidence = 0.0
        for line in response.split("\n"):
            lower = line.lower()
            if "confidence" in lower:
                import re
                match = re.search(r"(\d+)\s*%", line)
                if match:
                    confidence = int(match.group(1)) / 100.0
                    break

        # Extract proposed changes (lines starting with file paths or numbers)
        changes: list[dict[str, Any]] = []
        for line in response.split("\n"):
            stripped = line.strip()
            if stripped and ("." in stripped[:60]) and any(
                stripped.startswith(p) for p in ("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")
            ):
                # Try to extract file path and description
                parts = stripped.lstrip("-*0123456789. ").split(":", 1)
                if len(parts) == 2 and "/" in parts[0] or "." in parts[0]:
                    changes.append({
                        "file": parts[0].strip().strip("`*"),
                        "description": parts[1].strip(),
                    })

        plan = ArchitectPlan(
            analysis=response,
            proposed_changes=changes,
            confidence=confidence,
        )
        self._last_plan = plan
        self._stats.architect_calls += 1
        return plan

    def record_editor_result(self, files_modified: list[str]) -> EditorResult:
        """Record the result of the editor pass."""
        result = EditorResult(
            files_modified=files_modified,
            summary=f"Modified {len(files_modified)} files",
        )
        self._stats.editor_calls += 1
        self._stats.total_files_modified += len(files_modified)
        return result


@dataclass(slots=True)
class DualModelStats:
    """Statistics for dual-model workflow."""
    architect_calls: int = 0
    editor_calls: int = 0
    total_files_modified: int = 0
