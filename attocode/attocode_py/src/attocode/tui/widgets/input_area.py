"""Prompt input area widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class _PromptTextArea(TextArea):
    """TextArea that submits on Enter, newline on Shift+Enter."""

    BINDINGS = [
        Binding("enter", "submit", "Submit", show=False),
    ]

    class Submitted(Message):
        """User pressed Enter to submit."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def _on_key(self, event: Key) -> None:
        if event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            value = self.text.strip()
            if value:
                self.post_message(self.Submitted(value))
            return
        super()._on_key(event)


class PromptInput(Widget):
    """Input area for user prompts.

    Uses TextArea for multi-line paste support. Enter submits,
    Shift+Enter inserts a newline. Supports history navigation.
    """

    DEFAULT_CSS = """
    PromptInput {
        height: auto;
        min-height: 3;
        max-height: 8;
    }

    PromptInput TextArea {
        height: auto;
        min-height: 3;
        max-height: 7;
        border: round #89b4fa;
        padding: 0 1;
    }

    PromptInput TextArea:focus {
        border: round #89b4fa;
    }

    PromptInput.disabled TextArea {
        opacity: 0.5;
    }
    """

    BINDINGS = [
        Binding("up", "history_prev", "Previous command", show=False),
        Binding("down", "history_next", "Next command", show=False),
    ]

    class Submitted(Message):
        """User submitted a prompt."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._enabled = True

    def compose(self) -> ComposeResult:
        yield _PromptTextArea(
            "",
            id="prompt-input",
            language=None,
            show_line_numbers=False,
            soft_wrap=True,
        )

    def on_mount(self) -> None:
        """Configure the text area."""
        ta = self.query_one("#prompt-input", _PromptTextArea)
        ta.tab_behavior = "focus"

    def on__prompt_text_area_submitted(self, event: _PromptTextArea.Submitted) -> None:
        """Handle Enter key from the inner TextArea."""
        event.stop()
        value = event.value
        if not value or not self._enabled:
            return
        if not self._history or self._history[-1] != value:
            self._history.append(value)
        self._history_index = -1
        ta = self.query_one("#prompt-input", _PromptTextArea)
        ta.clear()
        self.post_message(self.Submitted(value))

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable input."""
        self._enabled = enabled
        self.set_class(not enabled, "disabled")
        ta = self.query_one("#prompt-input", _PromptTextArea)
        ta.read_only = not enabled

    def action_history_prev(self) -> None:
        """Navigate to previous history entry."""
        if not self._history:
            return
        if self._history_index == -1:
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        ta = self.query_one("#prompt-input", _PromptTextArea)
        ta.clear()
        ta.insert(self._history[self._history_index])

    def action_history_next(self) -> None:
        """Navigate to next history entry."""
        if self._history_index == -1:
            return
        self._history_index += 1
        ta = self.query_one("#prompt-input", _PromptTextArea)
        ta.clear()
        if self._history_index >= len(self._history):
            self._history_index = -1
        else:
            ta.insert(self._history[self._history_index])

    def focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#prompt-input", _PromptTextArea).focus()
