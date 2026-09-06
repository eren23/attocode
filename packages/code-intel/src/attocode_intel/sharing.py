"""Explicitly copy selected knowledge to a team; never send source files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def share(argv):
    parser = argparse.ArgumentParser(prog="attocode-code-intel share")
    parser.add_argument("--project", default=".")
    parser.add_argument("--learning", type=int, required=True, help="Local learning ID to copy")
    parser.add_argument("--server", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--token-env", default="ATTOCODE_API_KEY")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    from attocode_intel._internal.integrations.context.memory_store import MemoryStore

    root = Path(args.project).resolve()
    with MemoryStore(str(root)) as store:
        row = next((row for row in store.list_all() if row["id"] == args.learning), None)
    if row is None:
        parser.error("Active learning not found")
    payload = {
        key: row[key]
        for key in ("type", "description", "details", "scope", "confidence", "anchor_blob_oid")
    }
    payload["workspace"] = args.repo
    if args.dry_run:
        print(json.dumps({"operation": "record_learning", "arguments": payload}, indent=2))
        return
    from urllib.parse import urlsplit

    parsed = urlsplit(args.server)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        parser.error("Server must be an HTTP(S) URL without embedded credentials")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"Set {args.token_env} to a team API key with intelligence:write scope")
    import httpx

    response = httpx.post(
        args.server.rstrip("/") + "/api/v2/operations/record_learning",
        json=payload,
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))
