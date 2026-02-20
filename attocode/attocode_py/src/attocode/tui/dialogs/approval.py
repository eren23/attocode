"""Approval dialog for tool permission requests."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ApprovalResult:
    """Result of an approval dialog."""

    def __init__(
        self,
        approved: bool,
        always_allow: bool = False,
        deny_reason: str | None = None,
    ) -> None:
        self.approved = approved
        self.always_allow = always_allow
        self.deny_reason = deny_reason


class ApprovalDialog(ModalScreen[ApprovalResult]):
    """Modal dialog for approving/denying tool execution.

    Keyboard shortcuts:
    - Y: Approve once
    - A: Always allow (session-scoped)
    - N: Deny
    - D: Deny with reason (not yet implemented, acts as N)
    """

    DEFAULT_CSS = """
    ApprovalDialog {
        align: center middle;
    }

    #approval-container {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: double $warning;
        background: $surface;
        padding: 1 2;
    }

    .danger-high #approval-container {
        border: double $error;
    }

    .danger-safe #approval-container {
        border: double $success;
    }

    #approval-buttons {
        height: auto;
        align: center middle;
        layout: horizontal;
        padding: 1 0 0 0;
    }

    #approval-buttons Button {
        margin: 0 1;
        min-width: 18;
    }
    """

    BINDINGS = [
        Binding("y", "approve", "Approve", show=True),
        Binding("a", "always_allow", "Always Allow", show=True),
        Binding("n", "deny", "Deny", show=True),
        Binding("d", "deny", "Deny", show=False),
        Binding("escape", "deny", "Deny", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any],
        danger_level: str = "moderate",
        context: str = "",
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = args
        self.danger_level = danger_level
        self.context = context

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-container"):
            yield Static(self._render_title(), classes="dialog-title")
            yield Static(self._render_content(), classes="dialog-content")
            with Horizontal(id="approval-buttons"):
                yield Button("Approve (y)", id="btn-approve", variant="success")
                yield Button("Always Allow (a)", id="btn-always", variant="warning")
                yield Button("Deny (n)", id="btn-deny", variant="error")

    def _render_title(self) -> Text:
        text = Text()
        text.append("Permission Required", style="bold")
        return text

    def _render_content(self) -> Text:
        text = Text()

        # Risk level
        risk_style = {
            "safe": "green",
            "low": "blue",
            "moderate": "yellow",
            "high": "red",
            "critical": "bold red",
        }.get(self.danger_level, "yellow")
        text.append(f"Risk: {self.danger_level}\n", style=risk_style)

        # Tool info
        text.append("Tool: ", style="bold")
        text.append(f"{self.tool_name}\n")

        # Arguments
        if self.tool_args:
            text.append("Args:\n", style="bold")
            for key, val in self.tool_args.items():
                val_str = str(val)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."
                text.append(f"  {key}: ", style="dim bold")
                text.append(f"{val_str}\n", style="dim")

        # Context
        if self.context:
            text.append("\n")
            text.append(self.context[:200], style="dim italic")

        return text

    def on_mount(self) -> None:
        self.query_one("#btn-approve", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self.action_approve()
        elif event.button.id == "btn-always":
            self.action_always_allow()
        elif event.button.id == "btn-deny":
            self.action_deny()

    def action_approve(self) -> None:
        """Approve the tool call."""
        self.dismiss(ApprovalResult(approved=True))

    def action_always_allow(self) -> None:
        """Always allow this tool pattern."""
        self.dismiss(ApprovalResult(approved=True, always_allow=True))

    def action_deny(self) -> None:
        """Deny the tool call."""
        self.dismiss(ApprovalResult(approved=False))
