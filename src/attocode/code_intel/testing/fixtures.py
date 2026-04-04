"""Standardized pytest fixtures for code intelligence testing.

Provides reusable fixtures for CodeIntelService, ASTService, and
related components. These fixtures handle initialization, cleanup,
and reset of singletons to ensure test isolation.

For real repos, set ATTOCODE_PROJECT_DIR env var before running tests.

Usage::

    import pytest
    from attocode.code_intel.testing.fixtures import code_intel_service, ast_service

    class TestMyTool:
        def test_something(self, code_intel_service, ast_service):
            assert code_intel_service is not None
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from attocode.code_intel.service import CodeIntelService
    from attocode.integrations.context.ast_service import ASTService


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a minimal Python project in tmp_path for testing.

    Creates:
        - src/main.py, src/utils.py
        - tests/test_main.py
        - pyproject.toml
    """
    src = tmp_path / "src"
    tests = tmp_path / "tests"

    src.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        'import os\nfrom src.utils import helper\n\ndef main():\n    """Entry point."""\n    return helper(42)\n\ndef cli(args: list) -> int:\n    """CLI interface."""\n    return 0\n'
    )
    (src / "utils.py").write_text(
        'import os\n\ndef helper(value: int) -> str:\n    """Process a value."""\n    return str(value)\n\nclass BaseProcessor:\n    """Base class."""\n    def process(self) -> None: pass\n'
    )
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(
        'import pytest\nfrom src.main import main\n\ndef test_main():\n    assert main() == "42"\n'
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
    )

    return tmp_path


@pytest.fixture
def code_intel_service(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> "CodeIntelService":
    """Provide a CodeIntelService instance for the sample project.

    Resets all singletons before and after the test to ensure isolation.
    """
    import attocode.code_intel._shared as ci_shared
    from attocode.code_intel.config import CodeIntelConfig
    from attocode.code_intel.service import CodeIntelService

    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(sample_project))

    CodeIntelService._reset_instances()
    ci_shared._service = None
    ci_shared._remote_service = None

    config = CodeIntelConfig(project_dir=str(sample_project))
    service = CodeIntelService.get_instance(str(sample_project))

    yield service

    CodeIntelService._reset_instances()
    ci_shared._service = None
    ci_shared._remote_service = None
    monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)


@pytest.fixture
def ast_service(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> "ASTService":
    """Provide an ASTService instance for the sample project.

    Initializes skeleton indexing for fast test execution.
    """
    import attocode.code_intel._shared as ci_shared
    from attocode.integrations.context.ast_service import ASTService

    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(sample_project))

    ASTService.clear_instances()
    ci_shared._ast_service = None

    service = ASTService.get_instance(str(sample_project))
    if not service.initialized:
        service.initialize_skeleton(indexing_depth="minimal")

    yield service

    ASTService.clear_instances()
    ci_shared._ast_service = None
    monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)
