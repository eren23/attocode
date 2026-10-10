"""Explain and conservatively diversify broad lexical navigation queries."""

from __future__ import annotations

import math
import os
import re
from dataclasses import replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from attocode_intel.focused_evidence import task_terms, terms
from attocode_intel.test_ranking import is_test_path

if TYPE_CHECKING:
    from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchResult


_QUERY_FILLER = frozenset({
    "where", "which", "what", "why", "find", "locate", "show", "explain",
    "implementation", "implemented", "handling", "handled",
})
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".sh",
})


def broad_rank_enabled() -> bool:
    """Keep the unproven lexical promotion out of default navigation."""
    return os.environ.get("ATTOCODE_INTEL_BROAD_RERANK") == "1"


def _default_file_diversity(
    query: str, candidates: list[SemanticSearchResult], top_k: int,
    file_filter: str,
) -> list[SemanticSearchResult]:
    """Return distinct files in original rank order when a full page exists.

    This preserves the first-hit file and the order of all first file
    occurrences. If the candidate pool cannot supply ``top_k`` distinct files,
    retain the old page rather than silently returning fewer hits.
    """
    if len(query_concepts(query)) < 2 or file_filter or re.search(r"\btests?\b", query, re.I):
        return candidates[:top_k]
    selected = []
    seen = set()
    for row in candidates:
        if row.file_path not in seen:
            selected.append(row)
            seen.add(row.file_path)
            if len(selected) == top_k:
                return selected
    return candidates[:top_k]


def query_concepts(query: str) -> tuple[str, ...]:
    """Retain task concepts, not question phrasing or explicit exclusions."""
    positive, _ = task_terms(query)
    return tuple(sorted(positive - _QUERY_FILLER))


def hit_evidence(query: str, result: SemanticSearchResult) -> dict[str, object]:
    """Report exactly which query concepts appear in identity and source."""
    concepts = set(query_concepts(query))
    identity = terms(f"{result.file_path} {result.name}")
    evidence_text = result.text.split("\n", 1)[-1] if result.start_line else result.text
    text_terms = terms(evidence_text)
    in_identity = sorted(concepts & identity)
    in_text = sorted(concepts & text_terms)
    fields = []
    if in_identity:
        fields.append("identity")
    if in_text:
        fields.append("source_body" if result.start_line else "symbol_metadata")
    return {
        "matched_terms": sorted(set(in_identity) | set(in_text)),
        "match_fields": fields,
    }


def _matches_exclusion(result: SemanticSearchResult, negative: set[str]) -> bool:
    """Keep explicit negative hints from receiving a full-coverage bonus."""
    if not negative:
        return False
    identity = terms(f"{result.file_path} {result.name}")
    source = terms(result.text)
    return bool(source & negative) or any(
        term == token or (len(term) >= 4 and term in token)
        for term in negative for token in identity
    )


def _component(path: str) -> str:
    parts = PurePosixPath(path).parent.parts
    if not parts:
        return "."
    if parts[0] == "packages" and len(parts) > 1:
        return "/".join(parts[:2])
    if parts[0] in {"src", "legacy"} and len(parts) > 2:
        return "/".join(parts[:4])
    return "/".join(parts[:2])


def demote_tests(query: str, candidates: list[SemanticSearchResult]) -> list[SemanticSearchResult]:
    """Put test files after the other files, unless a short query asks for tests.

    An issue is fixed in source files, and ``suggest_tests`` finds the tests. A long
    issue often says "test" about its reproduction, so only a short query shows test
    intent. The order in each group does not change.
    """
    if re.search(r"\btests?\b", query, re.IGNORECASE) and len(terms(query)) <= 20:
        return candidates
    return sorted(candidates, key=lambda row: is_test_path(row.file_path))


def _source_weight(path: str, test_intent: bool) -> float:
    normalized = f"/{path.lower().replace('\\', '/')}"
    if any(part in normalized for part in (
        "/legacy/", "/lessons/", "/eval/", "/examples/", "/docs_src/",
    )):
        return 0.0
    if not test_intent and any(part in normalized for part in ("/test/", "/tests/", "/docs/")):
        return 0.0
    return 1.0 if PurePosixPath(path).suffix.lower() in _SOURCE_EXTENSIONS else 0.0


def rerank_broad_candidates(
    query: str, candidates: list[SemanticSearchResult], top_k: int,
    file_filter: str = "",
) -> list[SemanticSearchResult]:
    """Favor multi-concept source evidence while retaining ambiguous alternatives.

    Only two-concept queries with a partial top hit are reordered. Longer
    queries already have discriminating evidence; exhaustive source-body term
    coverage tends to over-promote incidental docs and comments in them.
    """
    if top_k <= 0 or not candidates:
        return []
    if not broad_rank_enabled():
        return _default_file_diversity(query, candidates, top_k, file_filter)
    concepts = query_concepts(query)
    _, negative = task_terms(query)
    if len(concepts) != 2:
        return candidates[:top_k]
    concept_set = set(concepts)
    evidence = [hit_evidence(query, row) for row in candidates]
    if concept_set <= set(evidence[0]["matched_terms"]):
        return candidates[:top_k]
    test_intent = bool(re.search(r"\btests?\b", query, re.IGNORECASE))
    boostable = {
        index for index, (row, item) in enumerate(zip(candidates, evidence, strict=True))
        if concept_set <= set(item["matched_terms"])
        and _source_weight(row.file_path, test_intent) > 0
        and not _matches_exclusion(row, negative)
    }
    if not boostable:
        return candidates[:top_k]
    anchor = next(
        (row for row in candidates if _source_weight(row.file_path, test_intent) > 0
         and not _matches_exclusion(row, negative)),
        None,
    )
    if anchor is not None:
        anchor_component = _component(anchor.file_path)
        local = {index for index in boostable
                 if _component(candidates[index].file_path) == anchor_component}
        if local:
            boostable = local

    peak = max(row.score for row in candidates)
    adjusted = []
    for index, row in enumerate(candidates):
        # The existing RRF score remains the tie-breaker. A complete match
        # in the preferred component gets one peak-score bonus.
        bonus = (
            peak * _source_weight(row.file_path, test_intent)
            if index in boostable
            else 0.0
        )
        adjusted.append((replace(row, score=round(row.score + bonus, 6)), index))
    adjusted.sort(key=lambda pair: (-pair[0].score, pair[1]))

    if file_filter or test_intent:
        return [row for row, _ in adjusted[:top_k]]

    # Greedy file diversity prevents one implementation's class, methods and
    # tests from monopolizing a broad query. It never discards a candidate.
    selected: list[SemanticSearchResult] = []
    seen_files: dict[str, int] = {}
    while adjusted and len(selected) < top_k:
        winner = max(
            range(len(adjusted)),
            key=lambda i: (
                adjusted[i][0].score / math.pow(2.5, seen_files.get(adjusted[i][0].file_path, 0)),
                -adjusted[i][1],
            ),
        )
        row, _ = adjusted.pop(winner)
        effective_score = row.score / math.pow(2.5, seen_files.get(row.file_path, 0))
        selected.append(replace(row, score=round(effective_score, 6)))
        seen_files[row.file_path] = seen_files.get(row.file_path, 0) + 1
    return selected


def query_diagnostics(
    query: str, candidates: list[SemanticSearchResult], file_filter: str = "",
) -> dict[str, object]:
    """Show ambiguity without pretending to know a user's intended subsystem."""
    concepts = query_concepts(query)
    _, negative = task_terms(query)
    components: list[str] = []
    if 2 <= len(concepts) <= 5:
        for row in candidates:
            if len(hit_evidence(query, row)["matched_terms"]) != len(concepts):
                continue
            if _matches_exclusion(row, negative):
                continue
            component = _component(row.file_path)
            if component not in components:
                components.append(component)
            if len(components) >= 4:
                break
    ambiguous = not file_filter and len(components) >= 2
    return {
        "concepts": list(concepts[:5]),
        "scope": file_filter or "workspace",
        "ambiguous": ambiguous,
        "matching_components": components[:3] if ambiguous else [],
    }


def next_search_top_k(candidate_count: int, requested: int, delivered: int) -> int | None:
    """Suggest a larger page only for candidates already in this search pool.

    This is a fresh search request, not a stable cursor or a relevance claim.
    A caller may have delivered fewer than requested due to its output budget.
    """
    if candidate_count <= delivered or requested <= 0:
        return None
    return max(requested, min(candidate_count, max(24, requested * 2)))
