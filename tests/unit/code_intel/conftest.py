"""Shared fixtures for unit/code_intel tests.

Provides base fixtures that individual tool tests can use.
Tool-specific fixtures are in tests/unit/code_intel/tools/conftest.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def unit_test_project(tmp_path: Path) -> Path:
    """Create a minimal project for unit tests.

    This fixture creates a basic Python project structure with:
        - src/main.py
        - src/utils.py
        - tests/test_main.py
        - pyproject.toml

    Use this as a base fixture for tool-specific setups.
    """
    src = tmp_path / "src"
    tests = tmp_path / "tests"

    src.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        "import os\nfrom src.utils import helper\n\ndef main():\n    return helper(42)\n\ndef cli(args):\n    return 0\n"
    )
    (src / "utils.py").write_text(
        "def helper(value):\n    return str(value)\n\nclass BaseProcessor:\n    def process(self): pass\n\nclass DataProcessor(BaseProcessor):\n    def __init__(self, name):\n        self.name = name\n"
    )
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(
        "import pytest\ndef test_basic(): pass\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
    )

    return tmp_path
