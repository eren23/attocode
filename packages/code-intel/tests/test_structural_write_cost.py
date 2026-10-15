"""Structural persistence retains evidence while bounding native SQL steps."""

import sqlite3

import pytest
from attocode_intel._internal.integrations.context.index_store import IndexStore, StoredFile


@pytest.fixture
def store(tmp_path):
    index = IndexStore(str(tmp_path / "symbols.db"))
    index.save_files_batch([
        StoredFile(path, 1, 1, "python", 1, "digest") for path in ("a.py", "b.py")
    ])
    try:
        yield index
    finally:
        index.close()


def evidence(count):
    symbols = [dict(name=f"item{i}", qualified_name=f"Scope.item{i}", kind="method",
                    line=i, end_line=i + 1, source="lsp") for i in range(count)]
    refs = [dict(symbol_name=f"item{i}", ref_kind="call", line=i, column=i + 2,
                 source="lsp", syntax_name=f"scope.item{i}",
                 caller_qualified_name="Caller.run", definition_key=f"a.py:{i}")
            for i in range(count)]
    return symbols, refs


def snapshot(store):
    return [list(map(tuple, store._get_conn().execute(f"SELECT * FROM {table} ORDER BY id")))
            for table in ("symbols", "refs")]


def test_bounded_statements_preserve_all_evidence_and_row_order(store):
    conn = store._get_conn()
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    symbols, refs = evidence(133)  # two full groups and a partial tail
    statements = []
    conn.set_trace_callback(statements.append)
    store.save_analysis_batch([("a.py", symbols, refs)])
    conn.set_trace_callback(None)
    assert sum(s.lstrip().startswith("INSERT INTO symbols") for s in statements) == 3
    assert sum(s.lstrip().startswith("INSERT INTO refs") for s in statements) == 3
    assert sum(s == "COMMIT" for s in statements) == 1
    actual_symbols, actual_refs = snapshot(store)
    assert actual_symbols == [
        (i + 1, "a.py", s["name"], s["qualified_name"], s["kind"], s["line"],
         s["end_line"], s["source"]) for i, s in enumerate(symbols)
    ]
    assert actual_refs == [
        (i + 1, "a.py", r["symbol_name"], r["ref_kind"], r["line"], r["column"],
         r["source"], r["syntax_name"], r["caller_qualified_name"], r["definition_key"])
        for i, r in enumerate(refs)
    ]
    # Partial writes preserve the other table; defaults and empty replacement
    # retain their public save_symbols/save_references meanings.
    store.save_symbols("a.py", [dict(name="fresh", qualified_name="fresh", kind="function")])
    assert snapshot(store)[1] == actual_refs
    assert snapshot(store)[0][0][1:] == ("a.py", "fresh", "fresh", "function", 0, 0, "tree-sitter")
    store.save_references("a.py", [dict(symbol_name="fresh")])
    assert snapshot(store)[1][0][1:] == ("a.py", "fresh", "call", 0, 0, "tree-sitter", "", "", "")
    store.save_references("a.py", [])
    assert not store.load_references() and len(store.load_symbols()) == 1


@pytest.mark.parametrize("table", ["symbols", "refs"])
@pytest.mark.parametrize("failure", ["sql", "iteration"])
def test_second_group_failure_rolls_back_prior_file_and_all_tables(store, table, failure):
    old = evidence(1)
    store.save_analysis_batch([("a.py", *old), ("b.py", *old)])
    before = snapshot(store)
    symbols, refs = evidence(133)
    rows, key = (symbols, "name") if table == "symbols" else (refs, "symbol_name")
    if failure == "sql":
        rows[100][key] = None  # NOT NULL violation after the first group succeeded
        error = sqlite3.IntegrityError
    else:
        del rows[100][key]  # lazy row generation can fail after earlier SQL writes
        error = KeyError
    with pytest.raises(error):
        store.save_analysis_batch([("a.py", [], []), ("b.py", symbols, refs)])
    assert snapshot(store) == before
    store.save_analysis_batch([("a.py", [], []), ("b.py", *evidence(133))])
    assert not store.load_symbols("a.py") and not store.load_references("a.py")
    assert len(store.load_symbols("b.py")) == len(store.load_references("b.py")) == 133
    assert store._get_conn().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
