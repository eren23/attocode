"""Extract required literal trigrams from regex patterns.

Uses Python's sre_parse to decompose regex into literal runs,
then extracts 3-character overlapping sequences. Returns an empty
list for patterns that can't be meaningfully decomposed (e.g., ".*").
"""

from __future__ import annotations

import sys
import zlib

# sre_parse is deprecated in 3.11+ in favor of re._parser
if sys.version_info >= (3, 11):
    import re._parser as sre_parse  # type: ignore[import-not-found]
else:
    import sre_parse  # type: ignore[import-deprecated]


def _trigram_hash(tri: bytes) -> int:
    """CRC32 of a 3-byte sequence, masked to u32."""
    return zlib.crc32(tri) & 0xFFFFFFFF


def _extract_literal_runs(parsed: sre_parse.SubPattern) -> list[str]:
    """Walk sre_parse tree and extract contiguous literal character runs.

    Only literals unconditionally required in every match are collected.
    Branches (|), optional quantifiers, wildcards, and character classes
    flush the current run without contributing literals.
    """
    runs: list[str] = []
    current: list[str] = []

    for op, av in parsed:
        if op == sre_parse.LITERAL:
            current.append(chr(av))

        elif op == sre_parse.NOT_LITERAL:
            # Negated literal — not a known character, flush
            if current:
                runs.append("".join(current))
                current = []

        elif op == sre_parse.SUBPATTERN:
            # av = (group_id, add_flags, del_flags, sub_pattern)
            if current:
                runs.append("".join(current))
                current = []
            sub_runs = _extract_literal_runs(av[-1])
            runs.extend(sub_runs)

        elif op == sre_parse.BRANCH:
            # (None, [branch1, branch2, ...]) — flush, attempt common prefix
            if current:
                runs.append("".join(current))
                current = []
            branches = av[1]
            if branches:
                branch_run_lists = [_extract_literal_runs(b) for b in branches]
                first_runs = [brl[0] if brl else "" for brl in branch_run_lists]
                min_len = min(len(r) for r in first_runs)
                common: list[str] = []
                for i in range(min_len):
                    if all(r[i] == first_runs[0][i] for r in first_runs):
                        common.append(first_runs[0][i])
                    else:
                        break
                if len(common) >= 3:
                    runs.append("".join(common))

        elif op in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            # av = (min_count, max_count, sub_pattern)
            if current:
                runs.append("".join(current))
                current = []
            min_count, _max_count, sub_pattern = av
            if min_count >= 1:
                sub_runs = _extract_literal_runs(sub_pattern)
                runs.extend(sub_runs)
            # min_count == 0 means the sub_pattern may not appear at all

        elif op == sre_parse.AT:
            # Anchors (^, $, \b, \B) — no character consumed, skip
            pass

        elif op == sre_parse.IN:
            # Character class [abc\d] — could be any listed char, flush
            if current:
                runs.append("".join(current))
                current = []

        else:
            # Wildcard, backreference, lookahead/lookbehind — flush
            if current:
                runs.append("".join(current))
                current = []

    if current:
        runs.append("".join(current))

    # Only keep runs that yield at least one trigram (need >= 3 chars)
    return [r for r in runs if len(r) >= 3]


def extract_required_trigrams(
    pattern: str,
    *,
    case_insensitive: bool = False,
    include_literals: bool = False,
) -> list[int] | tuple[list[int], list[str]]:
    """Extract trigram hashes that MUST appear in any string matching the regex.

    Returns a list of CRC32 trigram hashes (u32). An empty list means the
    pattern has no extractable required trigrams and the caller should fall
    back to brute-force scanning.

    Args:
        pattern: A Python regex pattern string.
        case_insensitive: When True, trigrams are extracted from the
            lowercased literal runs so they match lowercased content
            used during case-insensitive index queries.
        include_literals: When True, also return the human-readable trigram
            strings alongside hashes (for diagnostics / explain mode).

    Returns:
        When *include_literals* is False (default): deduplicated list of
        trigram hashes, possibly empty.
        When *include_literals* is True: ``(hashes, literals)`` tuple where
        *literals* contains the decoded trigram strings in the same order.
    """
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return ([], []) if include_literals else []

    try:
        literal_runs = _extract_literal_runs(parsed)
    except Exception:
        return ([], []) if include_literals else []

    if case_insensitive:
        literal_runs = [run.lower() for run in literal_runs]

    seen: set[int] = set()
    hashes: list[int] = []
    literals: list[str] = []
    for run in literal_runs:
        run_bytes = run.encode("utf-8", errors="replace")
        for i in range(len(run_bytes) - 2):
            tri = run_bytes[i : i + 3]
            h = _trigram_hash(tri)
            if h not in seen:
                seen.add(h)
                hashes.append(h)
                if include_literals:
                    literals.append(tri.decode("utf-8", errors="replace"))

    if include_literals:
        return (hashes, literals)
    return hashes


def longest_literal_run(pattern: str) -> str:
    """Return the longest contiguous literal string extractable from *pattern*.

    Useful for diagnostics and for estimating whether the trigram filter
    is likely to be selective (short runs yield many candidate files).
    """
    try:
        parsed = sre_parse.parse(pattern)
        runs = _extract_literal_runs(parsed)
    except Exception:
        return ""
    return max(runs, key=len) if runs else ""
