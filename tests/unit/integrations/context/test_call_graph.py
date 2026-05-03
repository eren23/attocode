"""Tests for the function-level call graph in CrossRefIndex + IndexStore.

Covers:
* SymbolRef carrying caller_qualified_name auto-populates call_edges.
* get_callees / get_callers traversal at depth 1 and N (with cycles).
* remove_file scrubs edges keyed on callers from that file.
* IndexStore round-trips caller_qualified_name and survives reload via
  CrossRefIndex.set_store + load_from_store.
* Parser-level extract_references emits caller_qualified_name when the
  call sits inside a top-level Python function.
"""

from __future__ import annotations

from attocode.code_intel.indexing.parser import (
    _enclosing_caller,
    extract_references,
)
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)
from attocode.integrations.context.index_store import IndexStore


def _ref(symbol: str, *, caller: str = "", file: str = "x.py", line: int = 1) -> SymbolRef:
    return SymbolRef(
        symbol_name=symbol,
        ref_kind="call",
        file_path=file,
        line=line,
        caller_qualified_name=caller,
    )


def _def(qname: str, *, file: str = "x.py", line: int = 1) -> SymbolLocation:
    bare = qname.rsplit(".", 1)[-1]
    return SymbolLocation(
        name=bare, qualified_name=qname, kind="function",
        file_path=file, start_line=line, end_line=line + 5,
    )


class TestAddReferencePopulatesCallEdges:
    def test_call_edge_added_from_reference(self):
        idx = CrossRefIndex()
        idx.add_reference(_ref("bar", caller="foo"))
        assert idx.call_edges["foo"] == {"bar"}
        assert idx.callers_of["bar"] == {"foo"}

    def test_no_edge_when_caller_missing(self):
        idx = CrossRefIndex()
        idx.add_reference(_ref("bar"))
        assert idx.call_edges == {}
        assert idx.callers_of == {}

    def test_no_edge_for_non_call_ref(self):
        idx = CrossRefIndex()
        ref = SymbolRef(
            symbol_name="X", ref_kind="import",
            file_path="x.py", line=1, caller_qualified_name="foo",
        )
        idx.add_reference(ref)
        assert idx.call_edges == {}

    def test_explicit_add_call_edge(self):
        idx = CrossRefIndex()
        idx.add_call_edge("foo", "bar")
        idx.add_call_edge("foo", "baz")
        assert idx.call_edges["foo"] == {"bar", "baz"}
        assert idx.callers_of["bar"] == {"foo"}
        assert idx.callers_of["baz"] == {"foo"}


class TestCallGraphTraversal:
    def test_get_callees_depth_1(self):
        idx = CrossRefIndex()
        idx.add_call_edge("a", "b")
        idx.add_call_edge("a", "c")
        assert idx.get_callees("a") == {"b", "c"}

    def test_get_callees_depth_n(self):
        idx = CrossRefIndex()
        idx.add_call_edge("a", "b")
        idx.add_call_edge("b", "c")
        idx.add_call_edge("c", "d")
        assert idx.get_callees("a", depth=2) == {"b", "c"}
        assert idx.get_callees("a", depth=3) == {"b", "c", "d"}
        # Going beyond the chain is a no-op, not an error.
        assert idx.get_callees("a", depth=10) == {"b", "c", "d"}

    def test_get_callers_inverse(self):
        idx = CrossRefIndex()
        idx.add_call_edge("a", "x")
        idx.add_call_edge("b", "x")
        assert idx.get_callers("x") == {"a", "b"}

    def test_cycle_terminates(self):
        idx = CrossRefIndex()
        idx.add_call_edge("a", "b")
        idx.add_call_edge("b", "a")
        # Should not loop forever; max depth caps the work.
        assert idx.get_callees("a", depth=10) == {"a", "b"}


class TestRemoveFileScrubsEdges:
    def test_caller_in_removed_file_is_dropped(self):
        idx = CrossRefIndex()
        idx.add_definition(_def("foo", file="caller.py"))
        idx.add_definition(_def("baz", file="other.py"))
        idx.add_reference(_ref("bar", caller="foo", file="caller.py"))
        idx.add_reference(_ref("qux", caller="baz", file="other.py"))

        idx.remove_file("caller.py")

        assert "foo" not in idx.call_edges
        assert "bar" not in idx.callers_of
        # Unrelated edges survive.
        assert idx.call_edges.get("baz") == {"qux"}
        assert idx.callers_of.get("qux") == {"baz"}


class TestIndexStoreRoundtrip:
    def test_save_and_load_caller(self, tmp_path):
        store = IndexStore(db_path=str(tmp_path / "x.db"))
        # File row first (FK).
        from attocode.integrations.context.index_store import StoredFile
        store.save_file(StoredFile(
            path="caller.py", mtime=1.0, size=10, language="python",
            line_count=10, content_hash="h",
        ))
        store.save_references("caller.py", [
            {
                "symbol_name": "bar",
                "ref_kind": "call",
                "line": 5,
                "column": 0,
                "source": "tree-sitter",
                "caller_qualified_name": "foo",
            },
            {
                "symbol_name": "baz",
                "ref_kind": "call",
                "line": 6,
                "column": 0,
                "source": "tree-sitter",
                # Missing caller_qualified_name — should default to "".
            },
        ])

        loaded = store.load_references("caller.py")
        by_name = {r.symbol_name: r for r in loaded}
        assert by_name["bar"].caller_qualified_name == "foo"
        assert by_name["baz"].caller_qualified_name == ""
        store.close()

    def test_cross_ref_index_load_reconstructs_call_edges(self, tmp_path):
        store = IndexStore(db_path=str(tmp_path / "x.db"))
        from attocode.integrations.context.index_store import StoredFile
        store.save_file(StoredFile(
            path="caller.py", mtime=1.0, size=10, language="python",
            line_count=10, content_hash="h",
        ))
        store.save_references("caller.py", [
            {
                "symbol_name": "bar",
                "ref_kind": "call",
                "line": 5,
                "column": 0,
                "source": "tree-sitter",
                "caller_qualified_name": "foo",
            },
        ])

        idx = CrossRefIndex()
        idx.set_store(store)
        idx.load_from_store()

        assert idx.call_edges["foo"] == {"bar"}
        assert idx.callers_of["bar"] == {"foo"}
        store.close()


class TestConcurrentMutation:
    """Review C3 — CrossRefIndex must tolerate concurrent ``add_*`` and
    ``remove_file`` calls from the LSP callback thread plus the
    background hydration thread. The lock added in this fix prevents
    the dict-corruption race that previously could crash ``remove_file``
    with a ``KeyError`` mid-iteration."""

    def test_concurrent_add_reference_does_not_lose_writes(self):
        import threading

        idx = CrossRefIndex()
        # Pre-define a callee so add_call_edge has a meaningful target.
        idx.add_definition(_def("target"))

        n_threads = 16
        per_thread = 25
        callers = [f"caller_{i}" for i in range(n_threads * per_thread)]
        barrier = threading.Barrier(n_threads)

        def worker(start: int):
            barrier.wait()
            for i in range(per_thread):
                idx.add_reference(_ref(
                    "target",
                    caller=callers[start + i],
                    file=f"f{start + i}.py",
                    line=1,
                ))

        threads = [
            threading.Thread(target=worker, args=(t * per_thread,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every caller should be in callers_of[target] — no lost writes.
        assert idx.callers_of["target"] == set(callers)

    def test_concurrent_remove_file_during_add_reference(self):
        """Stress-test interleaved removal + addition. The point isn't
        that any specific ref survives — it's that no thread crashes
        with ``KeyError`` or corrupts the dicts."""
        import threading

        idx = CrossRefIndex()
        idx.add_definition(_def("target"))

        stop = threading.Event()
        errors: list[BaseException] = []

        def adder():
            i = 0
            while not stop.is_set():
                try:
                    idx.add_reference(_ref(
                        "target", caller=f"c{i}",
                        file=f"f{i % 5}.py", line=1,
                    ))
                except BaseException as exc:
                    errors.append(exc)
                    return
                i += 1

        def remover():
            i = 0
            while not stop.is_set():
                try:
                    idx.remove_file(f"f{i % 5}.py")
                except BaseException as exc:
                    errors.append(exc)
                    return
                i += 1

        threads = [
            threading.Thread(target=adder),
            threading.Thread(target=adder),
            threading.Thread(target=remover),
        ]
        for t in threads:
            t.start()
        # Run for a short burst.
        import time as _time
        _time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)

        assert errors == [], errors


class TestEnclosingCaller:
    def test_innermost_wins(self):
        symbols = [
            {"name": "outer", "qualified_name": "outer", "kind": "function",
             "line_start": 1, "line_end": 30},
            {"name": "inner", "qualified_name": "inner", "kind": "function",
             "line_start": 10, "line_end": 20},
        ]
        assert _enclosing_caller(symbols, 15) == "inner"
        assert _enclosing_caller(symbols, 25) == "outer"
        assert _enclosing_caller(symbols, 100) == ""

    def test_classes_ignored(self):
        symbols = [
            {"name": "MyClass", "kind": "class",
             "line_start": 1, "line_end": 30},
            {"name": "do_thing", "kind": "method",
             "line_start": 5, "line_end": 10},
        ]
        assert _enclosing_caller(symbols, 7) == "do_thing"


class TestExtractReferencesEmitsCaller:
    def test_python_call_inside_function(self):
        source = (
            b"def outer():\n"
            b"    helper()\n"
            b"    return 1\n"
            b"\n"
            b"def helper():\n"
            b"    pass\n"
        )
        refs = extract_references(source, "x.py")
        helper_calls = [r for r in refs if r["symbol_name"] == "helper"]
        assert helper_calls, refs
        assert helper_calls[0]["caller_qualified_name"] == "outer"

    def test_top_level_call_has_empty_caller(self):
        source = (
            b"helper()\n"
            b"\n"
            b"def helper():\n"
            b"    pass\n"
        )
        refs = extract_references(source, "x.py")
        top_level = [r for r in refs if r["line"] == 1]
        assert top_level
        assert top_level[0]["caller_qualified_name"] == ""
