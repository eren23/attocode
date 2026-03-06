"""Transparency panel for agent decision visibility.

Shows the agent's reasoning process, including which tools were
considered, why decisions were made, and confidence levels.
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class TransparencyPanel(VerticalScroll):
    """Shows agent decision-making transparency.

    Displays:
    - Current reasoning/thinking steps
    - Tool selection rationale
    - Confidence scores for decisions
    - Alternative approaches considered
    """

    DEFAULT_CSS = """
    TransparencyPanel {
        height: auto;
        max-height: 15;
        border: round $surface;
        padding: 0 1;
    }
    TransparencyPanel .tp-header {
        color: $primary;
        text-style: bold;
    }
    TransparencyPanel .tp-decision {
        margin: 1 0 0 0;
    }
    TransparencyPanel .tp-confidence-high {
        color: $success;
    }
    TransparencyPanel .tp-confidence-low {
        color: $warning;
    }
    TransparencyPanel .tp-rationale {
        color: $text-muted;
    }
    """

    decisions: reactive[list[dict[str, Any]]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("Transparency", classes="tp-header")
        yield Static("", id="tp-reasoning", classes="tp-decision")
        yield Static("", id="tp-decisions", classes="tp-decision")

    def add_decision(
        self,
        action: str,
        rationale: str,
        confidence: float = 0.0,
        alternatives: list[str] | None = None,
    ) -> None:
        """Record an agent decision for display."""
        decision = {
            "action": action,
            "rationale": rationale,
            "confidence": confidence,
            "alternatives": alternatives or [],
            "timestamp": time.monotonic(),
        }
        current = list(self.decisions)
        current.append(decision)
        # Keep last 10 decisions
        if len(current) > 10:
            current = current[-10:]
        self.decisions = current
        self._render_decisions()

    def set_reasoning(self, text: str) -> None:
        """Update the current reasoning display."""
        widget = self.query_one("#tp-reasoning", Static)
        if len(text) > 200:
            text = text[:200] + "..."
        widget.update(Text(f"Thinking: {text}", style="italic"))

    def _render_decisions(self) -> None:
        """Render the decisions list."""
        widget = self.query_one("#tp-decisions", Static)
        if not self.decisions:
            widget.update("")
            return

        lines: list[str] = []
        for d in reversed(self.decisions[-5:]):
            conf = d["confidence"]
            conf_str = f"[{'high' if conf > 0.7 else 'low'}] {conf:.0%}"
            lines.append(f"  {conf_str} {d['action']}")
            if d["rationale"]:
                lines.append(f"    → {d['rationale'][:80]}")

        widget.update("\n".join(lines))

    def clear(self) -> None:
        """Clear all decisions."""
        self.decisions = []
        self.query_one("#tp-reasoning", Static).update("")
        self.query_one("#tp-decisions", Static).update("")
