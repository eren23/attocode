"""Budget extension dialog."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class BudgetDialog(ModalScreen[bool]):
    """Modal dialog for budget extension requests.

    Keyboard shortcuts:
    - Y: Approve extension
    - N: Deny extension
    """

    DEFAULT_CSS = """
    BudgetDialog {
        align: center middle;
    }

    #budget-container {
        width: 60;
        max-width: 80%;
        height: auto;
        border: double $warning;
        background: $surface;
        padding: 1 2;
    }

    #budget-buttons {
        height: auto;
        align: center middle;
        layout: horizontal;
        padding: 1 0 0 0;
    }

    #budget-buttons Button {
        margin: 0 1;
        min-width: 16;
    }
    """

    BINDINGS = [
        Binding("y", "approve", "Approve", show=True),
        Binding("n", "deny", "Deny", show=True),
        Binding("escape", "deny", "Deny", show=False),
    ]

    def __init__(
        self,
        current_tokens: int,
        used_pct: float,
        requested_tokens: int,
        reason: str = "",
    ) -> None:
        super().__init__()
        self.current_tokens = current_tokens
        self.used_pct = used_pct
        self.requested_tokens = requested_tokens
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Vertical(id="budget-container"):
            yield Static(self._render_title(), classes="dialog-title")
            yield Static(self._render_content(), classes="dialog-content")
            with Horizontal(id="budget-buttons"):
                yield Button("Approve (y)", id="btn-approve", variant="success")
                yield Button("Deny (n)", id="btn-deny", variant="error")

    def _render_title(self) -> Text:
        text = Text()
        text.append("Budget Extension Request", style="bold yellow")
        return text

    def _render_content(self) -> Text:
        text = Text()

        text.append("Current budget: ", style="dim")
        text.append(f"{self.current_tokens:,} tokens\n")

        text.append("Used: ", style="dim")
        pct_style = "red" if self.used_pct >= 0.9 else "yellow"
        text.append(f"{self.used_pct:.0%}\n", style=pct_style)

        text.append("Requested: ", style="dim")
        text.append(f"+{self.requested_tokens:,} tokens\n", style="bold")

        increase_pct = (
            self.requested_tokens / self.current_tokens * 100
            if self.current_tokens > 0
            else 0
        )
        text.append("Increase: ", style="dim")
        text.append(f"{increase_pct:.0f}%\n")

        if self.reason:
            text.append("\n")
            text.append(self.reason[:200], style="dim italic")

        return text

    def on_mount(self) -> None:
        self.query_one("#btn-approve", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self.action_approve()
        elif event.button.id == "btn-deny":
            self.action_deny()

    def action_approve(self) -> None:
        """Approve the budget extension."""
        self.dismiss(True)

    def action_deny(self) -> None:
        """Deny the budget extension."""
        self.dismiss(False)
