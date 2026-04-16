"""Rule-bench inner-loop evaluator.

Loads the active rule registry, applies a candidate's overrides, runs
rules over the labeled fixture corpus, scores per-rule TP/FP/FN, then
aggregates to severity-weighted F1 per language. The result feeds the
outer ``MetaHarnessRunner`` like any other ``EvalResult``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

from attoswarm.research.evaluator import EvalResult

from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.filters.pipeline import run_pipeline
from attocode.code_intel.rules.loader import load_yaml_rules
from attocode.code_intel.rules.model import (
    RuleSource,
    UnifiedRule,
)
from attocode.code_intel.rules.packs.pack_loader import (
    get_community_pack_dir,
    list_community_packs,
)
from attocode.code_intel.rules.registry import RuleRegistry
from attocode.code_intel.rules.testing import _finding_matches_rule

from eval.meta_harness.rule_bench.config import RuleBenchConfig
from eval.meta_harness.rule_bench.corpus import CorpusLoader, LabeledSample
from eval.meta_harness.rule_bench.scoring import (
    DEFAULT_SEVERITY_WEIGHTS,
    RuleBenchResult,
    RuleScore,
    aggregate_per_language,
    compute_composite,
)

logger = logging.getLogger(__name__)


class RuleBenchEvaluator:
    """Evaluator that scores a ``RuleBenchConfig`` against a labeled corpus.

    Mirrors the contract of :class:`CodeIntelBenchEvaluator` so the same
    outer loop drives both. ``evaluate(working_dir)`` reads
    ``rule_harness_config.yaml`` from ``working_dir`` if present; otherwise
    uses defaults.
    """

    def __init__(
        self,
        *,
        packs: list[str] | None = None,
        corpus_dir: str | None = None,
        severity_weights: dict[str, float] | None = None,
        config_filename: str = "rule_harness_config.yaml",
        include_community: bool = True,
        include_attocode: bool = True,
        include_legacy: bool = True,
    ) -> None:
        self._packs = list(packs) if packs else []
        self._corpus_dir = corpus_dir
        self._severity_weights = severity_weights or DEFAULT_SEVERITY_WEIGHTS
        self._config_filename = config_filename
        self._include_community = include_community
        self._include_attocode = include_attocode
        self._include_legacy = include_legacy

        # Cache: base registry + corpus get built once per evaluator instance.
        self._base_registry: RuleRegistry | None = None
        self._corpus: list[LabeledSample] | None = None

    # ------------------------------------------------------------------
    # Lazy initialization (so import time stays cheap)
    # ------------------------------------------------------------------

    def _build_base_registry(self) -> RuleRegistry:
        if self._base_registry is not None:
            return self._base_registry

        from attocode.code_intel.rules.packs.pack_loader import (
            _EXAMPLES_DIR,  # type: ignore[attr-defined]
            list_example_packs,
        )

        registry = RuleRegistry()
        loaded_packs: set[str] = set()
        # Explicit pack filter, or "all packs found on disk" when empty.
        explicit_filter = bool(self._packs)
        wanted = set(self._packs)

        # 1. Shipped example packs
        example_manifests = list_example_packs() if not explicit_filter else [
            type("M", (), {"name": p})() for p in self._packs
        ]
        for manifest in example_manifests:
            pack = manifest.name
            if explicit_filter and pack not in wanted:
                continue
            pack_dir = _EXAMPLES_DIR / pack
            if not pack_dir.is_dir():
                continue
            rules_dir = pack_dir / "rules"
            if not rules_dir.is_dir():
                rules_dir = pack_dir
            rules = load_yaml_rules(
                rules_dir, source=RuleSource.PACK, pack=pack,
            )
            for r in rules:
                registry.register(r)
            loaded_packs.add(pack)

        # 2. Community packs (when included)
        if self._include_community:
            community_dir = get_community_pack_dir()
            if community_dir.is_dir():
                for manifest in list_community_packs():
                    if explicit_filter and manifest.name not in wanted:
                        continue
                    pack_dir = community_dir / manifest.name
                    rules_dir = pack_dir / "rules"
                    if not rules_dir.is_dir():
                        rules_dir = pack_dir
                    rules = load_yaml_rules(
                        rules_dir, source=RuleSource.PACK, pack=manifest.name,
                    )
                    for r in rules:
                        registry.register(r)
                    loaded_packs.add(manifest.name)

        logger.info(
            "Rule-bench registry: %d rules across %d packs",
            registry.count, len(loaded_packs),
        )
        self._base_registry = registry
        return registry

    def _build_corpus(self) -> list[LabeledSample]:
        if self._corpus is not None:
            return self._corpus

        # If --packs was given, narrow the community fixtures to the same set.
        enabled_packs: set[str] | None = (
            set(self._packs) if self._packs else None
        )
        loader = CorpusLoader(
            include_community=self._include_community,
            include_attocode=self._include_attocode,
            include_legacy=self._include_legacy,
            enabled_packs=enabled_packs,
        )
        corpus = list(loader.iter_samples())
        logger.info("Rule-bench corpus: %d labeled samples", len(corpus))
        self._corpus = corpus
        return corpus

    # ------------------------------------------------------------------
    # Public evaluator contract
    # ------------------------------------------------------------------

    async def evaluate(self, working_dir: str) -> EvalResult:
        t0 = time.monotonic()

        config_path = os.path.join(working_dir, self._config_filename)
        if os.path.isfile(config_path):
            try:
                config = RuleBenchConfig.load_yaml(config_path)
                errors = config.validate()
                if errors:
                    return EvalResult(
                        metric_value=0.0,
                        error=f"Invalid config: {'; '.join(errors)}",
                        success=False,
                    )
            except Exception as exc:
                return EvalResult(
                    metric_value=0.0,
                    error=f"Failed to load config: {exc}",
                    success=False,
                )
        else:
            config = RuleBenchConfig.default()

        try:
            base_registry = self._build_base_registry()
            corpus = self._build_corpus()
        except Exception as exc:  # pragma: no cover - defensive
            return EvalResult(
                metric_value=0.0,
                error=f"Setup failed: {exc}",
                success=False,
            )

        if base_registry.count == 0:
            return EvalResult(
                metric_value=0.0,
                error="Empty rule registry — pass --packs",
                success=False,
            )
        if not corpus:
            return EvalResult(
                metric_value=0.0,
                error="Empty corpus — no labeled fixtures discovered",
                success=False,
            )

        cloned = config.apply_to_registry(base_registry)

        # Filter corpus by enabled languages (if any)
        if config.enabled_languages:
            allowed = set(config.enabled_languages)
            corpus = [s for s in corpus if s.language in allowed]

        result = self._score_corpus(cloned, corpus, config.global_min_confidence)
        elapsed = time.monotonic() - t0

        per_lang_scalars = result.per_language_scalars()
        rule_bench_payload = result.to_dict()
        metadata: dict[str, Any] = {
            "rule_bench": rule_bench_payload,
            "per_language": per_lang_scalars,
            "config": config.to_dict(),
            "elapsed_seconds": round(elapsed, 2),
        }

        return EvalResult(
            metric_value=round(result.composite_score, 4),
            raw_output=json.dumps(rule_bench_payload, indent=2, default=str),
            metadata=metadata,
            metrics={
                "weighted_f1": round(result.weighted_f1, 4),
                "precision": round(result.precision, 4),
                "recall": round(result.recall, 4),
            },
            constraint_checks={
                "latency_ok": elapsed < 300,
                "any_per_lang_signal": bool(per_lang_scalars),
            },
        )

    # ------------------------------------------------------------------
    # Scoring (pure)
    # ------------------------------------------------------------------

    def _score_corpus(
        self,
        registry: RuleRegistry,
        corpus: list[LabeledSample],
        min_confidence: float,
    ) -> RuleBenchResult:
        # Run only enabled rules, but score every rule so disabled rules
        # still surface in the per-rule report (their unmet expects become
        # FNs the proposer can see).
        enabled_rules = registry.all_rules(enabled_only=True)
        all_rules = registry.all_rules(enabled_only=False)
        rule_index: dict[str, UnifiedRule] = {r.qualified_id: r for r in all_rules}

        rule_scores: dict[str, RuleScore] = {}
        for r in all_rules:
            language = r.languages[0] if r.languages else ""
            rule_scores[r.qualified_id] = RuleScore(
                rule_id=r.qualified_id,
                pack=r.pack,
                language=language,
                severity=r.severity,
                enabled=r.enabled,
            )

        rules = enabled_rules

        annotations_total = 0
        fixture_counts_by_language: dict[str, int] = defaultdict(int)

        for sample in corpus:
            fixture_counts_by_language[sample.language] += 1
            annotations_total += len(sample.expected_findings)

            findings = execute_rules(
                [sample.file_path], rules, project_dir="",
            )
            findings = run_pipeline(findings, min_confidence=min_confidence)

            # Group findings by line for fast match lookup
            findings_by_line: dict[int, list[Any]] = defaultdict(list)
            for f in findings:
                findings_by_line[f.line].append(f)

            # Lines that have any expectation (positive or negative)
            expected_lines = {a.line for a in sample.expected_findings}

            # Track which findings have been "claimed" by an expectation so
            # they don't double-count as both TP and FP.
            claimed: set[tuple[int, str]] = set()

            for ann in sample.expected_findings:
                line_findings = findings_by_line.get(ann.line, [])
                matched_finding = None
                for fnd in line_findings:
                    if _finding_matches_rule(fnd.rule_id, ann.rule_id):
                        matched_finding = fnd
                        break

                if ann.kind == "expect":
                    if matched_finding is not None:
                        # TP — credit goes to the resolved rule
                        rule_id = matched_finding.rule_id
                        if rule_id in rule_scores:
                            rule_scores[rule_id].tp += 1
                            claimed.add((ann.line, rule_id))
                    else:
                        # FN — try to credit the expected rule by suffix
                        target_rule_id = self._resolve_expected_rule(
                            ann.rule_id, rule_index,
                        )
                        if target_rule_id and target_rule_id in rule_scores:
                            rule_scores[target_rule_id].fn += 1

                elif ann.kind == "ok":
                    if matched_finding is not None:
                        # FP — rule fired where we said it shouldn't
                        rule_id = matched_finding.rule_id
                        if rule_id in rule_scores:
                            rule_scores[rule_id].fp += 1
                            claimed.add((ann.line, rule_id))
                # "todoruleid" is informational — never counts as TP/FP/FN.

            # Findings on lines without any expectation are FPs (the file
            # didn't claim those rules should fire here). Limited to lines
            # with at least one annotation in the file as a whole, AND not
            # already claimed.
            if expected_lines:
                for line, line_findings in findings_by_line.items():
                    for fnd in line_findings:
                        key = (line, fnd.rule_id)
                        if key in claimed:
                            continue
                        if line in expected_lines:
                            continue  # handled above
                        if fnd.rule_id in rule_scores:
                            rule_scores[fnd.rule_id].fp += 1

        per_language = aggregate_per_language(
            rule_scores,
            severity_weights=self._severity_weights,
            fixture_counts_by_language=dict(fixture_counts_by_language),
        )

        # Per-rule weighted_f1 too, for downstream LLM proposer analysis
        for score in rule_scores.values():
            weight = self._severity_weights.get(score.severity, 1.0)
            tp_w = score.tp * weight
            fp_w = score.fp * weight
            fn_w = score.fn * weight
            from eval.meta_harness.rule_bench.scoring import severity_weighted_f1

            _, _, f1 = severity_weighted_f1(tp_w, fp_w, fn_w)
            score.weighted_f1 = f1

        composite = compute_composite(per_language)

        # Aggregate-level precision/recall (severity-weighted across all rules)
        total_tp = sum(s.true_positives_weighted for s in per_language.values())
        total_fp = sum(s.false_positives_weighted for s in per_language.values())
        total_fn = sum(s.false_negatives_weighted for s in per_language.values())
        from eval.meta_harness.rule_bench.scoring import severity_weighted_f1

        precision, recall, weighted_f1_overall = severity_weighted_f1(
            total_tp, total_fp, total_fn,
        )

        return RuleBenchResult(
            composite_score=composite,
            weighted_f1=weighted_f1_overall,
            precision=precision,
            recall=recall,
            per_language=per_language,
            per_rule=rule_scores,
            fixtures_total=len(corpus),
            annotations_total=annotations_total,
        )

    @staticmethod
    def _resolve_expected_rule(
        annotation_rule_id: str,
        rule_index: dict[str, UnifiedRule],
    ) -> str | None:
        """Find a registered rule whose qualified_id matches the annotation."""
        if annotation_rule_id in rule_index:
            return annotation_rule_id
        # Suffix match (annotation may use bare id when rule is pack-qualified)
        for qid in rule_index:
            if qid.endswith("/" + annotation_rule_id):
                return qid
        return None
