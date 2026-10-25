"""Opt-in, bounded file relationships for deterministic local search."""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from attocode_intel.query_ranking import demote_tests, query_diagnostics


def _identity(row):
    return (row.file_path, row.chunk_type, row.name,
            row.start_line or row.definition_start_line,
            row.end_line or row.definition_end_line)


def context_reason(context, path):
    relation = context.get('relations', {}).get(path) if context.get('applied') else None
    return {'context_reason': {'context_file': context['file'], 'relation': relation}} if relation else {}


def search(service, query, top_k, file_filter, context_file, mode='auto'):
    if mode not in {'auto', 'keyword'}:
        raise ValueError('context_file search does not support vector mode')
    root = Path(service.project_dir).resolve()
    relative = PurePosixPath(context_file)
    if (not context_file or relative.is_absolute() or '..' in relative.parts
            or '\\' in context_file or not (root / context_file).resolve().is_relative_to(root)
            or not (root / context_file).is_file()):
        raise ValueError('context_file must be an existing source file inside this workspace')
    relative = relative.as_posix()
    manager = service._get_semantic_search()
    depth = service._retrieval_depth(top_k)
    # Discovery is shared with ordinary lexical search and enforces its ignore policy.
    manager.warm()
    lexical_query = query
    if mode == 'auto':
        from attocode_intel._internal.integrations.context.semantic_search import _expand_query
        languages = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.go': 'go',
                     '.rs': 'rust', '.java': 'java', '.rb': 'ruby'}
        language = next((lang for ext, lang in languages.items() if file_filter.endswith(ext)), '')
        lexical_query = _expand_query(query, language)
    global_rows = service._search_after_warmup(manager, lambda: manager.search_candidates(
        lexical_query, top_k=depth, file_filter=file_filter))
    context = {'file': relative, 'status': 'unavailable', 'applied': False,
               'paths': [], 'relations': {}, 'omitted_paths': 0, 'absence_proven': False}
    try:
        ast = service._get_ast_service()
        eligible = {f.relative_path for f in ast._context_mgr._files}
        if relative not in eligible:
            raise ValueError('context_file is not eligible for structural indexing')
        imports = ast.get_dependencies(relative) & eligible
        importers = ast.get_dependents(relative) & eligible
        # Validate physical containment again for every candidate, including aliases.
        neighbors = sorted(p for p in (imports | importers) - {relative}
                           if (root / p).resolve().is_relative_to(root) and (root / p).is_file())
        paths = [relative, *neighbors[:31]]
        snapshot = ast.hydration_snapshot()
        coverage = {k: snapshot.get(k) for k in ('phase', 'parsed_files', 'total_files', 'discovery_truncated')}
        context.update(status='ready' if snapshot.get('phase') == 'ready' else 'partial', applied=True,
                       paths=paths, omitted_paths=max(0, len(neighbors)-31), coverage=coverage,
                       relations={p: 'context' if p == relative else 'imports' if p in imports else 'importer'
                                  for p in paths})
    except (OSError, RuntimeError, AttributeError):
        pass
    rows = global_rows
    if context['applied']:
        local_rows = manager.search_candidates(lexical_query, top_k=depth, file_filter=file_filter,
                                               allowed_paths=frozenset(context['paths']))
        original = {_identity(r): r for r in global_rows}
        merged, seen = [], set()
        for row in [*local_rows, *global_rows]:
            key = _identity(row)
            if key not in seen:
                seen.add(key)
                merged.append(original.get(key, row))
        rows = demote_tests(query, merged)[:depth]
    ranking = {'method': 'context_lexical', 'returned_count': min(top_k, len(rows)),
               'model_status': 'off', 'broad_ranker': 'off',
               'query': query_diagnostics(query, rows, file_filter), 'context': context}
    return rows, rows[:top_k], ranking
