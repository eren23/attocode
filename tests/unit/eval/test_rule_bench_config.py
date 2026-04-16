"""Unit tests for ``RuleBenchConfig`` + ``RuleOverride`` + ``apply_to_registry``."""

from __future__ import annotations

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

from eval.meta_harness.rule_bench.config import (
    RuleBenchConfig,
    RuleOverride,
    merge_overrides,
)


def _stub_rule(
    rid: str = "py-foo",
    *,
    pack: str = "python",
    severity: RuleSeverity = RuleSeverity.MEDIUM,
    confidence: float = 0.8,
    enabled: bool = True,
) -> UnifiedRule:
    return UnifiedRule(
        id=rid,
        name=rid,
        description="stub",
        severity=severity,
        category=RuleCategory.CORRECTNESS,
        languages=["python"],
        pattern=re.compile("foo"),
        source=RuleSource.PACK,
        pack=pack,
        confidence=confidence,
        enabled=enabled,
    )


@pytest.fixture()
def base_registry() -> RuleRegistry:
    reg = RuleRegistry()
    reg.register(_stub_rule("py-foo"))
    reg.register(_stub_rule("py-bar", severity=RuleSeverity.HIGH))
    reg.register(_stub_rule("go-baz", pack="go"))
    return reg


class TestRuleBenchConfigDefaults:
    def test_default_validates_clean(self) -> None:
        assert RuleBenchConfig.default().validate() == []

    def test_apply_default_returns_clone_with_same_rules(
        self, base_registry: RuleRegistry,
    ) -> None:
        cfg = RuleBenchConfig.default()
        cloned = cfg.apply_to_registry(base_registry)
        assert cloned.count == base_registry.count
        # Different object identities
        assert cloned is not base_registry


class TestValidate:
    def test_invalid_confidence_caught(self) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "py-foo": RuleOverride(rule_id="py-foo", confidence_override=1.5),
            },
        )
        errors = cfg.validate()
        assert any("confidence_override" in e for e in errors)

    def test_invalid_severity_caught(self) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "py-foo": RuleOverride(rule_id="py-foo", severity_override="apocalyptic"),
            },
        )
        errors = cfg.validate()
        assert any("severity_override" in e for e in errors)

    def test_invalid_min_confidence_caught(self) -> None:
        cfg = RuleBenchConfig(global_min_confidence=1.2)
        errors = cfg.validate()
        assert any("global_min_confidence" in e for e in errors)


class TestApplyToRegistry:
    def test_disabling_via_override(self, base_registry: RuleRegistry) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "python/py-foo": RuleOverride(rule_id="python/py-foo", enabled=False),
            },
        )
        cloned = cfg.apply_to_registry(base_registry)
        rule = cloned.get("python/py-foo")
        assert rule is not None
        assert rule.enabled is False

    def test_disabling_via_bare_id(self, base_registry: RuleRegistry) -> None:
        # Override keyed by bare id should still match a pack-qualified rule
        cfg = RuleBenchConfig(
            rule_overrides={
                "py-foo": RuleOverride(rule_id="py-foo", enabled=False),
            },
        )
        cloned = cfg.apply_to_registry(base_registry)
        rule = cloned.get("python/py-foo")
        assert rule is not None
        assert rule.enabled is False

    def test_confidence_override_applied(self, base_registry: RuleRegistry) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "python/py-foo": RuleOverride(
                    rule_id="python/py-foo", confidence_override=0.42,
                ),
            },
        )
        cloned = cfg.apply_to_registry(base_registry)
        rule = cloned.get("python/py-foo")
        assert rule is not None
        assert rule.confidence == pytest.approx(0.42)

    def test_severity_override_applied(self, base_registry: RuleRegistry) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "python/py-foo": RuleOverride(
                    rule_id="python/py-foo", severity_override="critical",
                ),
            },
        )
        cloned = cfg.apply_to_registry(base_registry)
        rule = cloned.get("python/py-foo")
        assert rule is not None
        assert rule.severity == RuleSeverity.CRITICAL

    def test_pack_deactivation_disables_all_pack_rules(
        self, base_registry: RuleRegistry,
    ) -> None:
        cfg = RuleBenchConfig(pack_activation={"python": False})
        cloned = cfg.apply_to_registry(base_registry)
        py_foo = cloned.get("python/py-foo")
        py_bar = cloned.get("python/py-bar")
        go_baz = cloned.get("go/go-baz")
        assert py_foo is not None and py_foo.enabled is False
        assert py_bar is not None and py_bar.enabled is False
        assert go_baz is not None and go_baz.enabled is True  # untouched

    def test_apply_does_not_mutate_caller(self, base_registry: RuleRegistry) -> None:
        original = base_registry.get("python/py-foo")
        assert original is not None
        original_confidence = original.confidence

        cfg = RuleBenchConfig(
            rule_overrides={
                "python/py-foo": RuleOverride(
                    rule_id="python/py-foo", confidence_override=0.1,
                ),
            },
        )
        cfg.apply_to_registry(base_registry)

        # Caller's registry must be unchanged
        still_original = base_registry.get("python/py-foo")
        assert still_original is not None
        assert still_original.confidence == original_confidence


class TestSerialization:
    def test_round_trip_yaml(self, tmp_path: Path) -> None:
        cfg = RuleBenchConfig(
            rule_overrides={
                "python/py-foo": RuleOverride(
                    rule_id="python/py-foo",
                    enabled=False,
                    confidence_override=0.6,
                    severity_override="high",
                ),
            },
            pack_activation={"python": True, "go": False},
            global_min_confidence=0.7,
            enabled_languages=["python", "go"],
        )
        path = tmp_path / "rule_harness_config.yaml"
        cfg.save_yaml(str(path))

        reloaded = RuleBenchConfig.load_yaml(str(path))
        assert reloaded.global_min_confidence == pytest.approx(0.7)
        assert reloaded.pack_activation == {"python": True, "go": False}
        assert reloaded.enabled_languages == ["python", "go"]
        assert "python/py-foo" in reloaded.rule_overrides
        ov = reloaded.rule_overrides["python/py-foo"]
        assert ov.enabled is False
        assert ov.confidence_override == pytest.approx(0.6)
        assert ov.severity_override == "high"

    def test_from_dict_tolerates_dict_overrides(self) -> None:
        # Some hand-written configs use {rule_id: payload} instead of a list
        cfg = RuleBenchConfig.from_dict({
            "rule_overrides": {
                "py-foo": {"enabled": False, "confidence_override": 0.3},
            },
        })
        assert "py-foo" in cfg.rule_overrides
        ov = cfg.rule_overrides["py-foo"]
        assert ov.enabled is False
        assert ov.confidence_override == pytest.approx(0.3)


class TestExtraRules:
    def test_extra_rule_registered(self, base_registry: RuleRegistry) -> None:
        cfg = RuleBenchConfig(
            extra_rules=[
                {
                    "id": "synth-1",
                    "message": "synthetic rule",
                    "severity": "high",
                    "pattern": "TODO",
                    "languages": ["python"],
                    "category": "style",
                },
            ],
        )
        cloned = cfg.apply_to_registry(base_registry)
        synth = cloned.get("rule_bench_synth/synth-1")
        assert synth is not None
        assert synth.severity == RuleSeverity.HIGH

    def test_invalid_extra_rule_skipped(self, base_registry: RuleRegistry) -> None:
        # Missing required ``message`` field — loader returns None
        cfg = RuleBenchConfig(
            extra_rules=[
                {"id": "broken-1", "severity": "high"},
            ],
        )
        cloned = cfg.apply_to_registry(base_registry)
        # No new rule registered; original count preserved
        assert cloned.count == base_registry.count


class TestMergeOverrides:
    def test_merge_adds_override(self) -> None:
        base = RuleBenchConfig.default()
        merged = merge_overrides(
            base,
            RuleOverride(rule_id="py-foo", confidence_override=0.5),
        )
        assert "py-foo" in merged.rule_overrides
        assert base.rule_overrides == {}  # base untouched
