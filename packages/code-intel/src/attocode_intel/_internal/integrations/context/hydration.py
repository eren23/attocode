"""Progressive hydration state and tier classification.

Determines how aggressively to index a repository based on its size,
and tracks progressive indexing state across phases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

# Tier constants
TIER_SMALL = "small"
TIER_MEDIUM = "medium"
TIER_LARGE = "large"
TIER_HUGE = "huge"

# Tier boundaries (source file count)
_MEDIUM_THRESHOLD = 1_000
_LARGE_THRESHOLD = 5_000
_HUGE_THRESHOLD = 20_000

# Skeleton parse budgets per tier
_SKELETON_BUDGETS = {
    TIER_SMALL: None,    # None = parse all
    TIER_MEDIUM: 500,
    TIER_LARGE: 300,
    TIER_HUGE: 200,
}


def classify_tier(source_file_count: int) -> str:
    """Classify repo into a hydration tier based on source file count."""
    if source_file_count >= _HUGE_THRESHOLD:
        return TIER_HUGE
    if source_file_count >= _LARGE_THRESHOLD:
        return TIER_LARGE
    if source_file_count >= _MEDIUM_THRESHOLD:
        return TIER_MEDIUM
    return TIER_SMALL


def skeleton_budget(tier: str, total_files: int) -> int:
    """Return how many files to parse in Phase 1 (skeleton)."""
    budget = _SKELETON_BUDGETS.get(tier)
    if budget is None:
        return total_files  # small: parse all
    return min(budget, total_files)


@dataclass
class HydrationState:
    """Tracks progressive indexing state."""
    tier: str = TIER_SMALL
    total_files: int = 0
    parsed_files: int = 0
    reference_indexed_files: int = 0
    dep_graph_files: int = 0
    embedding_coverage: float = 0.0
    phase: str = "skeleton"              # skeleton | hydrating | ready
    started_at: float = field(default_factory=time.monotonic)

    @property
    def parse_coverage(self) -> float:
        if self.total_files == 0:
            return 1.0
        return self.parsed_files / self.total_files

    @property
    def reference_coverage(self) -> float:
        if self.total_files == 0:
            return 1.0
        return self.reference_indexed_files / self.total_files

    @property
    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "phase": self.phase,
            "total_files": self.total_files,
            "parsed_files": self.parsed_files,
            "parse_coverage": round(self.parse_coverage, 3),
            "reference_indexed_files": self.reference_indexed_files,
            "reference_coverage": round(self.reference_coverage, 3),
            "dep_graph_files": self.dep_graph_files,
            "embedding_coverage": round(self.embedding_coverage, 3),
            "elapsed_ms": round(self.elapsed_ms, 1),
        }
