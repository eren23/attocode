"""Optional workspace-scoped language-server enrichment for daily navigation."""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from ._internal.integrations.context.codebase_ast import detect_language
from ._internal.integrations.context.syntax_evidence import symbol_position


class PrecisionSession:
    def __init__(self, service):
        self.service = service
        self.documents = {}
        self.pending = set()
        self.completed = {}
        self.failures = {}
        self.verified_languages = set()

    def invalidate(self, paths):
        self.pending.update(paths)
        self.completed.clear()
        self.failures.clear()

    async def enrich(self, name, file_path=None):
        if os.environ.get("ATTOCODE_INTEL_PRECISION", "auto") == "off":
            return {"status": "disabled"}
        ast = self.service._get_ast_service()
        definitions = ast.find_symbol(name)
        if file_path is not None:
            definitions = [d for d in definitions if d.file_path == file_path]
        if not definitions:
            return {"status": "no_definition"}
        key = tuple((d.file_path, d.start_line, d.qualified_name) for d in definitions)
        if key in self.completed:
            return self.completed[key]
        from ._internal.integrations.lsp.client import BUILTIN_SERVERS
        outcomes = []
        for definition in definitions[:8]:
            language = detect_language(definition.file_path)
            server_id = "typescript" if language == "javascript" else language
            config = BUILTIN_SERVERS.get(server_id)
            if not config or not shutil.which(config.command):
                outcomes.append({"language": language, "status": "unavailable"})
                continue
            if server_id in self.failures:
                outcomes.append({"language": language, "status": self.failures[server_id]})
                continue
            manager = self.service._get_lsp_manager()
            try:
                async with asyncio.timeout(5):
                    if server_id not in manager.get_active_servers():
                        manager._timeout = 3
                        await manager.start_server(server_id, Path(self.service.project_dir).as_uri())
                    # Send edits/deletions for all previously opened documents.
                    for rel in list(self.pending):
                        path = str(Path(self.service.project_dir) / rel)
                        if path in self.documents:
                            if Path(path).is_file():
                                self.documents[path] += 1
                                manager.notify_file_changed(path, Path(path).read_text(), self.documents[path])
                            else:
                                manager.notify_file_closed(path)
                                self.documents.pop(path)
                        elif Path(path).is_file() and manager._get_client_for_file(path):
                            manager.notify_file_opened(path, Path(path).read_text())
                            self.documents[path] = 1
                        self.pending.discard(rel)
                    path = str(Path(self.service.project_dir) / definition.file_path)
                    if path not in self.documents:
                        manager.notify_file_opened(path, Path(path).read_text())
                        self.documents[path] = 1
                    position = symbol_position(path, definition.name, definition.start_line,
                                               definition.end_line, language)
                    if position is None:
                        outcomes.append({"language": language, "status": "identifier_unavailable"})
                        continue
                    # Supply the explicit queried symbol; body ranges alone are ambiguous.
                    callback = manager.on_result_callback
                    manager.on_result_callback = None
                    try:
                        resolved = await manager.get_definition(path, *position)
                        if resolved is None:
                            outcomes.append({"language": language, "status": "not_resolved"})
                            continue
                        references = await manager.get_references(path, *position, include_declaration=False)
                    finally:
                        manager.on_result_callback = callback
                    ast.ingest_lsp_results("references", path, references,
                                           {"line": position[0], "col": position[1],
                                            "symbol_name": definition.qualified_name})
                    self.verified_languages.add(language)
                    outcomes.append({"language": language, "status": "verified",
                                     "symbol": definition.qualified_name, "references": len(references)})
            except Exception as exc:
                status = "timeout" if isinstance(exc, TimeoutError) or isinstance(exc.__cause__, TimeoutError) else "failed"
                self.failures[server_id] = status
                outcomes.append({"language": language, "status": status})
        status = "verified" if outcomes and all(o["status"] == "verified" for o in outcomes) else "partial"
        result = {"status": status, "queries": outcomes,
                  "definitions_truncated": len(definitions) > 8}
        self.completed[key] = result
        return result
