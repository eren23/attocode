"""Bounded, contiguous search previews; lexical overlap is not semantic relevance."""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import replace
from pathlib import Path

from attocode_intel.focused_evidence import task_terms, terms


def source_body(result) -> str:
    """Remove the body index's location header, without dropping a source line."""
    first, separator, rest = result.text.partition("\n")
    if (result.start_line and separator
            and first == f"{result.file_path}:{result.start_line}-{result.end_line}"):
        return rest
    return result.text


def snippet_window(body: str, query: str, max_chars: int, start_line: int | None) -> dict:
    """Select an exact substring and report the source lines it intersects.

    Anchor on the earliest line with the most distinct positive query terms.
    Include one preceding line when it fits, then following lines within the cap.
    Metadata and zero-overlap source retain the old prefix. Long source lines
    can be partial, explicitly marked truncated, with their actual line number.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    begin = 0
    finish = min(len(body), max_chars)
    if start_line and body:
        positive, _ = task_terms(query)
        lines = body.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        scores = [len(positive & terms(line)) for line in lines]
        anchor = max(range(len(lines)), key=lambda index: (scores[index], -index))
        if scores[anchor]:
            begin = offsets[anchor]
            finish = offsets[anchor + 1]
            if finish - begin > max_chars:
                # Retain matching evidence even after a long single-line prefix.
                match = next((m for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*", lines[anchor])
                              if terms(m.group()) & positive), None)
                begin += max(0, match.start() - max_chars // 4) if match else 0
                finish = min(offsets[anchor + 1], begin + max_chars)
            else:
                if anchor and finish - offsets[anchor - 1] <= max_chars:
                    begin = offsets[anchor - 1]
                end = anchor + 1
                while end < len(lines) and offsets[end + 1] - begin <= max_chars:
                    end += 1
                finish = offsets[end]
    snippet = body[begin:finish]
    first_line = start_line + bisect_right(offsets, begin) - 1 if start_line and snippet else None
    last_line = start_line + bisect_left(offsets, finish) - 1 if start_line and snippet else None
    return {
        "snippet": snippet,
        "snippet_truncated": begin > 0 or finish < len(body),
        "snippet_start_line": first_line,
        "snippet_end_line": last_line,
    }


def search_snippet(result, query: str, max_chars: int) -> dict:
    return snippet_window(source_body(result), query, max_chars, result.start_line or None)


def hydrate_selected_sources(root_dir: str, results: list) -> list:
    """Attach current source to selected metadata hits without reranking.

    Read at most eight files / two MB per page, at most one MB per file.
    Missing, ambiguous, changing and out-of-workspace sources retain metadata.
    A class/method hit can only acquire that exact definition's source.
    """
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file

    root = Path(root_dir).resolve()
    sources = {}
    remaining = 2_000_000
    enriched = []
    for hit in results:
        enriched.append(hit)
        if hit.start_line or hit.chunk_type not in {"file", "class", "function", "method"}:
            continue
        try:
            path = (root / hit.file_path).resolve()
            if not path.is_relative_to(root):
                continue
            if path not in sources:
                if len(sources) >= 8 or remaining <= 0:
                    continue
                sources[path] = None
                before = path.stat()
                cap = min(1_000_000, remaining)
                if before.st_size > cap:
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(cap + 1)
                remaining -= len(raw)
                after = path.stat()
                if len(raw) > cap or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    continue
                content = raw.decode("utf-8")
                sources[path] = (content, content.splitlines(keepends=True))
            if sources[path] is None:
                continue
            content, lines = sources[path]
            if hit.chunk_type == "file":
                start, end = 1, len(lines)
            else:
                ast = parse_file(str(path), content)
                if hit.chunk_type == "class":
                    matches = [c for c in ast.classes if c.name == hit.name]
                elif hit.chunk_type == "method":
                    matches = [m for c in ast.classes for m in c.methods
                               if f"{c.name}.{m.name}" == hit.name]
                else:
                    matches = [f for f in ast.functions if f.name == hit.name]
                if len(matches) != 1:
                    continue
                start, end = matches[0].start_line, matches[0].end_line
            if 1 <= start <= end <= len(lines):
                enriched[-1] = replace(hit, text="".join(lines[start - 1:end]),
                                       start_line=start, end_line=end)
        except (OSError, UnicodeError, ValueError):
            continue
    return enriched
