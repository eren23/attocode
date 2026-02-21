"""Command palette widget with fuzzy search.

Provides a Ctrl+P style command palette for quick access to
agent commands, settings, and actions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, ListView, ListItem, Static


@dataclass(slots=True)
class CommandEntry:
    """A command available in the palette."""

    name: str
    description: str
    shortcut: str = ""
    category: str = "general"
    callback: Callable[[], Any] | None = None
    is_hidden: bool = False


def fuzzy_match(query: str, text: str) -> float:
    """Compute a fuzzy match score (0.0 = no match, 1.0 = exact).

    Uses a simple sequential character matching algorithm with
    bonuses for consecutive matches and word boundary matches.
    """
    if not query:
        return 1.0

    query_lower = query.lower()
    text_lower = text.lower()

    # Exact substring match gets high score
    if query_lower in text_lower:
        return 0.9 + (len(query) / len(text)) * 0.1 if text else 0.0

    # Sequential character matching
    score = 0.0
    query_idx = 0
    last_match_idx = -2
    consecutive_bonus = 0.0

    for i, char in enumerate(text_lower):
        if query_idx >= len(query_lower):
            break
        if char == query_lower[query_idx]:
            score += 1.0
            # Bonus for consecutive matches
            if i == last_match_idx + 1:
                consecutive_bonus += 0.5
            # Bonus for word boundary matches
            if i == 0 or text[i - 1] in " -_/":
                score += 0.3
            last_match_idx = i
            query_idx += 1

    # All query chars must be found
    if query_idx < len(query_lower):
        return 0.0

    total = score + consecutive_bonus
    max_possible = len(query) * 1.8  # max score per char
    return min(1.0, total / max_possible) if max_possible > 0 else 0.0


class CommandRegistry:
    """Registry of available commands."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandEntry] = {}

    def register(
        self,
        name: str,
        description: str,
        *,
        shortcut: str = "",
        category: str = "general",
        callback: Callable[[], Any] | None = None,
        hidden: bool = False,
    ) -> None:
        """Register a command."""
        self._commands[name] = CommandEntry(
            name=name,
            description=description,
            shortcut=shortcut,
            category=category,
            callback=callback,
            is_hidden=hidden,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        include_hidden: bool = False,
    ) -> list[tuple[CommandEntry, float]]:
        """Search commands by fuzzy matching.

        Returns:
            List of (command, score) tuples, sorted by score descending.
        """
        results: list[tuple[CommandEntry, float]] = []

        for cmd in self._commands.values():
            if cmd.is_hidden and not include_hidden:
                continue
            # Match against both name and description
            name_score = fuzzy_match(query, cmd.name)
            desc_score = fuzzy_match(query, cmd.description) * 0.7
            score = max(name_score, desc_score)
            if score > 0.1:
                results.append((cmd, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    @property
    def commands(self) -> list[CommandEntry]:
        return list(self._commands.values())


# ─── Default commands ────────────────────────────────────────────────────────

def register_default_commands(registry: CommandRegistry) -> None:
    """Register the default set of agent commands."""
    defaults = [
        ("/help", "Show available commands", "Ctrl+P"),
        ("/clear", "Clear conversation history", ""),
        ("/status", "Show agent status", ""),
        ("/budget", "Show budget usage", ""),
        ("/context", "Show context window usage", ""),
        ("/compact", "Trigger context compaction", ""),
        ("/undo", "Undo last file change", "Ctrl+Z"),
        ("/save", "Save current session", ""),
        ("/load", "Load a saved session", ""),
        ("/exit", "Exit the agent", "Ctrl+C"),
        ("/plan", "Show current plan", ""),
        ("/show-plan", "Show detailed plan with diffs", ""),
        ("/approve", "Approve pending plan", ""),
        ("/reject", "Reject pending plan", ""),
        ("/tasks", "Show task list", ""),
        ("/agents", "List available agents", ""),
        ("/skills", "List available skills", ""),
        ("/debug", "Toggle debug panel", "Alt+D"),
        ("/diff", "Show recent file changes", ""),
        ("/trace", "Show trace summary", ""),
        ("/swarm", "Show swarm status", ""),
        # Thread commands
        ("/fork", "Fork conversation into a new thread", ""),
        ("/threads", "List conversation threads", ""),
        ("/switch", "Switch to a different thread", ""),
        ("/rollback", "Remove last N messages", ""),
        ("/restore", "Restore from a checkpoint", ""),
        # Goals
        ("/goals", "Manage session goals", ""),
        # Agent discovery
        ("/find", "Search agents by keyword", ""),
        ("/suggest", "Suggest agent for a task", ""),
        ("/auto", "Auto-select agent for a task", ""),
        # Security / debug
        ("/audit", "Show tool call audit log", ""),
        ("/powers", "Show agent capabilities", ""),
        # Session
        ("/reset", "Reset conversation state", ""),
        ("/handoff", "Export session handoff summary", ""),
        # Info
        ("/sandbox", "Show sandbox configuration", ""),
        ("/lsp", "Show LSP integration status", ""),
        ("/tui", "Show TUI feature list", ""),
    ]
    for name, desc, shortcut in defaults:
        registry.register(name, desc, shortcut=shortcut, category="commands")


# ─── Palette Screen ─────────────────────────────────────────────────────────

class CommandPaletteScreen(ModalScreen[str | None]):
    """Modal screen for the command palette.

    Shows a search input and filtered list of commands.
    Pressing Enter selects the highlighted command.
    Pressing Escape closes without selection.
    """

    DEFAULT_CSS = """
    CommandPaletteScreen {
        align: center middle;
    }

    #palette-container {
        width: 60;
        max-height: 20;
        border: round #89b4fa;
        background: $surface;
        padding: 1;
    }

    #palette-input {
        dock: top;
        margin: 0 0 1 0;
    }

    #palette-results {
        height: auto;
        max-height: 15;
    }

    .palette-item {
        height: 1;
        padding: 0 1;
    }

    .palette-item:hover {
        background: #89b4fa 20%;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_palette", "Close", show=False),
    ]

    def __init__(
        self,
        registry: CommandRegistry,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self._registry = registry
        self._results: list[CommandEntry] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Input(
                placeholder="Type a command...",
                id="palette-input",
            )
            yield ListView(id="palette-results")

    def on_mount(self) -> None:
        self._update_results("")
        self.query_one("#palette-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._results:
            self.dismiss(self._results[0].name)
        else:
            # Treat raw input as a command
            value = event.value.strip()
            if value:
                self.dismiss(value if value.startswith("/") else f"/{value}")

    def action_dismiss_palette(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        if 0 <= idx < len(self._results):
            self.dismiss(self._results[idx].name)

    def _update_results(self, query: str) -> None:
        results_view = self.query_one("#palette-results", ListView)
        results_view.clear()
        self._results.clear()

        if query:
            matches = self._registry.search(query)
            for cmd, score in matches:
                self._results.append(cmd)
        else:
            self._results = [
                c for c in self._registry.commands if not c.is_hidden
            ]

        for cmd in self._results[:10]:
            shortcut = f"  [{cmd.shortcut}]" if cmd.shortcut else ""
            label = f"{cmd.name}  {cmd.description}{shortcut}"
            results_view.append(ListItem(Static(label), classes="palette-item"))
