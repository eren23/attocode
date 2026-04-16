"""Stage-1 sweep proposer for the rule-bench harness.

Stage 1 only mutates numeric/boolean rule fields (enabled, confidence,
severity). Stage-2 template generation lands in Step 9.

The proposer is intentionally simple: pick 1-3 random rules from the
current best config's registry view, perturb each one, package as a new
``RuleBenchConfig``. Deterministic per-iteration seed for reproducibility.
"""

from __future__ import annotations

import random
from typing import Any

from attocode.code_intel.rules.model import RuleSeverity

from eval.meta_harness.rule_bench.config import (
    RuleBenchConfig,
    RuleOverride,
)

_SEVERITY_LADDER: list[str] = [
    RuleSeverity.CRITICAL.value,
    RuleSeverity.HIGH.value,
    RuleSeverity.MEDIUM.value,
    RuleSeverity.LOW.value,
    RuleSeverity.INFO.value,
]


def propose_sweep_rule_overrides(
    current_best: RuleBenchConfig,
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],  # noqa: ARG001 - signature parity
    n_candidates: int,
    iteration: int,
) -> list[tuple[RuleBenchConfig, str]]:
    """Generate ``n_candidates`` perturbations of ``current_best``.

    Picks rule ids from the most recent eval's per-rule report (so we
    target rules with actual signal). Falls back to existing override
    keys if the report is unavailable (e.g. before the first evaluation).
    """
    rng = random.Random(42 + iteration)

    available_rule_ids = _candidate_rule_ids(current_best, eval_metadata)
    if not available_rule_ids:
        # Nothing to perturb — return empty so the runner moves on.
        return []

    candidates: list[tuple[RuleBenchConfig, str]] = []
    for _ in range(n_candidates):
        n_changes = rng.randint(1, min(3, len(available_rule_ids)))
        chosen = rng.sample(available_rule_ids, n_changes)

        new_overrides = dict(current_best.rule_overrides)
        changes: list[str] = []
        for rule_id in chosen:
            existing = new_overrides.get(rule_id) or RuleOverride(rule_id=rule_id)
            mutation = rng.choice(["toggle_enabled", "bump_confidence", "shift_severity"])

            if mutation == "toggle_enabled":
                # Bias toward enabling — disabled rules mean lost recall.
                new_enabled = existing.enabled is False  # only flip if currently False
                if existing.enabled is None:
                    new_enabled = True if rng.random() > 0.3 else False
                updated = RuleOverride(
                    rule_id=rule_id,
                    enabled=new_enabled,
                    confidence_override=existing.confidence_override,
                    severity_override=existing.severity_override,
                )
                changes.append(f"{rule_id}.enabled={new_enabled}")

            elif mutation == "bump_confidence":
                base = existing.confidence_override
                if base is None:
                    base = 0.7  # Roughly the most common default in shipped packs
                shift = rng.gauss(0.0, 0.15)
                new_conf = max(0.0, min(1.0, base + shift))
                updated = RuleOverride(
                    rule_id=rule_id,
                    enabled=existing.enabled,
                    confidence_override=round(new_conf, 3),
                    severity_override=existing.severity_override,
                )
                changes.append(f"{rule_id}.confidence={new_conf:.3f}")

            else:  # shift_severity
                current_sev = existing.severity_override
                if current_sev not in _SEVERITY_LADDER:
                    current_sev = "medium"
                idx = _SEVERITY_LADDER.index(current_sev)
                # Move ±1 step on the ladder, clamped.
                step = rng.choice([-1, 1])
                new_idx = max(0, min(len(_SEVERITY_LADDER) - 1, idx + step))
                new_sev = _SEVERITY_LADDER[new_idx]
                updated = RuleOverride(
                    rule_id=rule_id,
                    enabled=existing.enabled,
                    confidence_override=existing.confidence_override,
                    severity_override=new_sev,
                )
                changes.append(f"{rule_id}.severity={new_sev}")

            new_overrides[rule_id] = updated

        new_cfg = RuleBenchConfig(
            rule_overrides=new_overrides,
            pack_activation=dict(current_best.pack_activation),
            global_min_confidence=current_best.global_min_confidence,
            enabled_languages=list(current_best.enabled_languages),
            extra_rules=list(current_best.extra_rules),
        )
        hypothesis = f"sweep: {', '.join(changes)}"
        candidates.append((new_cfg, hypothesis))

    return candidates


def propose_llm_rule_overrides(
    current_best: RuleBenchConfig,  # noqa: ARG001 - signature parity
    eval_metadata: dict[str, Any],  # noqa: ARG001
    history: list[dict[str, Any]],  # noqa: ARG001
    n_candidates: int,  # noqa: ARG001
    iteration: int,  # noqa: ARG001
) -> list[tuple[RuleBenchConfig, str]]:
    """Stage-2 LLM proposer placeholder — wired in Step 9.

    Returns an empty list for now so the runner falls back to sweep mode.
    """
    return []


def _candidate_rule_ids(
    current_best: RuleBenchConfig,
    eval_metadata: dict[str, Any],
) -> list[str]:
    """Pick rule ids worth mutating.

    Prefers the per-rule report from the last evaluation so we target
    rules with actual signal. Falls back to the override keys we already
    know about.
    """
    rule_bench = (eval_metadata or {}).get("rule_bench") or {}
    per_rule = rule_bench.get("per_rule") or {}
    if isinstance(per_rule, dict) and per_rule:
        # Surface rules with at least one TP/FP/FN — those are the ones
        # the corpus actually exercises; tuning anything else is noise.
        live = [
            rid for rid, score in per_rule.items()
            if (score.get("tp", 0) + score.get("fp", 0) + score.get("fn", 0)) > 0
        ]
        if live:
            return live
        return list(per_rule.keys())

    # Fall back to override keys (first iteration before any eval ran)
    if current_best.rule_overrides:
        return list(current_best.rule_overrides.keys())

    return []
