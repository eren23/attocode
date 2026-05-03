"""Tests for LSP-enriched call graph (A6).

Covers:
* ``merge_lsp_results`` propagates ``caller_qualified_name`` so the
  in-memory call_edges map gets populated for LSP-sourced refs.
* ``ASTService.ingest_lsp_results`` resolves the queried symbol as the
  callee and the enclosing function at each result location as the
  caller, attributing the edge with ``source="lsp"``.
* Legacy 3-arg callback (no ``query`` info) keeps the prior behaviour
  and does not silently produce wrong call_edges.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from attocode.integrations.context.ast_service import ASTService
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)

# ---------------------------------------------------------------------------
# Minimal stand-ins for LSPLocation/Range/Position so we don't need a live
# server to drive the ingestion path.
# ---------------------------------------------------------------------------


@dataclass
class _Pos:
    line: int
    character: int = 0


@dataclass
class _Range:
    start: _Pos
    end: _Pos


@dataclass
class _Loc:
    uri: str
    range: _Range


def _loc(file_path: str, start_line: int, end_line: int | None = None) -> _Loc:
    return _Loc(
        uri=f"file://{file_path}",
        range=_Range(_Pos(start_line), _Pos(end_line if end_line is not None else start_line)),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_PY = (
    "def helper():\n"          # line 1
    "    return 1\n"           # line 2
    "\n"                        # line 3
    "def caller():\n"          # line 4
    "    return helper()\n"    # line 5
    "\n"                        # line 6
    "class Greeter:\n"         # line 7
    "    def hello(self):\n"   # line 8
    "        return helper()\n"  # line 9
)


@pytest.fixture
def ast_service():
    """Build an initialized ASTService over a small Python file."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "mod.py").write_text(SAMPLE_PY, encoding="utf-8")
        svc = ASTService(root_dir=tmp)
        svc.initialize_skeleton(indexing_depth="full")
        # Force-parse the file so the AST cache + definitions exist for
        # _resolve_symbol_at_line to find them.
        svc.ensure_file_parsed("mod.py")
        yield svc


# ---------------------------------------------------------------------------
# CrossRefIndex.merge_lsp_results — carries the new caller field
# ---------------------------------------------------------------------------


class TestMergeLspResultsCarriesCaller:
    def test_caller_field_survives_merge_and_populates_call_edges(self):
        idx = CrossRefIndex()
        # Pre-existing definitions so add_reference can resolve.
        idx.add_definition(SymbolLocation(
            name="helper", qualified_name="helper", kind="function",
            file_path="src/mod.py", start_line=1, end_line=2,
        ))
        idx.add_definition(SymbolLocation(
            name="caller", qualified_name="caller", kind="function",
            file_path="src/mod.py", start_line=4, end_line=5,
        ))

        added = idx.merge_lsp_results(
            "src/mod.py",
            definitions=[],
            references=[SymbolRef(
                symbol_name="helper",
                ref_kind="call",
                file_path="src/mod.py",
                line=5,
                caller_qualified_name="caller",
            )],
        )
        assert added == 1
        # Both source-tagged "lsp" AND fed into call_edges.
        refs = idx.get_references("helper")
        assert any(r.source == "lsp" for r in refs)
        assert idx.call_edges.get("caller") == {"helper"}
        assert idx.callers_of.get("helper") == {"caller"}


# ---------------------------------------------------------------------------
# ASTService.ingest_lsp_results — resolves callee from query position and
# caller from each result's enclosing function.
# ---------------------------------------------------------------------------


def _snapshot_edges(idx: CrossRefIndex) -> dict[str, set[str]]:
    """Deep-copy the call_edges map for before/after comparison — the
    regular tree-sitter indexing path runs during fixture setup, so we
    measure A6's contribution as a *delta*."""
    return {k: set(v) for k, v in idx.call_edges.items()}


class TestIngestLspResultsCallGraph:
    def test_references_with_query_info_records_lsp_source_refs(
        self, ast_service: ASTService,
    ):
        """With ``query`` info, LSP-sourced refs land against the *queried*
        callee (``helper``) carrying the *enclosing function* as caller,
        and the call-edges include the expected pairs (modulo whatever
        the regex pass already found)."""
        results = [_loc("mod.py", 4), _loc("mod.py", 7)]
        added = ast_service.ingest_lsp_results(
            tool_name="references",
            file_path="mod.py",
            results=results,
            query={"line": 0, "col": 4},  # 0-indexed: helper definition
        )
        # When the regular indexer already recorded the same (file, line)
        # pairs, ``merge_lsp_results`` dedupes — so ``added`` may be zero.
        # The substantive assertion is that the LSP-attributed edges
        # exist in the call graph.
        assert added >= 0
        idx = ast_service._index
        # Callee resolution worked: every LSP ref attributes to ``helper``.
        helper_refs_lsp = [
            r for r in idx.get_references("helper") if r.source == "lsp"
        ]
        assert helper_refs_lsp, idx.references
        callers = {r.caller_qualified_name for r in helper_refs_lsp}
        assert {"caller", "Greeter.hello"} <= callers, callers
        # And the call graph reflects the same edges.
        assert "helper" in idx.call_edges.get("caller", set())
        assert "helper" in idx.call_edges.get("Greeter.hello", set())

    def test_legacy_callback_without_query_adds_no_new_edges(
        self, ast_service: ASTService,
    ):
        """3-arg callers (no ``query``) preserve the prior behaviour: refs
        land with the enclosing function as ``symbol_name`` and no caller
        attribution — so the LSP path itself adds no new call_edges."""
        before = _snapshot_edges(ast_service._index)
        ast_service.ingest_lsp_results(
            tool_name="references",
            file_path="mod.py",
            results=[_loc("mod.py", 4)],
        )
        after = _snapshot_edges(ast_service._index)
        assert before == after, (before, after)

    def test_definition_results_dont_contribute_to_call_edges(
        self, ast_service: ASTService,
    ):
        """Definition results don't feed call_edges even with query info."""
        before = _snapshot_edges(ast_service._index)
        ast_service.ingest_lsp_results(
            tool_name="definition",
            file_path="mod.py",
            results=[_loc("mod.py", 0, 1)],
            query={"line": 0, "col": 4},
        )
        after = _snapshot_edges(ast_service._index)
        assert before == after

    def test_legacy_lsp_ref_does_not_overwrite_tree_sitter_entry(
        self, ast_service: ASTService,
    ):
        """I2 — when the LSP-sourced ref has no caller_qualified_name
        (legacy callback or non-references tool), it must NOT overwrite
        an existing tree-sitter ref at the same (file, line) — the
        tree-sitter ``symbol_name`` is the actual callee while the
        LSP-fallback ``symbol_name`` would be the enclosing function,
        which would invert the call_edges direction."""
        idx = ast_service._index
        # Pre-populate a tree-sitter ref for ``helper`` at line 5
        # (matches the SAMPLE_PY ``return helper()`` line).
        helper_refs_before = [r for r in idx.get_references("helper") if r.source == "tree-sitter"]
        assert helper_refs_before, "fixture should have produced a tree-sitter ref"

        # Run an LSP ingest with a result at line 5 BUT no query info —
        # the legacy fallback would set symbol_name=enclosing fn.
        ast_service.ingest_lsp_results(
            tool_name="references",
            file_path="mod.py",
            results=[_loc("mod.py", 4)],  # 0-indexed: line 5
        )

        # The tree-sitter ref for 'helper' at line 5 must still exist.
        helper_refs_after = [r for r in idx.get_references("helper") if r.source == "tree-sitter"]
        assert helper_refs_after, "tree-sitter ref was overwritten by legacy LSP fallback"

    def test_query_pointing_at_unknown_symbol_does_not_crash(
        self, ast_service: ASTService,
    ):
        """Out-of-range query line: callee resolves to "" and we fall back
        to the legacy path — no new call_edges, no crash."""
        before = _snapshot_edges(ast_service._index)
        added = ast_service.ingest_lsp_results(
            tool_name="references",
            file_path="mod.py",
            results=[_loc("mod.py", 4)],
            query={"line": 999, "col": 0},
        )
        assert added >= 0
        after = _snapshot_edges(ast_service._index)
        assert before == after
