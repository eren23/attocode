"""Diff-aware symbol reports and identity-scoped caller paths."""

from __future__ import annotations

from collections import deque

from attocode_intel.change_evidence import GitWorkspace, digest, seal
from attocode_intel.symbol_inspection import location, select_definitions
from attocode_intel.symbol_links import classify_symbol_references


def _identity(row):
    return row["file_path"], row["start_line"], row["qualified_name"]


def _coverage(service):
    coverage = service._get_ast_service().hydration_snapshot()
    return {
        key: coverage.get(key)
        for key in ("phase", "parsed_files", "total_files", "discovery_truncated")
    }


def _anchor(git, anchors, path):
    if path not in anchors:
        if len(anchors) >= 256:
            raise ValueError("More than 256 evidence files; reduce depth or symbol limits")
        raw = git.read(path)
        git.anchor_bytes += len(raw or b"")
        if git.anchor_bytes > 16 * 1024 * 1024:
            raise ValueError("Evidence sources exceed the 16 MiB collection limit")
        anchors[path] = digest(raw) if raw is not None else None


def _symbols(path, raw):
    if raw is None:
        return {}, "absent"
    if b"\0" in raw:
        return {}, "binary"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {}, "non_utf8"
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file

    ast = parse_file(path, content=text)
    source = text.splitlines(keepends=True)
    symbols, counts = {}, {}
    items = [
        (f, "method" if f.is_method else "function", f.qualified_name or f.name)
        for f in ast.functions
    ]
    for cls in ast.classes:
        items.append((cls, "class", cls.name))
        items.extend(
            (f, "method", f.qualified_name or cls.name + "." + f.name) for f in cls.methods
        )
    # Some parsers expose methods both on the class and in functions.
    seen = set()
    for node, kind, name in sorted(items, key=lambda x: (x[0].start_line, x[2], x[1])):
        identity = name, kind, node.start_line
        if identity in seen:
            continue
        seen.add(identity)
        key = name, kind
        ordinal = counts.get(key, 0)
        counts[key] = ordinal + 1
        symbols[(*key, ordinal)] = {
            "name": node.name,
            "qualified_name": name,
            "kind": kind,
            "file_path": path,
            "start_line": node.start_line,
            "end_line": node.end_line,
            "source_sha256": digest("".join(source[node.start_line - 1 : node.end_line]).encode()),
        }
    return symbols, ast.parsing_tier or "unsupported"


def _flow(service, git, definitions, depth, max_nodes, anchors):
    ast = service._get_ast_service()
    nodes = {_identity(location(d)): location(d) for d in definitions}
    queue = deque((d, 0) for d in definitions)
    visited, edges, unresolved = set(), [], []
    omitted = {"nodes": 0, "edges": 0, "unresolved": 0}
    omitted_nodes = set()
    while queue:
        git.check_deadline()
        definition, hop = queue.popleft()
        key = _identity(location(definition))
        if key in visited or hop >= depth:
            continue
        visited.add(key)
        _anchor(git, anchors, definition.file_path)
        overloads = [
            d
            for d in ast.get_file_symbols(definition.file_path)
            if d.qualified_name == definition.qualified_name
        ]
        if len(overloads) > 1:
            if len(unresolved) < 32:
                unresolved.append(
                    {
                        "target": location(definition),
                        "followed": False,
                        "reason": "Overload dispatch requires precise reference evidence",
                    }
                )
            else:
                omitted["unresolved"] += 1
            continue
        linked, candidates = classify_symbol_references(ast, definition)
        git.check_deadline()
        for ref in candidates:
            if ref["ref_kind"] == "call":
                if len(unresolved) < 32:
                    unresolved.append({**ref, "target": location(definition), "followed": False})
                else:
                    omitted["unresolved"] += 1
        for ref in linked:
            git.check_deadline()
            if ref["ref_kind"] != "call":
                continue
            path = ref["file_path"]
            _anchor(git, anchors, path)
            ast.ensure_file_parsed(path)
            enclosing = [
                d
                for d in ast.get_file_symbols(path)
                if d.kind in {"function", "method"} and d.start_line <= ref["line"] <= d.end_line
            ]
            enclosing.sort(key=lambda d: d.end_line - d.start_line)
            if enclosing and (
                len(enclosing) == 1
                or enclosing[0].end_line - enclosing[0].start_line
                < enclosing[1].end_line - enclosing[1].start_line
            ):
                caller = enclosing[0]
                row = location(caller)
            else:
                caller = None
                name = "<unresolved caller>" if enclosing else "<module>"
                row = {
                    "file_path": path,
                    "name": name,
                    "qualified_name": name,
                    "kind": "unknown" if enclosing else "module",
                    "start_line": ref["line"],
                    "end_line": ref["line"],
                }
            caller_key = _identity(row)
            if caller_key not in nodes:
                if len(nodes) >= max_nodes:
                    omitted_nodes.add(caller_key)
                    omitted["nodes"] = len(omitted_nodes)
                    continue
                nodes[caller_key] = row
            edge = {
                "caller": row,
                "callee": location(definition),
                "site": {"file_path": path, "line": ref["line"]},
                "resolution": ref["resolution"],
                "source": ref["source"],
            }
            if edge not in edges:
                if len(edges) >= 128:
                    omitted["edges"] += 1
                    continue
                edges.append(edge)
            if caller is not None and caller_key not in visited:
                queue.append((caller, hop + 1))
    return {
        "direction": "callers",
        "depth": depth,
        "nodes": list(nodes.values()),
        "edges": edges,
        "unresolved": unresolved,
        "omitted": omitted,
        "bounded": any(omitted.values()),
        "absence_proven": False,
        "note": "Static caller paths, not execution order or complete control/data flow. Unresolved name matches are not followed.",
    }


def _bounds(depth, max_nodes):
    if not 1 <= depth <= 3 or not 1 <= max_nodes <= 64:
        raise ValueError("depth must be 1..3 and max_nodes 1..64")


def _finish(git, before, request, anchors, **data):
    if git.snapshot(request.get("base", "")) != before:
        raise ValueError("Workspace changed during investigation; retry")
    for path, expected in anchors.items():
        raw = git.read(path)
        if (digest(raw) if raw is not None else None) != expected:
            raise ValueError("Evidence changed during investigation; retry")
    return seal(
        {
            "request": request,
            "snapshot": before,
            "anchors": anchors,
            "analysis": "partial",
            "absence_proven": False,
            **data,
        }
    )


def trace_flow_data(service, symbol_name, file_path=None, line=None, depth=2, max_nodes=32):
    _bounds(depth, max_nodes)
    git = GitWorkspace(service.project_dir)
    before = git.snapshot()
    definitions = select_definitions(service, symbol_name, file_path, line)
    request = {
        "operation": "trace_flow",
        "symbol_name": symbol_name,
        "file_path": file_path,
        "line": line,
        "depth": depth,
        "max_nodes": max_nodes,
    }
    if len(definitions) != 1:
        return _finish(
            git,
            before,
            request,
            {},
            status="ambiguous" if definitions else "not_found",
            definitions=[location(d) for d in definitions[:10]],
            total_definitions=len(definitions),
            coverage=_coverage(service),
        )
    anchors = {}
    flow = _flow(service, git, definitions, depth, max_nodes, anchors)
    return _finish(
        git, before, request, anchors, status="found", flow=flow, coverage=_coverage(service)
    )


def _impact(ast, changed, depth):
    visited, frontier, layers = set(changed), set(changed), []
    omitted = False
    for hop in range(1, depth + 1):
        next_frontier = set()
        for path in sorted(frontier):
            for dependent in sorted(ast.get_dependents(path)):
                if dependent in visited:
                    continue
                if len(visited) >= 128:
                    omitted = True
                    continue
                visited.add(dependent)
                next_frontier.add(dependent)
        if not next_frontier:
            break
        layers.append({"depth": hop, "files": sorted(next_frontier)})
        frontier = next_frontier
    return {
        "layers": layers,
        "bounded": omitted,
        "depth": depth,
        "interpretation": "potential_import_reachability",
        "absence_proven": False,
    }


def change_context_data(service, mode="working", base="", depth=2, max_files=24, max_symbols=32):
    _bounds(depth, 32)
    if not 1 <= max_files <= 32 or not 1 <= max_symbols <= 48:
        raise ValueError("max_files must be 1..32 and max_symbols 1..48")
    git = GitWorkspace(service.project_dir)
    before = git.snapshot(base)
    comparison, changes = git.changes(mode, base)
    request = {
        "operation": "change_context",
        "mode": mode,
        "base": base,
        "depth": depth,
        "max_files": max_files,
        "max_symbols": max_symbols,
    }
    files, symbols, anchors = [], [], {}
    omitted = {"files": max(0, len(changes) - max_files), "symbols": 0}
    for change in changes[:max_files]:
        path, old_path = change["file_path"], change["old_path"]
        git.path(path)
        git.path(old_path)
        if {change["old_mode"], change["new_mode"]} - {"000000", "100644", "100755"}:
            files.append(
                {
                    "file_path": path,
                    "old_path": old_path,
                    "status": change["status"],
                    "analysis": "unsupported_file_mode",
                }
            )
            continue
        old = git.blob(change["old_blob"])
        new = git.blob(change["new_blob"]) if mode == "staged" else git.read(path)
        _anchor(git, anchors, path)
        old_symbols, old_tier = _symbols(old_path, old)
        new_symbols, new_tier = _symbols(path, new)
        current_matches = git.read(path) == new
        files.append(
            {
                "file_path": path,
                "old_path": old_path,
                "status": change["status"],
                "before_sha256": digest(old) if old is not None else None,
                "after_sha256": digest(new) if new is not None else None,
                "before_parser": old_tier,
                "after_parser": new_tier,
                "current_source_matches": current_matches,
                "file_level_change": old != new or old_path != path,
            }
        )
        for key in sorted(old_symbols.keys() | new_symbols.keys()):
            previous, current = old_symbols.get(key), new_symbols.get(key)
            if (
                previous
                and current
                and previous["source_sha256"] == current["source_sha256"]
                and path == old_path
            ):
                continue
            if len(symbols) >= max_symbols:
                omitted["symbols"] += 1
                continue
            kind = (
                "added"
                if previous is None
                else "removed"
                if current is None
                else "modified"
                if previous["source_sha256"] != current["source_sha256"]
                else "moved"
            )
            symbols.append(
                {
                    "change": kind,
                    "before": previous,
                    "after": current,
                    "current_source_matches": current_matches,
                }
            )
    ast = service._get_ast_service()
    for row in symbols:
        current = row["after"]
        if current is None or not row["current_source_matches"]:
            row["flow"] = {
                "status": "unavailable",
                "reason": "Historical or index-only definition; current callers cannot be attributed to it.",
            }
            continue
        definitions = select_definitions(
            service, current["qualified_name"], current["file_path"], current["start_line"]
        )
        if len(definitions) != 1:
            row["flow"] = {
                "status": "unavailable",
                "reason": "Current definition is not uniquely indexed",
            }
            continue
        row["flow"] = _flow(service, git, definitions, depth, 16, anchors)
    changed = sorted({r[k] for r in files for k in ("file_path", "old_path")})
    impact = _impact(ast, changed, depth)
    from attocode_intel.tools.composite_tools import suggest_tests_data

    tests = (
        suggest_tests_data(changed)
        if changed
        else {"candidates": [], "note": "No changed files", "absence_proven": False}
    )
    from attocode_intel.test_ranking import is_test_path

    known_tests = {c["file_path"] for c in tests["candidates"]}
    for row in symbols:
        for edge in row.get("flow", {}).get("edges", []):
            path = edge["site"]["file_path"]
            if path in known_tests:
                continue
            raw = git.read(path) or b""
            rust_inline = path.endswith(".rs") and b"#[test]" in raw
            if is_test_path(path) or rust_inline:
                tests["candidates"].append(
                    {
                        "file_path": path,
                        "priority": 3,
                        "reasons": [
                            "Reached by an identity-linked caller path"
                            + (
                                "; contains a Rust test annotation (heuristic)"
                                if rust_inline
                                else ""
                            )
                        ],
                        "evidence": {"caller_path": True, "complete_coverage": False},
                    }
                )
                known_tests.add(path)
    total_tests = len(tests["candidates"])
    tests["candidates"] = tests["candidates"][:20]
    tests["total_candidates"] = total_tests
    for path in [p for layer in impact["layers"] for p in layer["files"]] + [
        c["file_path"] for c in tests["candidates"]
    ]:
        _anchor(git, anchors, path)
    return _finish(
        git,
        before,
        request,
        anchors,
        status="collected" if changes else "no_changes",
        comparison_revision=comparison,
        files=files,
        symbols=symbols,
        impact=impact,
        tests=tests,
        coverage=_coverage(service),
        omitted=omitted,
        bounded=any(omitted.values()),
        note="Changed symbols are source comparisons. Callers use the current working tree; removed/index-only definitions remain historical. Tests are candidates, not complete coverage.",
    )


def markdown_report(report):
    """Readable export alongside the full machine-checkable JSON report."""

    def safe(value):
        return str(value).replace("`", "\\`").replace("\n", "\\n").replace("\r", "\\r")

    lines = [
        "# Change investigation",
        "",
        f"Report: `{report['report_id']}`",
        f"Revision: `{report['snapshot']['head']}`",
        "",
        "Analysis is partial; missing relationships do not prove absence.",
        "",
    ]
    lines.extend(["## Files", ""])
    for row in report.get("files", []):
        old = row["old_path"]
        path = row["file_path"]
        name = f"{old} → {path}" if old != path else path
        lines.append(f"- {safe(row['status'])}: `{safe(name)}`")
    if report.get("bounded"):
        lines.append(
            "Some files or symbols were omitted by the requested bounds; inspect the JSON omission counts."
        )
    lines.extend(["", "## Changed symbols", ""])
    for row in report.get("symbols", []):
        definition = row["after"] or row["before"]
        lines.append(
            f"- {row['change']}: `{safe(definition['qualified_name'])}` at `{safe(definition['file_path'])}:{definition['start_line']}`"
        )
    flows = [r.get("flow", {}) for r in report.get("symbols", [])]
    if "flow" in report:
        flows.append(report["flow"])
    lines.extend(["", "## Caller evidence", ""])
    for flow in flows:
        if flow.get("status") == "unavailable":
            lines.append("- " + flow["reason"])
        if flow.get("bounded"):
            lines.append("- Caller evidence was capped; see JSON omission counts.")
        for edge in flow.get("edges", []):
            lines.append(
                f"- `{safe(edge['caller']['qualified_name'])}` → `{safe(edge['callee']['qualified_name'])}` at `{safe(edge['site']['file_path'])}:{edge['site']['line']}` ({edge['resolution']})"
            )
    lines.extend(["", "## Potential import impact", ""])
    for layer in report.get("impact", {}).get("layers", []):
        for path in layer["files"]:
            lines.append(f"- depth {layer['depth']}: `{safe(path)}`")
    lines.extend(["", "## Candidate tests", ""])
    for row in report.get("tests", {}).get("candidates", []):
        lines.append(f"- `{safe(row['file_path'])}`: {safe('; '.join(row['reasons']))}")
    lines.extend(
        [
            "",
            report.get("note", "Static paths are not execution order."),
            "",
            "Use the JSON export with `changes --check` to validate freshness.",
            "",
        ]
    )
    return "\n".join(lines)
