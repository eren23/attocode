"""Cross-reference-aware conflict advisor for AST reconciliation.

Uses CodeIntelService.cross_references_data() to determine blast radius
of symbol changes and advise the reconciler on which version to prefer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConflictAdvice:
    """Advice for resolving a merge conflict."""

    preferred_version: str  # "a" | "b" | "none"
    reason: str
    blast_radius_files: list[str] = field(default_factory=list)
    fan_in: int = 0


class ConflictAdvisor:
    """Advises on merge conflicts using cross-reference data.

    Uses fan-in (number of callers) to determine whether a symbol is
    a "public API" (fan-in > 5) or "private" (fan-in <= 2).

    Public APIs should preserve existing signatures; private symbols
    are safe to change.
    """

    def __init__(self, code_intel: Any) -> None:
        self._code_intel = code_intel

    def advise_conflict(
        self,
        symbol_name: str,
        file_path: str,
        version_a: str,
        version_b: str,
    ) -> ConflictAdvice:
        """Advise on which version to prefer for a conflicting symbol.

        Args:
            symbol_name: The conflicting symbol name.
            file_path: File containing the conflict.
            version_a: Content from agent A.
            version_b: Content from agent B.

        Returns:
            ConflictAdvice with a recommendation.
        """
        try:
            refs = self._code_intel.cross_references_data(symbol_name)
        except Exception as exc:
            logger.debug("cross_references_data failed for %s: %s", symbol_name, exc)
            return ConflictAdvice(
                preferred_version="none",
                reason=f"Could not analyze references for {symbol_name}",
            )

        if not isinstance(refs, dict):
            return ConflictAdvice(
                preferred_version="none",
                reason="No reference data available",
            )

        # Count callers (fan-in)
        callers = refs.get("references", refs.get("callers", []))
        if not isinstance(callers, list):
            callers = []
        fan_in = len(callers)

        # Collect blast-radius files
        blast_files: list[str] = []
        for ref in callers[:20]:
            fp = ref if isinstance(ref, str) else ref.get("file", "")
            if fp and fp not in blast_files:
                blast_files.append(fp)

        if fan_in > 5:
            # Public API — prefer version that preserves existing signature
            # Heuristic: version_a (first writer) is more likely to be
            # compatible since it was written against the original signature
            return ConflictAdvice(
                preferred_version="a",
                reason=(
                    f"Symbol '{symbol_name}' has {fan_in} callers (public API). "
                    f"Preferring version A to minimize blast radius."
                ),
                blast_radius_files=blast_files,
                fan_in=fan_in,
            )

        if fan_in <= 2:
            # Private symbol — either version is safe
            return ConflictAdvice(
                preferred_version="b",
                reason=(
                    f"Symbol '{symbol_name}' has {fan_in} callers (private). "
                    f"Either version is safe; preferring version B (latest)."
                ),
                blast_radius_files=blast_files,
                fan_in=fan_in,
            )

        # Moderate fan-in (3-5) — no strong preference
        return ConflictAdvice(
            preferred_version="none",
            reason=(
                f"Symbol '{symbol_name}' has {fan_in} callers (moderate). "
                f"Manual review recommended."
            ),
            blast_radius_files=blast_files,
            fan_in=fan_in,
        )
