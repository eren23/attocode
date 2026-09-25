"""Rule accuracy benchmark runner.

Discovers corpus files, executes rules, compares findings against
annotations, and computes per-rule/CWE/language precision/recall/F1.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Annotation patterns
_EXPECT_RE = re.compile(r"(?:#|//)\s*expect:\s*([\w./-]+)")
_NO_EXPECT_RE = re.compile(r"(?:#|//)\s*no-expect:")
# The same markers, for removal: they sit inline on the judged line, so a model
# scorer would otherwise read the correct rule id straight out of its context.
_ANNOTATION_RE = re.compile(
    r"[ \t]*(?:#|//)\s*(?:(?:no-)?expect:|ok:|(?:todo)?ruleid:|nosec\b).*$",
    re.MULTILINE,
)

CORPUS_DIR = Path(__file__).parent / "corpus"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuleAccuracyResult:
    """Per-rule accuracy metrics."""

    rule_id: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass(slots=True)
class CorpusFileResult:
    """Results for a single corpus file."""

    file_path: str
    language: str
    cwe: str
    is_true_negative_file: bool
    expected_rules: dict[int, str] = field(default_factory=dict)  # line -> rule_id
    actual_findings: dict[int, list[str]] = field(default_factory=dict)  # line -> [rule_ids]
    tp_lines: list[int] = field(default_factory=list)
    fp_lines: list[int] = field(default_factory=list)
    fn_lines: list[int] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkResult:
    """Full benchmark result."""

    file_results: list[CorpusFileResult] = field(default_factory=list)
    per_rule: dict[str, RuleAccuracyResult] = field(default_factory=dict)
    per_cwe: dict[str, RuleAccuracyResult] = field(default_factory=dict)
    per_language: dict[str, RuleAccuracyResult] = field(default_factory=dict)
    overall: RuleAccuracyResult = field(default_factory=lambda: RuleAccuracyResult(rule_id="overall"))
    # (confidence, is_true_positive) for every finding before the threshold —
    # what compute_calibration() needs to produce an ECE.
    scored: list[tuple[float, bool]] = field(default_factory=list)
    scorer: str = "constants"
    scorer_note: str = ""


# ---------------------------------------------------------------------------
# Corpus discovery
# ---------------------------------------------------------------------------


def discover_corpus(corpus_dir: str | Path = CORPUS_DIR) -> list[tuple[str, str, str]]:
    """Discover corpus files.

    Returns:
        List of (file_path, language, cwe) tuples.
    """
    corpus_path = Path(corpus_dir)
    if not corpus_path.is_dir():
        return []

    files: list[tuple[str, str, str]] = []
    for lang_dir in sorted(corpus_path.iterdir()):
        if not lang_dir.is_dir():
            continue
        language = lang_dir.name
        for cwe_dir in sorted(lang_dir.iterdir()):
            if not cwe_dir.is_dir():
                continue
            cwe = cwe_dir.name
            for f in sorted(cwe_dir.iterdir()):
                if f.is_file() and f.suffix in {
                    ".py", ".go", ".js", ".ts", ".java", ".rs",
                    ".kt", ".rb", ".php", ".c", ".cpp",
                }:
                    files.append((str(f), language, cwe))

    return files


def _parse_file_annotations(file_path: str) -> tuple[dict[int, str], bool]:
    """Parse expect annotations and no-expect markers from a corpus file.

    Returns:
        (line_to_rule_id dict, is_true_negative_file bool)
    """
    expectations: dict[int, str] = {}
    is_tn = False

    try:
        with open(file_path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                m = _EXPECT_RE.search(line)
                if m:
                    expectations[i] = m.group(1)
                if _NO_EXPECT_RE.search(line):
                    is_tn = True
    except OSError:
        pass

    return expectations, is_tn


def _finding_matches(finding_rule_id: str, expected_rule_id: str) -> bool:
    """Check if a finding matches an expected annotation."""
    if finding_rule_id == expected_rule_id:
        return True
    if finding_rule_id.endswith("/" + expected_rule_id):
        return True
    return False


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------

SCORERS = ("constants", "llm", "jev")


def _strip_annotations(findings: list[Any]) -> None:
    """Remove ground-truth markers from finding context, in place.

    Corpus files carry ``# expect: <rule_id>`` on the very line under
    judgement. Leaving it in hands any model scorer the answer key, and it
    also tells the model the file is a test fixture, which is its own bias.
    """
    for f in findings:
        f.code_snippet = _ANNOTATION_RE.sub("", f.code_snippet)
        f.description = _ANNOTATION_RE.sub("", f.description)
        f.context_before = [_ANNOTATION_RE.sub("", line) for line in f.context_before]
        f.context_after = [_ANNOTATION_RE.sub("", line) for line in f.context_after]


@contextmanager
def _active_scorer(scorer: str) -> Iterator[None]:
    """Pin the confidence source for one run, whatever the ambient env says."""
    if scorer not in SCORERS:
        raise ValueError(f"Unknown scorer {scorer!r}; expected one of {SCORERS}")

    from attocode_intel import confidence
    from attocode_intel._internal.integrations.feature_flags import registry

    registry.set_override("CONFIDENCE", "off" if scorer == "constants" else scorer)
    registry.set_override("CONFIDENCE_MODE", "live")
    # The dispatcher caps calls per invocation to keep a wide diff scan
    # affordable. The benchmark hands it the whole corpus at once and must score
    # all of it, or the unscored tail silently keeps its constants.
    previous_cap = confidence.MAX_CALLS
    confidence.MAX_CALLS = 1_000_000
    try:
        yield
    finally:
        confidence.MAX_CALLS = previous_cap
        registry.clear_override("CONFIDENCE")
        registry.clear_override("CONFIDENCE_MODE")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_accuracy_benchmark(
    corpus_dir: str | Path = CORPUS_DIR,
    *,
    min_confidence: float = 0.0,
    scorer: str = "constants",
) -> BenchmarkResult:
    """Run the rule accuracy benchmark against the corpus.

    Args:
        corpus_dir: Path to corpus directory.
        min_confidence: Minimum confidence threshold for findings. Note that the
            default of 0.0 filters nothing, so confidence changes cannot move
            precision or recall. Use 0.5 — the product default — to compare scorers.
        scorer: Where confidence comes from. "constants" is the shipped behaviour,
            "jev" asks Jev for a probability, "llm" asks the Haiku classifier in
            eval/llm_fp_filter.

    Returns:
        BenchmarkResult with per-rule, per-CWE, and per-language metrics.
    """
    from attocode.code_intel.rules.loader import load_builtin_rules
    from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack
    from attocode.code_intel.rules.executor import execute_rules
    from attocode.code_intel.rules.enricher import enrich_findings
    from attocode.code_intel.rules.filters.pipeline import filter_by_confidence, run_pipeline
    from attocode_intel import confidence

    # Load all rules
    rules = load_builtin_rules()
    for manifest in list_example_packs():
        rules.extend(load_pack(manifest))

    # Discover corpus
    corpus_files = discover_corpus(corpus_dir)
    if not corpus_files:
        logger.warning("No corpus files found in %s", corpus_dir)
        return BenchmarkResult()

    # dedup_findings keys on (file, line, category) and EnrichedFinding.file is a
    # basename, so batching the corpus into one pipeline call would merge findings
    # across files if two corpus files shared a name.
    basenames = [os.path.basename(fp) for fp, _lang, _cwe in corpus_files]
    if len(set(basenames)) != len(basenames):
        raise ValueError(
            "Corpus files must have unique basenames; dedup would merge across files"
        )

    result = BenchmarkResult(scorer=scorer)

    # Pass 1: run the rules and scrub ground-truth markers. Nothing is scored
    # yet, and each finding remembers the corpus file it came from.
    meta: dict[str, tuple[str, str, dict[int, str], bool]] = {}
    owner: dict[int, str] = {}
    all_findings: list[Any] = []
    for file_path, language, cwe in corpus_files:
        expectations, is_tn_file = _parse_file_annotations(file_path)
        meta[file_path] = (language, cwe, expectations, is_tn_file)
        found = execute_rules([file_path], rules, project_dir=str(Path(file_path).parent))
        enrich_findings(found, project_dir=str(Path(file_path).parent))
        _strip_annotations(found)
        for f in found:
            owner[id(f)] = file_path
        all_findings.extend(found)

    # Pass 2: one pipeline call for the whole corpus. Scoring per file gave a
    # model scorer ~2 findings at a time, so its thread pool sat idle and the
    # run cost one round trip per file instead of one per batch.
    with _active_scorer(scorer):
        scored = run_pipeline(all_findings, min_confidence=0.0)
        estimated, considered = confidence.last_run()

    # Calibration is measured before the threshold, over everything scored.
    for f in scored:
        _lang, _cwe, expectations, _tn = meta[owner[id(f)]]
        expected = expectations.get(f.line)
        is_tp = expected is not None and _finding_matches(f.rule_id, expected)
        result.scored.append((f.confidence, is_tp))

    survivors: dict[str, list[Any]] = {fp: [] for fp in meta}
    for f in filter_by_confidence(scored, min_confidence):
        survivors[owner[id(f)]].append(f)

    # Pass 3: per-file accounting, unchanged.
    for file_path, (language, cwe, expectations, is_tn_file) in meta.items():
        # Build findings map: line -> [rule_ids]
        findings_map: dict[int, list[str]] = {}
        for f in survivors[file_path]:
            findings_map.setdefault(f.line, []).append(f.rule_id)

        file_result = CorpusFileResult(
            file_path=file_path,
            language=language,
            cwe=cwe,
            is_true_negative_file=is_tn_file,
            expected_rules=expectations,
            actual_findings=findings_map,
        )

        # Compute TP/FP/FN for this file
        for line_no, expected_rule in expectations.items():
            line_findings = findings_map.get(line_no, [])
            matched = any(
                _finding_matches(fid, expected_rule) for fid in line_findings
            )
            if matched:
                file_result.tp_lines.append(line_no)
                _increment(result, expected_rule, cwe, language, "tp")
            else:
                file_result.fn_lines.append(line_no)
                _increment(result, expected_rule, cwe, language, "fn")

        # FP: findings on non-annotated lines
        expected_lines = set(expectations.keys())
        for line_no, rule_ids in findings_map.items():
            if line_no not in expected_lines:
                # In TN files, any finding is a FP
                # In TP files, findings on unannotated lines are also FPs
                for rid in rule_ids:
                    file_result.fp_lines.append(line_no)
                    _increment(result, rid, cwe, language, "fp")

        result.file_results.append(file_result)

    if considered and not estimated:
        raise RuntimeError(
            f"{scorer} scorer had no opinion on any of {considered} findings"
        )
    if considered and estimated < considered:
        result.scorer_note = (
            f"no opinion on {considered - estimated}/{considered} findings, "
            "constants stood"
        )

    return result


_METRIC_ATTR = {
    "tp": "true_positives",
    "fp": "false_positives",
    "fn": "false_negatives",
    "tn": "true_negatives",
}


def _increment(
    result: BenchmarkResult,
    rule_id: str,
    cwe: str,
    language: str,
    metric: str,
) -> None:
    """Increment a metric across per-rule, per-CWE, per-language, and overall."""
    attr = _METRIC_ATTR[metric]
    for key, store in [
        (rule_id, result.per_rule),
        (cwe, result.per_cwe),
        (language, result.per_language),
    ]:
        if key not in store:
            store[key] = RuleAccuracyResult(rule_id=key)
        setattr(store[key], attr, getattr(store[key], attr) + 1)

    setattr(result.overall, attr, getattr(result.overall, attr) + 1)
