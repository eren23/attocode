"""Small evidence bundles composed from one refreshed workspace."""
from __future__ import annotations

from pathlib import Path


def select_definitions(service, symbol_name, file_path=None, line=None):
    root = Path(service.project_dir).resolve()
    if file_path is not None:
        path = (root / file_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Path must remain inside the selected repository")
        file_path = path.relative_to(root).as_posix()
    if line is not None and line < 1:
        raise ValueError("line must be a positive definition start line")
    ast = service._get_ast_service()
    if (file_path is not None and file_path not in ast._ast_cache
            and any(fi.relative_path == file_path for fi in ast._context_mgr._files)):
        ast.ensure_file_parsed(file_path)
    definitions = ast.find_symbol(symbol_name)
    return [d for d in definitions if (file_path is None or d.file_path == file_path)
            and (line is None or d.start_line == line)]


def location(definition):
    return {key: getattr(definition, key) for key in
            ("name", "qualified_name", "kind", "file_path", "start_line", "end_line")}


def scoped_references(service, symbol_name, file_path=None, line=None):
    data = service.cross_references_data(symbol_name)
    if file_path is not None or line is not None:
        definitions = select_definitions(service, symbol_name, file_path, line)
        data["definitions"] = [location(d) for d in definitions]
        data["selection_unique"] = len(definitions) == 1
        if not definitions:
            data["references"] = []
            data["total_references"] = 0
            data["reference_candidates"] = []
            data["total_reference_candidates"] = 0
        elif len(definitions) == 1:
            from attocode_intel.symbol_links import classify_symbol_references
            linked, candidates = classify_symbol_references(service._get_ast_service(), definitions[0])
            data["references"] = linked
            data["total_references"] = len(linked)
            data["reference_candidates"] = candidates[:20]
            data["total_reference_candidates"] = len(candidates)
            data["reference_caveat"] = (
                "References are linked by same-file identity, explicit import bindings, or a language server. "
                "Same-name syntax matches without that evidence remain reference_candidates."
            )
    data["references"] = sorted(data["references"], key=lambda r: (
        r["file_path"], r["line"], r["ref_kind"], r["source"], r.get("symbol", "")))
    seen = set()
    unique = []
    for ref in data["references"]:
        identity = tuple(sorted((key, str(value)) for key, value in ref.items()))
        if identity not in seen:
            seen.add(identity)
            unique.append(ref)
    data["references"] = unique
    return data


def inspect_symbol_data(service, symbol_name, file_path=None, line=None, source_start_line=None, task_hint=None):
    definitions = select_definitions(service, symbol_name, file_path, line)
    if len(definitions) != 1:
        return {"status": "ambiguous" if definitions else "not_found", "symbol": symbol_name,
                "definitions": [location(d) for d in definitions[:10]],
                "total_definitions": len(definitions), "ambiguous": len(definitions) > 1,
                "follow_up": {"tool": "inspect_symbol", "select": "file_path and start_line as line"}}
    definition = definitions[0]
    path = definition.file_path
    root = Path(service.project_dir).resolve()
    source_path = (root / path).resolve()
    if not source_path.is_relative_to(root):
        raise ValueError("Path must remain inside the selected repository")
    # Check file identity across reading so an outside editor cannot pair stale lines with new text.
    before = source_path.stat()
    from attocode_intel.request_context import current_request
    request = current_request.get()
    tracker = request.stores.get("freshness") if request else None
    expected = (tracker.manifest or {}).get(path) if tracker else None
    if expected is not None and expected != (before.st_mtime_ns, before.st_ctime_ns, before.st_size):
        raise ValueError("Source changed after indexing; retry inspection")
    source = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    after = source_path.stat()
    if (before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (
            after.st_mtime_ns, after.st_ctime_ns, after.st_size):
        raise ValueError("Source changed during inspection; retry")
    from attocode_intel.tools.composite_tools import suggest_tests_data

    references = scoped_references(service, symbol_name, path, definition.start_line)
    imports = service.dependencies_data(path)
    linked_test_files = {ref["file_path"] for ref in references["references"]}
    tests = suggest_tests_data([path], symbol_name=definition.qualified_name, task_hint=task_hint,
                               linked_reference_files=linked_test_files)["candidates"]
    if source_start_line is not None and (isinstance(source_start_line, bool) or int(source_start_line) != source_start_line):
        raise ValueError("source_start_line must be an integer inside the selected definition")
    start = max(1, definition.start_line) if source_start_line is None else int(source_start_line)
    if not definition.start_line <= start <= min(len(source), definition.end_line):
        raise ValueError("source_start_line must be inside the selected definition")
    focused_preview = task_hint and source_start_line is None and definition.end_line - definition.start_line >= 60
    end = min(len(source), definition.end_line, start + (11 if focused_preview else 59))
    selection = {"symbol_name": symbol_name, "file_path": path, "line": definition.start_line}
    relationships = ([{"file_path": p, "kind": "imports"} for p in imports["imports"]]
                     + [{"file_path": p, "kind": "imported_by"} for p in imports["imported_by"]])
    result = {
        "status": "found", "definition": location(definition),
        "source": {"start_line": start, "end_line": end,
                   "text": "\n".join(source[start - 1:end]),
                   "truncated": start > definition.start_line or end < definition.end_line},
        "references": references["references"][:8], "total_references": references["total_references"],
        "reference_candidates": references.get("reference_candidates", [])[:5],
        "total_reference_candidates": references.get("total_reference_candidates", 0),
        "ambiguous": references["ambiguous"],
        "reference_caveat": references.get("reference_caveat", "Syntax references are candidates; verify source."),
        "imports": relationships[:5], "total_imports": len(relationships),
        "tests": tests[:5], "total_tests": len(tests), "absence_proven": False,
        "follow_up": {
            "references": {"tool": "cross_references", **selection},
            "imports": {"tool": "dependencies", "path": path},
            "tests": {"tool": "suggest_tests", "files": [path], "symbol_name": definition.qualified_name,
                      **({"task_hint": task_hint} if task_hint else {})},
            "source": {"file_path": path, "start_line": definition.start_line, "end_line": definition.end_line},
            "next_source": {"tool": "inspect_symbol", **selection, "source_start_line": end + 1}
                if end < definition.end_line else None,
        },
    }
    if task_hint:
        from attocode_intel.focused_evidence import source_excerpts
        result["source_excerpts"] = source_excerpts(source, definition, task_hint, preview_end=end)
        result["excerpt_selection"] = "Identifiers and executable literals ranked with enclosing syntax context; not exhaustive behavior coverage or data flow. Context ranges belong to their excerpt; cite each range separately."
    return result
