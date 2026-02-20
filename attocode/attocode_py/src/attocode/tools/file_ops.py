"""File operation tools: read, write, edit, list, glob."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


def _resolve_path(path: str, working_dir: str | None = None) -> Path:
    p = Path(path)
    if not p.is_absolute() and working_dir:
        p = Path(working_dir) / p
    return p.resolve()


async def read_file(args: dict[str, Any], working_dir: str | None = None) -> str:
    path = _resolve_path(args["path"], working_dir)
    if not path.exists():
        return f"Error: File not found: {path}"
    if not path.is_file():
        return f"Error: Not a file: {path}"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading file: {e}"

    offset = args.get("offset", 0)
    limit = args.get("limit")
    lines = content.splitlines(keepends=True)
    if offset > 0:
        lines = lines[offset:]
    if limit is not None:
        lines = lines[:limit]

    numbered = []
    for i, line in enumerate(lines, start=offset + 1):
        numbered.append(f"{i:>6}\t{line}")
    return "".join(numbered) if numbered else "(empty file)"


async def write_file(args: dict[str, Any], working_dir: str | None = None) -> str:
    path = _resolve_path(args["path"], working_dir)
    content = args["content"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except OSError as e:
        return f"Error writing file: {e}"


async def edit_file(args: dict[str, Any], working_dir: str | None = None) -> str:
    path = _resolve_path(args["path"], working_dir)
    old_string = args["old_string"]
    new_string = args["new_string"]
    replace_all = args.get("replace_all", False)

    if not path.exists():
        return f"Error: File not found: {path}"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error reading file: {e}"

    if old_string not in content:
        return f"Error: old_string not found in {path}"

    if not replace_all:
        count = content.count(old_string)
        if count > 1:
            return f"Error: old_string appears {count} times in {path}. Use replace_all=true or provide more context."
        content = content.replace(old_string, new_string, 1)
    else:
        content = content.replace(old_string, new_string)

    try:
        path.write_text(content, encoding="utf-8")
        return f"Successfully edited {path}"
    except OSError as e:
        return f"Error writing file: {e}"


async def list_files(args: dict[str, Any], working_dir: str | None = None) -> str:
    path = _resolve_path(args.get("path", "."), working_dir)
    if not path.exists():
        return f"Error: Directory not found: {path}"
    if not path.is_dir():
        return f"Error: Not a directory: {path}"
    try:
        entries = sorted(path.iterdir())
        lines = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{entry.name}{suffix}")
        return "\n".join(lines) if lines else "(empty directory)"
    except OSError as e:
        return f"Error listing directory: {e}"


async def glob_files(args: dict[str, Any], working_dir: str | None = None) -> str:
    pattern = args["pattern"]
    path = _resolve_path(args.get("path", "."), working_dir)
    if not path.exists():
        return f"Error: Directory not found: {path}"
    try:
        matches = sorted(path.glob(pattern))
        max_results = args.get("max_results", 100)
        if len(matches) > max_results:
            lines = [str(m.relative_to(path)) for m in matches[:max_results]]
            lines.append(f"... and {len(matches) - max_results} more")
        else:
            lines = [str(m.relative_to(path)) for m in matches]
        return "\n".join(lines) if lines else "No matches found"
    except OSError as e:
        return f"Error: {e}"


def create_file_tools(working_dir: str | None = None) -> list[Tool]:
    async def _read(args: dict[str, Any]) -> Any:
        return await read_file(args, working_dir)

    async def _write(args: dict[str, Any]) -> Any:
        return await write_file(args, working_dir)

    async def _edit(args: dict[str, Any]) -> Any:
        return await edit_file(args, working_dir)

    async def _list(args: dict[str, Any]) -> Any:
        return await list_files(args, working_dir)

    async def _glob(args: dict[str, Any]) -> Any:
        return await glob_files(args, working_dir)

    return [
        Tool(
            spec=ToolSpec(
                name="read_file",
                description="Read a file from the filesystem.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path to read"},
                        "offset": {"type": "integer", "description": "Line offset", "default": 0},
                        "limit": {"type": "integer", "description": "Max lines to read"},
                    },
                    "required": ["path"],
                },
            ),
            execute=_read,
            tags=["file", "read"],
        ),
        Tool(
            spec=ToolSpec(
                name="write_file",
                description="Write content to a file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
                danger_level=DangerLevel.MODERATE,
            ),
            execute=_write,
            tags=["file", "write"],
        ),
        Tool(
            spec=ToolSpec(
                name="edit_file",
                description="Edit a file by replacing old_string with new_string.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path to edit"},
                        "old_string": {"type": "string", "description": "Text to replace"},
                        "new_string": {"type": "string", "description": "Replacement text"},
                        "replace_all": {"type": "boolean", "default": False},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
                danger_level=DangerLevel.MODERATE,
            ),
            execute=_edit,
            tags=["file", "edit"],
        ),
        Tool(
            spec=ToolSpec(
                name="list_files",
                description="List files in a directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                    },
                },
            ),
            execute=_list,
            tags=["file", "list"],
        ),
        Tool(
            spec=ToolSpec(
                name="glob_files",
                description="Find files matching a glob pattern.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern"},
                        "path": {"type": "string", "default": "."},
                        "max_results": {"type": "integer", "default": 100},
                    },
                    "required": ["pattern"],
                },
            ),
            execute=_glob,
            tags=["file", "search"],
        ),
    ]
