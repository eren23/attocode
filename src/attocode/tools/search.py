"""Search tools: grep with optional trigram index pre-filtering."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from attocode.tools.base import Tool, ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigram index cache: one TrigramIndex per resolved project root.
# Populated lazily on first grep call; None = index unavailable.
# ---------------------------------------------------------------------------
_trigram_indexes: dict[str, Any] = {}


def _get_trigram_index(root: Path) -> Any | None:
    """Return a loaded TrigramIndex for *root*, or None if unavailable."""
    key = str(root)
    if key in _trigram_indexes:
        return _trigram_indexes[key]

    index_dir = root / ".attocode" / "index"
    if not index_dir.is_dir():
        _trigram_indexes[key] = None
        return None

    try:
        from attocode.integrations.context.trigram_index import TrigramIndex

        idx = TrigramIndex(index_dir=str(index_dir))
        if idx.load():
            _trigram_indexes[key] = idx
            logger.debug("trigram index loaded for %s", root)
        else:
            _trigram_indexes[key] = None
    except Exception:
        logger.debug("Failed to load trigram index for %s", root, exc_info=True)
        _trigram_indexes[key] = None

    return _trigram_indexes[key]


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

    # ------------------------------------------------------------------
    # Determine candidate file list.
    # Fast path: trigram index pre-filters to a narrow candidate set.
    # Slow path: full rglob (original behaviour, always correct).
    # ------------------------------------------------------------------
    if root.is_file():
        files: list[Path] = [root]
    else:
        trigram_idx = _get_trigram_index(root)
        if trigram_idx is not None and trigram_idx.is_ready():
            candidate_paths = trigram_idx.query(
                pattern, case_insensitive=case_insensitive
            )
            if candidate_paths is not None:
                if glob_filter:
                    import fnmatch
                    candidate_paths = [
                        p for p in candidate_paths
                        if fnmatch.fnmatch(Path(p).name, glob_filter)
                    ]
                files = sorted(root / p for p in candidate_paths)
                logger.debug(
                    "trigram filter: %d candidates for pattern %r",
                    len(files), pattern,
                )
            else:
                files = sorted(root.rglob(glob_filter or "*"))
        else:
            files = sorted(root.rglob(glob_filter or "*"))

    matches: list[str] = []

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
