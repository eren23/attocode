"""Learning validation dialog.

Displays proposed learnings from the agent's self-improvement system
and allows the user to approve, reject, or skip each learning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


@dataclass(slots=True)
class LearningProposal:
    """A proposed learning for validation."""

    id: str
    learning_type: str  # "pattern", "antipattern", "preference", "tool_usage"
    description: str
    evidence: str
    confidence: float = 0.0
    source_tool: str = ""


class LearningValidationDialog(ModalScreen[str]):
    """Modal dialog for validating proposed learnings.

    Keyboard shortcuts:
    - Y: Approve the learning
    - N: Reject the learning
    - S: Skip (decide later)
    - Escape: Skip
    """

    BINDINGS = [
        Binding("y", "approve", "Approve"),
        Binding("n", "reject", "Reject"),
        Binding("s", "skip", "Skip"),
        Binding("escape", "skip", "Skip"),
    ]

    DEFAULT_CSS = """
    LearningValidationDialog {
        align: center middle;
    }
    LearningValidationDialog > Vertical {
        width: 70;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    LearningValidationDialog .lvd-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    LearningValidationDialog .lvd-type {
        color: $warning;
    }
    LearningValidationDialog .lvd-description {
        margin: 1 0;
    }
    LearningValidationDialog .lvd-evidence {
        color: $text-muted;
        margin-bottom: 1;
    }
    LearningValidationDialog .lvd-confidence {
        color: $success;
    }
    LearningValidationDialog .lvd-actions {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, proposal: LearningProposal) -> None:
        super().__init__()
        self._proposal = proposal

    def compose(self) -> ComposeResult:
        p = self._proposal
        with Vertical():
            yield Static("Learning Validation", classes="lvd-title")
            yield Static(f"Type: {p.learning_type}", classes="lvd-type")
            yield Static(p.description, classes="lvd-description")
            if p.evidence:
                yield Static(f"Evidence: {p.evidence[:200]}", classes="lvd-evidence")
            yield Static(
                f"Confidence: {p.confidence:.0%}"
                + (f" | Source: {p.source_tool}" if p.source_tool else ""),
                classes="lvd-confidence",
            )
            yield Static(
                "[Y] Approve  [N] Reject  [S] Skip",
                classes="lvd-actions",
            )

    def action_approve(self) -> None:
        """Approve the learning."""
        self.dismiss("approve")

    def action_reject(self) -> None:
        """Reject the learning."""
        self.dismiss("reject")

    def action_skip(self) -> None:
        """Skip for now."""
        self.dismiss("skip")
