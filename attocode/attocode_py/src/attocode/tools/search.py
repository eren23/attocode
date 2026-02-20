"""Search tools: grep."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def grep_search(args: dict[str, Any], working_dir: str | None = None) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_filter = args.get("glob")
    max_results = args.get("max_results", 50)
    case_insensitive = args.get("case_insensitive", False)

    root = Path(path) if Path(path).is_absolute() else Path(working_dir or os.getcwd()) / path
    root = root.resolve()

    if not root.exists():
        return f"Error: Path not found: {root}"

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    matches: list[str] = []
    files = [root] if root.is_file() else sorted(root.rglob(glob_filter or "*"))

    for file in files:
        if not file.is_file() or file.name.startswith("."):
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        for i, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                rel = file.relative_to(root) if root.is_dir() else file.name
                matches.append(f"{rel}:{i}: {line.strip()}")
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    if not matches:
        return "No matches found"

    result = "\n".join(matches)
    if len(matches) >= max_results:
        result += f"\n... (limited to {max_results} results)"
    return result


def create_search_tools(working_dir: str | None = None) -> list[Tool]:
    async def _grep(args: dict[str, Any]) -> Any:
        return await grep_search(args, working_dir)

    return [
        Tool(
            spec=ToolSpec(
                name="grep",
                description="Search file contents using regex patterns.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "glob": {"type": "string"},
                        "max_results": {"type": "integer", "default": 50},
                        "case_insensitive": {"type": "boolean", "default": False},
                    },
                    "required": ["pattern"],
                },
            ),
            execute=_grep,
            tags=["search", "grep"],
        ),
    ]
