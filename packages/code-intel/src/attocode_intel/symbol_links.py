"""Resolve selected-symbol evidence through local import bindings."""
from __future__ import annotations

from collections import deque
from pathlib import Path, PurePosixPath

from attocode_intel._internal.integrations.context.cross_references import SymbolRef
from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates


def _file_index(ast):
    try:
        from attocode_intel._internal.integrations.context.codebase_context import _build_file_index
        return _build_file_index(ast._context_mgr._files, ast._root_dir)
    except AttributeError:
        return None


def _imports_from(ast, source, target, index):
    """Return bindings in *source* whose module resolves to *target*."""
    if index is None:
        return []
    try:
        from attocode_intel._internal.integrations.context.codebase_context import IMPORT_RESOLVERS
        file_ast = ast._ast_cache.get(source)
        if file_ast is None:
            ast.ensure_file_parsed(source)
            file_ast = ast._ast_cache.get(source)
        resolver = IMPORT_RESOLVERS.get(file_ast.language) if file_ast else None
        return [imp for imp in (file_ast.imports if file_ast else [])
                if resolver and resolver(imp.module, source, index) == target]
    except (AttributeError, OSError, ValueError):
        return []


def linked_names_by_file(ast, definition):
    """Map importers to local names explicitly bound to one definition.

    Reexports propagate the public name through TypeScript export clauses and
    Python package initializers. Ordinary imports establish a binding only in
    the importing file.
    """
    names = {definition.file_path: {definition.name, definition.qualified_name}}
    index = _file_index(ast)
    queue = deque([(definition.file_path, definition.name)])
    visited = set(queue)
    while queue:
        target, exported_name = queue.popleft()
        try:
            dependents = ast.get_dependents(target)
        except AttributeError:
            break
        for source in dependents:
            for imp in _imports_from(ast, source, target, index):
                imported = imp.names[-1] if imp.names else ("*" if imp.is_reexport else "")
                if imported not in {exported_name, "*"}:
                    continue
                local = imp.alias or (exported_name if imported == "*" else imported)
                bound = names.setdefault(source, set())
                bound.update({exported_name, imported, local})
                reexport = imp.is_reexport or PurePosixPath(source).name == "__init__.py"
                state = (source, local)
                if reexport and local and state not in visited:
                    visited.add(state)
                    queue.append(state)
    return names


def classify_symbol_references(ast, definition):
    """Partition references into linked evidence and unresolved candidates."""
    names_by_file = linked_names_by_file(ast, definition)
    query_names = {definition.name, definition.qualified_name}
    for names in names_by_file.values():
        query_names.update(names)
    for path in names_by_file:
        try:
            ast.ensure_references_indexed(path)
        except AttributeError:
            pass
    candidates = []
    seen = set()
    for name in query_names:
        try:
            refs = ast.get_callers(name)
        except AttributeError:
            refs = []
        for ref in refs:
            identity = (ref.file_path, ref.line, ref.ref_kind, ref.source, ref.symbol_name,
                        getattr(ref, "syntax_name", ""))
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(ref)

    # Calls through a public alias may not be in the global reference index:
    # the alias itself is not a definition, so the normal indexer deliberately
    # skips it. Scan only files that an explicit binding connected to the
    # selected definition, keeping this bounded and structurally scoped.
    try:
        root = Path(ast._root_dir)
        original_names = {definition.name, definition.qualified_name}
        for path, local_names in names_by_file.items():
            if not local_names - original_names:
                continue
            file_ast = ast._ast_cache.get(path)
            if file_ast is None:
                continue
            content = (root / path).read_text(encoding="utf-8", errors="replace")
            for written, kind, line in reference_candidates(str(root / path), content, file_ast.language) or []:
                parts = written.split(".")
                if not ({written, parts[0], parts[-1]} & local_names):
                    continue
                ref = SymbolRef(symbol_name=written, ref_kind=kind, file_path=path,
                                line=line, source="tree-sitter")
                identity = (ref.file_path, ref.line, ref.ref_kind, ref.source, ref.symbol_name,
                            getattr(ref, "syntax_name", ""))
                if identity not in seen:
                    seen.add(identity)
                    candidates.append(ref)
    except (AttributeError, OSError):
        pass

    try:
        same_name_definitions = ast.find_symbol(definition.name)
        definition_count = len({(item.file_path, item.qualified_name)
                                for item in same_name_definitions})
    except AttributeError:
        same_name_definitions = []
        definition_count = 2
    same_file_count = len({item.qualified_name for item in same_name_definitions
                           if item.file_path == definition.file_path})
    selected_parent = (definition.qualified_name.rsplit(".", 1)[0]
                       if "." in definition.qualified_name else "")
    linked, unresolved = [], []
    for ref in candidates:
        local_names = names_by_file.get(ref.file_path, set())
        syntax_name = getattr(ref, "syntax_name", "") or ref.symbol_name
        caller = getattr(ref, "caller_qualified_name", "")
        if (ref.file_path == definition.file_path
                and (same_file_count <= 1
                     or (selected_parent and caller.rsplit(".", 1)[0] == selected_parent))):
            resolution = "same_file"
        elif {syntax_name, syntax_name.split(".", 1)[0]} & local_names:
            resolution = "import_binding"
        elif ref.source == "lsp" and definition_count == 1:
            resolution = "language_server"
        else:
            resolution = "same_name_candidate"
        row = {"ref_kind": ref.ref_kind, "file_path": ref.file_path, "line": ref.line,
               "source": ref.source, "symbol": ref.symbol_name, "resolution": resolution}
        if syntax_name != ref.symbol_name:
            row["syntax"] = syntax_name
        (linked if resolution != "same_name_candidate" else unresolved).append(row)

    by_site = {}
    for row in unresolved + linked:
        site = row["file_path"], row["line"], row["ref_kind"], row["source"]
        existing = by_site.get(site)
        if (existing is None or existing["resolution"] == "same_name_candidate"
                or row["resolution"] != "same_name_candidate"):
            by_site[site] = row
    linked = [row for row in by_site.values() if row["resolution"] != "same_name_candidate"]
    unresolved = [row for row in by_site.values() if row["resolution"] == "same_name_candidate"]
    def order(row):
        return row["file_path"], row["line"], row["ref_kind"], row["source"], row["symbol"]

    return sorted(linked, key=order), sorted(unresolved, key=order)
