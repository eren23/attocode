"""Tree structure renderer using box-drawing characters.

Usage::

    from attocode.tracing.analysis.views import TreeNode

    root = TreeNode(
        event_id="root",
        kind="iteration",
        label="Iteration 1",
        children=[
            TreeNode(event_id="a", kind="tool_call", label="bash ls"),
            TreeNode(event_id="b", kind="llm_call", label="claude-sonnet"),
        ],
    )
    widget = TreeRenderer(root=root)
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text

from attocode.tracing.analysis.views import TreeNode

# Box-drawing segments.
_TEE = "\u251c\u2500\u2500 "  # ├──
_ELL = "\u2514\u2500\u2500 "  # └──
_PIPE = "\u2502   "           # │   (with trailing spaces for indent)
_SPACE = "    "               # plain indent


class TreeRenderer(Widget):
    """Renders a :class:`TreeNode` hierarchy using box-drawing characters.

    Each node is displayed on its own line with appropriate indentation::

        Iteration 1
        \u251c\u2500\u2500 bash ls (12ms)
        \u2514\u2500\u2500 claude-sonnet
    """

    DEFAULT_CSS = """
    TreeRenderer {
        height: auto;
    }
    """

    root: reactive[TreeNode | None] = reactive(None, layout=True)

    def __init__(
        self,
        root: TreeNode | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.root = root

    def render(self) -> Text:
        if self.root is None:
            return Text("(empty tree)")

        text = Text()
        self._render_node(text, self.root, prefix="", is_last=True, is_root=True)
        return text

    def _render_node(
        self,
        text: Text,
        node: TreeNode,
        prefix: str,
        is_last: bool,
        is_root: bool,
    ) -> None:
        """Recursively render a node and its children."""
        if not is_root:
            connector = _ELL if is_last else _TEE
            text.append(prefix)
            text.append(connector, style="dim")

        # Node label with kind-based styling.
        style = _kind_style(node.kind)
        text.append(node.label, style=style)

        # Optional duration annotation.
        if node.duration_ms is not None:
            text.append(f" ({node.duration_ms:.0f}ms)", style="dim")

        text.append("\n")

        # Recurse into children.
        child_prefix = prefix
        if not is_root:
            child_prefix += _SPACE if is_last else _PIPE

        for i, child in enumerate(node.children):
            is_child_last = i == len(node.children) - 1
            self._render_node(text, child, child_prefix, is_child_last, is_root=False)

    def get_content_height(self, container, viewport, width: int) -> int:  # noqa: ANN001
        """Report the number of lines needed."""
        if self.root is None:
            return 1
        return _count_nodes(self.root)


def _count_nodes(node: TreeNode) -> int:
    """Count total nodes in a tree (each node = 1 line)."""
    return 1 + sum(_count_nodes(c) for c in node.children)


def _kind_style(kind: str) -> str:
    """Return a Rich style based on the node kind."""
    styles: dict[str, str] = {
        "iteration": "bold cyan",
        "llm_call": "bold magenta",
        "tool_call": "green",
        "tool_result": "dim green",
        "error": "bold red",
        "compaction": "yellow",
    }
    return styles.get(kind, "")
