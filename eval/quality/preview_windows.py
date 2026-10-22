"""Evaluation-only contiguous preview candidate; never installed as a default."""
from __future__ import annotations

from collections import Counter

from attocode_intel.focused_evidence import task_terms, terms
from attocode_intel.search_evidence import snippet_window as baseline_window


def window_preview(body, query, max_chars, start_line):
    """Replace only when a whole-line window adds positive terms without losing any."""
    baseline = baseline_window(body, query, max_chars, start_line)
    if not start_line or not body or len(body) <= max_chars:
        return baseline
    positive, _ = task_terms(query)
    old = positive & terms(baseline['snippet'])
    if not old or old == positive:
        return baseline
    lines = body.splitlines(keepends=True)
    offsets = [0]
    matches = []
    for line in lines:
        offsets.append(offsets[-1] + len(line))
        matches.append(positive & terms(line))
    counts = Counter()
    right = 0
    best = None
    best_size = len(old)
    for left in range(len(lines)):
        while right < len(lines) and offsets[right + 1] - offsets[left] <= max_chars:
            counts.update(matches[right])
            right += 1
        covered = counts.keys()
        if old < covered and len(covered) > best_size:
            best = left, right
            best_size = len(covered)
        if right == left:
            right += 1  # Oversized line: retain the existing partial-line fallback.
        else:
            for word in matches[left]:
                counts[word] -= 1
                if counts[word] == 0:
                    del counts[word]
    if best is None:
        return baseline
    left, right = best
    return {'snippet': body[offsets[left]:offsets[right]],
            'snippet_start_line': start_line + left,
            'snippet_end_line': start_line + right - 1,
            'snippet_truncated': left > 0 or right < len(lines)}
