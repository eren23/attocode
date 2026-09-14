"""Workspace-scoped reference continuations over immutable result snapshots."""
from __future__ import annotations

import json
import secrets
from collections import OrderedDict
from copy import deepcopy

from attocode_intel.output import bounded_compact, compact_result


def scope(context, args):
    tracker = context.stores.get("freshness")
    return (context.workspace, context.source, context.revision, getattr(tracker, "generation", 0),
            args["symbol_name"], args.get("file_path"), args.get("line"))


def continuation(context, args):
    cursor = args.get("cursor")
    if not cursor:
        return None
    pages = context.stores.get("reference_pages", {})
    record = pages.get(cursor)
    if record is None or record["scope"] != scope(context, args):
        raise ValueError("Reference cursor expired or belongs to another query; restart without cursor")
    return record


def paginate(context, args, payload, metadata, budget, compact):
    size = args.get("page_size") if args.get("page_size") is not None else 20
    if not 1 <= size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    record = continuation(context, args)
    offset = record["offset"] if record else 0
    if record:
        payload, metadata = record["payload"], record["metadata"]
    rows = payload["references"]
    token = secrets.token_hex(16)
    page = {**payload, "references": rows[offset:offset + size],
            "next_cursor": token, "total_references": len(rows)}
    metadata = {**metadata, "truncated": offset + size < len(rows)}
    if compact:
        rendered = json.loads(bounded_compact(metadata, page, budget).content[0].text)
        page = rendered["data"]
        compact_meta = rendered["metadata"]
    count = len(page["references"])
    if count == 0 and offset < len(rows):
        raise ValueError("max_tokens is too small for one reference and provenance; increase it")
    more = offset + count < len(rows)
    page["next_cursor"] = token if more else None
    if more:
        pages = context.stores.setdefault("reference_pages", OrderedDict())
        pages[token] = {"scope": scope(context, args), "offset": offset + count,
                        "payload": payload, "metadata": metadata}
        while len(pages) > 64:
            pages.popitem(last=False)
    if compact:
        compact_meta["truncated"] = compact_meta.get("truncated", False) or more
        return compact_result(compact_meta, page)
    return deepcopy(page), metadata
