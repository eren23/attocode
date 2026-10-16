"""Resolve selected-symbol evidence through local import bindings."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path, PurePosixPath

from attocode_intel._internal.integrations.context.cross_references import SymbolRef
from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates


def _file_index(ast):
    try:
        from attocode_intel._internal.integrations.context.codebase_context import _build_file_index
        return _build_file_index(ast._context_mgr._files, ast._root_dir, ast._ast_cache)
    except AttributeError:
        return None


def _imports_from(ast, source, target, index):
    """Return bindings in *source* whose module resolves to *target*."""
    if index is None:
        return []
    try:
        from attocode_intel._internal.integrations.context.codebase_context import (
            resolve_import_targets,
        )
        file_ast = ast._ast_cache.get(source)
        if file_ast is None:
            ast.ensure_file_parsed(source)
            file_ast = ast._ast_cache.get(source)
        return [imp for imp in (file_ast.imports if file_ast else [])
                if target in resolve_import_targets(file_ast.language, imp.module, source, index, include_system=imp.include_system)]
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
                source_ast = ast._ast_cache.get(source)
                target_ast = ast._ast_cache.get(target)
                parent = definition.qualified_name.rsplit('.', 1)[0] if '.' in definition.qualified_name else ''
                if (source_ast and target_ast and parent in {c.name for c in target_ast.classes}
                        and source_ast.language in {'java', 'csharp', 'scala', 'php', 'kotlin'}):
                    module = imp.module.replace('\\', '.')
                    namespaces = {ns.replace('\\', '.') for ns in target_ast.namespaces}
                    if (module.endswith('.' + parent) or module in {ns + '.*' for ns in namespaces}
                            or source_ast.language == 'csharp' and module in namespaces):
                        names.setdefault(source, set()).add(f'{imp.alias or parent}.{exported_name}')
                        continue
                    if module.endswith('.' + parent + '.' + exported_name):
                        names.setdefault(source, set()).add(imp.alias or exported_name)
                        continue
                imported = imp.names[-1] if imp.names else ("*" if imp.is_reexport else "")
                if imported not in {exported_name, "*"}:
                    continue
                local = imp.alias or (exported_name if imported == "*" else imported)
                if source_ast and source_ast.language == "go":
                    package_names = target_ast.namespaces if target_ast else []
                    package = imp.alias or (package_names[0] if len(package_names) == 1 else "")
                    if not package or package in {"_", "."}:
                        continue
                    names.setdefault(source, set()).add(f"{package}.{exported_name}")
                    continue
                bound = names.setdefault(source, set())
                if imported == "*" and imp.alias and not imp.is_reexport:
                    # Namespace imports bind ns.member, not every bare member or
                    # every other call through ns.
                    bound.add(f"{imp.alias}.{exported_name}")
                else:
                    bound.add(local)
                if source_ast and source_ast.language == "swift":
                    bound.add(f"{imp.module}.{exported_name}")
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
        selected_key = json.dumps([definition.file_path, definition.start_line, definition.qualified_name])
        precise_key = getattr(ref, "definition_key", "")
        if precise_key and precise_key != selected_key:
            continue
        local_names = names_by_file.get(ref.file_path, set())
        syntax_name = getattr(ref, "syntax_name", "") or ref.symbol_name
        caller = getattr(ref, "caller_qualified_name", "")
        # A unique method name in a file does not bind arbitrary receivers to
        # its class (e.g. store.close() is not Gateway.close()).
        same_file = ref.file_path == definition.file_path
        local_identity = (
            not selected_parent and same_file_count == 1 and syntax_name == definition.name
        ) or (
            bool(selected_parent) and (
                syntax_name == definition.qualified_name
                or (syntax_name in {f"{receiver}.{definition.name}" for receiver in ("self", "cls", "this")}
                    and caller.rsplit(".", 1)[0] == selected_parent)
            )
        )
        selected_ast = ast._ast_cache.get(definition.file_path)
        source_ast = ast._ast_cache.get(ref.file_path)
        same_go_package = (
            selected_ast is not None and source_ast is not None
            and selected_ast.language == source_ast.language == "go"
            and PurePosixPath(ref.file_path).parent == PurePosixPath(definition.file_path).parent
            and len(selected_ast.namespaces) == 1
            and selected_ast.namespaces == source_ast.namespaces
            and not selected_parent and syntax_name == definition.name
            and sum(1 for d in same_name_definitions
                    if PurePosixPath(d.file_path).parent == PurePosixPath(definition.file_path).parent
                    and d.qualified_name == definition.qualified_name) == 1
        )
        if ref.source == "lsp" and precise_key == selected_key:
            resolution = "language_server"
        elif same_file and local_identity:
            resolution = "same_file"
        elif same_go_package:
            resolution = "package_binding"
        elif not same_file and {syntax_name, syntax_name.split(".", 1)[0]} & local_names:
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
