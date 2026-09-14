"""Deterministic lexical evidence selection; excerpts are never stitched together."""
from __future__ import annotations

import io
import re
import tokenize
from collections import Counter

STOP_WORDS = frozenset({"a", "an", "and", "are", "as", "at", "be", "by", "code", "def", "do", "does", "for", "from", "function", "how", "in", "is", "it", "method", "of", "on", "or", "return", "self", "test", "tests", "the", "this", "to", "use", "value", "with"})


def terms(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower())
    return {word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 4 else word
            for word in words if len(word) > 2 and word not in STOP_WORDS}


def source_excerpts(source, definition, task_hint, *, preview_end=0):
    """Rank code identifiers, favor branches/assignments, and return disjoint ranges.

    This is a lexical aid, not semantic relevance or complete control-flow coverage.
    Python strings/comments do not become evidence just by repeating query words.
    """
    from attocode_intel.structural_evidence import structural_excerpts
    structured = structural_excerpts(source, definition, task_hint, preview_end)
    if structured is not None:
        return structured
    query = terms(task_hint)
    if not query:
        return []
    first, last = definition.start_line, min(definition.end_line, len(source))
    identifiers = {}
    if definition.file_path.endswith(".py"):
        try:
            for token in tokenize.generate_tokens(io.StringIO("\n".join(source)).readline):
                if token.type == tokenize.NAME and first <= token.start[0] <= last:
                    identifiers.setdefault(token.start[0], []).append(token.string)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass  # Only retain tokens actually read; do not invent coverage.
    else:
        for number in range(first, last + 1):
            line = source[number - 1].strip()
            if line.startswith(("#", "//", "/*", "*")):
                continue
            code = re.sub(r"(['\"]).*?\1", "", line).split("//", 1)[0]
            identifiers[number] = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", code)
    candidates = []
    for number, names in identifiers.items():
        if number <= preview_end:
            continue  # The caller already supplies this source verbatim.
        hits = Counter(term for name in names for term in terms(name) if term in query)
        if not hits:
            continue
        code = source[number - 1].strip()
        # Guards and stores often express behavior more directly than annotations.
        action = bool(re.match(r"(?:if|elif|else|return|case|throw|raise)\b", code) or
                      (not code.endswith(",") and re.search(r"(?<![=!<>])=(?!=)", code)))
        # Multiple participating identifiers help distinguish access from simple
        # initialization, but repetition is capped so annotations cannot dominate.
        score = sum(min(count, 2) for count in hits.values()) + 2 * int(action)
        candidates.append((number, score, set(hits)))
    selected, covered = [], set()
    while candidates and len(selected) < 3:
        number, _, hits = max(candidates, key=lambda row: (row[1] + len(row[2] - covered), -row[0]))
        start, end = max(first, preview_end + 1, number - 1), min(last, number + 3)
        selected.append({"file_path": definition.file_path, "start_line": start, "end_line": end,
                         "text": "\n".join(source[start - 1:end]), "matched_terms": sorted(hits), "context_ranges": [],
                         "context_incomplete": True, "context_relation": "structural context unavailable"})
        covered.update(hits)
        candidates = [row for row in candidates if min(last, row[0] + 3) < start or max(first, row[0] - 1) > end]
    # Keep relevance ordering, so output budgeting drops lower ranked whole excerpts.
    return selected
