"""Evaluation-only candidate; baseline until online controls demonstrate RED."""
from attocode_intel.search_evidence import snippet_window


def window_preview(body, query, max_chars, start_line):
    return snippet_window(body, query, max_chars, start_line)
