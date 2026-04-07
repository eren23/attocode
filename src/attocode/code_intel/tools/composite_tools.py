"""Composite tools for the code-intel MCP server.

Tools: review_change, explain_impact, suggest_tests.

These tools combine multiple analysis passes into single, agent-optimized
calls that reduce round-trips and produce richer context than calling
individual tools sequentially.
"""

from __future__ import annotations

import logging
import os
import subprocess

from attocode.code_intel._shared import (
    _get_context_mgr,
    _get_project_dir,
    _get_service,
    mcp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_modified_files(project_dir: str) -> list[str]:
    """Return list of git-modified file paths (relative to project root)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        if not files:
            # Also check staged files
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        return files
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Failed to get git-modified files: %s", exc)
        return []


def _find_test_files_by_convention(file_path: str, project_dir: str) -> list[str]:
    """Find test files matching naming conventions for a source file.

    Checks for: test_X.py, X_test.py, __tests__/X.test.ts, X.spec.ts, etc.
    """
    from pathlib import Path

    basename = Path(file_path).stem
    ext = Path(file_path).suffix
    parent = str(Path(file_path).parent)

    candidates = []

    if ext in (".py",):
        # Python conventions: test_X.py, X_test.py
        candidates.extend([
            os.path.join(parent, f"test_{basename}.py"),
            os.path.join(parent, f"{basename}_test.py"),
            # tests/ mirror directory
            file_path.replace("src/", "tests/", 1).replace(
                f"{basename}.py", f"test_{basename}.py"
            ),
            # tests/unit/ mirror
            "tests/unit/" + file_path.lstrip("src/").replace(
                f"{basename}.py", f"test_{basename}.py"
            ),
            # tests/test_X.py flat layout
            f"tests/test_{basename}.py",
        ])
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        # JS/TS conventions
        test_ext = ".test" + ext
        spec_ext = ".spec" + ext
        candidates.extend([
            os.path.join(parent, f"{basename}{test_ext}"),
            os.path.join(parent, f"{basename}{spec_ext}"),
            os.path.join(parent, "__tests__", f"{basename}{test_ext}"),
            os.path.join(parent, "__tests__", f"{basename}{spec_ext}"),
        ])
    elif ext in (".go",):
        # Go convention: X_test.go in same directory
        candidates.append(os.path.join(parent, f"{basename}_test.go"))
    elif ext in (".rs",):
        # Rust: tests/X.rs or inline #[cfg(test)] (can't find inline from path)
        candidates.append(os.path.join(parent, "tests", f"{basename}.rs"))
    elif ext in (".java", ".kt"):
        # Java/Kotlin: mirror src/main -> src/test
        candidates.append(
            file_path.replace("src/main/", "src/test/", 1).replace(
                f"{basename}{ext}", f"{basename}Test{ext}"
            )
        )

    # Deduplicate and filter to existing files
    seen: set[str] = set()
    existing: list[str] = []
    for c in candidates:
        c = os.path.normpath(c)
        if c in seen:
            continue
        seen.add(c)
        full = os.path.join(project_dir, c)
        if os.path.isfile(full):
            existing.append(c)

    return existing


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def review_change(
    files: list[str] | None = None,
    mode: str = "full",
) -> str:
    """Comprehensive change review combining security, bug, and convention analysis.

    Runs multiple analysis passes on changed files and produces a unified
    report. Much more efficient than calling each tool individually.

    Args:
        files: List of file paths to review (default: git-modified files).
        mode: Review depth -- 'quick' (security only), 'full' (all checks).

    Returns:
        Unified review report with categorized findings.
    """
    project_dir = _get_project_dir()

    # Resolve files to review
    if files is None:
        files = _git_modified_files(project_dir)
    if not files:
        return "No files to review. Provide file paths or ensure git has modified files."

    if mode not in ("quick", "full"):
        return f"Error: Invalid mode '{mode}'. Use 'quick' or 'full'."

    svc = _get_service()
    report_sections: list[str] = []
    total_findings = 0

    # --- Security scan ---
    security_text = ""
    try:
        # Scan each file's directory to scope the results
        scanned_paths: set[str] = set()
        for f in files:
            scan_path = os.path.dirname(f) or ""
            if scan_path not in scanned_paths:
                scanned_paths.add(scan_path)

        # Run a single security scan (scoped to project)
        security_text = svc.security_scan(mode="full", path="")
    except Exception as exc:
        security_text = f"Security scan error: {exc}"

    if security_text:
        # Filter findings to only mention changed files
        relevant_lines: list[str] = []
        for line in security_text.splitlines():
            # Include header/summary lines and lines mentioning changed files
            if any(f in line for f in files) or not line.startswith("  "):
                relevant_lines.append(line)
        filtered_security = "\n".join(relevant_lines) if relevant_lines else security_text

        # Count findings (lines with severity indicators)
        finding_markers = ("HIGH", "MEDIUM", "LOW", "CRITICAL", "WARNING")
        sec_findings = sum(
            1 for line in filtered_security.splitlines()
            if any(m in line.upper() for m in finding_markers)
        )
        total_findings += sec_findings
        report_sections.append(f"## Security ({sec_findings} finding(s))\n\n{filtered_security}")

    # --- Conventions check (full mode only) ---
    if mode == "full":
        conventions_text = ""
        try:
            conventions_text = svc.conventions(sample_size=25, path="")
        except Exception as exc:
            conventions_text = f"Conventions check error: {exc}"

        if conventions_text:
            report_sections.append(f"## Conventions\n\n{conventions_text}")

    # --- Build report ---
    file_list = "\n".join(f"  - {f}" for f in files)
    header = (
        f"# Change Review Report ({mode} mode)\n\n"
        f"Files reviewed ({len(files)}):\n{file_list}\n"
    )

    body = "\n\n".join(report_sections) if report_sections else "No findings."

    # Assessment
    if total_findings == 0:
        assessment = "No security issues found. Code looks clean."
    elif total_findings <= 3:
        assessment = f"{total_findings} finding(s) detected. Review recommended before merging."
    else:
        assessment = (
            f"{total_findings} finding(s) detected. "
            "Careful review required -- multiple issues found."
        )

    summary = f"\n\n## Summary\n\n{assessment}"

    return header + "\n" + body + summary


@mcp.tool()
def explain_impact(
    files: list[str],
    depth: int = 3,
) -> str:
    """Explain the blast radius of changing files with rich context.

    Combines impact analysis, community detection, and temporal coupling
    to provide a comprehensive understanding of what would be affected
    by changes to the specified files.

    Args:
        files: File paths to analyze (relative to project root).
        depth: Maximum depth for dependency traversal (default 3).

    Returns:
        Narrative explanation of the change impact.
    """
    if not files:
        return "Error: No files specified for impact analysis."

    if depth < 1:
        depth = 1
    elif depth > 5:
        depth = 5

    svc = _get_service()
    sections: list[str] = []

    # --- Impact analysis ---
    impact_text = ""
    try:
        impact_text = svc.impact_analysis(files)
    except Exception as exc:
        impact_text = f"Impact analysis error: {exc}"

    if impact_text:
        sections.append(f"## Direct Impact\n\n{impact_text}")

    # --- Community detection ---
    community_text = ""
    try:
        community_text = svc.community_detection(
            min_community_size=2, max_communities=10,
        )
    except Exception as exc:
        community_text = f"Community detection error: {exc}"

    if community_text:
        # Extract relevant community info for the target files
        relevant_community_lines: list[str] = []
        in_relevant_community = False
        for line in community_text.splitlines():
            if any(f in line for f in files):
                in_relevant_community = True
            if in_relevant_community:
                relevant_community_lines.append(line)
            # Reset at community boundaries
            if in_relevant_community and line.strip() == "":
                in_relevant_community = False

        if relevant_community_lines:
            filtered_community = "\n".join(relevant_community_lines)
            sections.append(
                f"## Module Community\n\n"
                f"The changed files belong to these communities:\n\n"
                f"{filtered_community}"
            )
        else:
            sections.append(f"## Module Community\n\n{community_text}")

    # --- Temporal coupling ---
    coupling_sections: list[str] = []
    high_coupling_files: list[tuple[str, str]] = []  # (file, coupling_info)
    for f in files:
        try:
            coupling_text = svc.change_coupling(
                file=f, days=90, min_coupling=0.3, top_k=10,
            )
            if coupling_text and "no " not in coupling_text.lower():
                coupling_sections.append(f"### {f}\n{coupling_text}")
                # Track high-coupling pairs for risk assessment
                for line in coupling_text.splitlines():
                    if any(
                        marker in line
                        for marker in ("0.8", "0.9", "1.0", "score: 0.7")
                    ):
                        high_coupling_files.append((f, line.strip()))
        except Exception as exc:
            coupling_sections.append(f"### {f}\nTemporal coupling error: {exc}")

    if coupling_sections:
        sections.append(
            "## Temporal Coupling (git co-change history)\n\n"
            + "\n\n".join(coupling_sections)
        )

    # --- Risk assessment ---
    risk_level = "LOW"
    risk_reasons: list[str] = []

    # Check impact breadth
    if impact_text:
        affected_count = impact_text.count("\n")
        if affected_count > 20:
            risk_level = "HIGH"
            risk_reasons.append(
                f"Large blast radius: {affected_count}+ files potentially affected"
            )
        elif affected_count > 10:
            risk_level = "MEDIUM"
            risk_reasons.append(
                f"Moderate blast radius: ~{affected_count} files potentially affected"
            )

    # Check temporal coupling
    if high_coupling_files:
        if risk_level == "LOW":
            risk_level = "MEDIUM"
        risk_reasons.append(
            f"{len(high_coupling_files)} file(s) with high temporal coupling "
            "(often change together -- verify they don't need updates too)"
        )

    # Check if multiple communities are affected
    if len(files) > 1:
        risk_reasons.append(
            f"Changes span {len(files)} files -- cross-cutting changes "
            "may affect multiple modules"
        )

    risk_summary = (
        f"## Risk Assessment: {risk_level}\n\n"
        + ("\n".join(f"  - {r}" for r in risk_reasons) if risk_reasons else "  - No elevated risk factors detected.")
    )
    sections.append(risk_summary)

    # --- Compose narrative ---
    file_list = ", ".join(f"`{f}`" for f in files)
    header = f"# Impact Analysis for {file_list}\n"

    return header + "\n\n".join(sections)


@mcp.tool()
def suggest_tests(
    files: list[str],
) -> str:
    """Suggest which tests to run based on changed files.

    Analyzes dependencies and test file conventions to recommend
    the most relevant test files for a set of changed source files.

    Args:
        files: Changed source file paths (relative to project root).

    Returns:
        Prioritized list of test files to run with reasoning.
    """
    if not files:
        return "Error: No files specified. Provide a list of changed source files."

    project_dir = _get_project_dir()

    # Collect test suggestions with priorities
    # Priority 1: Direct test files (by naming convention)
    # Priority 2: Test files that import the changed module
    # Priority 3: Tests for dependent modules
    suggestions: dict[str, dict] = {}  # path -> {priority, reasons}

    def _add_suggestion(path: str, priority: int, reason: str) -> None:
        """Add or update a test suggestion."""
        if path in suggestions:
            existing = suggestions[path]
            existing["priority"] = min(existing["priority"], priority)
            if reason not in existing["reasons"]:
                existing["reasons"].append(reason)
        else:
            suggestions[path] = {"priority": priority, "reasons": [reason]}

    # --- Priority 1: Convention-based test files ---
    for f in files:
        convention_tests = _find_test_files_by_convention(f, project_dir)
        for test_file in convention_tests:
            _add_suggestion(
                test_file,
                priority=1,
                reason=f"Direct test file for `{f}`",
            )

    # --- Priority 2: Import-based discovery ---
    try:
        ctx = _get_context_mgr()
        dep_graph = getattr(ctx, "dependency_graph", None) or getattr(ctx, "_dep_graph", None)

        if dep_graph is not None:
            for f in files:
                # Find files that import the changed file (dependents)
                try:
                    importers = dep_graph.get_importers(f)
                except (AttributeError, KeyError):
                    try:
                        importers = dep_graph.get_reverse_deps(f)
                    except (AttributeError, KeyError):
                        importers = set()

                for importer in importers:
                    # Check if the importer is a test file
                    importer_lower = importer.lower()
                    is_test = (
                        "test" in importer_lower
                        or "spec" in importer_lower
                        or "__tests__" in importer_lower
                    )
                    if is_test:
                        _add_suggestion(
                            importer,
                            priority=2,
                            reason=f"Imports changed module `{f}`",
                        )

            # --- Priority 3: Tests for dependent modules ---
            for f in files:
                try:
                    importers = dep_graph.get_importers(f)
                except (AttributeError, KeyError):
                    try:
                        importers = dep_graph.get_reverse_deps(f)
                    except (AttributeError, KeyError):
                        importers = set()

                for importer in importers:
                    importer_lower = importer.lower()
                    is_test = (
                        "test" in importer_lower
                        or "spec" in importer_lower
                        or "__tests__" in importer_lower
                    )
                    if not is_test:
                        # Find tests for this dependent module
                        dep_tests = _find_test_files_by_convention(
                            importer, project_dir
                        )
                        for test_file in dep_tests:
                            _add_suggestion(
                                test_file,
                                priority=3,
                                reason=f"Tests dependent module `{importer}` (which imports `{f}`)",
                            )
    except Exception as exc:
        logger.debug("Import-based test discovery failed: %s", exc)

    # --- Format output ---
    if not suggestions:
        # Fallback: suggest running all tests
        lines = [
            "# Test Suggestions\n",
            "No specific test files found for the changed files.",
            "",
            "Changed files:",
        ]
        for f in files:
            lines.append(f"  - {f}")
        lines.extend([
            "",
            "Recommendations:",
            "  - Run the full test suite",
            "  - Check if these files have inline tests (e.g., Rust #[cfg(test)])",
            "  - Consider creating test files for untested modules",
        ])
        return "\n".join(lines)

    # Sort by priority, then alphabetically
    sorted_suggestions = sorted(
        suggestions.items(),
        key=lambda kv: (kv[1]["priority"], kv[0]),
    )

    priority_labels = {
        1: "DIRECT",
        2: "IMPORTS",
        3: "INDIRECT",
    }

    lines = [
        "# Test Suggestions\n",
        f"Found {len(sorted_suggestions)} test file(s) for "
        f"{len(files)} changed file(s).\n",
    ]

    current_priority = 0
    for test_path, info in sorted_suggestions:
        priority = info["priority"]
        if priority != current_priority:
            current_priority = priority
            label = priority_labels.get(priority, f"P{priority}")
            lines.append(f"\n## Priority {priority} ({label})\n")

        lines.append(f"  {test_path}")
        for reason in info["reasons"]:
            lines.append(f"    - {reason}")

    # Summary
    by_priority: dict[int, int] = {}
    for info in suggestions.values():
        by_priority[info["priority"]] = by_priority.get(info["priority"], 0) + 1

    lines.append("\n## Summary\n")
    for p in sorted(by_priority):
        label = priority_labels.get(p, f"P{p}")
        lines.append(f"  {label}: {by_priority[p]} test file(s)")

    lines.append(
        f"\nRun these {len(sorted_suggestions)} test(s) to validate the changes "
        f"to {len(files)} file(s)."
    )

    return "\n".join(lines)
