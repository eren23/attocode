"""Tests for DecomposeValidator."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from attoswarm.coordinator.decompose_validator import DecomposeValidator
from attoswarm.protocol.models import TaskSpec


class TestDecomposeValidator:
    def test_read_file_missing_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1", title="test", description="test",
                read_files=["nonexistent.py"],
            )]
            result = validator.validate(tasks)
            assert result.has_errors
            assert any(i.category == "file_existence" for i in result.issues)

    def test_target_file_missing_is_warning_for_modify(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1", title="test", description="test",
                target_files=["nonexistent.py"],
                task_kind="test",
            )]
            result = validator.validate(tasks)
            assert result.has_warnings
            assert not result.has_errors

    def test_target_file_missing_is_info_for_implement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1", title="test", description="test",
                target_files=["new_file.py"],
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            assert not result.has_errors
            assert not result.has_warnings

    def test_dependency_coherence_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create a file
            Path(td, "shared.py").write_text("x = 1", encoding="utf-8")
            validator = DecomposeValidator(root_dir=td)
            tasks = [
                TaskSpec(task_id="writer", title="w", description="w",
                         target_files=["shared.py"]),
                TaskSpec(task_id="reader", title="r", description="r",
                         read_files=["shared.py"]),  # no dep on writer!
            ]
            result = validator.validate(tasks)
            assert any(i.category == "dependency" for i in result.issues)

    def test_overlap_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "shared.py").write_text("x = 1", encoding="utf-8")
            validator = DecomposeValidator(root_dir=td)
            tasks = [
                TaskSpec(task_id="a", title="a", description="a",
                         target_files=["shared.py"]),
                TaskSpec(task_id="b", title="b", description="b",
                         target_files=["shared.py"]),
            ]
            result = validator.validate(tasks)
            assert any(i.category == "overlap" for i in result.issues)

    def test_valid_decomposition_scores_high(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.py").write_text("a = 1", encoding="utf-8")
            Path(td, "b.py").write_text("b = 2", encoding="utf-8")
            validator = DecomposeValidator(root_dir=td)
            tasks = [
                TaskSpec(task_id="t1", title="t1", description="d1",
                         target_files=["a.py"]),
                TaskSpec(task_id="t2", title="t2", description="d2",
                         target_files=["b.py"], deps=["t1"]),
            ]
            result = validator.validate(tasks)
            assert result.score > 0.8
