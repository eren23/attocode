"""Shared utilities for the HTTP API."""

from __future__ import annotations

import os

# Language detection by extension
LANG_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescriptreact", ".jsx": "javascriptreact",
    ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".metal": "cpp",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".xml": "xml", ".html": "html", ".css": "css",
    ".sql": "sql", ".md": "markdown", ".txt": "plaintext",
    ".dockerfile": "dockerfile",
}

# Max file size for content retrieval (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


def detect_language(path: str) -> str:
    """Detect language from file extension."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in LANG_MAP:
        return LANG_MAP[ext]
    basename = os.path.basename(path).lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename == "makefile":
        return "makefile"
    return ""


def is_binary(data: bytes) -> bool:
    """Heuristic binary detection: check for null bytes in first 8KB."""
    return b"\x00" in data[:8192]
