"""Tab 4: Model Health pane — model health dashboard."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Static


class ModelHealthDetail(Widget):
    """Detail view for a selected model."""

    DEFAULT_CSS = """
    ModelHealthDetail {
        height: 1fr;
        border: solid $accent;
        padding: 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._model: dict[str, Any] | None = None

    def render(self) -> Text:
        text = Text()
        if not self._model:
            text.append("Select a model for details", style="dim italic")
            return text

        m = self._model
        text.append(f"Model: {m.get('model', '?')}\n", style="bold underline")
        text.append("\n")

        # Health status
        healthy = m.get("healthy", True)
        text.append("Status: ", style="dim")
        text.append("Healthy\n" if healthy else "Unhealthy\n", style="green bold" if healthy else "red bold")
        text.append("\n")

        # Success rate bar
        rate = m.get("success_rate", 1.0)
        bar_width = 30
        filled = int(rate * bar_width)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        bar_style = "green" if rate >= 0.8 else "yellow" if rate >= 0.5 else "red"
        text.append(f"Success Rate: [{bar}] {rate:.0%}\n", style=bar_style)
        text.append("\n")

        # Stats
        text.append("Statistics\n", style="bold")
        text.append(f"  Successes:          {m.get('successes', 0)}\n", style="green dim")
        text.append(f"  Failures:           {m.get('failures', 0)}\n", style="red dim")
        text.append(f"  Rate Limits:        {m.get('rate_limits', 0)}\n", style="yellow dim")
        text.append(f"  Quality Rejections: {m.get('quality_rejections', 0)}\n", style="dim")
        text.append(f"  Avg Latency:        {m.get('average_latency_ms', 0):.0f}ms\n", style="dim")

        return text

    def show_model(self, model: dict[str, Any]) -> None:
        self._model = model
        self.refresh()


class ModelHealthPane(Widget):
    """Model health dashboard with table and detail view."""

    DEFAULT_CSS = """
    ModelHealthPane {
        height: 1fr;
    }
    ModelHealthPane #mh-table-container {
        width: 2fr;
    }
    ModelHealthPane #mh-detail-container {
        width: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._models: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="mh-table-container"):
                yield DataTable(id="mh-datatable", cursor_type="row")
            with Vertical(id="mh-detail-container"):
                yield ModelHealthDetail(id="mh-detail")

    def on_mount(self) -> None:
        table = self.query_one("#mh-datatable", DataTable)
        table.add_columns(
            "Model", "Status", "Success", "Fail", "RateLim",
            "QRej", "Latency", "Rate",
        )

    def update_state(self, state: dict[str, Any]) -> None:
        """Rebuild model health from state."""
        self._models = state.get("model_health", [])

        try:
            table = self.query_one("#mh-datatable", DataTable)
            table.clear()

            for m in self._models:
                model_name = m.get("model", "?")
                healthy = m.get("healthy", True)
                status_text = Text("OK", style="green") if healthy else Text("SICK", style="red")
                rate = m.get("success_rate", 1.0)
                rate_style = "green" if rate >= 0.8 else "yellow" if rate >= 0.5 else "red"

                table.add_row(
                    model_name[:20],
                    status_text,
                    str(m.get("successes", 0)),
                    str(m.get("failures", 0)),
                    str(m.get("rate_limits", 0)),
                    str(m.get("quality_rejections", 0)),
                    f"{m.get('average_latency_ms', 0):.0f}ms",
                    Text(f"{rate:.0%}", style=rate_style),
                    key=model_name,
                )
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show model detail."""
        model_name = str(event.row_key.value) if event.row_key else ""
        model = next((m for m in self._models if m.get("model") == model_name), None)
        if model:
            try:
                self.query_one("#mh-detail", ModelHealthDetail).show_model(model)
            except Exception:
                pass
