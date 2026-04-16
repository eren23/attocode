"""Unit tests for the rule-bench template engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.meta_harness.rule_bench.corpus import ExpectedFinding, LabeledSample
from eval.meta_harness.rule_bench.template_engine import (
    SUPPORTED_LANGUAGES,
    Template,
    TEMPLATES_DIR,
    gate_against_corpus,
    load_templates,
    substitute_slots,
    validate_template_instance,
)


class TestLoadTemplates:
    def test_loads_shipped_templates(self) -> None:
        templates = load_templates()
        assert TEMPLATES_DIR.is_dir()
        assert len(templates) >= 6
        # Spot-check the key ones
        for name in (
            "deprecated_api_call",
            "missing_error_check",
            "insecure_default_arg",
            "regex_redos",
            "string_concat_in_loop",
            "unsafe_deserialization",
        ):
            assert name in templates, f"Missing template: {name}"

    def test_each_template_has_slots_and_rule(self) -> None:
        for tid, template in load_templates().items():
            assert template.slots, f"{tid} has no slots"
            assert "id" in template.rule_body, f"{tid} rule_body missing id"
            assert "pattern" in template.rule_body, f"{tid} rule_body missing pattern"


class TestValidateTemplateInstance:
    def test_valid_instance(self) -> None:
        templates = load_templates()
        t = templates["string_concat_in_loop"]
        errors = validate_template_instance(
            t, {"language": "python", "concat_pattern": r"\+=\s*['\"]"},
        )
        assert errors == []

    def test_invalid_regex_caught(self) -> None:
        templates = load_templates()
        t = templates["string_concat_in_loop"]
        errors = validate_template_instance(
            t, {"language": "python", "concat_pattern": "(unbalanced"},
        )
        assert any("invalid regex" in e for e in errors)

    def test_unsupported_language_caught(self) -> None:
        templates = load_templates()
        t = templates["string_concat_in_loop"]
        errors = validate_template_instance(
            t, {"language": "klingon", "concat_pattern": r"\+="},
        )
        assert any("unsupported language" in e for e in errors)

    def test_missing_slot_caught(self) -> None:
        templates = load_templates()
        t = templates["deprecated_api_call"]
        errors = validate_template_instance(t, {"language": "python"})
        assert any("missing slots" in e for e in errors)

    def test_enum_slot_validates(self) -> None:
        templates = load_templates()
        t = templates["insecure_default_arg"]
        errors = validate_template_instance(
            t, {
                "language": "python",
                "arg_pattern": r"verify\s*=\s*False",
                "severity": "apocalyptic",
            },
        )
        assert any("not in enum" in e for e in errors)


class TestSubstituteSlots:
    def test_substitutes_placeholders(self) -> None:
        templates = load_templates()
        t = templates["string_concat_in_loop"]
        rule = substitute_slots(t, {
            "language": "python",
            "concat_pattern": r"\+=\s*['\"]",
        })
        assert rule["languages"] == ["python"]
        assert rule["pattern"] == r"\+=\s*['\"]"
        # slot_safe_name auto-derived from first slot value
        assert "python" in rule["id"].lower()

    def test_missing_slot_raises(self) -> None:
        templates = load_templates()
        t = templates["string_concat_in_loop"]
        with pytest.raises(KeyError):
            substitute_slots(t, {"language": "python"})


class TestGateAgainstCorpus:
    def _sample_with_pattern(self, tmp_path: Path, lines: list[str], expects: dict[int, str]) -> LabeledSample:
        path = tmp_path / "sample.py"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return LabeledSample(
            file_path=str(path),
            language="python",
            pack="attocode",
            expected_findings=[
                ExpectedFinding(line=ln, rule_id=rid, kind="expect")
                for ln, rid in expects.items()
            ],
        )

    def test_accepts_well_targeted_rule(self, tmp_path: Path) -> None:
        # Two TPs, zero FPs
        sample = self._sample_with_pattern(
            tmp_path,
            [
                "BAD_TOKEN = 1",
                "OTHER = 2",
                "BAD_TOKEN = 3",
            ],
            expects={1: "perf/python/foo-test", 3: "perf/python/foo-test"},
        )
        rule = {
            "id": "perf/python/foo-test",
            "message": "uses BAD_TOKEN",
            "severity": "low",
            "category": "performance",
            "pattern": r"\bBAD_TOKEN\b",
            "languages": ["python"],
        }
        accepted, reason = gate_against_corpus(rule, [sample])
        assert accepted, reason

    def test_rejects_too_few_tps(self, tmp_path: Path) -> None:
        sample = self._sample_with_pattern(
            tmp_path,
            ["BAD_TOKEN = 1"],
            expects={1: "perf/python/foo-test"},
        )
        rule = {
            "id": "perf/python/foo-test",
            "message": "uses BAD_TOKEN",
            "severity": "low",
            "category": "performance",
            "pattern": r"\bBAD_TOKEN\b",
            "languages": ["python"],
        }
        accepted, reason = gate_against_corpus(rule, [sample], min_tp=2)
        assert not accepted
        assert "insufficient TPs" in reason

    def test_rejects_too_broad_rule(self, tmp_path: Path) -> None:
        # Rule matches everything → many FPs
        path = tmp_path / "wide.py"
        path.write_text(
            "import os\nimport sys\nimport json\n", encoding="utf-8",
        )
        sample = LabeledSample(
            file_path=str(path),
            language="python",
            pack="attocode",
            expected_findings=[
                ExpectedFinding(line=99, rule_id="perf/python/wide-test", kind="expect"),
            ],
        )
        rule = {
            "id": "perf/python/wide-test",
            "message": "any import",
            "severity": "low",
            "category": "performance",
            "pattern": r"import",
            "languages": ["python"],
        }
        accepted, reason = gate_against_corpus(rule, [sample], min_tp=1, max_fp=1)
        assert not accepted
        # Rule fires on every import line (FP) but the expected line is 99
        # (no TP). Either rejection reason is acceptable; what matters is
        # that an over-broad rule never makes it through.
        assert "FPs" in reason or "TPs" in reason


class TestSupportedLanguages:
    def test_includes_attocode_targets(self) -> None:
        for lang in ("python", "go", "typescript", "rust", "java"):
            assert lang in SUPPORTED_LANGUAGES
