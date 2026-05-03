"""Evolutionary rule optimisation (A8).

Genetic-programming-style search over rule space. The evolutionary loop
takes a seed rule (or population) plus a labelled fixture directory and
iteratively mutates / crosses over candidates, keeping the elite under a
fitness function (precision + recall + speed). Designed as the
optimisation layer that pairs with :mod:`rules.synthesis` (which
produces seeds) and :mod:`rules.testing` (which provides ground truth
via inline annotations).

This v1 focuses on regex Tier-1 rules. Structural / composite mutation
operators are deliberately scoped out — they need richer AST surgery.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from attocode.code_intel.rules.model import (
    RuleSeverity,
    RuleSource,
    UnifiedRule,
)
from attocode.code_intel.rules.testing import RuleTestRunner

logger = logging.getLogger(__name__)


# Severity ordering used by SEVERITY_UP / SEVERITY_DOWN mutations.
_SEVERITY_LADDER: list[RuleSeverity] = [
    RuleSeverity.INFO,
    RuleSeverity.LOW,
    RuleSeverity.MEDIUM,
    RuleSeverity.HIGH,
    RuleSeverity.CRITICAL,
]


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Fitness:
    """Per-rule fitness signal sourced from RuleTestRunner + timing.

    Composite is a weighted blend; defaults match the roadmap brief
    ("weighted combination of precision, recall, CASTLE score, and
    execution speed"). We omit CASTLE here since it isn't wired yet —
    speed bonus and recall fill that slot.
    """

    precision: float
    recall: float
    f1: float
    speed_ms: float
    composite: float


def _compute_composite(
    *,
    precision: float,
    recall: float,
    speed_ms: float,
    speed_budget_ms: float = 50.0,
) -> float:
    """Weighted blend: 50% precision + 35% recall + 15% speed bonus.

    Speed bonus is ``max(0, 1 - speed_ms/budget)`` so anything under the
    budget gets a positive contribution; over-budget rules drop to zero.
    """
    speed_bonus = max(0.0, 1.0 - speed_ms / speed_budget_ms)
    return 0.50 * precision + 0.35 * recall + 0.15 * speed_bonus


def evaluate_rule(
    rule: UnifiedRule,
    *,
    fixtures_dir: str,
    project_dir: str = "",
) -> Fitness:
    """Run ``rule`` against the fixture corpus and compute fitness.

    Annotations on fixture lines are ``# expect: <rule-id>`` (TP target)
    and ``# ok: <rule-id>`` (negative — must NOT fire).
    """
    runner = RuleTestRunner([rule], project_dir=project_dir or fixtures_dir)
    t0 = time.monotonic()
    suite = runner.run_test_suite(fixtures_dir)
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    tp = sum(
        len([a for a in fr.passed if a.kind == "expect"])
        for fr in suite.file_results
    )
    fn = sum(
        sum(1 for ann, _msg in fr.failed if ann.kind == "expect")
        for fr in suite.file_results
    )
    fp = sum(len(fr.false_positives) for fr in suite.file_results)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    composite = _compute_composite(
        precision=precision, recall=recall, speed_ms=elapsed_ms,
    )
    return Fitness(
        precision=precision,
        recall=recall,
        f1=round(f1, 4),
        speed_ms=round(elapsed_ms, 3),
        composite=round(composite, 4),
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class MutationOperator(StrEnum):
    """Atomic mutations applied to a rule. None of them invent new
    pattern primitives — they only loosen / tighten what's already
    there. Composing many small mutations across generations is what
    gives the search its reach."""

    REGEX_WIDEN = "regex_widen"
    REGEX_NARROW = "regex_narrow"
    SEVERITY_UP = "severity_up"
    SEVERITY_DOWN = "severity_down"
    CONFIDENCE_UP = "confidence_up"
    CONFIDENCE_DOWN = "confidence_down"


def _widen_regex(pattern_src: str) -> str | None:
    """Drop one ``\\b`` anchor (the most common form of over-tightening)."""
    if r"\b" in pattern_src:
        return pattern_src.replace(r"\b", "", 1)
    return None


def _narrow_regex(pattern_src: str) -> str | None:
    """Add ``\\b`` boundaries on both sides if the pattern has no anchors."""
    if pattern_src.startswith(r"\b") and pattern_src.endswith(r"\b"):
        return None  # already maximally anchored
    out = pattern_src
    if not out.startswith(r"\b"):
        out = r"\b" + out
    if not out.endswith(r"\b"):
        out = out + r"\b"
    return out if out != pattern_src else None


def _shift_severity(rule: UnifiedRule, *, direction: int) -> RuleSeverity | None:
    try:
        idx = _SEVERITY_LADDER.index(rule.severity)
    except ValueError:
        return None
    new_idx = idx + direction
    if 0 <= new_idx < len(_SEVERITY_LADDER) and new_idx != idx:
        return _SEVERITY_LADDER[new_idx]
    return None


def mutate(
    rule: UnifiedRule,
    operator: MutationOperator,
    *,
    rng: random.Random | None = None,
    confidence_step: float = 0.1,
) -> UnifiedRule | None:
    """Apply ``operator`` to ``rule``. Returns the mutated copy or
    ``None`` when the mutation can't apply (e.g. widen on an already
    anchorless pattern). The rule's id is preserved — the caller is
    expected to re-id during crossover."""
    rng = rng or random.Random()

    if operator in (MutationOperator.REGEX_WIDEN, MutationOperator.REGEX_NARROW):
        if rule.pattern is None:
            return None
        new_src: str | None
        if operator == MutationOperator.REGEX_WIDEN:
            new_src = _widen_regex(rule.pattern.pattern)
        else:
            new_src = _narrow_regex(rule.pattern.pattern)
        if new_src is None:
            return None
        try:
            new_re = re.compile(new_src)
        except re.error:
            return None
        return replace(rule, pattern=new_re)

    if operator == MutationOperator.SEVERITY_UP:
        new_sev = _shift_severity(rule, direction=+1)
        if new_sev is None:
            return None
        return replace(rule, severity=new_sev)

    if operator == MutationOperator.SEVERITY_DOWN:
        new_sev = _shift_severity(rule, direction=-1)
        if new_sev is None:
            return None
        return replace(rule, severity=new_sev)

    if operator == MutationOperator.CONFIDENCE_UP:
        new_conf = min(1.0, round(rule.confidence + confidence_step, 4))
        if new_conf == rule.confidence:
            return None
        return replace(rule, confidence=new_conf)

    if operator == MutationOperator.CONFIDENCE_DOWN:
        new_conf = max(0.0, round(rule.confidence - confidence_step, 4))
        if new_conf == rule.confidence:
            return None
        return replace(rule, confidence=new_conf)

    return None


# ---------------------------------------------------------------------------
# Crossover
# ---------------------------------------------------------------------------


def crossover(
    parent_a: UnifiedRule,
    parent_b: UnifiedRule,
    *,
    rng: random.Random | None = None,
    child_id: str = "",
) -> UnifiedRule:
    """Combine two parents into a child rule. We splice scalar fields
    50/50 and prefer parent A's pattern (the regex is the most
    structural piece — random splicing across regex strings tends to
    produce invalid syntax)."""
    rng = rng or random.Random()
    pick_a = lambda: rng.random() < 0.5  # noqa: E731 — local lambda
    return UnifiedRule(
        id=child_id or f"{parent_a.id}-x-{parent_b.id}",
        name=parent_a.name if pick_a() else parent_b.name,
        description=parent_a.description if pick_a() else parent_b.description,
        severity=parent_a.severity if pick_a() else parent_b.severity,
        category=parent_a.category if pick_a() else parent_b.category,
        languages=list(parent_a.languages),  # languages stay with A's pattern
        pattern=parent_a.pattern,
        structural_pattern=parent_a.structural_pattern,
        cwe=parent_a.cwe if pick_a() else parent_b.cwe,
        tags=list(set(parent_a.tags) | set(parent_b.tags)),
        source=RuleSource.USER,
        tier=parent_a.tier,
        confidence=round((parent_a.confidence + parent_b.confidence) / 2, 4),
        recommendation=parent_a.recommendation if pick_a() else parent_b.recommendation,
        explanation=parent_a.explanation if pick_a() else parent_b.explanation,
        pack=parent_a.pack,
    )


# ---------------------------------------------------------------------------
# Selection + evolution loop
# ---------------------------------------------------------------------------


def tournament_select(
    ranked: list[tuple[UnifiedRule, Fitness]],
    *,
    k: int = 3,
    rng: random.Random | None = None,
) -> UnifiedRule:
    """Pick ``k`` random candidates and return the highest-composite one."""
    rng = rng or random.Random()
    if not ranked:
        raise ValueError("cannot select from empty population")
    sample = rng.sample(ranked, min(k, len(ranked)))
    sample.sort(key=lambda x: -x[1].composite)
    return sample[0][0]


@dataclass(slots=True)
class EvolutionState:
    """Snapshot of an evolution run after termination."""

    population: list[UnifiedRule]
    fitnesses: list[Fitness]
    best_rule: UnifiedRule
    best_fitness: Fitness
    generations_run: int
    stopped_reason: str  # "max_generations" | "plateau"
    history: list[float] = field(default_factory=list)  # best composite per gen


def evolve(
    seeds: list[UnifiedRule],
    *,
    fixtures_dir: str,
    project_dir: str = "",
    max_generations: int = 50,
    population_size: int = 12,
    elite_frac: float = 0.1,
    plateau_gens: int = 5,
    plateau_eps: float = 1e-3,
    rng: random.Random | None = None,
    log_path: str = "",
) -> EvolutionState:
    """Run the evolutionary loop. Caller supplies one or more seed rules;
    we pad/trim to ``population_size`` via mutation. ``fixtures_dir`` is
    a directory of inline-annotated source files (same format consumed
    by the ``test_rules`` MCP tool)."""
    if not seeds:
        raise ValueError("evolve() requires at least one seed rule")
    if max_generations < 1:
        raise ValueError(
            f"evolve() requires max_generations >= 1, got {max_generations}"
        )

    rng = rng or random.Random(42)

    # Dedupe seeds by id — duplicates would just burn fitness evaluations
    # on identical individuals before any mutation can diverge them.
    deduped: dict[str, UnifiedRule] = {}
    for s in seeds:
        deduped.setdefault(s.id, s)
    seeds = list(deduped.values())

    # Initialise population: seed + mutated copies until we hit the size.
    population: list[UnifiedRule] = list(seeds)[:population_size]
    operators = list(MutationOperator)
    while len(population) < population_size:
        parent = rng.choice(seeds)
        op = rng.choice(operators)
        child = mutate(parent, op, rng=rng)
        population.append(child or parent)

    elite_count = max(1, int(population_size * elite_frac))
    history: list[float] = []
    audit_log: list[dict] = []

    best_rule = population[0]
    best_fitness = Fitness(0.0, 0.0, 0.0, 0.0, 0.0)
    stopped_reason = "max_generations"
    generations_run = 0
    # Snapshot the last generation's evaluated population so the final
    # ``EvolutionState`` carries fitnesses that actually correspond to
    # the rules we report — and so we don't pay for re-evaluation after
    # the loop ends. Updated each generation.
    last_evaluated_rules: list[UnifiedRule] = list(population)
    last_evaluated_fits: list[Fitness] = []

    def _safe_evaluate(rule: UnifiedRule) -> Fitness:
        """Defensive wrapper — RuleTestRunner can raise on a malformed
        fixture or a tree-sitter crash. Surface the failure as a
        zero-fitness candidate so the loop continues and the audit log
        captures the broken individual instead of crashing the run."""
        try:
            return evaluate_rule(
                rule, fixtures_dir=fixtures_dir, project_dir=project_dir,
            )
        except Exception as exc:  # noqa: BLE001 — we want all errors caught
            logger.warning(
                "evaluate_rule failed for %s: %s", rule.id, exc,
            )
            return Fitness(0.0, 0.0, 0.0, 0.0, 0.0)

    for gen in range(max_generations):
        generations_run = gen + 1
        fitnesses = [_safe_evaluate(r) for r in population]
        ranked = sorted(
            zip(population, fitnesses, strict=True),
            key=lambda x: -x[1].composite,
        )
        last_evaluated_rules = [r for r, _ in ranked]
        last_evaluated_fits = [f for _, f in ranked]
        gen_best_rule, gen_best_fit = ranked[0]
        history.append(gen_best_fit.composite)

        audit_log.append({
            "generation": gen,
            "best_id": gen_best_rule.id,
            "best_pattern": (
                gen_best_rule.pattern.pattern if gen_best_rule.pattern else ""
            ),
            "best_composite": gen_best_fit.composite,
            "best_precision": gen_best_fit.precision,
            "best_recall": gen_best_fit.recall,
            "population_mean_composite": round(
                sum(f.composite for f in fitnesses) / len(fitnesses), 4,
            ),
        })

        if gen_best_fit.composite > best_fitness.composite:
            best_rule = gen_best_rule
            best_fitness = gen_best_fit

        # Plateau check: best composite hasn't budged across
        # ``plateau_gens`` consecutive generations. Require ≥2 entries
        # in history so a single-point window can't trigger the stop.
        if len(history) >= max(2, plateau_gens):
            recent = history[-plateau_gens:]
            if max(recent) - min(recent) < plateau_eps:
                stopped_reason = "plateau"
                break

        # Build next generation: elite + tournament-selected children.
        # Crossover children get unique IDs (parent_a-x-parent_b-gN) so
        # the population keeps diverse identifiers across generations
        # — without this every child collapses onto parent_a.id.
        next_pop: list[UnifiedRule] = [r for r, _ in ranked[:elite_count]]
        child_idx = 0
        while len(next_pop) < population_size:
            parent_a = tournament_select(ranked, k=3, rng=rng)
            if rng.random() < 0.5 and len(ranked) > 1:
                parent_b = tournament_select(ranked, k=3, rng=rng)
                child_id = f"{parent_a.id}-x-{parent_b.id}-g{gen}-{child_idx}"
                child = crossover(parent_a, parent_b, rng=rng, child_id=child_id)
            else:
                op = rng.choice(operators)
                child = mutate(parent_a, op, rng=rng) or parent_a
            next_pop.append(child)
            child_idx += 1
        population = next_pop

    if log_path:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(log_path).open("a", encoding="utf-8") as fh:
                for entry in audit_log:
                    fh.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.warning("Failed to persist evolution log to %s: %s", log_path, exc)

    return EvolutionState(
        population=last_evaluated_rules,
        fitnesses=last_evaluated_fits,
        best_rule=best_rule,
        best_fitness=best_fitness,
        generations_run=generations_run,
        stopped_reason=stopped_reason,
        history=history,
    )
