"""EvalHarness → Evaluator adapter for research orchestrator.

Bridges the existing ``EvalHarness`` benchmark infrastructure into the
``Evaluator`` protocol expected by the research orchestrator.  This
allows reusing EvalHarness benchmark suites as quality metrics in
research experiments.

Usage:
    from eval.harness import EvalHarness, BenchInstance
    from eval.research_adapter import EvalHarnessEvaluator

    harness = EvalHarness(agent_factory=my_factory)
    instances = [BenchInstance(...), ...]
    evaluator = EvalHarnessEvaluator(harness, instances)

    # Now usable as an Evaluator in research orchestrator
    result = await evaluator.evaluate(working_dir="/path/to/repo")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eval.harness import BenchInstance, EvalHarness

from attoswarm.research.evaluator import EvalResult

logger = logging.getLogger(__name__)


class EvalHarnessEvaluator:
    """Adapter that wraps an ``EvalHarness`` run into the ``Evaluator`` protocol.

    The metric value is the pass rate (passed / total) across all instances.
    """

    def __init__(
        self,
        harness: EvalHarness,
        instances: list[BenchInstance],
        *,
        concurrency: int = 1,
    ) -> None:
        self._harness = harness
        self._instances = instances
        self._concurrency = concurrency

    async def evaluate(self, working_dir: str) -> EvalResult:
        """Run the benchmark suite and return pass rate as metric."""
        try:
            results = await self._harness.run_suite(
                self._instances, concurrency=self._concurrency,
            )

            passed = sum(1 for r in results if r.tests_passed)
            total = len(results)
            rate = passed / total if total > 0 else 0.0

            metadata: dict[str, Any] = {
                "passed": passed,
                "total": total,
                "failures": [r.instance_id for r in results if not r.tests_passed],
            }

            return EvalResult(
                metric_value=rate,
                raw_output=f"{passed}/{total} instances passed",
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("EvalHarness run failed: %s", exc)
            return EvalResult(
                metric_value=0.0,
                error=str(exc),
                success=False,
            )
