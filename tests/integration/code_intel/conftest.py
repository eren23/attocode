"""Shared fixtures for code-intel integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService

SAMPLE_PROJECT = str(Path(__file__).resolve().parent.parent.parent / "fixtures" / "sample_project")


@pytest.fixture(scope="session")
def sample_project_dir() -> str:
    """Return the absolute path to the sample project fixture."""
    assert os.path.isdir(SAMPLE_PROJECT), f"Fixture not found: {SAMPLE_PROJECT}"
    return SAMPLE_PROJECT


@pytest.fixture(scope="session")
def service(sample_project_dir: str) -> CodeIntelService:
    """Create a real CodeIntelService on the sample project (shared across session)."""
    config = CodeIntelConfig(project_dir=sample_project_dir)
    svc = CodeIntelService(sample_project_dir, config)
    yield svc
    CodeIntelService._reset_instances()
