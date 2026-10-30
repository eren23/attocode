"""Real10k source boundary; execute only on online CI workers."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.quality.scale_workload import generate_tree


@pytest.mark.parametrize("order", ["search_first", "ast_first", "old_cache_reopen"])
async def test_gateway_retains_last_source_beyond_old_ten_thousand_cap(tmp_path, monkeypatch, order):
    monkeypatch.setenv("ATTOCODE_INTEL_MAX_FILES", "100000")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    root = tmp_path / "workspace"
    identity = generate_tree(root, 10000)
    expected = {f"module_{i}.py" for i in range(10000)} | {"pyproject.toml"}
    assert {p.name for p in root.iterdir()} == expected
    target = (root / "module_9999.py").read_bytes()
    old_count = None
    if order == "old_cache_reopen":
        old = SemanticSearchManager(str(root))
        try:
            old._warm_candidate_indexes()
            conn = old._open_body_db()
            try:
                old_count = conn.execute("SELECT count(*) FROM kw_files").fetchone()[0]
            finally:
                conn.close()
            assert old_count == 10000
        finally:
            old.close()
    gateway = OperationGateway(str(root), "daily", watch=False)
    pages = []
    ast_coverage = None
    try:
        if order == "ast_first":
            response = await gateway.execute("search_symbols", {"name": "operation_9999"})
            assert not response.isError
            service = next(iter(gateway._stores.values()))["service"]
            ast = service._ast_service
            if ast._hydration_thread is not None:
                await asyncio.to_thread(ast._hydration_thread.join, 180)
            ast_coverage = ast.hydration_snapshot()
            assert ast_coverage["total_files"] == ast_coverage["parsed_files"] == 10001
        args = {"query": "operation_9999", "file_filter": "module_9999.py", "top_k": 5, "max_tokens": 2500}
        first = await gateway.execute_mcp("semantic_search", args)
        assert not first.isError
        pages.append(first.model_dump(mode="json"))
        assert len(gateway._stores) == 1
        service = next(iter(gateway._stores.values()))["service"]
        manager = service._semantic_search
        assert await asyncio.to_thread(manager.wait_for_body_index, 180)
        response = await gateway.execute_mcp("semantic_search", args)
        assert not response.isError and response_tokens(response) <= 2500
        pages.append(response.model_dump(mode="json"))
        page = json.loads(response.content[0].text)
        state = manager.candidate_diagnostics()
        conn = manager._open_body_db()
        try:
            inventories = {table: sorted(row[0] for row in conn.execute(f"SELECT file_path FROM {table}"))
                           for table in ("kw_files", "body_files")}
        finally:
            conn.close()
        if path := os.environ.get("ATTOCODE_EXPERIMENT_EVIDENCE"):
            record = {"order": order, "generator": identity, "expected_paths": sorted(expected),
                      "target_sha256": hashlib.sha256(target).hexdigest(), "target_bytes": len(target),
                      "old_cache_files": old_count, "inventories": inventories, "diagnostics": state,
                      "responses": pages, "ast_initialized": service._ast_service is not None,
                      "ast_coverage": ast_coverage}
            (Path(path) / f"coverage-{order}.json").write_text(json.dumps(record, sort_keys=True) + "\n")
        assert page["data"]["results"], f"coverage boundary: {order} lost module_9999.py"
        assert all(set(paths) == expected for paths in inventories.values())
        assert state["discovery_selected_files"] == state["discovery_discovered_files"] == 10001
        assert state["discovery_max_files"] == 100000 and state["discovery_truncated"] is False
        assert state["body_indexed_files"] == state["keyword_indexed_files"] == 10001
        hit = page["data"]["results"][0]
        assert hit["file_path"] == "module_9999.py" and "operation_9999" in hit["snippet"]
        assert hit["snippet"] in target.decode() and page["metadata"]["workspace"] == str(root.resolve())
        if order == "search_first":
            assert service._ast_service is None
    finally:
        await gateway.close()
    assert not gateway._workers and not gateway._stores
