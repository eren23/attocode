"""Repeat real local MCP lifecycle operations without agents or models."""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import tempfile
import threading
import time
from pathlib import Path

import psutil
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.quality.runner import write_json


def percentile(values, fraction=.95):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


async def probe(root: Path, cycles=20):
    source = root / "worker.py"
    source.write_text("def original_symbol():\n    return 'needle_evidence'\n")
    process = psutil.Process()
    existing_threads = {t.ident for t in threading.enumerate()}
    records = []
    for cycle in range(cycles):
        gateway = OperationGateway(str(root), "daily", watch=cycle % 2 == 0, max_workspaces=1)
        row = {"cycle": cycle, "watch": gateway.watch}
        try:
            start = time.monotonic()
            result = await gateway.execute_mcp("inspect_symbol", {"symbol_name": "original_symbol", "file_path": "worker.py"})
            row["lookup_seconds"] = time.monotonic() - start
            assert not result.isError and "needle_evidence" in result.content[0].text
            assert response_tokens(result) <= 2000
            source.write_text("def original_symbol():\n    return 'needle_evidence'\ndef changed_symbol():\n    return 2\n")
            changed = await gateway.execute_mcp("search_symbols", {"name": "changed_symbol"})
            assert "changed_symbol" in changed.content[0].text and not changed.isError
            # Search warms asynchronously; a truthful 'warming' response is
            # not a retrieval miss. Readiness has its own bounded deadline.
            warming = time.monotonic()
            while True:
                ready = await gateway.execute_mcp("semantic_search", {"query": "needle evidence", "top_k": 5})
                assert not ready.isError, ready.content[0].text
                status = json.loads(ready.content[0].text)["data"]["ranking"]["index"]["status"]
                if status == "ready":
                    break
                assert time.monotonic() - warming < 5, "Search warmup exceeded five seconds"
                await asyncio.sleep(.05)
            row["warmup_seconds"] = time.monotonic() - warming
            start = time.monotonic()
            search = await gateway.execute_mcp("semantic_search", {"query": "needle evidence", "top_k": 5})
            row["search_seconds"] = time.monotonic() - start
            assert not search.isError and "worker.py" in search.content[0].text, search.content[0].text
            assert response_tokens(search) <= 2000
            source.write_text("def original_symbol():\n    return 'needle_evidence'\n")
            removed = await gateway.execute_mcp("search_symbols", {"name": "changed_symbol"})
            assert not any(r["name"] == "changed_symbol" for r in json.loads(removed.content[0].text)["data"])
            moved = root / "renamed.py"
            source.rename(moved)
            renamed = await gateway.execute_mcp("inspect_symbol", {"symbol_name": "original_symbol", "file_path": "renamed.py"})
            assert json.loads(renamed.content[0].text)["data"]["definition"]["file_path"] == "renamed.py"
            moved.unlink()
            deleted = await gateway.execute_mcp("search_symbols", {"name": "original_symbol"})
            assert not any(r["name"] == "original_symbol" for r in json.loads(deleted.content[0].text)["data"])
            source.write_text("def original_symbol():\n    return 'needle_evidence'\n")
        finally:
            await gateway.close()
        assert not gateway._workers and not gateway._stores
        gc.collect()
        row["fds_after_close"] = process.num_fds() if hasattr(process, "num_fds") else None
        row["rss_after_close"] = process.memory_info().rss
        records.append(row)
    fds = [r["fds_after_close"] for r in records if r["fds_after_close"] is not None]
    leaked_threads = [t.name for t in threading.enumerate()
                      if t.ident not in existing_threads and t.name.startswith(
                          ("intel-workspace", "intel-watch", "semantic-reindex", "bg-embedding", "lexical-candidate-indexer"))]
    assert not leaked_threads, leaked_threads
    assert not fds or max(fds[1:] or fds) <= fds[0] + 5, fds
    lookup = percentile([r["lookup_seconds"] for r in records[1:] or records])
    search = percentile([r["search_seconds"] for r in records[1:] or records])
    assert lookup < 1, lookup
    assert search < 2, search
    return {"passed": True, "cycles": records, "lookup_p95_seconds": lookup,
            "search_p95_seconds": search, "workload": "one-file edit/restart lifecycle",
            "leaked_threads": leaked_threads, "model_runs": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="quality-lifecycle-") as tmp:
        report = asyncio.run(probe(Path(tmp)))
    write_json(args.output, report)


if __name__ == "__main__":
    main()
