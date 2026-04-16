"""Unit tests for ``RuleBenchEvaluator``.

We exercise the evaluator against a fully synthetic registry + corpus so
the test is deterministic and independent of which packs ship today.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    UnifiedRule,
)
from attocode.code_intel.rules.registry import RuleRegistry

from eval.meta_harness.rule_bench.config import RuleBenchConfig, RuleOverride
from eval.meta_harness.rule_bench.corpus import (
    CorpusLoader,
    ExpectedFinding,
    LabeledSample,
)
from eval.meta_harness.rule_bench.evaluator import RuleBenchEvaluator


def _stub_rule(
    rid: str,
    *,
    pattern: str,
    severity: RuleSeverity = RuleSeverity.HIGH,
    languages: tuple[str, ...] = ("python",),
    pack: str = "synth",
    confidence: float = 0.9,
) -> UnifiedRule:
    return UnifiedRule(
        id=rid,
        name=rid,
        description="stub",
        severity=severity,
        category=RuleCategory.CORRECTNESS,
        languages=list(languages),
        pattern=re.compile(pattern),
        source=RuleSource.PACK,
        pack=pack,
        confidence=confidence,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def synthetic_evaluator(tmp_path: Path) -> RuleBenchEvaluator:
    """An evaluator wired to a synthetic corpus and registry."""
    # Build a corpus of two python fixtures.
    corpus_root = tmp_path / "fixtures"
    _write(
        corpus_root / "python" / "fires.py",
        "x = bad_call()  # expect: bad-call\n"
        "y = good_call()  # ok: bad-call\n",
    )
    _write(
        corpus_root / "python" / "double.py",
        "a = bad_call()  # expect: bad-call\n",
    )

    # Patch the loader's attocode dir to point at our synthetic corpus.
    evaluator = RuleBenchEvaluator(
        packs=[],
        include_community=False,
        include_attocode=True,
        include_legacy=False,
    )

    base = RuleRegistry()
    base.register(_stub_rule("bad-call", pattern=r"\bbad_call\("))
    evaluator._base_registry = base  # noqa: SLF001 - test injection

    samples = []
    for fixture in [
        corpus_root / "python" / "fires.py",
        corpus_root / "python" / "double.py",
    ]:
        loaded = CorpusLoader._load_sample(str(fixture), pack="attocode")  # noqa: SLF001
        if loaded is not None:
            samples.append(loaded)
    evaluator._corpus = samples  # noqa: SLF001
    return evaluator


def _run(coro):  # tiny helper — pytest-asyncio AUTO mode handles awaits but
    # this evaluator is plain async and the synthetic test doesn't need the
    # event loop fixture.
    return asyncio.run(coro)


class TestRuleBenchEvaluator:
    def test_baseline_full_recall(
        self, synthetic_evaluator: RuleBenchEvaluator, tmp_path: Path,
    ) -> None:
        result = _run(synthetic_evaluator.evaluate(str(tmp_path)))
        assert result.success is True
        assert result.metric_value > 0.0

        rule_bench = result.metadata["rule_bench"]
        assert rule_bench["fixtures_total"] == 2

        per_rule = rule_bench["per_rule"]
        bad_call = per_rule["synth/bad-call"]
        # Both expect lines should fire — TP=2, FP=0 (the ok line stays clean)
        assert bad_call["tp"] == 2
        assert bad_call["fp"] == 0
        assert bad_call["fn"] == 0

        # Per-language entry exists for python
        assert "python" in result.metadata["per_language"]
        assert result.metadata["per_language"]["python"] > 0.0

    def test_disabled_rule_misses_everything(
        self, synthetic_evaluator: RuleBenchEvaluator, tmp_path: Path,
    ) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "synth/bad-call": RuleOverride(
                    rule_id="synth/bad-call", enabled=False,
                ),
            },
        )
        config_path = tmp_path / "rule_harness_config.yaml"
        cfg.save_yaml(str(config_path))

        result = _run(synthetic_evaluator.evaluate(str(tmp_path)))
        assert result.success is True
        # No rules fire → every expect becomes an FN credited to the
        # disabled rule (so the proposer can see what it lost by disabling).
        rule_bench = result.metadata["rule_bench"]
        bad_call = rule_bench["per_rule"]["synth/bad-call"]
        assert bad_call["tp"] == 0
        assert bad_call["fp"] == 0
        assert bad_call["fn"] == 2
        assert bad_call["enabled"] is False
        # Recall collapses to 0, so composite is 0
        assert result.metric_value == 0.0

    def test_invalid_config_returns_failure(
        self, synthetic_evaluator: RuleBenchEvaluator, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "rule_harness_config.yaml"
        bad.write_text(
            "global_min_confidence: 1.5\nrule_overrides: []\n",
            encoding="utf-8",
        )
        result = _run(synthetic_evaluator.evaluate(str(tmp_path)))
        assert result.success is False
        assert "Invalid config" in result.error

    def test_empty_corpus_returns_failure(self, tmp_path: Path) -> None:
        evaluator = RuleBenchEvaluator(
            packs=[], include_community=False, include_attocode=False,
            include_legacy=False,
        )
        evaluator._base_registry = RuleRegistry()  # noqa: SLF001
        evaluator._base_registry.register(_stub_rule("x", pattern="x"))  # noqa: SLF001
        evaluator._corpus = []  # noqa: SLF001
        result = _run(evaluator.evaluate(str(tmp_path)))
        assert result.success is False

    def test_empty_registry_returns_failure(self, tmp_path: Path) -> None:
        evaluator = RuleBenchEvaluator(
            packs=[], include_community=False, include_attocode=False,
            include_legacy=False,
        )
        evaluator._base_registry = RuleRegistry()  # noqa: SLF001
        evaluator._corpus = []  # noqa: SLF001
        # corpus is also empty so we expect the registry-empty message first
        result = _run(evaluator.evaluate(str(tmp_path)))
        assert result.success is False
        assert "registry" in result.error.lower() or "corpus" in result.error.lower()
