"""Rule-bench proposers (stage 1 sweep + stage 2 template).

Stage 1 (``propose_sweep_rule_overrides``) mutates numeric/boolean rule
fields — enabled, confidence, severity. Deterministic per-iteration seed.

Stage 2 (``propose_llm_rule_overrides``) asks an LLM to fill rule
templates, validates each instance, and runs the fixture-coverage gate
before adding survivors to the candidate's ``extra_rules``.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Any

import yaml

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
    current_best: RuleBenchConfig,
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int,
    iteration: int,  # noqa: ARG001 - signature parity
) -> list[tuple[RuleBenchConfig, str]]:
    """Stage-2 LLM proposer — fills templates and gates against the corpus.

    Calls Claude with the template manifest and worst-performing rules,
    parses returned slot fillings, validates each, runs the
    fixture-coverage gate, and packages survivors as new candidates.

    Returns an empty list when no LLM API key is configured or when
    every proposed candidate fails validation/gating.
    """
    try:
        from eval.meta_harness._llm_client import call_llm, load_env
    except Exception:  # pragma: no cover - import sanity
        return []

    try:
        load_env()
    except Exception:
        return []

    from eval.meta_harness.rule_bench.template_engine import (
        gate_against_corpus,
        load_templates,
        substitute_slots,
        validate_template_instance,
    )

    templates = load_templates()
    if not templates:
        return []

    prompt = _build_template_prompt(
        templates, current_best, eval_metadata, history, n_candidates,
    )
    try:
        text = call_llm(prompt)
    except Exception as exc:
        # No key, network failure, etc. — runner falls back to sweep.
        logging.getLogger(__name__).debug("LLM template call failed: %s", exc)
        return []

    proposals = _parse_llm_template_response(text)

    # Build a tiny in-memory corpus snapshot for the gate. We re-read the
    # full corpus rather than relying on cached state to keep the gate
    # decoupled from the evaluator instance.
    from eval.meta_harness.rule_bench.corpus import CorpusLoader

    corpus = list(CorpusLoader().iter_samples())

    candidates: list[tuple[RuleBenchConfig, str]] = []
    for proposal in proposals[:n_candidates]:
        template_id = proposal.get("template_id")
        slots = proposal.get("slots") or {}
        hypothesis = proposal.get("hypothesis", "")

        template = templates.get(template_id)
        if template is None:
            continue

        errors = validate_template_instance(template, slots)
        if errors:
            logging.getLogger(__name__).debug(
                "Template %s failed validation: %s", template_id, errors,
            )
            continue

        try:
            rule_dict = substitute_slots(template, slots)
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "Template substitution failed for %s: %s", template_id, exc,
            )
            continue

        accepted, reason = gate_against_corpus(rule_dict, corpus)
        if not accepted:
            continue

        new_cfg = RuleBenchConfig(
            rule_overrides=dict(current_best.rule_overrides),
            pack_activation=dict(current_best.pack_activation),
            global_min_confidence=current_best.global_min_confidence,
            enabled_languages=list(current_best.enabled_languages),
            extra_rules=[*current_best.extra_rules, rule_dict],
        )
        full_hypothesis = (
            f"template:{template_id} ({reason})" + (
                f" — {hypothesis}" if hypothesis else ""
            )
        )
        candidates.append((new_cfg, full_hypothesis))

    return candidates


def _build_template_prompt(
    templates: dict,
    current_best: RuleBenchConfig,  # noqa: ARG001 - reserved for future signal
    eval_metadata: dict[str, Any],
    history: list[dict[str, Any]],  # noqa: ARG001
    n_candidates: int,
) -> str:
    """Build the LLM prompt — template manifest + worst-performing rules."""
    rule_bench = (eval_metadata or {}).get("rule_bench") or {}
    per_rule = rule_bench.get("per_rule") or {}
    worst = sorted(
        per_rule.values(),
        key=lambda r: r.get("weighted_f1", 0.0),
    )[:3]

    template_blocks: list[str] = []
    for tid, t in templates.items():
        slot_lines = "\n".join(
            f"  - {s.name} ({s.kind}): {s.description}" for s in t.slots
        )
        template_blocks.append(
            f"### {tid}\n{t.description}\nSlots:\n{slot_lines}"
        )

    worst_block = "\n".join(
        f"  - {r.get('rule_id')}: F1={r.get('weighted_f1', 0):.3f} "
        f"(tp={r.get('tp', 0)} fp={r.get('fp', 0)} fn={r.get('fn', 0)})"
        for r in worst
    ) or "  (no per-rule data yet)"

    return (
        "You are extending a rule-bench harness with new rules.\n\n"
        f"Worst-performing rules from the last evaluation:\n{worst_block}\n\n"
        f"Available templates:\n\n" + "\n\n".join(template_blocks) + "\n\n"
        f"Propose up to {n_candidates} new rules by filling templates. "
        f"For each, output a fenced YAML block:\n\n"
        "```yaml\n"
        "template_id: <one-of-the-templates>\n"
        "hypothesis: <why this rule helps>\n"
        "slots:\n"
        "  language: <python|go|...>\n"
        "  <slot>: <value>\n"
        "  ...\n"
        "```\n"
    )


def _parse_llm_template_response(text: str) -> list[dict[str, Any]]:
    """Extract template-instance dicts from fenced YAML blocks in *text*."""
    pattern = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
    out: list[dict[str, Any]] = []
    for block in pattern.findall(text):
        try:
            data = yaml.safe_load(block)
        except Exception:
            continue
        if isinstance(data, dict) and "template_id" in data:
            out.append(data)
    return out


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
