"""Colored severity badge widget.

Usage::

    badge = SeverityBadge(severity="critical")
    # Renders:  [CRITICAL]
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text

_SEVERITY_STYLES: dict[str, str] = {
    "critical": "white on red bold",
    "high": "red bold",
    "medium": "yellow",
    "low": "blue",
}

_VALID_SEVERITIES = frozenset(_SEVERITY_STYLES)


class SeverityBadge(Widget):
    """Inline badge that displays a severity level with threshold-based color.

    Supported severities: ``critical``, ``high``, ``medium``, ``low``.
    """

    DEFAULT_CSS = """
    SeverityBadge {
        height: 1;
        width: auto;
    }
    """

    severity: reactive[str] = reactive("low")

    def __init__(
        self,
        severity: str = "low",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.severity = severity.lower()

    def render(self) -> Text:
        label = self.severity.upper()
        style = _SEVERITY_STYLES.get(self.severity, "dim")
        text = Text()
        text.append("[", style="dim")
        text.append(label, style=style)
        text.append("]", style="dim")
        return text
