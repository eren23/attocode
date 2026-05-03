"""Tests for rules.evolution — mutations, crossover, selection, evolve loop."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from attocode.code_intel.rules.evolution import (
    Fitness,
    MutationOperator,
    _compute_composite,
    _narrow_regex,
    _widen_regex,
    crossover,
    evaluate_rule,
    evolve,
    mutate,
    tournament_select,
)
from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)


def _rule(
    rule_id: str,
    pattern: str = r"\bdanger\b",
    *,
    severity: RuleSeverity = RuleSeverity.MEDIUM,
    confidence: float = 0.6,
    languages: list[str] | None = None,
) -> UnifiedRule:
    return UnifiedRule(
        id=rule_id,
        name=rule_id,
        description="m",
        severity=severity,
        category=RuleCategory.SUSPICIOUS,
        languages=list(languages or ["python"]),
        pattern=re.compile(pattern),
        source=RuleSource.USER,
        tier=RuleTier.REGEX,
        confidence=confidence,
        pack="evo",
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestRegexEdits:
    def test_widen_drops_first_anchor(self):
        assert _widen_regex(r"\bdanger\b") == r"danger\b"

    def test_widen_returns_none_when_no_anchor(self):
        assert _widen_regex("danger") is None

    def test_narrow_adds_both_anchors(self):
        assert _narrow_regex("danger") == r"\bdanger\b"

    def test_narrow_returns_none_when_already_anchored(self):
        assert _narrow_regex(r"\bdanger\b") is None

    def test_narrow_partial(self):
        assert _narrow_regex(r"\bdanger") == r"\bdanger\b"


class TestComposite:
    def test_perfect_precision_recall_under_budget(self):
        score = _compute_composite(precision=1.0, recall=1.0, speed_ms=10.0)
        # 0.5 + 0.35 + (0.15 * (1 - 10/50)) = 0.5 + 0.35 + 0.12 = 0.97
        assert score == pytest.approx(0.97, abs=1e-3)

    def test_over_budget_speed_zero_bonus(self):
        score = _compute_composite(precision=1.0, recall=1.0, speed_ms=200.0)
        # speed bonus = max(0, 1 - 200/50) = 0
        assert score == pytest.approx(0.85, abs=1e-3)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class TestMutate:
    def test_widen_returns_new_rule_with_dropped_boundary(self):
        rule = _rule("r1", pattern=r"\bdanger\b")
        mutated = mutate(rule, MutationOperator.REGEX_WIDEN)
        assert mutated is not None
        assert mutated.pattern.pattern == r"danger\b"
        # Original untouched.
        assert rule.pattern.pattern == r"\bdanger\b"

    def test_widen_returns_none_when_no_anchor(self):
        rule = _rule("r1", pattern="danger")
        assert mutate(rule, MutationOperator.REGEX_WIDEN) is None

    def test_narrow_adds_anchors(self):
        rule = _rule("r1", pattern="danger")
        mutated = mutate(rule, MutationOperator.REGEX_NARROW)
        assert mutated is not None
        assert mutated.pattern.pattern == r"\bdanger\b"

    def test_severity_up_walks_ladder(self):
        rule = _rule("r1", severity=RuleSeverity.LOW)
        mutated = mutate(rule, MutationOperator.SEVERITY_UP)
        assert mutated is not None
        assert mutated.severity == RuleSeverity.MEDIUM

    def test_severity_up_at_top_returns_none(self):
        rule = _rule("r1", severity=RuleSeverity.CRITICAL)
        assert mutate(rule, MutationOperator.SEVERITY_UP) is None

    def test_severity_down_walks_ladder(self):
        rule = _rule("r1", severity=RuleSeverity.HIGH)
        mutated = mutate(rule, MutationOperator.SEVERITY_DOWN)
        assert mutated is not None
        assert mutated.severity == RuleSeverity.MEDIUM

    def test_confidence_up(self):
        rule = _rule("r1", confidence=0.6)
        mutated = mutate(rule, MutationOperator.CONFIDENCE_UP)
        assert mutated is not None
        assert mutated.confidence == pytest.approx(0.7)

    def test_confidence_clamped_at_1(self):
        rule = _rule("r1", confidence=1.0)
        assert mutate(rule, MutationOperator.CONFIDENCE_UP) is None

    def test_confidence_clamped_at_0(self):
        rule = _rule("r1", confidence=0.0)
        assert mutate(rule, MutationOperator.CONFIDENCE_DOWN) is None

    def test_widen_with_no_anchor_returns_none(self):
        """When the pattern has no ``\\b`` to drop, widen is a no-op."""
        rule = _rule("r1", pattern=r"\w+")
        assert mutate(rule, MutationOperator.REGEX_WIDEN) is None


# ---------------------------------------------------------------------------
# Crossover
# ---------------------------------------------------------------------------


class TestCrossover:
    def test_combines_fields_from_both_parents(self):
        a = _rule("a", pattern=r"\bfoo\b", severity=RuleSeverity.LOW, confidence=0.4)
        b = _rule("b", pattern=r"\bbar\b", severity=RuleSeverity.HIGH, confidence=0.8)
        rng = random.Random(0)
        child = crossover(a, b, rng=rng)
        # Child id is composed when none provided.
        assert child.id == "a-x-b"
        # Pattern always inherited from A (regex splicing is unsafe).
        assert child.pattern.pattern == r"\bfoo\b"
        # Confidence is the mean of parents.
        assert child.confidence == pytest.approx(0.6, abs=1e-3)
        # Severity is one of the parents'.
        assert child.severity in (RuleSeverity.LOW, RuleSeverity.HIGH)

    def test_explicit_child_id(self):
        a = _rule("a")
        b = _rule("b")
        child = crossover(a, b, child_id="custom")
        assert child.id == "custom"


# ---------------------------------------------------------------------------
# Tournament selection
# ---------------------------------------------------------------------------


class TestTournament:
    def test_picks_higher_composite(self):
        ranked = [
            (_rule("hi"), Fitness(1.0, 1.0, 1.0, 5.0, 0.95)),
            (_rule("lo"), Fitness(0.1, 0.1, 0.1, 5.0, 0.10)),
        ]
        rng = random.Random(0)
        # k=2 forces both to be sampled — winner is "hi".
        winner = tournament_select(ranked, k=2, rng=rng)
        assert winner.id == "hi"

    def test_empty_ranked_raises(self):
        with pytest.raises(ValueError):
            tournament_select([], rng=random.Random(0))


# ---------------------------------------------------------------------------
# Evaluate + evolve loop end-to-end on a tiny corpus
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_corpus(tmp_path: Path) -> Path:
    """A tiny annotated fixture directory the evolver can score against.

    ``danger()`` lines should fire ``r1``; ``safe()`` lines should not.
    """
    f = tmp_path / "fixtures"
    f.mkdir()
    (f / "case.py").write_text(
        "def main():\n"
        "    danger()  # expect: r1\n"
        "    safe()    # ok: r1\n",
        encoding="utf-8",
    )
    return f


class TestEvaluateRule:
    def test_perfect_rule_scores_high(self, fixture_corpus: Path):
        rule = _rule("r1", pattern=r"\bdanger\b")
        fit = evaluate_rule(rule, fixtures_dir=str(fixture_corpus))
        assert fit.precision == 1.0
        assert fit.recall == 1.0
        assert fit.f1 == 1.0
        assert fit.composite > 0.85

    def test_overly_broad_rule_loses_precision(self, fixture_corpus: Path):
        # Matches BOTH danger and safe — precision drops.
        rule = _rule("r1", pattern=r"\(\)")
        fit = evaluate_rule(rule, fixtures_dir=str(fixture_corpus))
        assert fit.precision < 1.0
        assert fit.composite < 0.95

    def test_misses_positives_gives_zero_recall(self, fixture_corpus: Path):
        rule = _rule("r1", pattern=r"\bnever-matches-anything-zzz\b")
        fit = evaluate_rule(rule, fixtures_dir=str(fixture_corpus))
        assert fit.recall == 0.0


class TestEvolveLoop:
    def test_evolve_returns_best_state(self, fixture_corpus: Path):
        seed = _rule("r1", pattern=r"\bdanger\b")
        state = evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=3,
            population_size=4,
            plateau_gens=2,
            rng=random.Random(0),
        )
        assert state.generations_run >= 1
        # Best is at least as good as the (already optimal) seed.
        assert state.best_fitness.f1 == 1.0
        assert state.best_fitness.precision == 1.0
        assert state.stopped_reason in ("plateau", "max_generations")

    def test_evolve_writes_audit_log(self, fixture_corpus: Path, tmp_path: Path):
        seed = _rule("r1", pattern=r"\bdanger\b")
        log_path = tmp_path / "evo.jsonl"
        evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=2,
            population_size=3,
            plateau_gens=10,  # don't plateau — force max_generations
            rng=random.Random(0),
            log_path=str(log_path),
        )
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert lines  # at least one generation logged
        entry = json.loads(lines[0])
        for key in (
            "generation", "best_id", "best_pattern", "best_composite",
            "best_precision", "best_recall", "population_mean_composite",
        ):
            assert key in entry, key

    def test_evolve_plateau_early_stop(self, fixture_corpus: Path):
        # An already-perfect seed should plateau immediately.
        seed = _rule("r1", pattern=r"\bdanger\b")
        state = evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=20,
            population_size=4,
            plateau_gens=2,
            plateau_eps=1e-3,
            rng=random.Random(0),
        )
        assert state.stopped_reason == "plateau"
        assert state.generations_run < 20

    def test_evolve_requires_seeds(self, fixture_corpus: Path):
        with pytest.raises(ValueError):
            evolve([], fixtures_dir=str(fixture_corpus))

    def test_evolve_rejects_zero_max_generations(self, fixture_corpus: Path):
        """Review C1 — ``max_generations=0`` would have produced an
        EvolutionState with len(population) != len(fitnesses). Caller
        passing 0 must get a clean ValueError, not a silently-broken
        result."""
        seed = _rule("r1")
        with pytest.raises(ValueError, match="max_generations"):
            evolve([seed], fixtures_dir=str(fixture_corpus), max_generations=0)

    def test_evolve_continues_on_individual_evaluation_failure(
        self, fixture_corpus: Path, monkeypatch,
    ):
        """Review C2 — when ``RuleTestRunner`` raises for a candidate, the
        evolve loop must surface a zero-fitness for that individual
        rather than crashing the whole run."""
        from attocode.code_intel.rules import evolution as evo

        seed = _rule("r1", pattern=r"\bdanger\b")
        # Make every other evaluate_rule call raise — the safe wrapper
        # should swallow it and substitute zero fitness.
        original = evo.evaluate_rule
        call_count = {"n": 0}

        def flaky(rule, *, fixtures_dir, project_dir):
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                raise RuntimeError("synthetic fixture crash")
            return original(rule, fixtures_dir=fixtures_dir, project_dir=project_dir)

        monkeypatch.setattr(evo, "evaluate_rule", flaky)
        # Should NOT raise. Best fitness is the seed (which evaluates fine).
        state = evo.evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=2,
            population_size=4,
            plateau_gens=99,
            rng=random.Random(0),
        )
        assert state.generations_run >= 1
        # At least one zero-fitness should have shown up across both gens.
        zero_count = sum(
            1 for f in state.fitnesses if f.composite == 0.0
        )
        assert zero_count >= 1

    def test_population_and_fitnesses_correspond_after_loop(self, fixture_corpus: Path):
        """C1 — `EvolutionState.fitnesses[i]` must rank `population[i]`.
        Specifically: after a plateau exit, the returned population is
        the actually-evaluated last generation, NOT next_pop."""
        seed = _rule("r1", pattern=r"\bdanger\b")
        state = evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=10,
            population_size=4,
            plateau_gens=2,
            rng=random.Random(0),
        )
        assert len(state.population) == len(state.fitnesses)
        # Best in returned slice should match best_fitness.
        assert max(f.composite for f in state.fitnesses) >= state.best_fitness.composite - 1e-6

    def test_crossover_child_ids_unique_across_generations(
        self, fixture_corpus: Path,
    ):
        """C2 — crossover children must not all share parent_a.id, so
        post-evolution populations have diverse identifiers."""
        seed = _rule("r1", pattern=r"\bdanger\b")
        # Force-disable plateau by setting plateau_gens > max so we
        # actually hit max_generations and population evolves several
        # times. Composite-perfect seeds will plateau — use a less
        # perfect seed that lets evolution diversify.
        state = evolve(
            [_rule("seed", pattern=r"danger")],
            fixtures_dir=str(fixture_corpus),
            max_generations=4,
            population_size=8,
            plateau_gens=999,
            rng=random.Random(1),
        )
        ids = [r.id for r in state.population]
        # Allow some duplication via elitism / mutation no-ops, but
        # crossover should have produced at least one unique-suffixed
        # id across multiple generations of crossover events.
        unique_ids = set(ids)
        assert len(unique_ids) >= 2, ids

    def test_plateau_gens_one_does_not_terminate_immediately(
        self, fixture_corpus: Path,
    ):
        """I1 — `plateau_gens=1` must not cause the loop to bail after
        a single generation. A single-element history window has zero
        variance by definition; the guard should require ≥2 entries."""
        seed = _rule("r1", pattern=r"\bdanger\b")
        state = evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=4,
            population_size=4,
            plateau_gens=1,
            rng=random.Random(0),
        )
        assert state.generations_run >= 2, state

    def test_evolution_can_recover_overly_widened_seed(self, fixture_corpus: Path):
        """An anchorless seed has lower precision; the evolver should be
        able to mutate it back toward a precise pattern over a few
        generations."""
        seed = _rule("r1", pattern="danger")  # no anchors
        baseline = evaluate_rule(seed, fixtures_dir=str(fixture_corpus))
        state = evolve(
            [seed],
            fixtures_dir=str(fixture_corpus),
            max_generations=5,
            population_size=8,
            plateau_gens=10,
            rng=random.Random(0),
        )
        assert state.best_fitness.composite >= baseline.composite
