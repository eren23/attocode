"""A single output budget, including all composed sections."""

from __future__ import annotations

import json
from copy import deepcopy

from mcp import types

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens
from attocode_intel.search_evidence import snippet_window


def bounded_text(text: str, max_tokens: int) -> tuple[str, bool]:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if count_tokens(text) <= max_tokens:
        return text, False
    suffix = "\n[Truncated; narrow the query or increase max_tokens.]"
    if count_tokens(suffix) >= max_tokens:
        suffix = ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid] + suffix) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + suffix, True


def compact_metadata(metadata: dict) -> dict:
    """Provenance is mandatory; detailed diagnostics live in capabilities."""
    result = {key: metadata[key] for key in
              ("workspace", "workspaces", "warming_workspaces", "source", "revision",
               "freshness", "truncated", "ranking")
              if key in metadata}
    coverage = metadata.get("coverage", {})
    analysis = metadata.get("analysis", {})
    if coverage:
        result["index"] = {key: coverage[key] for key in
                           ("phase", "parsed_files", "total_files", "discovery_truncated") if key in coverage}
        if coverage.get("excluded_checkout_roots"):
            result["index"]["excluded_checkout_roots_found"] = len(coverage["excluded_checkout_roots"])
        if coverage.get("excluded_checkout_roots_truncated"):
            result["index"]["excluded_checkout_roots_truncated"] = True
    if analysis:
        result["analysis"] = analysis.get("status", "partial")
        result["absence_proven"] = False
        result["precision"] = analysis.get("precision", {}).get("status", "not_requested")
    return result


def compact_result(metadata: dict, data) -> types.CallToolResult:
    # Text-only MCP works in clients that ignore structuredContent and avoids duplication
    # in clients that include both representations in the model's context.
    text = json.dumps({"metadata": metadata, "data": data}, ensure_ascii=False, separators=(",", ":"))
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def response_tokens(result: types.CallToolResult) -> int:
    return count_tokens(result.model_dump_json(exclude_none=True))


def bounded_bootstrap(metadata: dict, body: str, max_tokens: int) -> types.CallToolResult:
    """Fit whole bootstrap sections into the serialized MCP budget."""
    if not body.startswith("## "):
        return bounded_compact(metadata, {"result": body}, max_tokens)
    sections = ["## " + section for section in body.removeprefix("## ").split("\n\n## ")]
    compact = compact_metadata(metadata)
    probe_metadata = {**compact, "truncated": True}
    selected: list[str] = []
    omitted_search = False
    for section in sections:
        candidate = "\n\n".join([*selected, section])
        if response_tokens(compact_result(probe_metadata, {"result": candidate})) <= max_tokens:
            selected.append(section)
        elif section.startswith("## Relevant Code"):
            # Search hits are indivisible evidence. Never let the generic string
            # shortener turn a ranked result into a plausible-looking fragment.
            omission = "## Relevant Code\nTop match omitted; increase max_tokens."
            candidate = "\n\n".join([*selected, omission])
            if response_tokens(compact_result(probe_metadata, {"result": candidate})) <= max_tokens:
                selected.append(omission)
                omitted_search = True
            else:
                raise ValueError("max_tokens is too small to report omitted search evidence; increase it")
    if not selected:
        return bounded_compact(metadata, {"result": body}, max_tokens)
    compact["truncated"] = compact.get("truncated", False) or omitted_search or len(selected) != len(sections)
    return compact_result(compact, {"result": "\n\n".join(selected)})


def _search_truncation(metadata, data, upstream_truncated):
    """Describe the delivered page, retaining unrelated upstream truncation."""
    omitted = metadata.get("omitted", {})
    missing = data["ranking"].get("omitted_results_due_to_budget", 0)
    if "data.results" in omitted:
        if missing:
            omitted["data.results"] = missing
        else:
            omitted.pop("data.results")
    shortened = any(row.get("snippet_truncated") for row in data["results"])
    if not shortened:
        omitted.pop("data.results.snippet", None)
    if not omitted:
        metadata.pop("omitted", None)
    metadata["truncated"] = bool(upstream_truncated or missing or shortened or omitted)


def _fill_search_prefix(metadata, data, rows, total, max_tokens, *, upstream_truncated=False):
    """Recover consecutive omitted hits without shortening delivered evidence."""
    _search_truncation(metadata, data, upstream_truncated)
    while len(data["results"]) < len(rows):
        hit = deepcopy(rows[len(data["results"])])
        for short in (False, True):
            if short:
                if len(hit.get("snippet", "")) <= 32:
                    break
                hit.update(snippet_window(hit["snippet"], data.get("query", ""), 32,
                                          hit.get("snippet_start_line")))
                hit["snippet_truncated"] = True
            trial, provenance = deepcopy(data), deepcopy(metadata)
            trial["results"].append(hit)
            delivered = len(trial["results"])
            trial["ranking"]["delivered_count"] = delivered
            if total > delivered:
                trial["ranking"]["omitted_results_due_to_budget"] = total - delivered
            else:
                trial["ranking"].pop("omitted_results_due_to_budget", None)
            provenance["ranking"] = deepcopy(trial["ranking"])
            _search_truncation(provenance, trial, upstream_truncated)
            if response_tokens(compact_result(provenance, trial)) <= max_tokens:
                data, metadata = trial, provenance
                break
        else:
            return compact_result(metadata, data)
        if len(data["results"]) != delivered:
            return compact_result(metadata, data)
    return compact_result(metadata, data)



_SEARCH_SNIPPET_PROBES = 12
_SNIPPET_FIELDS = ("snippet", "snippet_start_line", "snippet_end_line", "snippet_truncated")


def _restore_search_snippets(result, originals, max_tokens, *, upstream_truncated=False):
    """Spend spare space without replacing any evidence on the fitted page.

    BPE counts and anchored windows need not be monotone. These are bounded
    probes, not a maximality search; every accepted page is checked in full.
    """
    page = json.loads(result.content[0].text)
    remaining = _SEARCH_SNIPPET_PROBES
    for index, original in enumerate(originals[:len(page["data"]["results"])]):
        if not remaining:
            break
        delivered = page["data"]["results"][index]
        if (not all(key in original and key in delivered for key in _SNIPPET_FIELDS)
                or {k: v for k, v in original.items() if k not in _SNIPPET_FIELDS}
                != {k: v for k, v in delivered.items() if k not in _SNIPPET_FIELDS}):
            continue
        body = original["snippet"]
        if (not isinstance(body, str) or not isinstance(delivered["snippet"], str)
                or len(body) <= len(delivered["snippet"])):
            continue

        def probe(window):
            nonlocal remaining, page, result
            remaining -= 1
            current = page["data"]["results"][index]
            if (len(window["snippet"]) <= len(current["snippet"])
                    or current["snippet"] not in window["snippet"]):
                return "skip"
            old_first, old_last = current["snippet_start_line"], current["snippet_end_line"]
            first, last = window["snippet_start_line"], window["snippet_end_line"]
            if old_first is None and old_last is None:
                if first is not None or last is not None:
                    return "skip"
            elif (not all(type(n) is int for n in (old_first, old_last, first, last))
                  or not 1 <= first <= old_first <= old_last <= last):
                return "skip"
            trial = deepcopy(page)
            trial["data"]["results"][index].update(window)
            _search_truncation(trial["metadata"], trial["data"], upstream_truncated)
            candidate = compact_result(trial["metadata"], trial["data"])
            if response_tokens(candidate) > max_tokens:
                return "over"
            page, result = trial, candidate
            return "fit"

        # The original window is the only source of additional text. Check it
        # first, then retain the best tested larger anchored window that fits.
        if probe({key: original[key] for key in _SNIPPET_FIELDS}) == "fit":
            continue
        lo, hi = len(delivered["snippet"]) + 1, len(body) - 1
        while lo <= hi and remaining:
            cap = (lo + hi) // 2
            window = snippet_window(body, page["data"].get("query", ""), cap,
                                    original["snippet_start_line"])
            window["snippet_truncated"] |= original["snippet_truncated"]
            if probe(window) == "over":
                hi = cap - 1
            else:
                lo = cap + 1
    return result


def bounded_search(metadata, data, max_tokens, *, all_results, follow_up=None):
    """Fit search delivery, reserving a progressing retry after final omissions."""
    payload = deepcopy(data)
    if follow_up is None:
        payload.pop("follow_up", None)
    # Keep the legacy fitted evidence as the floor for a newly added hint.
    # Recovery may add rows, but a continuation must not crowd out that floor.
    try:
        fitted = bounded_compact(metadata, payload, max_tokens, search_results=[])
    except ValueError:
        if "follow_up" not in payload:
            raise
        # An optional hint must not make an otherwise usable page fail.
        payload.pop("follow_up")
        fitted = bounded_compact(metadata, payload, max_tokens, search_results=[])
    protected = json.loads(fitted.content[0].text)
    total = len(payload["results"]) + payload["ranking"].get("omitted_results_due_to_budget", 0)
    result = _fill_search_prefix(protected["metadata"], protected["data"],
                                 all_results, total, max_tokens,
                                 upstream_truncated=metadata.get("truncated", False))
    delivered = json.loads(result.content[0].text)
    search_deeper = bool(follow_up and follow_up.get("reason") == "search_deeper")
    if (follow_up and "follow_up" not in payload
            and (search_deeper or delivered["data"]["ranking"].get("omitted_results_due_to_budget"))):
        payload["follow_up"] = follow_up
        try:
            with_hint = bounded_compact(metadata, payload, max_tokens, search_results=all_results)
        except ValueError:
            # The hint alone can exceed a tiny budget; retain the usable page.
            pass
        else:
            candidate = json.loads(with_hint.content[0].text)
            prefix = protected["data"]["results"]
            if candidate["data"]["results"][:len(prefix)] == prefix:
                result, delivered = with_hint, candidate
    if (not search_deeper
            and len(delivered["data"]["results"]) >= delivered["data"]["ranking"]["candidate_pool_count"]):
        delivered["data"].pop("follow_up", None)
        result = compact_result(delivered["metadata"], delivered["data"])
    return _restore_search_snippets(result, all_results, max_tokens,
                                    upstream_truncated=metadata.get("truncated", False))


def bounded_compact(metadata: dict, data, max_tokens: int, *, search_results=None) -> types.CallToolResult:
    """Bound the serialized result while retaining valid data and its provenance.

    The estimate uses the shared tokenizer, not a promise about every client's tokenizer.
    Only evidence collections and prose are shortened; paths, identifiers and flags survive.
    """
    metadata = compact_metadata(metadata)
    upstream_truncated = metadata.get("truncated", False)
    data = deepcopy(data)
    omitted = {}
    match data:
        case {"results": list() as result_rows,
              "ranking": {"candidate_pool_count": _, **ranking}}:
            search_result_count = len(result_rows)
            initial_search_omissions = ranking.get("omitted_results_due_to_budget", 0)
            recoverable = deepcopy(search_results if search_results is not None else result_rows)
        case _:
            search_result_count = None
            initial_search_omissions = 0
    while True:
        if search_result_count is not None:
            delivered = len(data["results"])
            if delivered < search_result_count:
                data["ranking"]["delivered_count"] = delivered
                data["ranking"]["omitted_results_due_to_budget"] = (
                    initial_search_omissions + search_result_count - delivered
                )
                metadata["ranking"] = deepcopy(data["ranking"])
                metadata["truncated"] = True
            _search_truncation(metadata, data, upstream_truncated)
        # Budget trimming can shorten a source page after inspection constructed its
        # continuation. Compute the next offset from the excerpt actually delivered.
        if (isinstance(data, dict) and isinstance(data.get("follow_up"), dict) and "next_source" in data["follow_up"]
                and "source" in data and "definition" in data):
            source, definition = data["source"], data["definition"]
            if source["end_line"] < source["start_line"]:
                raise ValueError("max_tokens is too small to include a complete source line; increase it")
            data["follow_up"]["next_source"] = ({
                "tool": "inspect_symbol", "symbol_name": definition["qualified_name"],
                "file_path": definition["file_path"], "line": definition["start_line"],
                "source_start_line": source["end_line"] + 1,
            } if source["end_line"] < definition["end_line"] else None)
        result = compact_result(metadata, data)
        if response_tokens(result) <= max_tokens:
            if search_result_count is not None:
                return _fill_search_prefix(metadata, data, recoverable,
                                           search_result_count + initial_search_omissions, max_tokens,
                                           upstream_truncated=upstream_truncated)
            return result
        if search_result_count is not None:
            # Search rows are identifiers plus optional prose. Spend the remaining
            # budget on shorter previews before sacrificing whole retrieved files.
            snippets = [hit for hit in data["results"]
                        if isinstance(hit, dict) and len(hit.get("snippet", "")) > 32]
            if snippets:
                hit = max(snippets, key=lambda item: len(item["snippet"]))
                hit.update(snippet_window(hit["snippet"], data.get("query", ""), len(hit["snippet"]) // 2,
                                          hit.get("snippet_start_line")))
                hit["snippet_truncated"] = True
                omitted["data.results.snippet"] = "shortened"
                metadata["truncated"] = True
                metadata["omitted"] = omitted
                continue
        choices = []

        def visit(value, parent=None, key=None, path="data", choices=choices):
            if isinstance(value, list) and value:
                # A partial match explanation would falsely imply that omitted
                # query terms did not match. Drop whole hits before splitting it.
                if key not in {"matched_terms", "match_fields"}:
                    choices.append((len(json.dumps(value)), parent, key, value, path))
            elif isinstance(value, str) and (key in {"text", "snippet", "result", "details", "description"}):
                if len(value) > 32:
                    choices.append((len(value), parent, key, value, path))
            elif isinstance(value, dict):
                if key == "languages" and value:
                    choices.append((len(json.dumps(value)), parent, key, value, path))
                else:
                    for child, item in value.items():
                        if child not in {"omitted", "follow_up", "definition"}:
                            visit(item, value, child, path + "." + child)

        wrapper = {"data": data}
        visit(data, wrapper, "data")
        if not choices:
            raise ValueError("max_tokens is too small to preserve provenance and evidence identifiers; increase it")
        _, parent, key, value, path = max(choices, key=lambda item: item[0])
        if isinstance(value, list):
            keep = len(value) // 2
            parent[key] = value[:keep]
            omitted[path] = omitted.get(path, 0) + len(value) - keep
        elif isinstance(value, dict):
            keep = len(value) // 2
            parent[key] = dict(list(value.items())[:keep])
            omitted[path] = omitted.get(path, 0) + len(value) - keep
        else:
            shortened = value[:len(value) // 2]
            if key == "snippet" and "snippet_truncated" in parent:
                query = data.get("query", "") if isinstance(data, dict) else ""
                parent.update(snippet_window(value, query, len(value) // 2,
                                             parent.get("snippet_start_line")))
                parent["snippet_truncated"] = True
                shortened = parent["snippet"]
            # Source excerpts must end on a complete line with accurate coordinates.
            if key == "text" and "start_line" in parent:
                shortened = shortened.rsplit("\n", 1)[0] if "\n" in shortened else ""
                parent["end_line"] = parent["start_line"] + len(shortened.splitlines()) - 1
                parent["truncated"] = True
            parent[key] = shortened
            omitted[path] = "shortened"
        data = wrapper["data"]
        metadata["truncated"] = True
        metadata["omitted"] = omitted
