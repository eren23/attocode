"""Symbol-focused test evidence, reusing the parsed index instead of scanning file bodies."""
from __future__ import annotations

from pathlib import PurePosixPath

from attocode_intel.focused_evidence import terms


def is_test_path(path):
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (any(p in {"test", "tests", "__tests__", "spec", "specs"} for p in parts)
            or name.startswith("test_") or ".test." in name or ".spec." in name
            or name.endswith(("_test.py", "_test.go", "Test.java", "Test.kt")))


def rank_symbol_tests(ast, suggestions, files, symbol_name, task_hint, distances):
    selected = [s for f in files for s in ast.get_file_symbols(f)
                if s.file_path == f and (s.name == symbol_name or s.qualified_name == symbol_name)]
    symbol_terms = terms(symbol_name or "")
    hint_terms = terms(task_hint or "")
    direct = set()
    for symbol in selected:
        direct.update(r.file_path for r in ast.get_callers(symbol.qualified_name) if is_test_path(r.file_path))
    # Search indexed test names as well as paths. A generic suite filename can
    # contain a focused regression; filename matching alone should not hide it.
    matches = {}
    for path in set(ast.index.file_symbols) | set(suggestions) | direct:
        inline = path in files and any("Rust inline test" in r for r in suggestions.get(path, {}).get("reasons", []))
        if not is_test_path(path) and not inline:
            continue
        path_terms = terms(PurePosixPath(path).stem)
        names = set().union(*(terms(s.name) for s in ast.get_file_symbols(path) if s.file_path == path))
        symbol_hits = symbol_terms & (path_terms | names)
        hint_hits = hint_terms & (path_terms | names)
        if path not in suggestions and path not in direct and not symbol_hits and not hint_hits:
            continue
        reasons = []
        if path in direct:
            reasons.append(f"Syntax reference to selected symbol `{symbol_name}`; verify same-name targets")
        if symbol_hits:
            reasons.append("Test name/path matches symbol terms: " + ", ".join(sorted(symbol_hits)))
        if hint_hits:
            reasons.append("Test name/path matches task terms: " + ", ".join(sorted(hint_hits)))
        info = suggestions.get(path, {"priority": 3, "reasons": []})
        matches[path] = {"file_path": path, "priority": 1 if path in direct else info["priority"],
                         "reasons": (reasons + info["reasons"])[:3],
                         "evidence": {"selected_symbol_reference": path in direct,
                                      "symbol_terms": sorted(symbol_hits), "task_terms": sorted(hint_hits),
                                      "import_distance": distances.get(path)}}
    def order(row):
        evidence = row["evidence"]
        # Selected-symbol references are strongest. Topic-specific test names can
        # outrank a broad module import, but remain explicitly lexical candidates.
        return (not evidence["selected_symbol_reference"],
                -(len(evidence["task_terms"]) + len(evidence["symbol_terms"])),
                row["priority"], evidence["import_distance"] if evidence["import_distance"] is not None else float("inf"),
                row["file_path"].startswith("docs/"), row["file_path"])
    return sorted(matches.values(), key=order)
