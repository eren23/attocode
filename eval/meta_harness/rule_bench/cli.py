"""CLI factory for the rule-bench mode.

``__main__._select_bench`` calls :func:`build_rule_bench` to assemble the
plumbing dict consumed by ``cmd_baseline`` / ``cmd_evaluate`` / ``cmd_run``.
"""

from __future__ import annotations

import argparse
from typing import Any

from eval.meta_harness.meta_loop import _BenchSpec
from eval.meta_harness.rule_bench.config import RuleBenchConfig
from eval.meta_harness.rule_bench.evaluator import RuleBenchEvaluator
from eval.meta_harness.rule_bench.predicate import rule_accept_predicate
from eval.meta_harness.rule_bench.proposer import (
    propose_llm_rule_overrides,
    propose_sweep_rule_overrides,
)


def build_rule_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble the rule-bench plumbing from parsed CLI args.

    Recognized args:
        --packs              comma-separated pack names to load
        --include-community  include packs/community/* (default: True
                             when --packs unset, False when --packs given
                             unless explicitly passed)
        --include-attocode-fixtures  include hand-labeled attocode corpus
        --include-legacy-corpus      include eval/rule_accuracy/corpus
    """
    packs: list[str] = []
    if getattr(args, "packs", None):
        packs = [p.strip() for p in args.packs.split(",") if p.strip()]

    # Default inclusion: if user gave --packs, narrow to those; otherwise
    # include every source so the harness has something to score.
    include_community = bool(getattr(args, "include_community", False)) or not packs
    include_attocode = bool(getattr(args, "include_attocode_fixtures", False)) or not packs
    include_legacy = bool(getattr(args, "include_legacy_corpus", False)) or not packs

    evaluator = RuleBenchEvaluator(
        packs=packs,
        include_community=include_community,
        include_attocode=include_attocode,
        include_legacy=include_legacy,
    )

    spec = _BenchSpec(
        name="rule",
        evaluator=evaluator,
        config_default=RuleBenchConfig.default(),
        config_filename="rule_harness_config.yaml",
        propose_sweep=propose_sweep_rule_overrides,
        propose_llm=propose_llm_rule_overrides,
        accept_predicate=rule_accept_predicate,
        artifact_prefix="rule_",
    )

    return {
        "name": "rule",
        "spec": spec,
        "evaluator": evaluator,
        "config_default": RuleBenchConfig.default(),
        "config_loader": RuleBenchConfig.load_yaml,
        "config_filename": "rule_harness_config.yaml",
        "artifact_prefix": "rule_",
    }
