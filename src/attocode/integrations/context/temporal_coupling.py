"""Temporal coupling analysis — git-history-based code intelligence.

Builds a co-change matrix from git history to identify:
- Files that frequently change together (change coupling)
- High-churn hotspots (most-modified files)
- Merge risk prediction (temporal + structural coupling)
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

logger = logging.getLogger(__name__)

# Minimum commits to consider a coupling signal meaningful
_MIN_COCHANGES = 2
# Cache staleness threshold (seconds)
_CACHE_TTL = 3600  # 1 hour


@dataclass(slots=True)
class CoChangeEntry:
    """A file that co-changes with a target file."""

    path: str
    coupling_score: float      # co_changes / min(changes_a, changes_b)
    co_changes: int            # times changed in same commit
    individual_changes: int    # total changes to this file


@dataclass(slots=True)
class ChurnEntry:
    """A file's churn metrics over a time window."""

    path: str
    commits: int
    authors: list[str]
    lines_added: int
    lines_removed: int
    churn_score: float         # normalized change intensity


@dataclass(slots=True)
class MergeRiskEntry:
    """A predicted file change from merge risk analysis."""

    path: str
    reason: str                # "temporal" | "structural" | "both"
    confidence: float
    coupling_score: float | None
    structural_distance: int | None


@dataclass
class TemporalCouplingAnalyzer:
    """Analyzes git history to find temporal coupling patterns.

    Usage::

        analyzer = TemporalCouplingAnalyzer(project_dir="/path/to/repo")
        coupling = analyzer.get_change_coupling("src/main.py", days=90)
        hotspots = analyzer.get_churn_hotspots(days=90)
        risk = analyzer.get_merge_risk(["src/auth.py"], dep_graph=graph)
    """

    project_dir: str

    # Cached analysis results
    _commit_files: list[dict] = field(default_factory=list, repr=False)
    _file_commits: dict[str, int] = field(default_factory=dict, repr=False)
    _co_change_matrix: dict[tuple[str, str], int] = field(default_factory=dict, repr=False)
    _file_churn: dict[str, dict] = field(default_factory=dict, repr=False)
    _cache_window_days: int = field(default=0, repr=False)
    _cache_time: float = field(default=0.0, repr=False)

    def _run_git(self, args: list[str]) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.debug("git %s failed: %s", " ".join(args), result.stderr.strip())
                return ""
            return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.debug("git command error: %s", exc)
            return ""

    def _ensure_cache(self, days: int) -> None:
        """Populate the co-change matrix cache if stale or wrong window."""
        now = time.time()
        if (
            self._cache_window_days == days
            and self._cache_time > 0
            and (now - self._cache_time) < _CACHE_TTL
        ):
            return

        self._build_cache(days)
        self._cache_window_days = days
        self._cache_time = now

    def _build_cache(self, days: int) -> None:
        """Parse git log and build the co-change matrix."""
        raw = self._run_git([
            "log",
            f"--since={days} days ago",
            "--numstat",
            "--format=%H|%an|%aI",
        ])
        if not raw.strip():
            self._commit_files = []
            self._file_commits = {}
            self._co_change_matrix = {}
            self._file_churn = {}
            return

        # Parse commits
        commits: list[dict] = []
        current: dict | None = None

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            # Header: sha|author|date
            if "|" in line and line.count("|") >= 2:
                parts = line.split("|", 2)
                if len(parts) == 3 and len(parts[0]) >= 7:
                    if current is not None:
                        commits.append(current)
                    current = {
                        "sha": parts[0],
                        "author": parts[1],
                        "date": parts[2][:10] if len(parts[2]) >= 10 else parts[2],
                        "files": [],
                    }
                    continue

            # Numstat: added\tremoved\tpath
            if current is not None and "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 3:
                    try:
                        added = int(parts[0]) if parts[0] != "-" else 0
                        removed = int(parts[1]) if parts[1] != "-" else 0
                    except ValueError:
                        continue
                    file_path = parts[2]
                    if " => " in file_path:
                        file_path = file_path.split(" => ")[-1].rstrip("}")
                        if "{" in file_path:
                            file_path = file_path.replace("{", "").replace("}", "")
                    current["files"].append({
                        "path": file_path,
                        "added": added,
                        "removed": removed,
                    })

        if current is not None:
            commits.append(current)

        self._commit_files = commits

        # Build file commit counts
        file_commits: dict[str, int] = defaultdict(int)
        file_churn: dict[str, dict] = defaultdict(
            lambda: {"commits": 0, "authors": set(), "added": 0, "removed": 0}
        )

        for commit in commits:
            file_paths = [f["path"] for f in commit["files"]]
            for f in commit["files"]:
                fp = f["path"]
                file_commits[fp] += 1
                churn = file_churn[fp]
                churn["commits"] += 1
                churn["authors"].add(commit["author"])
                churn["added"] += f["added"]
                churn["removed"] += f["removed"]

        self._file_commits = dict(file_commits)

        # Build co-change matrix
        co_changes: dict[tuple[str, str], int] = defaultdict(int)
        for commit in commits:
            file_paths = sorted(set(f["path"] for f in commit["files"]))
            # Only count pairs (skip mega-commits with > 50 files — likely merges/renames)
            if len(file_paths) > 50:
                continue
            for a, b in combinations(file_paths, 2):
                co_changes[(a, b)] += 1

        self._co_change_matrix = dict(co_changes)

        # Finalize churn (convert author sets to sorted lists)
        self._file_churn = {
            fp: {
                "commits": c["commits"],
                "authors": sorted(c["authors"]),
                "added": c["added"],
                "removed": c["removed"],
            }
            for fp, c in file_churn.items()
        }

    def get_change_coupling(
        self,
        file_path: str,
        *,
        days: int = 90,
        min_coupling: float = 0.3,
        top_k: int = 20,
    ) -> list[CoChangeEntry]:
        """Find files that frequently co-change with *file_path*.

        Args:
            file_path: Target file (relative to project root).
            days: Time window in days.
            min_coupling: Minimum coupling score to include (0.0-1.0).
            top_k: Maximum results to return.
        """
        self._ensure_cache(days)

        target_changes = self._file_commits.get(file_path, 0)
        if target_changes == 0:
            return []

        results: list[CoChangeEntry] = []
        for (a, b), count in self._co_change_matrix.items():
            other = None
            if a == file_path:
                other = b
            elif b == file_path:
                other = a
            if other is None:
                continue

            if count < _MIN_COCHANGES:
                continue

            other_changes = self._file_commits.get(other, 1)
            score = count / min(target_changes, other_changes)

            if score >= min_coupling:
                results.append(CoChangeEntry(
                    path=other,
                    coupling_score=round(score, 3),
                    co_changes=count,
                    individual_changes=other_changes,
                ))

        results.sort(key=lambda e: -e.coupling_score)
        return results[:top_k]

    def get_churn_hotspots(
        self,
        *,
        days: int = 90,
        top_n: int = 20,
    ) -> list[ChurnEntry]:
        """Rank files by change frequency.

        Args:
            days: Time window in days.
            top_n: Number of top files to return.
        """
        self._ensure_cache(days)

        if not self._file_churn:
            return []

        # Compute churn score: commits × (1 + log(added + removed + 1))
        import math
        entries: list[ChurnEntry] = []
        max_commits = max(c["commits"] for c in self._file_churn.values())

        for fp, churn in self._file_churn.items():
            total_lines = churn["added"] + churn["removed"]
            raw_score = churn["commits"] * (1 + math.log1p(total_lines))
            # Normalize to 0-1 range
            normalized = raw_score / (max_commits * (1 + math.log1p(
                max(c["added"] + c["removed"] for c in self._file_churn.values())
            ))) if max_commits > 0 else 0.0

            entries.append(ChurnEntry(
                path=fp,
                commits=churn["commits"],
                authors=churn["authors"],
                lines_added=churn["added"],
                lines_removed=churn["removed"],
                churn_score=round(normalized, 4),
            ))

        entries.sort(key=lambda e: -e.churn_score)
        return entries[:top_n]

    def get_churn_score(self, file_path: str, *, days: int = 90) -> float:
        """Return normalized churn score for a single file (0.0-1.0).

        Used by hotspot integration in helpers.py.
        """
        self._ensure_cache(days)
        churn = self._file_churn.get(file_path)
        if not churn or not self._file_churn:
            return 0.0

        import math
        total_lines = churn["added"] + churn["removed"]
        raw_score = churn["commits"] * (1 + math.log1p(total_lines))
        max_raw = max(
            c["commits"] * (1 + math.log1p(c["added"] + c["removed"]))
            for c in self._file_churn.values()
        )
        return round(raw_score / max_raw, 4) if max_raw > 0 else 0.0

    def get_merge_risk(
        self,
        files: list[str],
        *,
        days: int = 90,
        dep_graph_forward: dict[str, set[str]] | None = None,
        dep_graph_reverse: dict[str, set[str]] | None = None,
        min_confidence: float = 0.3,
        top_k: int = 20,
    ) -> list[MergeRiskEntry]:
        """Predict which files will likely need changes alongside *files*.

        Combines temporal coupling (co-change matrix) with structural
        coupling (dependency graph) for a unified risk assessment.

        Args:
            files: Files being modified.
            days: Time window for temporal coupling.
            dep_graph_forward: file -> set of files it imports (optional).
            dep_graph_reverse: file -> set of files that import it (optional).
            min_confidence: Minimum confidence to include.
            top_k: Maximum results.
        """
        self._ensure_cache(days)
        file_set = set(files)
        predictions: dict[str, MergeRiskEntry] = {}

        # Temporal predictions
        for fp in files:
            coupling = self.get_change_coupling(
                fp, days=days, min_coupling=0.2, top_k=50,
            )
            for entry in coupling:
                if entry.path in file_set:
                    continue
                confidence = entry.coupling_score * 0.8  # temporal weight
                if entry.path in predictions:
                    existing = predictions[entry.path]
                    if confidence > existing.confidence:
                        existing.confidence = round(confidence, 3)
                    if existing.reason == "structural":
                        existing.reason = "both"
                    existing.coupling_score = entry.coupling_score
                else:
                    predictions[entry.path] = MergeRiskEntry(
                        path=entry.path,
                        reason="temporal",
                        confidence=round(confidence, 3),
                        coupling_score=entry.coupling_score,
                        structural_distance=None,
                    )

        # Structural predictions (1-hop)
        if dep_graph_forward or dep_graph_reverse:
            fwd = dep_graph_forward or {}
            rev = dep_graph_reverse or {}
            for fp in files:
                neighbors: set[str] = set()
                neighbors.update(fwd.get(fp, set()))
                neighbors.update(rev.get(fp, set()))
                for neighbor in neighbors:
                    if neighbor in file_set:
                        continue
                    confidence = 0.5  # structural base confidence
                    if neighbor in predictions:
                        existing = predictions[neighbor]
                        if existing.reason == "temporal":
                            existing.reason = "both"
                            existing.confidence = round(
                                min(1.0, existing.confidence + confidence * 0.3), 3,
                            )
                        existing.structural_distance = 1
                    else:
                        predictions[neighbor] = MergeRiskEntry(
                            path=neighbor,
                            reason="structural",
                            confidence=round(confidence, 3),
                            coupling_score=None,
                            structural_distance=1,
                        )

        results = [e for e in predictions.values() if e.confidence >= min_confidence]
        results.sort(key=lambda e: -e.confidence)
        return results[:top_k]
