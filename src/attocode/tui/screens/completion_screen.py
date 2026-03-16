"""Completion Screen — modal summary shown when swarm finishes."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class CompletionScreen(ModalScreen[str]):
    """Modal showing run completion summary."""

    DEFAULT_CSS = """
    CompletionScreen {
        align: center middle;
    }
    #completion-modal {
        width: 70%;
        max-width: 90;
        height: auto;
        max-height: 22;
        border: round $success;
        background: $surface;
        padding: 1 2;
    }
    #completion-title {
        text-align: center;
        text-style: bold;
        color: $success;
        height: 1;
        margin-bottom: 1;
    }
    #completion-body {
        height: auto;
    }
    #completion-hint {
        height: 1;
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_review", "Review", show=True),
        Binding("m", "dismiss_merge", "Merge to main", show=True),
        Binding("k", "dismiss_keep", "Keep branch", show=True),
        Binding("q", "dismiss_quit", "Quit", show=True),
    ]

    def __init__(
        self,
        done: int = 0,
        failed: int = 0,
        total: int = 0,
        cost: float = 0.0,
        elapsed: str = "",
        files_modified: int = 0,
        git_branch: str = "",
        phase: str = "completed",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._done = done
        self._failed = failed
        self._total = total
        self._cost = cost
        self._elapsed = elapsed
        self._files_modified = files_modified
        self._git_branch = git_branch
        self._phase = phase

    def compose(self) -> ComposeResult:
        title = "Swarm Interrupted" if self._phase == "shutdown" else "Swarm Complete"
        with Vertical(id="completion-modal"):
            yield Static(title, id="completion-title")
            yield Static(self._build_body(), id="completion-body")
            yield Static(self._build_hint(), id="completion-hint")

    def _build_body(self) -> Text:
        text = Text()
        text.append(f"  Tasks: {self._done}/{self._total} completed", style="green")
        if self._failed:
            text.append(f" ({self._failed} failed)", style="red")
        text.append("\n")
        text.append(f"  Cost:  ${self._cost:.2f}\n", style="yellow")
        if self._elapsed:
            text.append(f"  Time:  {self._elapsed}\n", style="dim")
        if self._files_modified:
            text.append(f"  Files: {self._files_modified} modified\n", style="cyan")
        if self._git_branch:
            text.append(f"  Branch: {self._git_branch}\n", style="blue")
        return text

    def _build_hint(self) -> str:
        parts = []
        if self._git_branch:
            parts.append("[m] Merge  [k] Keep branch")
        parts.append("[ESC] Review  [q] Quit")
        return "  ".join(parts)

    def action_dismiss_review(self) -> None:
        self.dismiss("review")

    def action_dismiss_quit(self) -> None:
        self.dismiss("quit")

    def action_dismiss_merge(self) -> None:
        if not self._git_branch:
            return
        self.dismiss("merge")

    def action_dismiss_keep(self) -> None:
        if not self._git_branch:
            return
        self.dismiss("keep")
