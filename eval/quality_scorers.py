"""Extracted quality scoring functions for benchmark output evaluation.

Deterministic scorers that rate code-intel output quality on a 0-5 scale
based on structural patterns in the output preview text.

Extracted from scripts/.internal/gen_benchmark_chart.py for reuse
in CI regression tracking and other benchmark consumers.
"""

from __future__ import annotations

import re


def score_bootstrap(preview: str) -> int:
    """Score bootstrap output quality (0-5)."""
    score = 0
    if "Languages:" in preview or "languages" in preview.lower():
        score += 1
    if "Entry Points" in preview or "entry" in preview.lower():
        score += 1
    if "fan-in=" in preview or "Core Files" in preview:
        score += 1
    if "Directory Layout" in preview or "lines (" in preview:
        score += 1
    if "Tests" in preview or "test" in preview.lower():
        score += 1
    return min(score, 5)


def score_symbol_discovery(preview: str) -> int:
    """Score symbol discovery quality (0-5)."""
    score = 0
    if re.search(r"(class|struct|function|def|interface|type)\s+\w+", preview) and "No definitions" not in preview:
        score += 1
    if re.search(r":\d+-\d+", preview):
        score += 1
    if "Definitions" in preview and "References" in preview:
        score += 1
    if "[import]" in preview or "[call]" in preview:
        score += 1
    if re.search(r"References \(\d+\)", preview):
        score += 1
    return min(score, 5)


def score_dependency_tracing(preview: str) -> int:
    """Score dependency tracing quality (0-5)."""
    score = 0
    if "Imports (forward)" in preview:
        before_imported = preview.split("Imported by")[0] if "Imported by" in preview else preview
        if "(none)" not in before_imported:
            score += 1
    if "Imported by" in preview or "Imported by (reverse)" in preview:
        score += 1
    if re.search(r"depth=\d", preview):
        score += 1
    if "Impact analysis" in preview or "files affected" in preview:
        score += 1
    if re.search(r"^\s{4,}\S", preview, re.MULTILINE):
        score += 1
    return min(score, 5)


def score_architecture(preview: str) -> int:
    """Score architecture analysis quality (0-5)."""
    score = 0
    if "Community detection" in preview or "communities" in preview:
        score += 1
    m = re.search(r"(\d+) communities", preview)
    if m and int(m.group(1)) > 0:
        score += 1
    m2 = re.search(r"modularity=(0\.\d+)", preview)
    if m2 and float(m2.group(1)) > 0:
        score += 1
    if "Hub:" in preview or "hub" in preview.lower():
        score += 1
    if "hotspot" in preview.lower() or "complexity" in preview.lower():
        score += 1
    return min(score, 5)


def score_code_navigation(preview: str) -> int:
    """Score code navigation quality (0-5)."""
    score = 0
    if "No symbols found" not in preview and re.search(r"(class|method|function)\s+\w+", preview):
        score += 1
    if re.search(r"\b(class|method|function)\b", preview):
        score += 1
    if re.search(r"\(L\d+-\d+\)", preview):
        score += 1
    if "Cross-references" in preview or "References" in preview:
        score += 1
    if "[import]" in preview or "[call]" in preview or "Definitions (" in preview:
        score += 1
    return min(score, 5)


def score_semantic_search(preview: str, output_len: int) -> int:
    """Score semantic search quality (0-5)."""
    score = 0
    if "results" in preview.lower() or re.search(r"\d+\.", preview):
        score += 1
    if re.search(r"^\s*\d+\.\s", preview, re.MULTILINE):
        score += 1
    if re.search(r"\[(class|method|function|file)\]", preview):
        score += 1
    if re.search(r"score:\s*[\d.]+", preview):
        score += 1
    if output_len < 10000:
        score += 1
    return min(score, 5)


TASK_SCORERS = {
    "bootstrap": lambda d: score_bootstrap(d.get("output_preview", "")),
    "symbol_discovery": lambda d: score_symbol_discovery(d.get("output_preview", "")),
    "dependency_tracing": lambda d: score_dependency_tracing(d.get("output_preview", "")),
    "architecture": lambda d: score_architecture(d.get("output_preview", "")),
    "code_navigation": lambda d: score_code_navigation(d.get("output_preview", "")),
    "semantic_search": lambda d: score_semantic_search(
        d.get("output_preview", ""), d.get("output_len", 0)
    ),
}


def compute_repo_quality(repo_data: dict) -> float:
    """Compute average quality score (0-5) for a repo's benchmark data."""
    scores = []
    for task_name, scorer in TASK_SCORERS.items():
        task_data = repo_data.get(task_name, {})
        if task_data:
            scores.append(scorer(task_data))
    return sum(scores) / len(scores) if scores else 0.0
