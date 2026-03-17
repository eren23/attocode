"""Evaluator protocol and built-in evaluators.

Evaluators measure the quality metric for a research experiment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EvalResult:
    """Result of an evaluation."""

    metric_value: float
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    success: bool = True


@runtime_checkable
class Evaluator(Protocol):
    """Protocol for evaluation strategies."""

    async def evaluate(self, working_dir: str) -> EvalResult: ...


class CommandEvaluator:
    """Evaluator that runs a shell command and parses the last numeric line."""

    def __init__(self, command: str, timeout: float = 60.0) -> None:
        self._command = command
        self._timeout = timeout

    async def evaluate(self, working_dir: str) -> EvalResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                self._command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return EvalResult(
                    metric_value=0.0,
                    raw_output=stdout,
                    error=f"Exit code {proc.returncode}: {stderr[:500]}",
                    success=False,
                )

            # Parse last numeric line
            value = self._parse_last_numeric(stdout)
            if value is None:
                return EvalResult(
                    metric_value=0.0,
                    raw_output=stdout,
                    error="No numeric value found in output",
                    success=False,
                )

            return EvalResult(metric_value=value, raw_output=stdout)

        except TimeoutError:
            return EvalResult(
                metric_value=0.0,
                error=f"Evaluation timed out after {self._timeout}s",
                success=False,
            )
        except Exception as exc:
            return EvalResult(
                metric_value=0.0, error=str(exc), success=False,
            )

    @staticmethod
    def _parse_last_numeric(text: str) -> float | None:
        """Extract the last numeric value from text output."""
        for line in reversed(text.strip().splitlines()):
            line = line.strip()
            try:
                return float(line)
            except ValueError:
                # Try extracting number from line
                match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
                if match:
                    return float(match.group())
        return None


class ScriptEvaluator:
    """Evaluator that runs a Python script expecting JSON with a "metric" key."""

    def __init__(self, script_path: str, timeout: float = 60.0) -> None:
        self._script_path = script_path
        self._timeout = timeout

    async def evaluate(self, working_dir: str) -> EvalResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", self._script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")

            if proc.returncode != 0:
                stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
                return EvalResult(
                    metric_value=0.0,
                    raw_output=stdout,
                    error=f"Script exited {proc.returncode}: {stderr[:500]}",
                    success=False,
                )

            data = json.loads(stdout)
            value = float(data["metric"])
            metadata = {k: v for k, v in data.items() if k != "metric"}
            return EvalResult(metric_value=value, raw_output=stdout, metadata=metadata)

        except (json.JSONDecodeError, KeyError) as exc:
            return EvalResult(
                metric_value=0.0,
                raw_output=stdout if "stdout" in dir() else "",
                error=f"Failed to parse script output: {exc}",
                success=False,
            )
        except Exception as exc:
            return EvalResult(metric_value=0.0, error=str(exc), success=False)


class TestPassRateEvaluator:
    """Evaluator that runs pytest and returns pass rate as metric."""

    def __init__(self, test_path: str = "", timeout: float = 120.0) -> None:
        self._test_path = test_path
        self._timeout = timeout

    async def evaluate(self, working_dir: str) -> EvalResult:
        cmd = ["python", "-m", "pytest", "--tb=no", "-q"]
        if self._test_path:
            cmd.append(self._test_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")

            # Parse pytest output: "X passed, Y failed"
            passed = 0
            failed = 0
            for match in re.finditer(r"(\d+)\s+passed", stdout):
                passed = int(match.group(1))
            for match in re.finditer(r"(\d+)\s+failed", stdout):
                failed = int(match.group(1))

            total = passed + failed
            rate = passed / total if total > 0 else 0.0

            return EvalResult(
                metric_value=rate,
                raw_output=stdout,
                metadata={"passed": passed, "failed": failed, "total": total},
            )
        except Exception as exc:
            return EvalResult(metric_value=0.0, error=str(exc), success=False)


class CompositeEvaluator:
    """Weighted average of multiple evaluators."""

    def __init__(self, evaluators: list[tuple[Evaluator, float]]) -> None:
        self._evaluators = evaluators
        total_weight = sum(w for _, w in evaluators)
        self._weights = [(e, w / total_weight) for e, w in evaluators] if total_weight > 0 else evaluators

    async def evaluate(self, working_dir: str) -> EvalResult:
        results = await asyncio.gather(
            *(e.evaluate(working_dir) for e, _ in self._weights),
            return_exceptions=True,
        )

        weighted_sum = 0.0
        total_weight = 0.0
        errors: list[str] = []
        raw_parts: list[str] = []

        for (_, weight), result in zip(self._weights, results):
            if isinstance(result, Exception):
                errors.append(str(result))
                continue
            if not result.success:
                errors.append(result.error)
                continue
            weighted_sum += result.metric_value * weight
            total_weight += weight
            raw_parts.append(result.raw_output[:200])

        if total_weight == 0:
            return EvalResult(
                metric_value=0.0,
                error=f"All evaluators failed: {'; '.join(errors)}",
                success=False,
            )

        return EvalResult(
            metric_value=weighted_sum / total_weight * (sum(w for _, w in self._weights)),
            raw_output="\n---\n".join(raw_parts),
            metadata={"errors": errors} if errors else {},
        )
