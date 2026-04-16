"""Rule-bench configuration: per-rule overrides + pack activation.

A ``RuleBenchConfig`` describes one optimization candidate. The harness
applies it to a *clone* of the base ``RuleRegistry`` so the original is
never mutated — this lets repeated evaluations and parallel candidates
coexist without leaking state.

Stage-1 (tune-only) candidates only touch numeric/boolean fields:
``enabled``, ``confidence``, ``severity``. Stage-2 (templates) populates
``extra_rules`` with synthesized YAML — those are layered onto the cloned
registry the same way overrides are.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from attocode.code_intel.rules.loader import _parse_yaml_rule
from attocode.code_intel.rules.model import (
    RuleSeverity,
    RuleSource,
    UnifiedRule,
)
from attocode.code_intel.rules.registry import RuleRegistry

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {s.value for s in RuleSeverity}


@dataclass(slots=True)
class RuleOverride:
    """Per-rule tunable overrides. ``None`` fields inherit from the base rule."""

    rule_id: str  # qualified id (e.g. "python/py-mutable-default-arg")
    enabled: bool | None = None
    confidence_override: float | None = None
    severity_override: str | None = None  # RuleSeverity value

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"rule_id": self.rule_id}
        if self.enabled is not None:
            out["enabled"] = self.enabled
        if self.confidence_override is not None:
            out["confidence_override"] = round(self.confidence_override, 4)
        if self.severity_override is not None:
            out["severity_override"] = self.severity_override
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleOverride:
        return cls(
            rule_id=str(data["rule_id"]),
            enabled=data.get("enabled"),
            confidence_override=data.get("confidence_override"),
            severity_override=data.get("severity_override"),
        )


@dataclass(slots=True)
class RuleBenchConfig:
    """One rule-bench optimization candidate."""

    rule_overrides: dict[str, RuleOverride] = field(default_factory=dict)
    pack_activation: dict[str, bool] = field(default_factory=dict)
    global_min_confidence: float = 0.5
    enabled_languages: list[str] = field(default_factory=list)
    extra_rules: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def default(cls) -> RuleBenchConfig:
        return cls()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        errors: list[str] = []
        for ov in self.rule_overrides.values():
            if ov.confidence_override is not None and not (
                0.0 <= ov.confidence_override <= 1.0
            ):
                errors.append(
                    f"override {ov.rule_id}: confidence_override out of [0,1]: "
                    f"{ov.confidence_override}"
                )
            if (
                ov.severity_override is not None
                and ov.severity_override not in _VALID_SEVERITIES
            ):
                errors.append(
                    f"override {ov.rule_id}: invalid severity_override "
                    f"{ov.severity_override!r}"
                )
        if not (0.0 <= self.global_min_confidence <= 0.95):
            errors.append(
                f"global_min_confidence out of [0,0.95]: {self.global_min_confidence}"
            )
        return errors

    # ------------------------------------------------------------------
    # Apply to registry — never mutates caller's registry
    # ------------------------------------------------------------------

    def apply_to_registry(self, base_registry: RuleRegistry) -> RuleRegistry:
        """Return a fresh ``RuleRegistry`` with overrides + extras applied.

        The base registry is read-only after construction in this codebase,
        but we still clone defensively so retries / parallel evaluations
        never share mutable state.
        """
        cloned = RuleRegistry()

        for rule in base_registry.all_rules(enabled_only=False):
            # Pack-level toggle wins over per-rule (a deactivated pack
            # disables every rule it ships).
            pack_enabled = self.pack_activation.get(rule.pack)
            if pack_enabled is False:
                replacement = dataclasses.replace(rule, enabled=False)
                cloned.register(replacement)
                continue

            # Per-rule override (qualified id first, then bare id fallback)
            override = (
                self.rule_overrides.get(rule.qualified_id)
                or self.rule_overrides.get(rule.id)
            )
            if override is None:
                cloned.register(rule)
                continue

            new_rule = dataclasses.replace(
                rule,
                enabled=rule.enabled if override.enabled is None else override.enabled,
                confidence=(
                    rule.confidence
                    if override.confidence_override is None
                    else override.confidence_override
                ),
                severity=(
                    rule.severity
                    if override.severity_override is None
                    else RuleSeverity(override.severity_override)
                ),
            )
            cloned.register(new_rule)

        # Layer in stage-2 synthesized rules (parsed from raw dicts so the
        # config can be JSON/YAML-serialized end to end).
        for raw in self.extra_rules:
            try:
                rule = _parse_yaml_rule(
                    raw,
                    source=RuleSource.PACK,
                    pack=str(raw.get("pack", "rule_bench_synth")),
                    origin="rule_bench.extra_rules",
                )
            except Exception as exc:
                logger.warning("Skipping invalid extra_rule: %s", exc)
                continue
            if rule is not None:
                cloned.register(rule)

        return cloned

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_overrides": [ov.to_dict() for ov in self.rule_overrides.values()],
            "pack_activation": dict(self.pack_activation),
            "global_min_confidence": round(self.global_min_confidence, 4),
            "enabled_languages": list(self.enabled_languages),
            "extra_rules": list(self.extra_rules),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleBenchConfig:
        overrides_raw = data.get("rule_overrides") or []
        if isinstance(overrides_raw, dict):
            # Tolerate legacy/alt format: {rule_id: override_dict}
            overrides_raw = [
                {"rule_id": rid, **(payload or {})}
                for rid, payload in overrides_raw.items()
            ]
        rule_overrides = {
            str(ov["rule_id"]): RuleOverride.from_dict(ov) for ov in overrides_raw
        }
        return cls(
            rule_overrides=rule_overrides,
            pack_activation={
                str(k): bool(v) for k, v in (data.get("pack_activation") or {}).items()
            },
            global_min_confidence=float(data.get("global_min_confidence", 0.5)),
            enabled_languages=list(data.get("enabled_languages") or []),
            extra_rules=list(data.get("extra_rules") or []),
        )

    def save_yaml(self, path: str) -> None:
        import yaml

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=True)

    @classmethod
    def load_yaml(cls, path: str) -> RuleBenchConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)


def merge_overrides(base: RuleBenchConfig, *patches: RuleOverride) -> RuleBenchConfig:
    """Helper: produce a new config with additional overrides applied.

    Lets the proposer compose a candidate by stacking small mutations on
    top of the current best instead of rebuilding from scratch.
    """
    new = RuleBenchConfig.from_dict(base.to_dict())
    for patch in patches:
        new.rule_overrides[patch.rule_id] = patch
    return new
