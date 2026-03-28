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

    # --- Poison-task detection tests ---

    def test_title_bundling_three_plus_items(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Examples + Size Audit + Verification",
                description="do stuff",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            bundling = [i for i in result.issues if i.category == "title_bundling"]
            assert len(bundling) == 1
            assert bundling[0].severity == "warning"
            assert "3 items" in bundling[0].message

    def test_title_bundling_with_commas(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Linting, Formatting, Testing, Deploy",
                description="all the things",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            bundling = [i for i in result.issues if i.category == "title_bundling"]
            assert len(bundling) == 1
            assert "4 items" in bundling[0].message

    def test_title_bundling_with_and(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Build and Test and Deploy",
                description="pipeline",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            bundling = [i for i in result.issues if i.category == "title_bundling"]
            assert len(bundling) == 1

    def test_title_bundling_not_triggered_for_two_items(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Build and Test",
                description="two things is fine",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            bundling = [i for i in result.issues if i.category == "title_bundling"]
            assert len(bundling) == 0

    def test_scope_too_broad_over_10_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            files = [f"file_{i}.py" for i in range(12)]
            for f in files:
                Path(td, f).write_text("x = 1", encoding="utf-8")
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1", title="big task", description="touch everything",
                target_files=files,
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            scope_issues = [i for i in result.issues if i.category == "scope_too_broad"]
            assert len(scope_issues) == 1
            assert scope_issues[0].severity == "warning"
            assert "12 files" in scope_issues[0].message

    def test_scope_not_triggered_for_10_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            files = [f"file_{i}.py" for i in range(10)]
            for f in files:
                Path(td, f).write_text("x = 1", encoding="utf-8")
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1", title="ok task", description="just enough",
                target_files=files,
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            scope_issues = [i for i in result.issues if i.category == "scope_too_broad"]
            assert len(scope_issues) == 0

    def test_category_mixing_four_categories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Full pipeline task",
                description="Implement the feature, test it, review the code, and write a guide",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            mixing = [i for i in result.issues if i.category == "category_mixing"]
            assert len(mixing) == 1
            assert mixing[0].severity == "warning"
            assert "poison task" in mixing[0].message.lower()

    def test_category_mixing_not_triggered_for_three(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Build and test",
                description="Implement feature and validate it works, then review",
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            mixing = [i for i in result.issues if i.category == "category_mixing"]
            assert len(mixing) == 0

    def test_category_mixing_all_six_categories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            validator = DecomposeValidator(root_dir=td)
            tasks = [TaskSpec(
                task_id="t1",
                title="Everything task",
                description=(
                    "Create the feature, test and validate it, audit the code, "
                    "deploy to prod, document in the guide, and build a demo"
                ),
                task_kind="implement",
            )]
            result = validator.validate(tasks)
            mixing = [i for i in result.issues if i.category == "category_mixing"]
            assert len(mixing) == 1
            assert "6 responsibility categories" in mixing[0].message
