"""A single output budget, including all composed sections."""

from __future__ import annotations

import json
from copy import deepcopy

from mcp import types

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens


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
              ("workspace", "workspaces", "source", "revision", "freshness", "truncated", "ranking")
              if key in metadata}
    coverage = metadata.get("coverage", {})
    analysis = metadata.get("analysis", {})
    if coverage:
        result["index"] = {key: coverage[key] for key in
                           ("phase", "parsed_files", "total_files", "discovery_truncated") if key in coverage}
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


def bounded_compact(metadata: dict, data, max_tokens: int) -> types.CallToolResult:
    """Bound the serialized result while retaining valid data and its provenance.

    The estimate uses the shared tokenizer, not a promise about every client's tokenizer.
    Only evidence collections and prose are shortened; paths, identifiers and flags survive.
    """
    metadata = compact_metadata(metadata)
    data = deepcopy(data)
    omitted = {}
    while True:
        # Budget trimming can shorten a source page after inspection constructed its
        # continuation. Compute the next offset from the excerpt actually delivered.
        if (isinstance(data, dict) and isinstance(data.get("follow_up"), dict) and "next_source" in data["follow_up"]
                and "source" in data and "definition" in data):
            source, definition = data["source"], data["definition"]
            if source["end_line"] < source["start_line"]:
                raise ValueError("max_tokens is too small to include a complete source line; increase it")
            data["follow_up"]["next_source"] = ({
                "tool": "inspect_symbol", "symbol_name": definition["name"],
                "file_path": definition["file_path"], "line": definition["start_line"],
                "source_start_line": source["end_line"] + 1,
            } if source["end_line"] < definition["end_line"] else None)
        result = compact_result(metadata, data)
        if response_tokens(result) <= max_tokens:
            return result
        choices = []

        def visit(value, parent=None, key=None, path="data", choices=choices):
            if isinstance(value, list) and value:
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
