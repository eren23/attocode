"""Shared pattern-matching iteration for security scanners.

Both the filesystem-based scanner (`scanner.py`) and the DB-backed scanner
(`security_scanner_db.py`) need to walk lines of a file, apply per-pattern
language filtering, skip comment lines (unless a pattern opts in via
``scan_comments``), and yield regex hits. This module centralises that logic.

Callers construct their own finding record types — this generator only
reports (line_number, line_text, matched_pattern).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from attocode.integrations.security.patterns import SecurityPattern


def iter_pattern_matches(
    content: str,
    patterns: Iterable[SecurityPattern],
    language: str,
) -> Iterator[tuple[int, str, SecurityPattern]]:
    """Yield (line_number, line, pattern) for every pattern hit in ``content``.

    Filters applied per line × pattern:
    - Language filter: skip patterns scoped to other languages.
    - Comment-line skip: lines starting with ``#`` or ``//`` are skipped
      unless the pattern sets ``scan_comments=True`` (e.g. for stego payload
      detectors that specifically want to scan comments).

    A line may yield multiple matches if it hits multiple patterns; each
    produces a separate tuple.
    """
    for line_no, line in enumerate(content.splitlines(), 1):
        stripped = line.lstrip()
        is_comment = stripped.startswith("#") or stripped.startswith("//")
        for pat in patterns:
            if pat.languages and language not in pat.languages:
                continue
            if is_comment and not pat.scan_comments:
                continue
            if pat.pattern.search(line):
                yield line_no, line, pat
