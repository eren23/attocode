"""Composite bench evaluator — combines search + rule legs in one score.

Runs :class:`CodeIntelBenchEvaluator` (search + mcp_bench, weighted 0.4/0.6
internally) and :class:`RuleBenchEvaluator` in parallel, then folds them
into a single composite::

    composite = 0.3 * search_quality + 0.5 * mcp_bench + 0.2 * rule_bench

The per-language floor predicate still applies on the rule leg via
``metadata["per_language"]`` propagation, so a candidate that wins
search but breaks Go rules is still rejected.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import time
from typing import Any

from attoswarm.research.evaluator import EvalResult

from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.meta_loop import _BenchSpec
from eval.meta_harness.rule_bench.config import RuleBenchConfig
from eval.meta_harness.rule_bench.evaluator import RuleBenchEvaluator
from eval.meta_harness.rule_bench.predicate import rule_accept_predicate

logger = logging.getLogger(__name__)

# Composite weights — search 30%, mcp_bench 50%, rule 20%.
SEARCH_WEIGHT = 0.30
MCP_WEIGHT = 0.50
RULE_WEIGHT = 0.20


@dataclasses.dataclass(slots=True)
class CompositeConfig:
    """Wraps both leg configs into a single optimization candidate."""

    scoring: HarnessConfig = dataclasses.field(default_factory=HarnessConfig.default)
    rule_bench: RuleBenchConfig = dataclasses.field(
        default_factory=RuleBenchConfig.default,
    )

    @classmethod
    def default(cls) -> CompositeConfig:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring": self.scoring.to_dict(),
            "rule_bench": self.rule_bench.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompositeConfig:
        scoring = HarnessConfig.from_dict(data.get("scoring") or {})
        rb_raw = data.get("rule_bench") or {}
        rule_bench = RuleBenchConfig.from_dict(rb_raw)
        return cls(scoring=scoring, rule_bench=rule_bench)

    def save_yaml(self, path: str) -> None:
        import yaml as _yaml
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _yaml.safe_dump(self.to_dict(), f, sort_keys=False)

    @classmethod
    def load_yaml(cls, path: str) -> CompositeConfig:
        import yaml as _yaml

        with open(path, encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def validate(self) -> list[str]:
        errs = list(self.scoring.validate())
        errs.extend(self.rule_bench.validate())
        return errs


class CompositeBenchEvaluator:
    """Runs search + rule legs in parallel and folds them into a composite."""

    def __init__(
        self,
        *,
        search_evaluator: CodeIntelBenchEvaluator,
        rule_evaluator: RuleBenchEvaluator,
        config_filename: str = "composite_config.yaml",
        search_weight: float = SEARCH_WEIGHT,
        mcp_weight: float = MCP_WEIGHT,
        rule_weight: float = RULE_WEIGHT,
    ) -> None:
        self._search = search_evaluator
        self._rule = rule_evaluator
        self._config_filename = config_filename
        self._w_search = search_weight
        self._w_mcp = mcp_weight
        self._w_rule = rule_weight

    async def evaluate(self, working_dir: str) -> EvalResult:
        from pathlib import Path
        import os
        import tempfile

        t0 = time.monotonic()

        # Load composite config (if present) and split it across legs by
        # writing each half into a sibling temp dir for the leg's loader.
        config_path = os.path.join(working_dir, self._config_filename)
        if os.path.isfile(config_path):
            try:
                composite = CompositeConfig.load_yaml(config_path)
                errs = composite.validate()
                if errs:
                    return EvalResult(
                        metric_value=0.0,
                        error=f"Invalid composite config: {'; '.join(errs)}",
                        success=False,
                    )
            except Exception as exc:
                return EvalResult(
                    metric_value=0.0,
                    error=f"Failed to load composite config: {exc}",
                    success=False,
                )
        else:
            composite = CompositeConfig.default()

        with tempfile.TemporaryDirectory() as search_tmp, \
                tempfile.TemporaryDirectory() as rule_tmp:
            composite.scoring.save_yaml(
                os.path.join(search_tmp, "harness_config.yaml"),
            )
            composite.rule_bench.save_yaml(
                os.path.join(rule_tmp, "rule_harness_config.yaml"),
            )

            search_task = asyncio.create_task(self._search.evaluate(search_tmp))
            rule_task = asyncio.create_task(self._rule.evaluate(rule_tmp))
            search_result, rule_result = await asyncio.gather(
                search_task, rule_task,
            )

        elapsed = time.monotonic() - t0

        # Pull the search-leg sub-scores so we can re-weight at the
        # composite level rather than the search evaluator's internal 40/60.
        search_md = search_result.metadata or {}
        search_quality = (search_md.get("search_quality") or {}).get("composite") or 0.0
        mcp_bench = (search_md.get("mcp_bench") or {}).get("composite") or 0.0
        rule_score = rule_result.metric_value if rule_result.success else 0.0

        composite_score = (
            self._w_search * float(search_quality)
            + self._w_mcp * float(mcp_bench)
            + self._w_rule * float(rule_score)
        )

        # Forward the rule-bench per_language so the floor predicate can
        # still reject candidates that regress any single language.
        per_language: dict[str, float] = {}
        rule_md = rule_result.metadata or {}
        if isinstance(rule_md.get("per_language"), dict):
            per_language = {
                str(k): float(v) for k, v in rule_md["per_language"].items()
            }

        metadata: dict[str, Any] = {
            "search_quality": search_md.get("search_quality"),
            "mcp_bench": search_md.get("mcp_bench"),
            "rule_bench": rule_md.get("rule_bench"),
            "per_language": per_language,
            "composite": round(composite_score, 4),
            "weights": {
                "search": self._w_search,
                "mcp": self._w_mcp,
                "rule": self._w_rule,
            },
            "elapsed_seconds": round(elapsed, 2),
        }

        return EvalResult(
            metric_value=round(composite_score, 4),
            raw_output=json.dumps(metadata, indent=2, default=str),
            metadata=metadata,
            metrics={
                "search_composite": float(search_quality),
                "mcp_composite": float(mcp_bench),
                "rule_composite": float(rule_score),
            },
            constraint_checks={
                "latency_ok": elapsed < 600,
                "all_legs_ok": (
                    search_result.success and rule_result.success
                ),
            },
        )


def build_composite_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Factory consumed by ``__main__._select_bench("composite")``."""
    from eval.meta_harness.rule_bench.cli import build_rule_bench

    search_evaluator = CodeIntelBenchEvaluator(
        search_repos=args.search_repos.split(",") if args.search_repos else None,
        bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
        split="" if args.no_split else "eval",
    )
    rule_plumbing = build_rule_bench(args)
    rule_evaluator = rule_plumbing["evaluator"]

    composite_evaluator = CompositeBenchEvaluator(
        search_evaluator=search_evaluator,
        rule_evaluator=rule_evaluator,
    )

    spec = _BenchSpec(
        name="composite",
        evaluator=composite_evaluator,
        config_default=CompositeConfig.default(),
        config_filename="composite_config.yaml",
        propose_sweep=_composite_propose_stub,
        propose_llm=_composite_propose_stub,
        accept_predicate=rule_accept_predicate,
        artifact_prefix="composite_",
    )

    return {
        "name": "composite",
        "spec": spec,
        "evaluator": composite_evaluator,
        "config_default": CompositeConfig.default(),
        "config_loader": CompositeConfig.load_yaml,
        "config_filename": "composite_config.yaml",
        "artifact_prefix": "composite_",
    }


def _composite_propose_stub(
    current_best: Any,
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int,
    iteration: int,
) -> list:
    """Composite proposer is intentionally minimal — runners typically
    drive the search and rule benches independently, then run composite
    to confirm joint performance. Returns no candidates so the runner
    just re-evaluates the current best each iteration.
    """
    return []
