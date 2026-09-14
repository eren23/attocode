"""Report analysis capabilities independently of index progress."""
from __future__ import annotations

import shutil
from collections import Counter


def language_capabilities(verified_languages=()):
    from ._internal.integrations.context.codebase_ast import LANG_EXTENSIONS
    from ._internal.integrations.context.codebase_context import IMPORT_RESOLVERS
    from ._internal.integrations.context.ts_parser import is_available, supported_languages
    from ._internal.integrations.lsp.client import BUILTIN_SERVERS

    result = {}
    for language in sorted(set(LANG_EXTENSIONS.values()) | set(supported_languages())):
        server = BUILTIN_SERVERS.get("typescript" if language == "javascript" else language)
        parser = is_available(language)
        result[language] = {
            "search": "available",
            "definitions": "syntax" if parser else "fallback",
            "references": "syntax_candidates" if parser else "text_candidates",
            "dependencies": "partial" if language in IMPORT_RESOLVERS else "unavailable",
            "test_relationships": "heuristic",
            "precision_server": server.command if server else None,
            "precision_installed": bool(server and shutil.which(server.command)),
            "precision_verified": language in verified_languages,
        }
    return result


def analysis_report(service, precision=None):
    ast = service._ast_service
    if ast is None:
        return {"status": "not_started", "absence_proven": False}
    cache = ast._ast_cache.copy()
    tiers = Counter(getattr(a, "parsing_tier", "unknown") or "unknown" for a in cache.values())
    graph = ast._context_mgr._dep_graph
    unresolved = graph.unresolved if graph else {}
    limitations = [
        "Syntax matches are candidates; dynamic dispatch and external dependencies may be unresolved.",
        "No matches do not prove absence of references or impact.",
    ]
    return {
        "status": "partial",
        "absence_proven": False,
        "sources": sorted(tiers),
        "files_by_parser": dict(tiers),
        "unresolved_imports": sum(len(v) for v in unresolved.values()),
        "unresolved_import_samples": [
            {"file": path, "module": module}
            for path, modules in sorted(unresolved.items())[:5] for module in modules[:3]
        ],
        "unresolved_includes_external": True,
        "precision": precision or {"status": "not_requested"},
        "limitations": limitations,
    }
