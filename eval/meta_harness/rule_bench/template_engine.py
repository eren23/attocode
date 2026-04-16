"""Stage-2 template engine for the rule-bench harness.

A template is a YAML file describing:

- ``template_id``: short identifier
- ``description``: free text
- ``slots``: list of ``{name, kind, description?}`` entries the LLM fills
- ``rule``: a rule template body containing ``{{slot_name}}`` placeholders

When the proposer instantiates a template, we:

1. Substitute all slots into the rule body
2. Validate each slot against its declared kind (regex_fragment compiles,
   enum values match, language is recognized)
3. Run the rule against the existing labeled corpus and reject any that
   doesn't earn at least 2 TPs while staying under 2 FPs (the
   *fixture-coverage gate*)

Surviving rules get appended to the candidate's ``RuleBenchConfig.extra_rules``
so the inner-loop evaluator can score them alongside the base packs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.loader import _parse_yaml_rule
from attocode.code_intel.rules.model import RuleSource
from attocode.code_intel.rules.testing import _finding_matches_rule

from eval.meta_harness.rule_bench.corpus import LabeledSample

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Languages we know how to ship rules for. Keep in sync with executor._EXT_LANG.
SUPPORTED_LANGUAGES = {
    "python", "go", "javascript", "typescript",
    "rust", "java", "kotlin", "ruby", "php", "c", "cpp",
}

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}

# Regex matching a `{{slot_name}}` placeholder
_SLOT_RE = re.compile(r"\{\{\s*([\w]+)\s*\}\}")


# ---------------------------------------------------------------------------
# Template model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Slot:
    name: str
    kind: str
    description: str = ""

    @property
    def enum_choices(self) -> list[str]:
        if self.kind.startswith("enum:"):
            return self.kind.split(":", 1)[1].split("|")
        return []


@dataclass(slots=True)
class Template:
    template_id: str
    description: str
    slots: list[Slot] = field(default_factory=list)
    rule_body: dict[str, Any] = field(default_factory=dict)

    def slot_names(self) -> set[str]:
        return {s.name for s in self.slots}


def load_templates(templates_dir: Path | None = None) -> dict[str, Template]:
    """Load every ``*.yaml`` template from ``templates_dir``."""
    base = templates_dir or TEMPLATES_DIR
    out: dict[str, Template] = {}
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping template %s: %s", path, exc)
            continue
        if not isinstance(data, dict):
            continue
        template = _parse_template(data, path)
        if template is not None:
            out[template.template_id] = template
    return out


def _parse_template(data: dict, path: Path) -> Template | None:
    tid = data.get("template_id")
    if not tid:
        logger.warning("Template %s missing template_id", path)
        return None
    rule_body = data.get("rule")
    if not isinstance(rule_body, dict):
        logger.warning("Template %s missing rule body", path)
        return None
    slots_raw = data.get("slots") or []
    slots: list[Slot] = []
    for s in slots_raw:
        if not isinstance(s, dict) or "name" not in s or "kind" not in s:
            continue
        slots.append(
            Slot(
                name=str(s["name"]),
                kind=str(s["kind"]),
                description=str(s.get("description", "")),
            )
        )
    return Template(
        template_id=str(tid),
        description=str(data.get("description", "")),
        slots=slots,
        rule_body=rule_body,
    )


# ---------------------------------------------------------------------------
# Substitution + validation
# ---------------------------------------------------------------------------


def substitute_slots(
    template: Template, filled_slots: dict[str, str],
) -> dict[str, Any]:
    """Substitute slot placeholders into the template's rule body.

    Adds an implicit ``slot_safe_name`` derived from the first regex_fragment
    or text slot — used by templates to build collision-resistant rule ids.
    """
    enriched = dict(filled_slots)
    enriched.setdefault("slot_safe_name", _build_safe_name(template, filled_slots))

    def _sub_str(value: str) -> str:
        def repl(m: re.Match[str]) -> str:
            slot_name = m.group(1)
            if slot_name not in enriched:
                raise KeyError(f"Missing slot value: {slot_name}")
            return str(enriched[slot_name])

        return _SLOT_RE.sub(repl, value)

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _sub_str(node)
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        return node

    return _walk(template.rule_body)


def _build_safe_name(template: Template, filled: dict[str, str]) -> str:
    """Build a stable slug for the rule id from the first text-ish slot."""
    for slot in template.slots:
        value = filled.get(slot.name, "")
        if not value:
            continue
        slug = re.sub(r"[^\w]+", "-", value).strip("-").lower()
        if slug:
            return slug[:48]
    return template.template_id


def validate_template_instance(
    template: Template, filled_slots: dict[str, str],
) -> list[str]:
    """Validate slot values against their declared kinds. Return error list."""
    errors: list[str] = []
    expected = template.slot_names()
    missing = expected - set(filled_slots)
    if missing:
        errors.append(f"missing slots: {sorted(missing)}")
    extra = set(filled_slots) - expected - {"slot_safe_name"}
    if extra:
        errors.append(f"unknown slots: {sorted(extra)}")

    for slot in template.slots:
        value = filled_slots.get(slot.name)
        if value is None:
            continue
        if slot.kind == "regex_fragment":
            try:
                re.compile(value)
            except re.error as exc:
                errors.append(f"slot {slot.name}: invalid regex: {exc}")
        elif slot.kind == "text":
            if not value.strip():
                errors.append(f"slot {slot.name}: empty text")
        elif slot.kind == "language":
            if value not in SUPPORTED_LANGUAGES:
                errors.append(
                    f"slot {slot.name}: unsupported language {value!r}"
                )
        elif slot.kind.startswith("enum:"):
            if value not in slot.enum_choices:
                errors.append(
                    f"slot {slot.name}: not in enum {slot.enum_choices}"
                )

    return errors


# ---------------------------------------------------------------------------
# Fixture-coverage gate
# ---------------------------------------------------------------------------


def gate_against_corpus(
    rule_dict: dict[str, Any],
    corpus: list[LabeledSample],
    *,
    min_tp: int = 2,
    max_fp: int = 1,
) -> tuple[bool, str]:
    """Reject candidate rules that are too broad or too narrow.

    Returns ``(accepted, reason)``. ``min_tp=2`` ensures the rule has at
    least some signal on the existing corpus; ``max_fp<=1`` prevents
    candidates from regressing precision too aggressively before the
    full inner-loop eval even runs.
    """
    rule = _parse_yaml_rule(
        rule_dict, source=RuleSource.PACK, pack="rule_bench_synth",
        origin="template_gate",
    )
    if rule is None:
        return False, "rule failed to parse"

    tp = 0
    fp = 0
    for sample in corpus:
        # Quick language filter — universal rules apply everywhere
        if rule.languages and sample.language not in rule.languages:
            continue
        findings = execute_rules([sample.file_path], [rule], project_dir="")
        if not findings:
            continue
        # Map findings to expectations (just use the same matcher as the eval)
        for f in findings:
            matched_expect = False
            matched_ok = False
            for ann in sample.expected_findings:
                if ann.line != f.line:
                    continue
                if not _finding_matches_rule(f.rule_id, ann.rule_id):
                    continue
                if ann.kind == "expect":
                    matched_expect = True
                elif ann.kind == "ok":
                    matched_ok = True
            if matched_expect:
                tp += 1
            elif matched_ok:
                fp += 1
            elif sample.expected_findings:
                # Unexpected finding on a labeled file → FP
                fp += 1

    if tp < min_tp:
        return False, f"insufficient TPs (got {tp}, need >= {min_tp})"
    if fp > max_fp:
        return False, f"too many FPs (got {fp}, max {max_fp})"
    return True, f"tp={tp} fp={fp}"
