"""Fixture corpus discovery for the rule-bench harness.

Discovers labeled samples from three sources:

1. Community pack fixtures — ``packs/community/<pack>/fixtures/<rule-id>/{positive,negative}.<ext>``
2. Hand-labeled attocode fixtures — ``eval/rule_harness/fixtures/attocode/<lang>/*.<ext>``
3. Legacy CWE corpus — ``eval/rule_accuracy/corpus/<lang>/<cwe>/{tp_,tn_}<name>.<ext>``

All sources funnel through :class:`CorpusLoader.iter_samples` which yields
:class:`LabeledSample` instances. Annotation parsing reuses
``attocode.code_intel.rules.testing.parse_annotations`` so the harness
respects both attocode-native ``# expect:``/``# ok:`` markers AND the
semgrep-compat ``# ruleid:`` alias added in Step 1.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.executor import detect_language
from attocode.code_intel.rules.packs.pack_loader import (
    get_community_pack_dir,
    list_community_packs,
)
from attocode.code_intel.rules.testing import parse_annotations

# Per-pack project-relative fixture root layout under packs/community/<pack>/
_PACK_FIXTURE_DIR = "fixtures"

# Hand-labeled attocode-specific fixtures
_ATTOCODE_FIXTURE_DIR = (
    Path(__file__).parents[3]  # eval/meta_harness/rule_bench/ -> repo root
    / "eval" / "rule_harness" / "fixtures" / "attocode"
)

# Legacy CWE-organized corpus from eval/rule_accuracy/
_LEGACY_CORPUS_DIR = (
    Path(__file__).parents[3]
    / "eval" / "rule_accuracy" / "corpus"
)

# File extensions we'll consider as labeled samples
_LANG_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".java", ".kt", ".kts",
    ".rb", ".php", ".swift", ".cs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
}


@dataclass(slots=True, frozen=True)
class ExpectedFinding:
    """A single annotation parsed from a labeled fixture file."""

    line: int
    rule_id: str
    kind: str  # "expect" | "ok" | "todoruleid"


@dataclass(slots=True)
class LabeledSample:
    """One source file in the corpus plus its expected findings."""

    file_path: str
    language: str
    pack: str = ""  # empty for hand-labeled / legacy
    cwe: str = ""  # populated from legacy corpus dir layout
    expected_findings: list[ExpectedFinding] = field(default_factory=list)
    has_negative_assertions: bool = False  # any "# ok:" or "# no-expect:" markers


class CorpusLoader:
    """Iterate labeled samples from all enabled corpus sources."""

    def __init__(
        self,
        *,
        include_community: bool = True,
        include_attocode: bool = True,
        include_legacy: bool = True,
        enabled_packs: set[str] | None = None,
        community_dir: Path | None = None,
        attocode_dir: Path | None = None,
        legacy_dir: Path | None = None,
    ) -> None:
        self._include_community = include_community
        self._include_attocode = include_attocode
        self._include_legacy = include_legacy
        # ``None`` means "no filter, take all enabled packs found on disk".
        # An empty set means "no community fixtures" — the explicit zero state.
        self._enabled_packs = enabled_packs
        self._community_dir = community_dir or get_community_pack_dir()
        self._attocode_dir = attocode_dir or _ATTOCODE_FIXTURE_DIR
        self._legacy_dir = legacy_dir or _LEGACY_CORPUS_DIR

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def iter_samples(self) -> Iterator[LabeledSample]:
        if self._include_community:
            yield from self._iter_community()
        if self._include_attocode:
            yield from self._iter_attocode()
        if self._include_legacy:
            yield from self._iter_legacy()

    def sample_count_by_language(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sample in self.iter_samples():
            counts[sample.language] = counts.get(sample.language, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Community pack fixtures
    # ------------------------------------------------------------------

    def _iter_community(self) -> Iterator[LabeledSample]:
        if not self._community_dir.is_dir():
            return
        # Enumerate manifests so we know each pack's name even if its
        # fixtures dir is empty (informational only — empty dirs yield zero
        # samples). Falls back to directory walk if pack_loader is missing
        # the community dir entirely.
        try:
            manifests = list_community_packs()
        except Exception:
            manifests = []
        manifest_packs = {m.name for m in manifests}
        for entry in sorted(self._community_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            pack = entry.name
            if pack not in manifest_packs:
                # Stale dir without a manifest — skip rather than guess.
                continue
            if self._enabled_packs is not None and pack not in self._enabled_packs:
                continue
            fixtures_root = entry / _PACK_FIXTURE_DIR
            if not fixtures_root.is_dir():
                continue
            for rule_dir in sorted(fixtures_root.iterdir()):
                if not rule_dir.is_dir():
                    continue
                for fixture in sorted(rule_dir.iterdir()):
                    sample = self._load_sample(str(fixture), pack=pack)
                    if sample is not None:
                        yield sample

    # ------------------------------------------------------------------
    # Hand-labeled attocode-specific fixtures
    # ------------------------------------------------------------------

    def _iter_attocode(self) -> Iterator[LabeledSample]:
        if not self._attocode_dir.is_dir():
            return
        for lang_dir in sorted(self._attocode_dir.iterdir()):
            if not lang_dir.is_dir():
                continue
            for fixture in sorted(lang_dir.rglob("*")):
                if not fixture.is_file():
                    continue
                sample = self._load_sample(str(fixture), pack="attocode")
                if sample is not None:
                    yield sample

    # ------------------------------------------------------------------
    # Legacy CWE-organized corpus
    # ------------------------------------------------------------------

    def _iter_legacy(self) -> Iterator[LabeledSample]:
        if not self._legacy_dir.is_dir():
            return
        for lang_dir in sorted(self._legacy_dir.iterdir()):
            if not lang_dir.is_dir():
                continue
            for cwe_dir in sorted(lang_dir.iterdir()):
                if not cwe_dir.is_dir():
                    continue
                for fixture in sorted(cwe_dir.iterdir()):
                    sample = self._load_sample(
                        str(fixture), pack="legacy", cwe=cwe_dir.name,
                    )
                    if sample is not None:
                        yield sample

    # ------------------------------------------------------------------
    # Per-file loader (shared)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_sample(
        file_path: str, *, pack: str = "", cwe: str = "",
    ) -> LabeledSample | None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _LANG_EXTENSIONS:
            return None
        language = detect_language(file_path)
        if not language:
            return None

        annotations = parse_annotations(file_path)
        expected: list[ExpectedFinding] = [
            ExpectedFinding(line=a.line, rule_id=a.rule_id, kind=a.kind)
            for a in annotations
        ]
        has_negatives = any(a.kind == "ok" for a in annotations)

        # Skip files with neither expectations nor negative assertions —
        # they're fixture scaffolding (imports, helpers) not labeled signal.
        if not expected and not has_negatives:
            return None

        return LabeledSample(
            file_path=file_path,
            language=language,
            pack=pack,
            cwe=cwe,
            expected_findings=expected,
            has_negative_assertions=has_negatives,
        )
