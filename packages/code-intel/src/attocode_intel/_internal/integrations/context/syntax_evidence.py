"""Syntax evidence shared by navigation and optional precise lookup.

These candidates describe source syntax, not type-resolved relationships.
"""
from __future__ import annotations

from pathlib import Path


def rust_imports(node, source: bytes) -> list[dict]:
    def text(n):
        return source[n.start_byte:n.end_byte].decode()

    line = node.start_point[0] + 1
    if node.type == "mod_item":
        name = node.child_by_field_name("name")
        return ([{"module": "mod:" + text(name), "start_line": line}]
                if name and not node.child_by_field_name("body") else [])
    result = []

    def visit(n, prefix=""):
        if n.type == "scoped_use_list":
            path = n.child_by_field_name("path")
            visit(n.child_by_field_name("list"), prefix + (text(path) + "::" if path else ""))
        elif n.type == "use_list":
            for child in n.named_children:
                visit(child, prefix)
        else:
            path = n.child_by_field_name("path") if n.type == "use_as_clause" else n
            alias = n.child_by_field_name("alias") if n.type == "use_as_clause" else None
            module = prefix + text(path)
            module = module.removesuffix("::self")
            name = module.rsplit("::", 1)[-1]
            result.append({"module": module, "names": [] if name == "*" else [name],
                           "alias": text(alias) if alias else "", "start_line": line})

    argument = node.child_by_field_name("argument")
    if argument:
        visit(argument)
    return result


def syntax_tree(path: str, content: str, language: str):
    from .ts_parser import _get_parser
    parser = _get_parser("tsx" if Path(path).suffix == ".tsx" else language)
    return parser.parse(content.encode()) if parser else None


def reference_candidates(path: str, content: str, language: str):
    """Return call/type candidates, or None when syntax parsing is unavailable."""
    tree = syntax_tree(path, content, language)
    if tree is None:
        return None
    source = content.encode()
    result = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in {"comment", "line_comment", "block_comment", "string", "string_literal"}:
            continue
        if node.type in {"call", "call_expression", "method_invocation", "object_creation_expression", "new_expression"}:
            target = (node.child_by_field_name("function") or node.child_by_field_name("name")
                      or node.child_by_field_name("constructor"))
            if target:
                # Generic Rust calls have a wrapper around their function path.
                target = target.child_by_field_name("function") or target
                name = source[target.start_byte:target.end_byte].decode().replace("::", ".")
                if all(part.isidentifier() for part in name.split(".")):
                    result.append((name, "call", target.start_point[0] + 1))
                    if language == "rust" and "." in name:
                        result.append((name.rsplit(".", 1)[0], "attribute", target.start_point[0] + 1))
        stack.extend(reversed(node.named_children))
    return result


def symbol_position(path: str, name: str, start_line: int, end_line: int, language: str):
    """Locate the identifier token, returning LSP's UTF-16 position."""
    content = Path(path).read_text(encoding="utf-8")
    tree = syntax_tree(path, content, language)
    if tree is None:
        return None
    source = content.encode()
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        line = node.start_point[0] + 1
        if node.end_point[0] + 1 < start_line or line > end_line:
            continue
        if (node.type in {"identifier", "type_identifier", "property_identifier", "field_identifier"}
                and source[node.start_byte:node.end_byte].decode() == name):
            prefix = source[:node.start_byte].rsplit(b"\n", 1)[-1].decode()
            return line - 1, len(prefix.encode("utf-16-le")) // 2
        stack.extend(reversed(node.named_children))
    return None
