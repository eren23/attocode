"""Local grading for SWE-bench instances.

Two tiers:
1. Local: apply patch, run FAIL_TO_PASS tests via pytest
2. Official: dispatch to swebench.harness.run_evaluation (if installed)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from eval.harness import BenchInstance

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GradeResult:
    """Result of grading a SWE-bench instance."""

    instance_id: str
    passed: bool = False
    partial_credit: float = 0.0  # 0.0 to 1.0
    fail_to_pass_total: int = 0
    fail_to_pass_passed: int = 0
    pass_to_pass_total: int = 0
    pass_to_pass_passed: int = 0
    test_output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def grade_local(
    instance: BenchInstance,
    instance_dir: str,
    patch: str = "",
    *,
    timeout: int = 300,
) -> GradeResult:
    """Grade an instance locally by running FAIL_TO_PASS tests.

    Steps:
    1. Apply the agent's patch (if not already applied via git)
    2. Apply the test_patch (adds/updates test files)
    3. Run FAIL_TO_PASS tests
    4. Optionally check PASS_TO_PASS tests haven't regressed
    """
    result = GradeResult(instance_id=instance.instance_id)

    # Parse FAIL_TO_PASS tests
    fail_to_pass = _parse_test_list(
        instance.metadata.get("fail_to_pass", "")
    )
    pass_to_pass = _parse_test_list(
        instance.metadata.get("pass_to_pass", "")
    )

    result.fail_to_pass_total = len(fail_to_pass)
    result.pass_to_pass_total = len(pass_to_pass)

    if not fail_to_pass:
        result.error = "No FAIL_TO_PASS tests specified"
        return result

    # Apply agent patch, then test patch.
    ok, err = _apply_patch(instance_dir, patch, "Agent patch")
    if not ok:
        result.error = err
        return result

    ok, err = _apply_patch(instance_dir, instance.test_patch, "Test patch")
    if not ok:
        result.error = err
        return result

    # Run FAIL_TO_PASS tests
    f2p_passed = 0
    f2p_output_parts = []

    for test_id in fail_to_pass:
        passed, output = _run_single_test(instance_dir, test_id, timeout=timeout)
        if passed:
            f2p_passed += 1
        f2p_output_parts.append(f"{'PASS' if passed else 'FAIL'}: {test_id}")

    result.fail_to_pass_passed = f2p_passed

    # Run PASS_TO_PASS tests (check no regressions)
    p2p_passed = 0
    for test_id in pass_to_pass[:20]:  # Cap to avoid long runs
        passed, _ = _run_single_test(instance_dir, test_id, timeout=timeout)
        if passed:
            p2p_passed += 1

    result.pass_to_pass_passed = p2p_passed

    # Compute results
    result.passed = f2p_passed == len(fail_to_pass)
    if len(fail_to_pass) > 0:
        result.partial_credit = f2p_passed / len(fail_to_pass)

    result.test_output = "\n".join(f2p_output_parts)

    return result


def grade_official(
    instance: BenchInstance,
    patch: str,
    *,
    timeout: int = 600,
) -> GradeResult:
    """Grade using the official SWE-bench harness.

    Requires: pip install swebench
    """
    result = GradeResult(instance_id=instance.instance_id)

    try:
        from swebench.harness.run_evaluation import run_evaluation

        eval_result = run_evaluation(
            predictions=[{
                "instance_id": instance.instance_id,
                "model_patch": patch,
            }],
            instances=[{
                "instance_id": instance.instance_id,
                "repo": instance.repo,
                "base_commit": instance.base_commit,
                "test_patch": instance.test_patch,
                "patch": instance.patch_gold,
            }],
            timeout=timeout,
        )

        if eval_result:
            r = eval_result[0]
            result.passed = r.get("resolved", False)
            result.test_output = r.get("test_output", "")

    except ImportError:
        result.error = (
            "swebench package not installed. "
            "Run: pip install swebench\n"
            "Falling back to local grading."
        )
        logger.warning(result.error)
    except Exception as e:
        result.error = str(e)
        logger.error("Official grading failed: %s", e)

    return result


def _parse_test_list(raw: str) -> list[str]:
    """Parse a test list from SWE-bench metadata.

    Can be a JSON array string or comma-separated.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: comma/newline separated
    return [t.strip() for t in raw.replace("\n", ",").split(",") if t.strip()]


_VALID_TEST_ID_RE = re.compile(r"^[\w./:\[\]\-]+$")


def _run_single_test(
    working_dir: str,
    test_id: str,
    *,
    timeout: int = 120,
) -> tuple[bool, str]:
    """Run a single test and return (passed, output)."""
    # Validate test_id to prevent command injection
    if not _VALID_TEST_ID_RE.match(test_id):
        return False, f"Invalid test_id format: {test_id!r}"

    try:
        # Try pytest first
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", test_id, "-x", "-q", "--tb=short"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stdout + proc.stderr
        return proc.returncode == 0, output[:2000]
    except subprocess.TimeoutExpired:
        return False, f"Test timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def _apply_patch(
    working_dir: str,
    patch_text: str,
    label: str,
) -> tuple[bool, str]:
    """Apply patch text; treat already-applied patches as success."""
    if not patch_text:
        return True, ""

    try:
        proc = subprocess.run(
            ["git", "apply", "--allow-empty", "-"],
            input=patch_text,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return True, ""

        # If reverse-check succeeds, the patch is already applied.
        reverse_check = subprocess.run(
            ["git", "apply", "--reverse", "--check", "--allow-empty", "-"],
            input=patch_text,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if reverse_check.returncode == 0:
            return True, ""

        return False, f"{label} failed to apply: {proc.stderr[:200]}"
    except Exception as exc:
        return False, f"{label} apply error: {exc}"
