"""Scaffold hand-labeled corpus fixtures from example pack rule examples.

Walks ``packs/examples/<lang>/rules/*.yaml``, finds rules with at least
one ``examples: [{bad, good}]`` entry, and emits a fixture stub at
``eval/rule_harness/fixtures/attocode/<lang>/<rule-id>.<ext>`` containing:

- the ``bad`` snippet wrapped in a function/scope, with ``# expect:``
  appended to the offending line
- the ``good`` snippet with ``# ok:`` appended

The output is a starting point — humans then edit each file to add
edge cases, ensure it compiles, and add nearby unrelated code so we
measure FP rate properly.

Usage::

    python -m eval.rule_harness.scripts.seed_attocode_fixtures \\
        [--overwrite] [--lang python,go,...]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).parents[3]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

EXAMPLES_DIR = (
    _PROJECT_ROOT / "src" / "attocode" / "code_intel" / "rules" / "packs" / "examples"
)
FIXTURE_ROOT = (
    _PROJECT_ROOT / "eval" / "rule_harness" / "fixtures" / "attocode"
)

# language → file extension + line comment marker
LANG_INFO: dict[str, tuple[str, str]] = {
    "python": (".py", "#"),
    "go": (".go", "//"),
    "typescript": (".ts", "//"),
    "javascript": (".js", "//"),
    "rust": (".rs", "//"),
    "java": (".java", "//"),
    "kotlin": (".kt", "//"),
    "ruby": (".rb", "#"),
    "php": (".php", "//"),
    "c": (".c", "//"),
    "cpp": (".cpp", "//"),
}


def discover_rule_examples(
    pack_dir: Path,
) -> list[tuple[str, dict, str]]:
    """Return ``(rule_id, rule_dict, language)`` triples that have examples."""
    out: list[tuple[str, dict, str]] = []
    rules_dir = pack_dir / "rules"
    if not rules_dir.is_dir():
        return out
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping %s: %s", yaml_file, exc)
            continue
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if not item.get("examples"):
                continue
            languages = item.get("languages") or []
            if isinstance(languages, str):
                languages = [languages]
            lang = languages[0] if languages else pack_dir.name
            out.append((str(item["id"]), item, lang))
    return out


def render_fixture(rule_id: str, rule: dict, language: str) -> str:
    """Build the fixture body from a rule's first example."""
    if language not in LANG_INFO:
        raise ValueError(f"Unknown language: {language}")
    _ext, marker = LANG_INFO[language]
    examples = rule.get("examples") or []
    if not examples:
        raise ValueError(f"Rule {rule_id} has no examples")
    first = examples[0]
    bad = str(first.get("bad", "")).rstrip()
    good = str(first.get("good", "")).rstrip()

    header = (
        f"{marker} Auto-seeded fixture for rule '{rule_id}'.\n"
        f"{marker} Hand-curate before relying on this for scoring:\n"
        f"{marker}   - confirm `# expect:` lines target the actual offending line\n"
        f"{marker}   - add nearby unrelated code so we measure FP rate\n"
        f"{marker}   - ensure the file compiles in your target toolchain\n\n"
    )

    bad_block = _annotate_block(
        bad, marker=marker, kind="expect", rule_id=rule_id,
    )
    good_block = _annotate_block(
        good, marker=marker, kind="ok", rule_id=rule_id,
    )

    return (
        header
        + f"{marker} --- BAD: rule MUST fire ---\n"
        + bad_block
        + f"\n\n{marker} --- GOOD: rule must NOT fire ---\n"
        + good_block
        + "\n"
    )


def _annotate_block(code: str, *, marker: str, kind: str, rule_id: str) -> str:
    """Append ``marker kind: rule_id`` to the first non-empty code line."""
    if not code.strip():
        return code
    lines = code.splitlines()
    annotated_idx = None
    for i, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith(marker):
            annotated_idx = i
            break
    if annotated_idx is None:
        return code
    lines[annotated_idx] = f"{lines[annotated_idx]}  {marker} {kind}: {rule_id}"
    return "\n".join(lines)


def seed_fixtures(
    *,
    languages: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, list[str]]:
    """Walk example packs and emit fixture stubs per rule.

    Returns ``{language: [list of fixture paths written]}``.
    """
    summary: dict[str, list[str]] = {}
    if not EXAMPLES_DIR.is_dir():
        logger.error("Example packs dir missing: %s", EXAMPLES_DIR)
        return summary

    for pack_dir in sorted(EXAMPLES_DIR.iterdir()):
        if not pack_dir.is_dir() or pack_dir.name.startswith("_"):
            continue
        for rule_id, rule, language in discover_rule_examples(pack_dir):
            if languages and language not in languages:
                continue
            if language not in LANG_INFO:
                continue
            ext, _marker = LANG_INFO[language]
            target_dir = FIXTURE_ROOT / language
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / f"{rule_id}{ext}"
            if target_file.exists() and not overwrite:
                logger.info("Skipping (exists): %s", target_file)
                continue
            try:
                body = render_fixture(rule_id, rule, language)
            except ValueError as exc:
                logger.warning("Skipping %s: %s", rule_id, exc)
                continue
            target_file.write_text(body, encoding="utf-8")
            summary.setdefault(language, []).append(str(target_file))

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="eval.rule_harness.scripts.seed_attocode_fixtures",
        description=(
            "Auto-seed hand-labeled corpus stubs from example pack rule examples"
        ),
    )
    parser.add_argument("--lang", default="",
                        help="Comma-separated languages to seed (default: all)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing fixture files")
    args = parser.parse_args()

    langs = [s.strip() for s in args.lang.split(",") if s.strip()] if args.lang else None
    summary = seed_fixtures(languages=langs, overwrite=args.overwrite)

    total = sum(len(v) for v in summary.values())
    print(f"Seeded {total} fixture stub(s)")
    for lang, files in sorted(summary.items()):
        print(f"  {lang}: {len(files)}")
        for path in files:
            print(f"    {path}")

    if total == 0:
        print("\nHint: pass --overwrite to regenerate existing fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
