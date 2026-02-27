"""Tab 8: AST & Blackboard Inspector pane."""

from __future__ import annotations

import json
import os
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static, Tree


class ASTExplorerMini(Widget):
    """Mini AST explorer showing indexed files and their symbols."""

    DEFAULT_CSS = """
    ASTExplorerMini {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, ast_service: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ast_service = ast_service
        self._codemap: dict[str, Any] | None = None

    def compose(self):
        yield Tree("AST Index", id="ast-tree")

    def on_mount(self) -> None:
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        """Build the tree from AST service or codemap snapshot."""
        try:
            tree = self.query_one("#ast-tree", Tree)
        except Exception:
            return

        tree.clear()

        # Try direct AST service first
        if self._ast_service and hasattr(self._ast_service, "_ast_cache"):
            self._build_from_service(tree)
            return

        # Fallback: read codemap.json
        if self._codemap:
            self._build_from_codemap(tree)

    def _build_from_service(self, tree: Tree) -> None:
        """Build tree from live AST service."""
        svc = self._ast_service
        if not svc or not hasattr(svc, "_ast_cache"):
            return

        file_count = len(svc._ast_cache)
        symbol_count = sum(
            len(v) for v in svc.index.definitions.values()
        ) if svc.index else 0

        root = tree.root
        root.label = f"AST Index ({file_count} files, {symbol_count} symbols)"

        for rel_path in sorted(svc._ast_cache.keys())[:100]:
            file_ast = svc._ast_cache[rel_path]
            symbols: list[str] = []
            for func in getattr(file_ast, "functions", []):
                symbols.append(f"fn {func.name}")
            for cls in getattr(file_ast, "classes", []):
                symbols.append(f"cls {cls.name}")

            node = root.add(f"{rel_path} ({len(symbols)} symbols)")
            for sym in symbols[:20]:
                node.add_leaf(sym)

        root.expand()

    def _build_from_codemap(self, tree: Tree) -> None:
        """Build tree from a codemap.json dict."""
        root = tree.root
        data = self._codemap or {}
        files = data.get("files", {})
        root.label = f"AST Index ({len(files)} files)"

        for fpath, fdata in sorted(list(files.items())[:100]):
            symbols = fdata.get("symbols", [])
            node = root.add(f"{fpath} ({len(symbols)} symbols)")
            for sym in symbols[:20]:
                if isinstance(sym, dict):
                    node.add_leaf(f"{sym.get('kind', '?')} {sym.get('name', '?')}")
                else:
                    node.add_leaf(str(sym))

        root.expand()

    def load_codemap(self, output_dir: str) -> None:
        """Load codemap.json from the event bridge output dir."""
        path = os.path.join(output_dir, "codemap.json")
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    self._codemap = json.load(f)
                self._refresh_tree()
            except Exception:
                pass

    def set_ast_service(self, svc: Any) -> None:
        """Set the AST service reference and refresh."""
        self._ast_service = svc
        self._refresh_tree()


class BlackboardInspector(Widget):
    """Blackboard metrics and entry browser."""

    DEFAULT_CSS = """
    BlackboardInspector {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, blackboard: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._blackboard = blackboard
        self._snapshot: dict[str, Any] | None = None

    def render(self) -> Text:
        text = Text()
        text.append("Blackboard Inspector\n", style="bold underline")
        text.append("\n")

        entries: dict[str, Any] = {}
        metrics: dict[str, int] = {}

        # Try live blackboard first
        if self._blackboard:
            try:
                if hasattr(self._blackboard, "get_metrics"):
                    metrics = self._blackboard.get_metrics()
                if hasattr(self._blackboard, "items"):
                    for key, val in self._blackboard.items():
                        entries[key] = val
            except Exception:
                pass
        elif self._snapshot:
            entries = self._snapshot.get("entries", {})
            metrics = self._snapshot.get("metrics", {})

        # Metrics
        text.append("Metrics\n", style="bold")
        text.append(f"  Entries: {metrics.get('total', len(entries))}\n", style="dim")
        text.append(f"  Reads:  {metrics.get('reads', 0)}\n", style="dim")
        text.append(f"  Writes: {metrics.get('writes', 0)}\n", style="dim")
        text.append(f"  Deletes:{metrics.get('deletes', 0)}\n", style="dim")

        text.append("\n")

        # Entries (grouped by namespace prefix)
        if entries:
            text.append("Entries\n", style="bold")
            namespaces: dict[str, list[tuple[str, Any]]] = {}
            for key, val in sorted(entries.items()):
                ns = key.split(".")[0] if "." in key else key.split("/")[0] if "/" in key else "_root"
                namespaces.setdefault(ns, []).append((key, val))

            for ns in sorted(namespaces):
                text.append(f"  [{ns}]\n", style="cyan")
                for key, val in namespaces[ns][:10]:
                    val_str = str(val)[:60] if val is not None else "null"
                    text.append(f"    {key}: ", style="dim bold")
                    text.append(f"{val_str}\n", style="dim")
                if len(namespaces[ns]) > 10:
                    text.append(f"    ... +{len(namespaces[ns]) - 10} more\n", style="dim")
        else:
            text.append("No entries\n", style="dim italic")

        return text

    def load_snapshot(self, output_dir: str) -> None:
        """Load blackboard.json from the event bridge output dir."""
        path = os.path.join(output_dir, "blackboard.json")
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    self._snapshot = json.load(f)
                self.refresh()
            except Exception:
                pass

    def set_blackboard(self, bb: Any) -> None:
        """Set the blackboard reference."""
        self._blackboard = bb
        self.refresh()


class ASTBlackboardPane(Widget):
    """Two sub-panels (horizontal split): AST Explorer + Blackboard Inspector."""

    DEFAULT_CSS = """
    ASTBlackboardPane {
        height: 1fr;
    }
    ASTBlackboardPane #astbb-left {
        width: 1fr;
    }
    ASTBlackboardPane #astbb-right {
        width: 1fr;
    }
    """

    def __init__(
        self,
        ast_service: Any = None,
        blackboard: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ast_service = ast_service
        self._blackboard = blackboard

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="astbb-left"):
                yield ASTExplorerMini(
                    ast_service=self._ast_service,
                    id="ast-explorer-mini",
                )
            with Vertical(id="astbb-right"):
                yield BlackboardInspector(
                    blackboard=self._blackboard,
                    id="bb-inspector",
                )

    def update_state(self, state: dict[str, Any], output_dir: str = "") -> None:
        """Refresh AST explorer and blackboard inspector from disk or live data."""
        # Reload codemap and blackboard snapshots from output_dir if available
        if output_dir:
            try:
                self.query_one("#ast-explorer-mini", ASTExplorerMini).load_codemap(
                    output_dir
                )
            except Exception:
                pass
            try:
                self.query_one("#bb-inspector", BlackboardInspector).load_snapshot(
                    output_dir
                )
            except Exception:
                pass
        else:
            # Just refresh the blackboard (uses live reference if set)
            try:
                self.query_one("#bb-inspector", BlackboardInspector).refresh()
            except Exception:
                pass
