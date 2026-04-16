"""Rule-bench harness — measures rule precision/recall to drive optimization.

Plugs into :class:`eval.meta_harness.meta_loop.MetaHarnessRunner` via the
``BenchSpec`` interface so the same outer loop, proposer, and evolution
journal can optimize rule packs alongside search-scoring parameters.
"""

from eval.meta_harness.rule_bench.corpus import (
    CorpusLoader,
    ExpectedFinding,
    LabeledSample,
)
from eval.meta_harness.rule_bench.scoring import (
    DEFAULT_SEVERITY_WEIGHTS,
    LanguageScore,
    RuleBenchResult,
    RuleScore,
    aggregate_per_language,
    compute_composite,
    severity_weighted_f1,
)

__all__ = [
    "DEFAULT_SEVERITY_WEIGHTS",
    "CorpusLoader",
    "ExpectedFinding",
    "LabeledSample",
    "LanguageScore",
    "RuleBenchResult",
    "RuleScore",
    "aggregate_per_language",
    "compute_composite",
    "severity_weighted_f1",
]
