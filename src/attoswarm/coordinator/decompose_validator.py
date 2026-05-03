"""Multi-signal decomposition validator.

Validates the task graph before execution begins, checking:
1. File existence (do target_files exist or is task creating them?)
2. Symbol resolvability (do symbol_scope entries exist in AST?)
3. Dependency coherence (if A targets file X and B reads X, is there A→B edge?)
4. Overlap detection (two tasks targeting same function without dep edge)
5. Orphan detection (tasks disconnected from DAG)
6. Granularity check (complexity estimation from file sizes/symbol counts)
7. Title bundling (detect "poison tasks" with 3+ bundled items in title)
8. Scope breadth (>10 target files = scope_too_broad)
9. Category mixing (title/description spans 4+ responsibility categories)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:

    from attoswarm.protocol.models import TaskSpec

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ValidationIssue:
    """A single validation issue found in the decomposition."""

    severity: str  # "error" | "warning" | "info"
    category: str  # "file_existence" | "symbol" | "dependency" | "overlap" | "orphan" | "granularity" | "title_bundling" | "scope_too_broad" | "category_mixing"
    task_id: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "task_id": self.task_id,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass(slots=True)
class ValidationResult:
    """Result of decomposition validation."""

    issues: list[ValidationIssue] = field(default_factory=list)
    score: float = 1.0  # 0.0 (terrible) to 1.0 (perfect)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [i.to_dict() for i in self.issues],
        }


class DecomposeValidator:
    """Validates a decomposed task graph before execution.

    Usage::

        validator = DecomposeValidator(
            root_dir="/path/to/repo",
            ast_service=ast_service,
        )
        result = validator.validate(tasks)
        if result.has_errors:
            request_redecomposition(result.issues)
    """

    def __init__(
        self,
        root_dir: str,
        ast_service: Any | None = None,
    ) -> None:
        self._root_dir = root_dir
        self._ast_service = ast_service

    def validate(self, tasks: list[TaskSpec]) -> ValidationResult:
        """Run all validation checks on the task list."""
        result = ValidationResult()

        self._check_file_existence(tasks, result)
        self._check_symbol_resolvability(tasks, result)
        self._check_dependency_coherence(tasks, result)
        self._check_overlap(tasks, result)
        self._check_orphans(tasks, result)
        self._check_granularity(tasks, result)
        self._check_title_bundling(tasks, result)
        self._check_scope_breadth(tasks, result)
        self._check_category_mixing(tasks, result)

        # Compute score from issues
        error_penalty = result.error_count * 0.15
        warning_penalty = result.warning_count * 0.05
        result.score = max(0.0, 1.0 - error_penalty - warning_penalty)

        return result

    def _check_file_existence(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check that target_files exist (unless task kind is 'implement' for new files)."""
        for task in tasks:
            for f in task.target_files:
                abs_path = os.path.join(self._root_dir, f)
                if not os.path.exists(abs_path):
                    if task.task_kind in ("implement", "design"):
                        result.issues.append(ValidationIssue(
                            severity="info",
                            category="file_existence",
                            task_id=task.task_id,
                            message=f"Target file '{f}' does not exist (will be created)",
                        ))
                    else:
                        result.issues.append(ValidationIssue(
                            severity="warning",
                            category="file_existence",
                            task_id=task.task_id,
                            message=f"Target file '{f}' does not exist",
                            suggestion="Verify the file path or change task_kind to 'implement'",
                        ))

            # Read files must exist
            for f in task.read_files:
                abs_path = os.path.join(self._root_dir, f)
                if not os.path.exists(abs_path):
                    result.issues.append(ValidationIssue(
                        severity="error",
                        category="file_existence",
                        task_id=task.task_id,
                        message=f"Read file '{f}' does not exist",
                        suggestion="Remove from read_files or fix the path",
                    ))

    def _check_symbol_resolvability(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check that symbol_scope entries are resolvable in the AST index."""
        if not self._ast_service:
            return

        for task in tasks:
            for symbol in task.symbol_scope:
                try:
                    found = self._ast_service.find_symbol(symbol)
                    if not found:
                        result.issues.append(ValidationIssue(
                            severity="warning",
                            category="symbol",
                            task_id=task.task_id,
                            message=f"Symbol '{symbol}' not found in AST index",
                            suggestion="Verify symbol name or it may be created by this task",
                        ))
                except Exception:
                    pass  # AST service may not support find_symbol

    def _check_dependency_coherence(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check that file read/write relationships have corresponding dep edges."""
        # Build file -> writer mapping
        file_writers: dict[str, str] = {}
        for task in tasks:
            for f in task.target_files:
                file_writers[f] = task.task_id

        # Check readers have deps on writers
        for task in tasks:
            for f in task.read_files:
                writer = file_writers.get(f)
                if writer and writer != task.task_id and writer not in task.deps:
                    result.issues.append(ValidationIssue(
                        severity="warning",
                        category="dependency",
                        task_id=task.task_id,
                        message=f"Reads file '{f}' written by task '{writer}' but no dependency edge",
                        suggestion=f"Add '{writer}' to deps of '{task.task_id}'",
                    ))

    def _check_overlap(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check for two tasks targeting the same file without a dep edge."""
        file_tasks: dict[str, list[str]] = {}
        for task in tasks:
            for f in task.target_files:
                file_tasks.setdefault(f, []).append(task.task_id)

        task_deps: dict[str, set[str]] = {t.task_id: set(t.deps) for t in tasks}

        for f, task_ids in file_tasks.items():
            if len(task_ids) < 2:
                continue
            for i in range(len(task_ids)):
                for j in range(i + 1, len(task_ids)):
                    a, b = task_ids[i], task_ids[j]
                    # Check if there's a dep edge in either direction
                    if b not in task_deps.get(a, set()) and a not in task_deps.get(b, set()):
                        result.issues.append(ValidationIssue(
                            severity="warning",
                            category="overlap",
                            task_id=a,
                            message=f"Tasks '{a}' and '{b}' both target '{f}' without dep edge",
                            suggestion="Add a dependency or split file responsibilities",
                        ))

    def _check_orphans(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check for tasks disconnected from the DAG."""
        # Tasks that are depended upon
        has_dependents = set()
        for task in tasks:
            for dep in task.deps:
                has_dependents.add(dep)

        for task in tasks:
            if not task.deps and task.task_id not in has_dependents and len(tasks) > 1:
                result.issues.append(ValidationIssue(
                    severity="info",
                    category="orphan",
                    task_id=task.task_id,
                    message=f"Task '{task.task_id}' is disconnected (no deps and no dependents)",
                    suggestion="Consider adding dependencies or this may be intentionally independent",
                ))

    def _check_granularity(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Check task granularity using file sizes and target counts."""
        for task in tasks:
            # Too many target files
            if len(task.target_files) > 10:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    category="granularity",
                    task_id=task.task_id,
                    message=f"Task targets {len(task.target_files)} files (may be too broad)",
                    suggestion="Consider splitting into smaller tasks",
                ))

            # Estimate complexity from file sizes
            total_lines = 0
            for f in task.target_files:
                abs_path = os.path.join(self._root_dir, f)
                try:
                    if os.path.exists(abs_path):
                        total_lines += sum(1 for _ in open(abs_path, encoding="utf-8", errors="ignore"))
                except Exception:
                    pass

            if total_lines > 3000:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    category="granularity",
                    task_id=task.task_id,
                    message=f"Target files total ~{total_lines} lines (may be too complex for one task)",
                    suggestion="Consider splitting by function or subsystem",
                ))

    # --- Poison-task detection rules ---

    # Pattern that splits on "+", "&", commas, or " and " to detect bundled items
    _BUNDLING_SPLIT_RE = re.compile(r"\s*(?:\+|&|,|\band\b)\s*", re.IGNORECASE)

    # Category keyword groups for mixing detection
    _CATEGORY_KEYWORDS: dict[str, set[str]] = {
        "implement": {"implement", "build", "create"},
        "test": {"test", "verify", "validate"},
        "audit": {"audit", "review", "analyze"},
        "deploy": {"deploy", "release", "ship"},
        "document": {"document", "readme", "guide"},
        "example": {"example", "demo", "sample"},
    }

    def _check_title_bundling(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Flag tasks whose titles bundle 3+ separate responsibilities.

        Detects titles like "Examples + Size Audit + Verification" by splitting
        on ``+``, ``&``, commas, and the word "and".
        """
        for task in tasks:
            parts = self._BUNDLING_SPLIT_RE.split(task.title)
            # Filter out empty strings that can result from leading/trailing separators
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 3:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    category="title_bundling",
                    task_id=task.task_id,
                    message=(
                        f"Title bundles {len(parts)} items: {parts!r}. "
                        f"This is a 'poison task' — too many responsibilities in one task"
                    ),
                    suggestion="Split into separate single-responsibility tasks",
                ))

    def _check_scope_breadth(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Flag tasks with >10 target files as scope_too_broad."""
        for task in tasks:
            n = len(task.target_files)
            if n > 10:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    category="scope_too_broad",
                    task_id=task.task_id,
                    message=f"Task targets {n} files — scope is too broad for reliable execution",
                    suggestion="Decompose into focused sub-tasks touching fewer files each",
                ))

    def _check_category_mixing(
        self,
        tasks: list[TaskSpec],
        result: ValidationResult,
    ) -> None:
        """Flag tasks whose title/description spans 4+ distinct responsibility categories.

        Categories: implement/build/create, test/verify/validate, audit/review/analyze,
        deploy/release/ship, document/readme/guide, example/demo/sample.
        """
        for task in tasks:
            text = f"{task.title} {task.description}".lower()
            # Tokenize on word boundaries for accurate matching
            words = set(re.findall(r"[a-z]+", text))
            matched_categories: list[str] = []
            for cat_name, keywords in self._CATEGORY_KEYWORDS.items():
                if words & keywords:
                    matched_categories.append(cat_name)
            if len(matched_categories) >= 4:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    category="category_mixing",
                    task_id=task.task_id,
                    message=(
                        f"Task mixes {len(matched_categories)} responsibility categories "
                        f"({', '.join(sorted(matched_categories))}). "
                        f"This is a 'poison task' — too many concerns in one task"
                    ),
                    suggestion="Split into tasks with a single category of responsibility each",
                ))

