"""Repo overview widget — interactive codebase tree with search and lazy symbol loading."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Static, Tree

from attocode.tui.widgets.command_palette import fuzzy_match

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 0.3


class RepoOverviewWidget(Widget):
    """Interactive codebase overview with tree-based file/symbol hierarchy.

    Sections: Languages (bar chart), searchable Tree with Entry Points,
    Top Files (expandable to symbols), and Dependency Hubs.
    Selecting a file posts FileSelected; selecting a symbol posts SymbolSelected.
    """

    DEFAULT_CSS = """
    RepoOverviewWidget {
        height: auto;
        max-height: 100;
        overflow-y: auto;
        padding: 0 1;
        display: none;
    }
    RepoOverviewWidget.visible {
        display: block;
    }
    RepoOverviewWidget #overview-search {
        margin: 0 0 1 0;
    }
    RepoOverviewWidget #codebase-tree {
        height: auto;
        max-height: 40;
    }
    RepoOverviewWidget Collapsible {
        margin: 0 0 1 0;
    }
    """

    BAR_WIDTH = 25

    class FileSelected(Message):
        """Posted when user selects a file node."""

        def __init__(self, file_path: str, view: str) -> None:
            super().__init__()
            self.file_path = file_path
            self.view = view  # "deps" or "impact"

    class SymbolSelected(Message):
        """Posted when user selects a symbol node."""

        def __init__(self, file_path: str, symbol_name: str, start_line: int) -> None:
            super().__init__()
            self.file_path = file_path
            self.symbol_name = symbol_name
            self.start_line = start_line

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir: str = ""
        self._total_files: int = 0
        self._total_lines: int = 0
        self._languages: dict[str, int] = {}
        self._top_files: list[dict[str, Any]] = []
        self._entry_points: list[str] = []
        self._dep_stats: dict[str, Any] = {}
        self._ast_service: Any = None
        self._loaded_file_nodes: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Static("", id="overview-header")
        yield Static("", id="overview-summary")
        yield Collapsible(
            Static("", id="lang-chart"),
            title="Languages",
            id="overview-langs",
        )
        yield Input(placeholder="Search files and symbols...", id="overview-search")
        yield Tree("Codebase Explorer", id="codebase-tree")

    def set_overview(
        self,
        *,
        root_dir: str = "",
        total_files: int = 0,
        total_lines: int = 0,
        languages: dict[str, int] | None = None,
        top_files: list[dict[str, Any]] | None = None,
        entry_points: list[str] | None = None,
        dep_stats: dict[str, Any] | None = None,
    ) -> None:
        """Update the displayed overview data by populating child widgets."""
        self._root_dir = root_dir
        self._total_files = total_files
        self._total_lines = total_lines
        self._languages = languages or {}
        self._top_files = top_files or []
        self._entry_points = entry_points or []
        self._dep_stats = dep_stats or {}

        self._update_header_and_langs()
        self._rebuild_tree()
        self.add_class("visible")

    def set_ast_service(self, svc: Any) -> None:
        """Inject an already-initialized ASTService."""
        self._ast_service = svc

    # --- Internal: header / summary / languages ---

    def _update_header_and_langs(self) -> None:
        if not self._total_files:
            return

        # Header
        header = self.query_one("#overview-header", Static)
        header_text = Text()
        header_text.append("Repo Overview", style="bold underline")
        if self._root_dir:
            header_text.append(f" — {self._root_dir}", style="dim")
        header.update(header_text)

        # Summary
        summary = self.query_one("#overview-summary", Static)
        n_langs = len(self._languages)
        sum_text = Text()
        sum_text.append(f"  {self._total_files} files", style="bold cyan")
        sum_text.append("  |  ", style="dim")
        sum_text.append(f"{self._total_lines:,} lines", style="bold cyan")
        sum_text.append("  |  ", style="dim")
        sum_text.append(
            f"{n_langs} language{'s' if n_langs != 1 else ''}", style="bold cyan"
        )
        summary.update(sum_text)

        # Languages bar chart
        if self._languages:
            lang_chart = self.query_one("#lang-chart", Static)
            lang_text = Text()
            total = sum(self._languages.values())
            sorted_langs = sorted(
                self._languages.items(), key=lambda x: x[1], reverse=True
            )
            for lang, count in sorted_langs[:10]:
                pct = (count / total * 100) if total else 0
                filled = int(pct / 100 * self.BAR_WIDTH)
                empty = self.BAR_WIDTH - filled

                if pct >= 40:
                    bar_style = "bold green"
                elif pct >= 15:
                    bar_style = "yellow"
                else:
                    bar_style = "cyan"

                label = f"{lang} ({count})".ljust(22)
                lang_text.append(f"  {label} ")
                lang_text.append("\u2588" * filled, style=bar_style)
                lang_text.append("\u2591" * empty, style="dim")
                lang_text.append(f" {pct:.0f}%\n", style="dim")
            lang_chart.update(lang_text)

    # --- Tree building ---

    def _rebuild_tree(self, filter_query: str = "") -> None:
        """Build/rebuild the codebase tree, optionally filtered."""
        try:
            tree = self.query_one("#codebase-tree", Tree)
        except Exception:
            return

        tree.clear()
        self._loaded_file_nodes.clear()

        if not self._total_files:
            tree.root.set_label("Codebase Explorer (0 files)")
            return

        tree.root.set_label(f"Codebase Explorer ({self._total_files} files)")

        q = filter_query.lower()

        # Collect AST symbol names for search matching
        ast_symbol_map: dict[str, list[str]] = {}  # rel_path -> [symbol_names]
        if q:
            svc = self._get_ast_service()
            if svc:
                for rel_path, file_ast in svc._ast_cache.items():
                    names: list[str] = []
                    for fn in file_ast.functions:
                        names.append(fn.name)
                    for cls in file_ast.classes:
                        names.append(cls.name)
                        for m in cls.methods:
                            names.append(m.name)
                    names.extend(file_ast.top_level_vars)
                    ast_symbol_map[rel_path] = names

        # --- Entry Points ---
        filtered_entries = [
            ep for ep in self._entry_points
            if not q or self._best_match_score(ep, q, ast_symbol_map) >= _FUZZY_THRESHOLD
        ]
        if filtered_entries:
            entry_branch = tree.root.add("Entry Points", data={"kind": "category"})
            for ep in filtered_entries:
                node = entry_branch.add(ep, data={"kind": "file", "path": ep, "view": "deps"})
                node.add_leaf("Loading symbols...", data={"kind": "placeholder"})

        # --- Top Files ---
        filtered_top = [
            f for f in self._top_files
            if not q
            or self._best_match_score(f.get("relative_path", ""), q, ast_symbol_map) >= _FUZZY_THRESHOLD
        ]
        if filtered_top:
            top_branch = tree.root.add("Top Files (by importance)", data={"kind": "category"})
            for f in filtered_top:
                rp = f.get("relative_path", "?")
                importance = f.get("importance", 0.0)
                lang = f.get("language", "")
                label = f"{_short_path(rp)}  [{importance:.2f}] {lang}"
                node = top_branch.add(label, data={"kind": "file", "path": rp, "view": "deps"})
                node.add_leaf("Loading symbols...", data={"kind": "placeholder"})
                # Auto-expand if a symbol name fuzzy-matched the query
                # Skip single-char queries to avoid expanding everything
                if q and len(q) >= 2:
                    symbol_names = ast_symbol_map.get(rp, [])
                    if any(fuzzy_match(q, n) >= _FUZZY_THRESHOLD for n in symbol_names):
                        node.expand()

        # --- Dependency Hubs ---
        top_hubs = self._dep_stats.get("top_hubs", [])
        filtered_hubs = [
            (path, count) for path, count in top_hubs
            if not q
            or self._best_match_score(path, q, ast_symbol_map) >= _FUZZY_THRESHOLD
        ]
        if filtered_hubs:
            hub_branch = tree.root.add("Dependency Hubs", data={"kind": "category"})
            for path, count in filtered_hubs:
                label = f"{_short_path(path)}  (<- {count} importers)"
                node = hub_branch.add(
                    label,
                    data={"kind": "file", "path": path, "view": "impact"},
                )
                node.add_leaf("Loading symbols...", data={"kind": "placeholder"})
                if q and len(q) >= 2:
                    symbol_names = ast_symbol_map.get(path, [])
                    if any(fuzzy_match(q, n) >= _FUZZY_THRESHOLD for n in symbol_names):
                        node.expand()

        tree.root.expand()

    def _best_match_score(
        self, path: str, query: str, symbol_map: dict[str, list[str]]
    ) -> float:
        """Return best fuzzy match score across file path and its symbol names."""
        best = fuzzy_match(query, path)
        for name in symbol_map.get(path, []):
            best = max(best, fuzzy_match(query, name))
        return best

    # --- Lazy symbol loading on expand ---

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        data = node.data
        if not isinstance(data, dict) or data.get("kind") != "file":
            return

        path = data.get("path", "")
        if path in self._loaded_file_nodes:
            return
        self._loaded_file_nodes.add(path)

        # Remove placeholder children
        node.remove_children()

        svc = self._get_ast_service()
        if svc is None:
            node.add_leaf("(AST service unavailable)", data={"kind": "placeholder"})
            return

        rel = svc.to_rel(path)
        file_ast = svc._ast_cache.get(rel)
        if file_ast is None:
            node.add_leaf("(no symbols indexed)", data={"kind": "placeholder"})
            return

        has_symbols = False

        # Classes as branches with methods underneath
        for cls in file_ast.classes:
            bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            cls_label = f"cls {cls.name}{bases_str}  L{cls.start_line}-{cls.end_line}"
            cls_node = node.add(
                cls_label,
                data={
                    "kind": "symbol",
                    "path": path,
                    "name": cls.name,
                    "qualified_name": cls.name,
                    "symbol_kind": "class",
                    "start_line": cls.start_line,
                    "end_line": cls.end_line,
                },
            )
            for method in cls.methods:
                prefix = "async fn" if method.is_async else "fn"
                params = ", ".join(method.params[:4])
                if len(method.params) > 4:
                    params += ", ..."
                m_label = f"{prefix} {method.name}({params})  L{method.start_line}-{method.end_line}"
                cls_node.add_leaf(
                    m_label,
                    data={
                        "kind": "symbol",
                        "path": path,
                        "name": method.name,
                        "qualified_name": f"{cls.name}.{method.name}",
                        "symbol_kind": "method",
                        "start_line": method.start_line,
                        "end_line": method.end_line,
                    },
                )
            has_symbols = True

        # Top-level functions as leaves (filtering applies for all query lengths,
        # but auto-expand only kicks in for len(q) >= 2 — this intentional asymmetry
        # reduces noise for single-char queries while still narrowing the file list)
        for fn in file_ast.functions:
            if fn.is_method:
                continue
            prefix = "async fn" if fn.is_async else "fn"
            params = ", ".join(fn.params[:4])
            if len(fn.params) > 4:
                params += ", ..."
            fn_label = f"{prefix} {fn.name}({params})  L{fn.start_line}-{fn.end_line}"
            node.add_leaf(
                fn_label,
                data={
                    "kind": "symbol",
                    "path": path,
                    "name": fn.name,
                    "qualified_name": fn.name,
                    "symbol_kind": "function",
                    "start_line": fn.start_line,
                    "end_line": fn.end_line,
                },
            )
            has_symbols = True

        # Top-level constants
        for var_name in file_ast.top_level_vars:
            node.add_leaf(
                f"const {var_name}",
                data={
                    "kind": "symbol",
                    "path": path,
                    "name": var_name,
                    "qualified_name": var_name,
                    "symbol_kind": "variable",
                    "start_line": 0,
                    "end_line": 0,
                },
            )
            has_symbols = True

        if not has_symbols:
            node.add_leaf("(no symbols)", data={"kind": "placeholder"})

    # --- Node selection ---

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not isinstance(data, dict):
            return

        kind = data.get("kind")
        if kind == "file":
            self.post_message(
                self.FileSelected(data["path"], data.get("view", "deps"))
            )
        elif kind == "symbol":
            self.post_message(
                self.SymbolSelected(
                    data["path"],
                    data.get("qualified_name", data["name"]),
                    data.get("start_line", 0),
                )
            )

    # --- Search ---

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "overview-search":
            return
        self._rebuild_tree(filter_query=event.value.strip())

    # --- AST service access ---

    def _get_ast_service(self) -> Any:
        if self._ast_service is not None:
            return self._ast_service
        try:
            from attocode.integrations.context.ast_service import ASTService

            svc = ASTService.get_instance(self._root_dir or ".")
            if not svc.initialized:
                svc.initialize()
            self._ast_service = svc
            return svc
        except Exception:
            return None


def _short_path(path: str, max_len: int = 45) -> str:
    """Shorten a file path for display, preserving start and end."""
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) <= 3:
        return path
    short = "/".join(parts[:1]) + "/\u2026/" + "/".join(parts[-2:])
    if len(short) <= max_len:
        return short
    return path[: max_len - 1] + "\u2026"
