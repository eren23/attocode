"""Tests for ASTService progressive hydration."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.integrations.context.ast_service import ASTService
from attocode.integrations.context.hydration import (
    TIER_MEDIUM,
    TIER_SMALL,
    HydrationState,
)


def _create_python_files(root: Path, count: int) -> None:
    """Create N Python files with simple content."""
    src = root / "src"
    src.mkdir(exist_ok=True)
    for i in range(count):
        (src / f"mod_{i}.py").write_text(
            f"def func_{i}():\n    return {i}\n\nclass Class_{i}:\n    pass\n",
            encoding="utf-8",
        )


class TestInitializeSkeleton:
    def test_small_repo_parses_all(self, tmp_path: Path):
        _create_python_files(tmp_path, 10)
        svc = ASTService(str(tmp_path))
        state = svc.initialize_skeleton()
        assert state.tier == TIER_SMALL
        assert state.parsed_files == 10
        assert state.phase == "ready"

    def test_medium_repo_parses_subset(self, tmp_path: Path):
        _create_python_files(tmp_path, 1500)
        svc = ASTService(str(tmp_path))
        state = svc.initialize_skeleton()
        assert state.tier == TIER_MEDIUM
        assert state.parsed_files <= 500
        assert state.phase == "skeleton"
        assert svc.initialized

    def test_skeleton_indexes_definitions(self, tmp_path: Path):
        _create_python_files(tmp_path, 5)
        svc = ASTService(str(tmp_path))
        svc.initialize_skeleton()
        assert len(svc._index.definitions) > 0


class TestEnsureFileParsed:
    def test_parses_missing_file(self, tmp_path: Path):
        _create_python_files(tmp_path, 1500)
        svc = ASTService(str(tmp_path))
        svc.initialize_skeleton()
        all_files = list((tmp_path / "src").glob("*.py"))
        unparsed = [
            f for f in all_files
            if os.path.relpath(f, tmp_path) not in svc._ast_cache
        ]
        assert len(unparsed) > 0
        rel = os.path.relpath(unparsed[0], tmp_path)
        result = svc.ensure_file_parsed(rel)
        assert result is True
        assert rel in svc._ast_cache

    def test_noop_for_already_parsed(self, tmp_path: Path):
        _create_python_files(tmp_path, 5)
        svc = ASTService(str(tmp_path))
        svc.initialize_skeleton()
        rel = "src/mod_0.py"
        result = svc.ensure_file_parsed(rel)
        assert result is False


class TestEnsureReferencesIndexed:
    def test_indexes_references_on_demand(self, tmp_path: Path):
        _create_python_files(tmp_path, 1500)
        svc = ASTService(str(tmp_path))
        svc.initialize_skeleton()
        rel = "src/mod_0.py"
        svc.ensure_file_parsed(rel)
        svc.ensure_references_indexed(rel)
        assert rel in svc._reference_indexed_files


import time


class TestStartHydration:
    def test_hydrates_remaining_files(self, tmp_path: Path):
        _create_python_files(tmp_path, 1500)
        svc = ASTService(str(tmp_path))
        state = svc.initialize_skeleton()
        initial_parsed = state.parsed_files
        assert initial_parsed <= 500

        svc.start_hydration()
        for _ in range(100):
            time.sleep(0.1)
            if state.phase == "ready":
                break
        svc.stop_hydration()

        assert state.parsed_files > initial_parsed
        assert state.phase == "ready"

    def test_noop_on_small_repo(self, tmp_path: Path):
        _create_python_files(tmp_path, 10)
        svc = ASTService(str(tmp_path))
        state = svc.initialize_skeleton()
        assert state.phase == "ready"
        svc.start_hydration()
        svc.stop_hydration()
        assert state.phase == "ready"

    def test_stop_hydration_is_safe(self, tmp_path: Path):
        _create_python_files(tmp_path, 10)
        svc = ASTService(str(tmp_path))
        svc.initialize_skeleton()
        svc.stop_hydration()  # should not raise
