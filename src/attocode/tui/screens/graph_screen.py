"""Graph Screen — modal screen composing dependency, impact, and hotspot views."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from rich.text import Text  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Vertical  # noqa: E402
from textual.screen import Screen  # noqa: E402
from textual.widgets import Footer, Static  # noqa: E402

from attocode.tui.widgets.dependency_graph import DependencyGraphWidget  # noqa: E402
from attocode.tui.widgets.hotspot_heatmap import HotspotHeatmap  # noqa: E402
from attocode.tui.widgets.impact_graph import ImpactGraphWidget  # noqa: E402
from attocode.tui.widgets.repo_overview import RepoOverviewWidget  # noqa: E402

if TYPE_CHECKING:
    from textual.app import ComposeResult

_VIEWS = ("overview", "deps", "impact", "hotspots")
_VIEW_LABELS = {
    "overview": "Overview",
    "deps": "Dependencies",
    "impact": "Impact Analysis",
    "hotspots": "Hotspot Heatmap",
}


@dataclass(slots=True)
class _NavEntry:
    mode: str    # "overview", "deps", "impact", "hotspots"
    file: str    # file path (empty for overview/hotspots)
    label: str   # breadcrumb label


class GraphScreen(Screen):
    """Modal screen with tabbed graph views (overview / deps / impact / hotspots).

    Args:
        mode: Initial view — "overview", "deps", "impact", or "hotspots".
        file: File path for deps/impact modes.
        working_dir: Project root for AST service lookup.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("backspace", "go_back", "Back", show=True),
        Binding("tab", "next_view", "Next View", show=True),
        Binding("shift+tab", "prev_view", "Prev View", show=True),
    ]

    DEFAULT_CSS = """
    GraphScreen {
        background: $surface;
    }
    #graph-header {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 2;
    }
    #graph-breadcrumb {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
    }
    #graph-body {
        height: 1fr;
        overflow-y: auto;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        mode: str = "hotspots",
        file: str = "",
        working_dir: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._mode = mode if mode in _VIEWS else "overview"
        self._file = file
        self._working_dir = working_dir
        self._nav_history: list[_NavEntry] = []

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="graph-header")
        yield Static("", id="graph-breadcrumb")
        with Vertical(id="graph-body"):
            yield RepoOverviewWidget(id="graph-overview")
            yield DependencyGraphWidget(id="graph-deps")
            yield ImpactGraphWidget(id="graph-impact")
            yield HotspotHeatmap(id="graph-hotspots")
        yield Footer()

    def on_mount(self) -> None:
        self._show_current_view()
        self.run_worker(self._load_data, thread=True)

    def _header_text(self) -> str:
        parts = []
        for v in _VIEWS:
            label = _VIEW_LABELS[v]
            if v == self._mode:
                parts.append(f"[{label}]")
            else:
                parts.append(f" {label} ")
        return "  ".join(parts)

    def _update_header(self) -> None:
        try:
            self.query_one("#graph-header", Static).update(self._header_text())
        except Exception as e:
            logger.debug("GraphScreen: header update failed: %s", e)

    def _update_breadcrumb(self) -> None:
        try:
            bc = self.query_one("#graph-breadcrumb", Static)
        except Exception:
            return
        text = Text()
        for entry in self._nav_history:
            text.append(entry.label, style="dim")
            text.append(" > ", style="dim")
        # Current view
        current = _VIEW_LABELS.get(self._mode, self._mode)
        if self._file:
            current += f": {_short_path(self._file)}"
        text.append(current, style="bold")
        bc.update(text)

    def _show_current_view(self) -> None:
        """Show only the widget for the current mode."""
        for view in _VIEWS:
            widget_id = f"#graph-{view}"
            try:
                w = self.query_one(widget_id)
                w.display = (view == self._mode)
            except Exception as e:
                logger.debug("GraphScreen: view toggle failed for %s: %s", widget_id, e)
        self._update_header()
        self._update_breadcrumb()

    # --- Central navigation ---

    def _navigate_to(self, mode: str, file: str = "", *, push_history: bool = True) -> None:
        """Navigate to a view, optionally pushing current state to history."""
        if push_history:
            label = _VIEW_LABELS.get(self._mode, self._mode)
            if self._file:
                label += f": {_short_path(self._file)}"
            self._nav_history.append(_NavEntry(self._mode, self._file, label))

        self._file = file
        self._mode = mode

        if mode in ("deps", "impact") and file:
            try:
                from attocode.integrations.context.ast_service import ASTService

                svc = ASTService.get_instance(self._working_dir or ".")
                if not svc.initialized:
                    svc.initialize()
                if mode == "deps":
                    self._load_deps(svc)
                elif mode == "impact":
                    self._load_impact(svc)
            except Exception as e:
                logger.debug("GraphScreen: nav load failed: %s", e)

        self._show_current_view()

    # --- Data loading ---

    def _load_data(self) -> None:
        """Load data from AST service and populate all widgets."""
        self._load_overview()

        try:
            from attocode.integrations.context.ast_service import ASTService
            svc = ASTService.get_instance(self._working_dir or ".")
            if not svc.initialized:
                svc.initialize()
        except Exception as e:
            logger.debug("GraphScreen: AST service init failed: %s", e)
            svc = None

        if svc:
            # Pass AST service to overview widget for lazy symbol loading
            try:
                overview = self.query_one("#graph-overview", RepoOverviewWidget)
                overview.set_ast_service(svc)
            except Exception:
                pass

            self._load_hotspots(svc)
            if self._file:
                self._load_deps(svc)
                self._load_impact(svc)

        self._show_current_view()

    def _load_overview(self) -> None:
        """Load overview data using CodebaseContextManager."""
        try:
            from attocode.integrations.context.codebase_context import (
                CodebaseContextManager,
                build_dependency_graph,
            )

            root = self._working_dir or "."
            ctx_mgr = CodebaseContextManager(root_dir=root)
            ctx_mgr.discover_files()

            files = ctx_mgr._files
            total_files = len(files)
            total_lines = sum(f.line_count for f in files)

            languages: dict[str, int] = {}
            for f in files:
                if f.language:
                    languages[f.language] = languages.get(f.language, 0) + 1

            top_files = sorted(files, key=lambda f: f.importance, reverse=True)[:15]
            top_files_data = [
                {
                    "relative_path": f.relative_path,
                    "importance": f.importance,
                    "language": f.language,
                    "is_test": f.is_test,
                    "is_config": f.is_config,
                }
                for f in top_files
            ]

            entry_keywords = ("main", "cli", "__main__", "app", "entry")
            entry_points = [
                f.relative_path
                for f in files
                if any(k in f.relative_path.lower() for k in entry_keywords)
            ][:10]

            dep_stats: dict[str, Any] = {}
            try:
                graph = build_dependency_graph(files, root)
                total_edges = sum(len(t) for t in graph.forward.values())
                hubs = sorted(
                    graph.reverse.items(),
                    key=lambda x: len(x[1]),
                    reverse=True,
                )[:10]
                dep_stats = {
                    "files_with_imports": len(graph.forward),
                    "files_imported": len(graph.reverse),
                    "total_edges": total_edges,
                    "top_hubs": [(p, len(i)) for p, i in hubs],
                }
            except Exception:
                pass

            widget = self.query_one("#graph-overview", RepoOverviewWidget)
            widget.set_overview(
                root_dir=root,
                total_files=total_files,
                total_lines=total_lines,
                languages=languages,
                top_files=top_files_data,
                entry_points=entry_points,
                dep_stats=dep_stats,
            )
        except Exception as e:
            logger.debug("GraphScreen: overview load failed: %s", e)

    def _load_deps(self, svc: Any) -> None:
        """Load dependency data for a file."""
        rel = svc.to_rel(self._file)
        depth = 2

        outbound: dict[int, list[str]] = {}
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(rel, 0)])
        while queue:
            current, d = queue.popleft()
            if current in visited or d > depth:
                continue
            visited.add(current)
            if d > 0:
                outbound.setdefault(d, []).append(current)
            for dep in sorted(svc.get_dependencies(current)):
                if dep not in visited:
                    queue.append((dep, d + 1))

        inbound: dict[int, list[str]] = {}
        visited_rev: set[str] = set()
        queue_rev: deque[tuple[str, int]] = deque([(rel, 0)])
        while queue_rev:
            current, d = queue_rev.popleft()
            if current in visited_rev or d > depth:
                continue
            visited_rev.add(current)
            if d > 0:
                inbound.setdefault(d, []).append(current)
            for dep in sorted(svc.get_dependents(current)):
                if dep not in visited_rev:
                    queue_rev.append((dep, d + 1))

        try:
            widget = self.query_one("#graph-deps", DependencyGraphWidget)
            widget.set_graph(rel, outbound, inbound, depth)
        except Exception as e:
            logger.debug("GraphScreen: failed to set deps widget: %s", e)

    def _load_impact(self, svc: Any) -> None:
        """Load impact analysis for a file."""
        rel = svc.to_rel(self._file)

        max_depth = 5
        impact: dict[int, list[str]] = {}
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(rel, 0)])
        while queue:
            current, d = queue.popleft()
            if current in visited or d > max_depth:
                continue
            visited.add(current)
            if d > 0:
                impact.setdefault(d, []).append(current)
            for dep in sorted(svc.get_dependents(current)):
                if dep not in visited:
                    queue.append((dep, d + 1))

        try:
            widget = self.query_one("#graph-impact", ImpactGraphWidget)
            widget.set_impact(rel, impact)
        except Exception as e:
            logger.debug("GraphScreen: failed to set impact widget: %s", e)

    def _load_hotspots(self, svc: Any) -> None:
        """Load hotspot data."""
        idx = svc.index
        hotspots: list[dict[str, Any]] = []

        for f in idx.file_symbols:
            fan_in = len(idx.get_dependents(f))
            fan_out = len(idx.get_dependencies(f))
            symbol_count = len(idx.file_symbols.get(f, set()))
            score = fan_in * 2 + fan_out + symbol_count

            category = ""
            if fan_in > 10:
                category = "hub"
            elif fan_out > 10:
                category = "coupling"
            elif symbol_count > 20:
                category = "god-file"

            hotspots.append({
                "file": f,
                "score": score,
                "fan_in": fan_in,
                "fan_out": fan_out,
                "category": category,
            })

        hotspots.sort(key=lambda h: h["score"], reverse=True)
        hotspots = hotspots[:15]

        try:
            widget = self.query_one("#graph-hotspots", HotspotHeatmap)
            widget.set_hotspots(hotspots)
        except Exception as e:
            logger.debug("GraphScreen: failed to set hotspots widget: %s", e)

    # --- Message handlers ---

    def on_repo_overview_widget_file_selected(
        self, msg: RepoOverviewWidget.FileSelected
    ) -> None:
        """Drill down: switch to deps or impact view for the selected file."""
        self._navigate_to(msg.view, msg.file_path)

    def on_repo_overview_widget_symbol_selected(
        self, msg: RepoOverviewWidget.SymbolSelected
    ) -> None:
        """Navigate to deps view for the file containing the selected symbol."""
        self._navigate_to("deps", msg.file_path)

    # --- Actions ---

    def action_go_back(self) -> None:
        if not self._nav_history:
            self.dismiss()
            return
        entry = self._nav_history.pop()
        self._navigate_to(entry.mode, entry.file, push_history=False)

    def action_next_view(self) -> None:
        idx = _VIEWS.index(self._mode)
        new_mode = _VIEWS[(idx + 1) % len(_VIEWS)]
        self._navigate_to(
            new_mode,
            self._file if new_mode in ("deps", "impact") else "",
            push_history=False,
        )

    def action_prev_view(self) -> None:
        idx = _VIEWS.index(self._mode)
        new_mode = _VIEWS[(idx - 1) % len(_VIEWS)]
        self._navigate_to(
            new_mode,
            self._file if new_mode in ("deps", "impact") else "",
            push_history=False,
        )


def _short_path(path: str, max_len: int = 25) -> str:
    """Shorten a file path for breadcrumb display."""
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) <= 2:
        return path
    return parts[0] + "/\u2026/" + parts[-1]
