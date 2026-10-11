"""Symbol-focused test evidence, reusing the parsed index instead of scanning file bodies."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from attocode_intel.focused_evidence import task_terms, terms


def is_test_path(path):
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (any(p in {"test", "tests", "__tests__", "spec", "specs"} for p in parts)
            # .NET test projects: UnitsNet.Tests/, Kavita.Services.Tests/
            or any(p.endswith((".Tests", ".Test", ".UnitTests", ".IntegrationTests")) for p in parts[:-1])
            or name.startswith("test_") or ".test." in name or ".spec." in name
            or name.endswith(("_test.py", "_test.go", "Test.java", "Test.kt", "Tests.java", "Tests.kt",
                              "Test.cs", "Tests.cs", "_test.c", "_test.cc", "_test.cpp", "_unittest.cc")))


_TEST_PREFIX = re.compile(r"^(?:unit)?tests?[_-]|^Tests?(?=[A-Z])")
_TEST_SUFFIX = re.compile(r"(?:[_-](?:unit)?(?:tests?|spec)|Tests?|Spec)$")
# These names say little; the folder names the module (pkg/__init__.py, src/index.ts).
_GENERIC_STEMS = {"__init__", "index", "mod", "lib", "main"}


def _plain(name):
    return name.lower().replace("_", "").replace("-", "")


def file_subject(path):
    """The name that a test for this file would carry: lib/pkg/figure.py -> figure."""
    p = PurePosixPath(path)
    stem = p.name.split(".")[0]
    if stem in _GENERIC_STEMS and p.parent.name:
        stem = p.parent.name
    return _plain(stem)


def test_subject(path):
    """The name that a test file is for: test_figure.py, FigureTest.java, figure.test.ts -> figure.

    None when the name has no test affix: a fixture or generated file in a test folder.
    """
    p = PurePosixPath(path)
    stem = p.name.split(".")[0]
    core = _TEST_SUFFIX.sub("", _TEST_PREFIX.sub("", stem))
    if core == stem and ".test." not in p.name and ".spec." not in p.name and "__tests__" not in p.parts:
        return None
    return _plain(core)


def folder_overlap(path, other):
    """The number of folder names that two paths share, in any position."""
    return len(set(PurePosixPath(path).parent.parts) & set(PurePosixPath(other).parent.parts))


def name_matched_tests(changed_file, test_paths, limit=10):
    """Test files named for ``changed_file``, best first, as (path, priority, reason).

    Priority 1: the nearest tests whose name without the test affix is the file name, if
    they share a folder name with it. Priority 3: the same name farther away. Priority 4: the test file name only
    contains the file name, as a plain file-name search finds it. Nearest means the most
    folder names in common, so src/test/java/org/x mirrors src/main/java/org/x.
    """
    subject = file_subject(changed_file)
    if len(subject) < 3:
        return []

    def shared(path):
        return folder_overlap(path, changed_file)

    exact = [path for path in test_paths if test_subject(path) == subject]
    named = set(exact)
    loose = [path for path in test_paths if path not in named and subject in _plain(PurePosixPath(path).name)]
    exact.sort(key=lambda path: (-shared(path), len(path), path))
    loose.sort(key=lambda path: (-shared(path), len(path), path))
    nearest = shared(exact[0]) if exact else 0
    rows = [(path, 1 if nearest and shared(path) == nearest else 3, f"Test file named for `{changed_file}`")
            for path in exact]
    rows += [(path, 4, f"Test file name contains `{PurePosixPath(changed_file).stem}`") for path in loose]
    return rows[:limit]


def rank_symbol_tests(ast, suggestions, files, symbol_name, task_hint, distances,
                      linked_reference_files=None, relevance_by_file=None):
    selected = [s for f in files for s in ast.get_file_symbols(f)
                if s.file_path == f and (s.name == symbol_name or s.qualified_name == symbol_name)]
    symbol_terms = terms(symbol_name or "")
    hint_terms, excluded_terms = task_terms(task_hint or "")
    relevance_by_file = relevance_by_file or {}
    direct = set(linked_reference_files or ())
    if linked_reference_files is None:
        for symbol in selected:
            from attocode_intel.symbol_links import classify_symbol_references
            linked, _ = classify_symbol_references(ast, symbol)
            direct.update(r["file_path"] for r in linked if is_test_path(r["file_path"]))
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
        excluded_hits = excluded_terms & (path_terms | names)
        if path not in suggestions and path not in direct and not symbol_hits and not hint_hits:
            continue
        reasons = []
        if path in direct:
            reasons.append(f"Reference linked to selected symbol `{symbol_name}` by import or language-server evidence")
        if symbol_hits:
            reasons.append("Test name/path matches symbol terms: " + ", ".join(sorted(symbol_hits)))
        if hint_hits:
            reasons.append("Test name/path matches task terms: " + ", ".join(sorted(hint_hits)))
        info = suggestions.get(path, {"priority": 3, "reasons": []})
        matches[path] = {"file_path": path, "priority": 1 if path in direct else info["priority"],
                         "reasons": (reasons + info["reasons"])[:3],
                         "evidence": {"selected_symbol_reference": path in direct,
                                      "reference_resolution": "linked" if path in direct else None,
                                      "symbol_terms": sorted(symbol_hits), "task_terms": sorted(hint_hits),
                                      "import_distance": distances.get(path)},
                         "_excluded_hits": len(excluded_hits)}
    def order(row):
        evidence = row["evidence"]
        # Selected-symbol references are strongest, followed by an actual reverse
        # import path. Lexical matches remain useful candidates after graph evidence.
        return (not evidence["selected_symbol_reference"],
                evidence["import_distance"] is None,
                row["_excluded_hits"] > 0,
                -relevance_by_file.get(row["file_path"], 0.0),
                -(len(evidence["task_terms"]) + len(evidence["symbol_terms"])),
                row["priority"], evidence["import_distance"] if evidence["import_distance"] is not None else float("inf"),
                row["file_path"].startswith("docs/"), row["file_path"])
    ranked = sorted(matches.values(), key=order)
    for row in ranked:
        row.pop("_excluded_hits")
    return ranked
