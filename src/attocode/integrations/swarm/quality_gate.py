"""Swarm quality gate -- pre-flight checks, LLM judge, artifact verification."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    SwarmConfig,
    SwarmTask,
    SwarmTaskResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Local Dataclasses
# =============================================================================


@dataclass
class QualityGateConfig:
    """Configuration for the quality gate LLM judge."""

    model: str | None = None
    persona: str | None = None


@dataclass
class QualityGateResult:
    """Result from quality-gate evaluation."""

    score: int  # 1-5
    feedback: str
    passed: bool
    artifact_auto_fail: bool = False
    pre_flight_reject: bool = False
    gate_error: bool = False
    gate_error_message: str = ""


@dataclass
class ConcreteCheckResult:
    """Result from concrete filesystem checks."""

    passed: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class ArtifactReport:
    """Report on task artifact existence and content."""

    all_empty: bool
    summary: str
    files: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# LLM Provider Protocol
# =============================================================================


class _LLMProvider(Protocol):
    """Minimal LLM provider interface for the quality gate."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 800,
        temperature: float = 0.1,
    ) -> dict[str, Any]: ...


# =============================================================================
# Artifact Checking
# =============================================================================


def check_artifacts(task: SwarmTask) -> ArtifactReport:
    """Check whether a task's ``target_files`` exist on disk.

    Returns an :class:`ArtifactReport` summarising what was found.
    """
    if not task.target_files:
        return ArtifactReport(
            all_empty=False,
            summary="No target files specified",
        )

    file_entries: list[dict[str, Any]] = []
    existing_count = 0
    total_bytes = 0

    for fpath in task.target_files:
        entry: dict[str, Any] = {"path": fpath, "exists": False, "size": 0}
        if os.path.isfile(fpath):
            entry["exists"] = True
            try:
                size = os.path.getsize(fpath)
                entry["size"] = size
                total_bytes += size
                existing_count += 1
            except OSError:
                pass
        file_entries.append(entry)

    all_empty = existing_count == 0 or total_bytes == 0
    summary_parts: list[str] = [
        f"{existing_count}/{len(task.target_files)} target files exist",
    ]
    if total_bytes > 0:
        summary_parts.append(f"total {total_bytes} bytes")
    if all_empty:
        summary_parts.append("ALL EMPTY OR MISSING")

    return ArtifactReport(
        all_empty=all_empty,
        summary=", ".join(summary_parts),
        files=file_entries,
    )


def check_artifacts_enhanced(
    task: SwarmTask,
    task_result: SwarmTaskResult | None = None,
    base_dir: str | None = None,
) -> ArtifactReport:
    """Extended artifact check using target_files, files_modified, and output.

    Searches for files mentioned in:
    1. ``task.target_files``
    2. ``task_result.files_modified``
    3. File paths extracted from the task output via regex
    """
    all_paths: set[str] = set()

    # Source 1: target_files
    if task.target_files:
        all_paths.update(task.target_files)

    # Source 2: files_modified from result
    if task_result and task_result.files_modified:
        all_paths.update(task_result.files_modified)

    # Source 3: extract file paths from output text
    if task_result and task_result.output:
        # Match paths like ./foo/bar.ts, src/thing.py, /abs/path.js
        path_pattern = re.compile(
            r"""(?:^|\s)"""
            r"""((?:\.{0,2}/)?"""
            r"""(?:[\w._-]+/)*"""
            r"""[\w._-]+"""
            r"""\.(?:ts|tsx|js|jsx|py|json|yaml|yml|toml|md|css|scss|html|sql|go|rs|java|c|cpp|h|hpp))"""
            r"""(?:\s|$|[,;:)\]}>])""",
            re.MULTILINE,
        )
        for match in path_pattern.finditer(task_result.output):
            all_paths.add(match.group(1))

    if not all_paths:
        return ArtifactReport(
            all_empty=False,
            summary="No artifact files identified",
        )

    cwd = base_dir or os.getcwd()
    file_entries: list[dict[str, Any]] = []
    existing_count = 0
    total_bytes = 0

    for fpath in sorted(all_paths):
        abs_path = fpath if os.path.isabs(fpath) else os.path.join(cwd, fpath)
        entry: dict[str, Any] = {"path": fpath, "exists": False, "size": 0}
        if os.path.isfile(abs_path):
            entry["exists"] = True
            try:
                size = os.path.getsize(abs_path)
                entry["size"] = size
                total_bytes += size
                existing_count += 1
            except OSError:
                pass
        file_entries.append(entry)

    all_empty = existing_count == 0 or total_bytes == 0
    summary_parts: list[str] = [
        f"{existing_count}/{len(all_paths)} artifact files exist",
    ]
    if total_bytes > 0:
        summary_parts.append(f"total {total_bytes} bytes")
    if all_empty:
        summary_parts.append("ALL EMPTY OR MISSING")

    return ArtifactReport(
        all_empty=all_empty,
        summary=", ".join(summary_parts),
        files=file_entries,
    )


# =============================================================================
# Pre-flight Checks (synchronous, no LLM)
# =============================================================================

# Regex patterns for budget-excuse language in closure reports
_BUDGET_EXCUSE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bran out of (?:budget|tokens|context)\b", re.IGNORECASE),
    re.compile(r"\bbudget (?:limit|exceeded|exhausted)\b", re.IGNORECASE),
    re.compile(r"\binsufficient (?:budget|tokens)\b", re.IGNORECASE),
    re.compile(r"\btoken (?:limit|budget) (?:reached|hit|exceeded)\b", re.IGNORECASE),
    re.compile(r"\bcould not complete.*(?:budget|token|resource)\b", re.IGNORECASE),
    re.compile(r"\bcontext (?:window|length) (?:exceeded|limit)\b", re.IGNORECASE),
]

# Patterns indicating the task description implies file creation
_FILE_CREATION_INDICATORS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:create|write|generate|add|implement)\b.*\b(?:file|module|component|class|function)\b", re.IGNORECASE),
    re.compile(r"\b(?:file|module|component|class)\b.*\b(?:create|write|generate|add|implement)\b", re.IGNORECASE),
    re.compile(r"\bset up\b", re.IGNORECASE),
    re.compile(r"\bscaffold\b", re.IGNORECASE),
    re.compile(r"\binitiali[sz]e\b", re.IGNORECASE),
]


def run_pre_flight_checks(
    task: SwarmTask,
    result: SwarmTaskResult,
    swarm_config: SwarmConfig | None = None,
    cached_artifacts: ArtifactReport | None = None,
) -> QualityGateResult | None:
    """Run synchronous pre-flight quality checks (no LLM required).

    Returns a failing :class:`QualityGateResult` if any check fails, or
    ``None`` if all checks pass and LLM evaluation should proceed.
    """
    # V4: All target files empty/missing
    artifact_report = cached_artifacts or check_artifacts(task)
    if task.target_files and artifact_report.all_empty:
        return QualityGateResult(
            score=1,
            feedback=(
                f"All target files are empty or missing. "
                f"Artifact report: {artifact_report.summary}"
            ),
            passed=False,
            artifact_auto_fail=True,
        )

    # V7: Task type requires tool calls but got zero
    task_type_str = task.type.value if hasattr(task.type, "value") else str(task.type)
    type_config = BUILTIN_TASK_TYPE_CONFIGS.get(task_type_str)
    if type_config and type_config.requires_tool_calls:
        if result.tool_calls is not None and result.tool_calls == 0:
            return QualityGateResult(
                score=0,
                feedback=(
                    f"Task type '{task_type_str}' requires tool calls but "
                    f"none were made. This indicates no real work was performed."
                ),
                passed=False,
                pre_flight_reject=True,
            )

    # V10: No files modified + no tool calls + description implies file creation
    if (
        (not result.files_modified or len(result.files_modified) == 0)
        and (result.tool_calls is not None and result.tool_calls == 0)
    ):
        implies_creation = any(
            p.search(task.description) for p in _FILE_CREATION_INDICATORS
        )
        if implies_creation:
            return QualityGateResult(
                score=1,
                feedback=(
                    "Task description implies file creation but no files were "
                    "modified and no tool calls were made."
                ),
                passed=False,
                artifact_auto_fail=True,
            )

    # V6: Closure report findings are all budget excuses
    if result.closure_report and result.closure_report.get("findings"):
        findings: list[Any] = result.closure_report["findings"]
        if findings and all(_is_budget_excuse(str(f)) for f in findings):
            return QualityGateResult(
                score=1,
                feedback=(
                    "All closure report findings are budget/resource excuses "
                    "with no concrete work artifacts."
                ),
                passed=False,
                pre_flight_reject=True,
            )

    return None


def _is_budget_excuse(text: str) -> bool:
    """Check whether a finding string is a budget/resource excuse."""
    return any(p.search(text) for p in _BUDGET_EXCUSE_PATTERNS)


# =============================================================================
# Concrete Filesystem Checks
# =============================================================================


def run_ast_checks(
    task: SwarmTask,
    result: SwarmTaskResult,
    ast_service: Any = None,
) -> list[str]:
    """Run AST-based quality checks on a completed task.

    Checks that:
    - Modified files parse successfully (via AST service re-index)
    - Expected symbols still exist after modification
    - No unintended signature changes

    Returns a list of issue strings (empty = all good).
    """
    if ast_service is None:
        return []

    issues: list[str] = []
    modified = result.files_modified or []
    if not modified:
        return []

    try:
        for fpath in modified:
            if not os.path.isfile(fpath):
                continue

            # Check if file parses correctly
            if hasattr(ast_service, "parse_file"):
                try:
                    ast_service.parse_file(fpath)
                except Exception as exc:
                    issues.append(f"AST parse error in {fpath}: {exc}")

            # Check that symbols still exist after modification
            if hasattr(ast_service, "get_file_symbols"):
                try:
                    symbols = ast_service.get_file_symbols(fpath)
                    if not symbols and os.path.getsize(fpath) > 100:
                        issues.append(
                            f"No symbols found in {fpath} after modification "
                            f"(file has {os.path.getsize(fpath)} bytes)"
                        )
                except Exception:
                    pass
    except Exception:
        pass

    return issues


def run_concrete_checks(
    task: SwarmTask,
    result: SwarmTaskResult,
) -> ConcreteCheckResult:
    """Run synchronous filesystem validation for code tasks.

    Checks that:
    - Modified files exist and are non-empty.
    - JSON files parse cleanly.
    - Code files (.ts/.tsx/.js/.jsx/.py) have roughly balanced braces.
    """
    issues: list[str] = []

    if not result.files_modified:
        return ConcreteCheckResult(passed=True, issues=[])

    for fpath in result.files_modified:
        if not os.path.isfile(fpath):
            issues.append(f"File does not exist: {fpath}")
            continue

        try:
            size = os.path.getsize(fpath)
        except OSError:
            issues.append(f"Cannot stat file: {fpath}")
            continue

        if size == 0:
            issues.append(f"File is empty: {fpath}")
            continue

        # JSON validation
        if fpath.endswith(".json"):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                issues.append(f"JSON parse error in {fpath}: {exc}")
                continue

        # Brace balance for code files
        code_extensions = (".ts", ".tsx", ".js", ".jsx", ".py")
        if any(fpath.endswith(ext) for ext in code_extensions):
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                open_braces = content.count("{")
                close_braces = content.count("}")
                imbalance = abs(open_braces - close_braces)
                if imbalance > 3:
                    issues.append(
                        f"Brace imbalance in {fpath}: "
                        f"{open_braces} open vs {close_braces} close "
                        f"(diff={imbalance})"
                    )
            except OSError as exc:
                issues.append(f"Cannot read {fpath}: {exc}")

    return ConcreteCheckResult(
        passed=len(issues) == 0,
        issues=issues,
    )


# =============================================================================
# LLM Judge Evaluation
# =============================================================================


async def evaluate_worker_output(
    provider: Any,
    orchestrator_model: str,
    task: SwarmTask,
    result: SwarmTaskResult,
    judge_config: QualityGateConfig | None = None,
    quality_threshold: int = 3,
    on_usage: Callable[[dict[str, Any]], None] | None = None,
    file_artifacts: ArtifactReport | None = None,
    swarm_config: SwarmConfig | None = None,
    cached_artifact_report: ArtifactReport | None = None,
    emit: Callable[..., None] | None = None,
) -> QualityGateResult:
    """Evaluate a worker's output using pre-flight checks and an LLM judge.

    Flow:
    1. Compute artifact report.
    2. Run synchronous pre-flight checks -- return early on failure.
    3. Build judge prompt with scoring rubric (1-5).
    4. Call ``provider.chat()`` with ``max_tokens=800, temperature=0.1``.
    5. Parse response for ``SCORE: N`` and ``FEEDBACK: text``.
    6. On LLM error: return score=3, gate_error=True.
    """
    # Step 1: Compute artifact report
    artifact_report = cached_artifact_report or file_artifacts
    if artifact_report is None:
        artifact_report = check_artifacts_enhanced(task, result)

    # Step 2: Pre-flight checks
    pre_flight = run_pre_flight_checks(
        task, result, swarm_config=swarm_config, cached_artifacts=artifact_report
    )
    if pre_flight is not None:
        # Emit quality result for pre-flight failure too
        if emit is not None:
            try:
                from attocode.integrations.swarm.types import swarm_event
                emit(swarm_event(
                    "swarm.quality.result",
                    task_id=task.id,
                    score=pre_flight.score,
                    feedback=pre_flight.feedback,
                    passed=pre_flight.passed,
                    artifact_auto_fail=pre_flight.artifact_auto_fail,
                ))
            except Exception:
                pass
        return pre_flight

    # Step 3: Build judge prompt
    judge_prompt = _build_quality_prompt(task, result, artifact_report)

    # Determine model
    model = orchestrator_model
    if judge_config and judge_config.model:
        model = judge_config.model

    # Step 4: Call LLM
    try:
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": judge_prompt},
        ]

        response = await provider.chat(
            messages,
            model=model,
            max_tokens=800,
            temperature=0.1,
        )

        # Extract content from response
        content = ""
        if isinstance(response, dict):
            content = response.get("content", "")
            if not content:
                # Try nested message format
                msg = response.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", "")
            # Report usage if callback provided
            usage = response.get("usage")
            if usage and on_usage:
                on_usage(usage)
        elif isinstance(response, str):
            content = response

        if not content:
            return QualityGateResult(
                score=3,
                feedback="Quality gate received empty response from judge LLM.",
                passed=quality_threshold <= 3,
                gate_error=True,
                gate_error_message="Empty response from LLM judge",
            )

        # Step 5: Parse response
        score, feedback = _parse_quality_response(content)
        passed = score >= quality_threshold

        gate_result = QualityGateResult(
            score=score,
            feedback=feedback,
            passed=passed,
        )

        # Emit quality result event
        if emit is not None:
            try:
                from attocode.integrations.swarm.types import swarm_event
                emit(swarm_event(
                    "swarm.quality.result",
                    task_id=task.id,
                    score=score,
                    feedback=feedback,
                    passed=passed,
                    artifact_auto_fail=False,
                ))
            except Exception:
                pass

        return gate_result

    except Exception as exc:
        # Step 6: On LLM error, return safe default
        logger.warning("Quality gate LLM error: %s", exc)
        return QualityGateResult(
            score=3,
            feedback=f"Quality gate encountered an error: {exc}",
            passed=quality_threshold <= 3,
            gate_error=True,
            gate_error_message=str(exc),
        )


# =============================================================================
# Private: Judge Prompt Building
# =============================================================================

_JUDGE_SYSTEM_PROMPT = """\
You are a strict quality-gate judge for a multi-agent AI coding system. \
Your job is to evaluate whether a worker agent's output meets the task \
requirements. Be concise and specific. Focus on concrete evidence of \
work completed (files created/modified, tests passing, etc.) rather \
than narrative quality."""


def _build_quality_prompt(
    task: SwarmTask,
    result: SwarmTaskResult,
    artifact_report: ArtifactReport,
) -> str:
    """Build the LLM judge prompt with scoring rubric."""
    task_type_str = task.type.value if hasattr(task.type, "value") else str(task.type)

    sections: list[str] = [
        "## Task Under Review",
        f"**ID:** {task.id}",
        f"**Type:** {task_type_str}",
        f"**Complexity:** {task.complexity}/10",
        f"**Description:** {task.description}",
    ]

    if task.target_files:
        sections.append(f"**Target Files:** {', '.join(task.target_files)}")

    sections.append("")
    sections.append("## Worker Output")

    # Truncate very long output for the judge
    output = result.output
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"
    sections.append(output)

    sections.append("")
    sections.append("## Execution Metrics")
    sections.append(f"- Tool calls: {result.tool_calls}")
    sections.append(f"- Files modified: {result.files_modified or 'none'}")
    sections.append(f"- Tokens used: {result.tokens_used}")
    sections.append(f"- Duration: {result.duration_ms}ms")
    if result.model:
        sections.append(f"- Model: {result.model}")

    sections.append("")
    sections.append("## Artifact Report")
    sections.append(artifact_report.summary)
    if artifact_report.files:
        for af in artifact_report.files[:10]:
            status = "EXISTS" if af.get("exists") else "MISSING"
            size = af.get("size", 0)
            sections.append(f"  - {af['path']}: {status} ({size} bytes)")

    sections.append("")
    sections.append("## Scoring Rubric")
    sections.append(
        "Rate the output on a scale of 1-5:\n"
        "  1 = No meaningful work done (hollow, boilerplate only, all failures)\n"
        "  2 = Partial attempt, major issues (wrong approach, missing key files)\n"
        "  3 = Acceptable but incomplete (core work done, some gaps)\n"
        "  4 = Good quality (task fulfilled, minor issues at most)\n"
        "  5 = Excellent (thorough, well-structured, all requirements met)\n"
    )

    sections.append(
        "Respond with exactly two lines:\n"
        "SCORE: <number 1-5>\n"
        "FEEDBACK: <one sentence explaining the score>"
    )

    return "\n".join(sections)


# =============================================================================
# Private: Response Parsing
# =============================================================================

_SCORE_PATTERN = re.compile(r"SCORE:\s*(\d)", re.IGNORECASE)
_FEEDBACK_PATTERN = re.compile(r"FEEDBACK:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _parse_quality_response(content: str) -> tuple[int, str]:
    """Extract SCORE and FEEDBACK from the judge LLM response.

    Returns ``(score, feedback)``.  Falls back to score=3 and the raw
    content as feedback if parsing fails.
    """
    score = 3  # safe default
    feedback = content.strip()

    score_match = _SCORE_PATTERN.search(content)
    if score_match:
        parsed = int(score_match.group(1))
        if 1 <= parsed <= 5:
            score = parsed

    feedback_match = _FEEDBACK_PATTERN.search(content)
    if feedback_match:
        feedback = feedback_match.group(1).strip()
        # Trim trailing whitespace and newlines from feedback
        feedback = feedback.split("\n")[0].strip()

    return score, feedback
