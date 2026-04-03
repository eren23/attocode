"""Helper utilities for code intelligence testing.

Provides utility functions for creating test projects and
common test patterns. For real repos, use ATTOCODE_PROJECT_DIR.

Usage::

    from attocode.code_intel.testing.helpers import create_sample_project

    # Create a project with custom files
    project = create_sample_project(tmp_path, {
        "src/main.py": "def foo(): pass",
        "src/utils.py": "def bar(): pass",
    })
"""

from __future__ import annotations

from pathlib import Path


def create_sample_project(
    tmp_path: Path,
    files: dict[str, str],
    *,
    with_git: bool = False,
) -> Path:
    """Create a sample project with custom file structure.

    Args:
        tmp_path: The parent temporary directory.
        files: Dict mapping file paths (relative to project root)
               to their contents.
        with_git: Whether to create a .git directory.

    Returns:
        Path to the created project root.

    Example::

        project = create_sample_project(tmp_path, {
            "src/main.py": "def main(): pass",
            "src/utils.py": "def helper(): pass",
            "tests/test_main.py": "def test_main(): pass",
        })
    """
    for file_path, content in files.items():
        full_path = tmp_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    if with_git:
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "config").write_text("[core]\n\tautocrlf = true\n")

    return tmp_path


def get_tool_names() -> list[str]:
    """Return the list of MCP tool module names.

    Returns:
        List of tool module names (without .py extension).
    """
    from attocode.code_intel import tools as tools_module

    tool_dir = Path(tools_module.__file__).parent
    return [f.stem for f in tool_dir.glob("*.py") if not f.stem.startswith("_")]


__all__ = [
    "create_sample_project",
    "get_tool_names",
]
