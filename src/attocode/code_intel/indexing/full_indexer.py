"""Full indexer — reads all files from git tree, indexes content, symbols, deps.

Uses content-addressed storage: files with the same content across branches
are stored and indexed only once.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Callable

from attocode.code_intel.indexing.parser import detect_language, extract_imports, extract_references, extract_symbols

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from attocode.code_intel.git.manager import GitRepoManager

logger = logging.getLogger(__name__)

# Skip binary/large files
_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
                    ".ttf", ".eot", ".pdf", ".zip", ".tar", ".gz", ".bin", ".exe",
                    ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class", ".o"}
_MAX_FILE_SIZE = 1_000_000  # 1MB


def _load_path_aliases(known_paths: set[str], config_contents: dict[str, bytes]) -> dict[str, str]:
    """Parse tsconfig.json/jsconfig.json for path alias mappings.

    Returns dict mapping alias prefix to resolved directory.
    E.g., {"@/": "frontend/src/"} from paths: {"@/*": ["./src/*"]}
    """
    import json
    from pathlib import PurePosixPath

    aliases: dict[str, str] = {}
    config_names = [p for p in known_paths if p.endswith(("tsconfig.json", "jsconfig.json"))]

    for config_path in config_names:
        raw = config_contents.get(config_path)
        if not raw:
            continue
        try:
            config = json.loads(raw.decode("utf-8", errors="replace"))
            paths = config.get("compilerOptions", {}).get("paths", {})
            base_url = config.get("compilerOptions", {}).get("baseUrl", ".")
            config_dir = str(PurePosixPath(config_path).parent)

            for alias_pattern, targets in paths.items():
                if not targets:
                    continue
                prefix = alias_pattern.rstrip("*")
                target = targets[0].rstrip("*")
                resolved = str(PurePosixPath(config_dir) / base_url / target)
                resolved = resolved.lstrip("./")
                if not resolved.endswith("/"):
                    resolved += "/"
                aliases[prefix] = resolved
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            continue
    return aliases


def _resolve_import_path(
    import_name: str,
    source_path: str,
    known_paths: set[str],
    language: str | None,
    aliases: dict[str, str] | None = None,
) -> str | None:
    """Resolve an import string to a file path in the repo.

    Returns the matching path or None if unresolvable.
    """
    from pathlib import PurePosixPath

    if language == "python":
        # foo.bar -> foo/bar.py or foo/bar/__init__.py
        parts = import_name.replace(".", "/")
        candidates = [f"{parts}.py", f"{parts}/__init__.py"]
    elif language in ("javascript", "typescript"):
        if import_name.startswith("."):
            # Relative import — resolve against source dir
            source_dir = str(PurePosixPath(source_path).parent)
            base = str(PurePosixPath(source_dir) / import_name)
            # Normalize path (remove ../)
            base = str(PurePosixPath(base))
        else:
            # Try path aliases first
            base = None
            if aliases:
                for prefix, target_dir in aliases.items():
                    if import_name.startswith(prefix):
                        remainder = import_name[len(prefix):]
                        base = f"{target_dir}{remainder}"
                        break
            if base is None:
                # Bare specifier (node_modules) — skip
                return None
        candidates = [
            f"{base}.ts", f"{base}.tsx", f"{base}.js", f"{base}.jsx",
            f"{base}/index.ts", f"{base}/index.tsx",
            f"{base}/index.js", f"{base}/index.jsx",
            base,  # exact match (e.g., .json, .css)
        ]
    else:
        return None

    for c in candidates:
        # Normalize: strip leading ./ if any
        c = c.lstrip("./")
        if c in known_paths:
            return c
    return None


class FullIndexer:
    """Full repository indexer.

    Reads all files from a git tree at a specific ref, computes content hashes,
    extracts symbols, and stores everything in content-addressed storage.

    Content dedup: if a file's content has already been stored (from another
    branch or previous indexing), the content, symbols, and embeddings are
    reused automatically via SHA-256 keying.
    """

    def __init__(
        self,
        session: AsyncSession,
        git_manager: GitRepoManager,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self._session = session
        self._git = git_manager
        self._progress = progress_callback or (lambda _: None)

    async def index(
        self,
        repo_id: str,
        branch_id: uuid.UUID,
        ref: str = "main",
    ) -> dict:
        """Perform a full index of a branch.

        Returns stats dict: {files_indexed, symbols_found, skipped_existing,
                            errors, duration_ms}.
        """
        import time

        from attocode.code_intel.storage.branch_overlay import BranchOverlay
        from attocode.code_intel.storage.content_store import ContentStore
        from attocode.code_intel.storage.dependency_store import DependencyStore
        from attocode.code_intel.storage.symbol_store import SymbolStore

        start = time.monotonic()
        content_store = ContentStore(self._session)
        symbol_store = SymbolStore(self._session)
        dep_store = DependencyStore(self._session)
        overlay = BranchOverlay(self._session)

        stats = {
            "files_indexed": 0,
            "symbols_found": 0,
            "references_found": 0,
            "skipped_existing": 0,
            "skipped_binary": 0,
            "dependencies_found": 0,
            "errors": 0,
        }

        # Get all files from git tree recursively
        all_files = self._walk_tree(repo_id, ref)
        total = len(all_files)
        known_paths = {path for path, _ in all_files}

        self._progress({"phase": "indexing", "total": total, "current": 0})

        # Capture tsconfig/jsconfig contents for path alias resolution
        config_contents: dict[str, bytes] = {}

        # Batch overlay updates
        overlay_updates: list[tuple[str, str, str]] = []
        # Track path->sha for dependency resolution (second pass)
        path_to_sha: dict[str, str] = {}
        # Deferred import extraction: (path, sha, imports, language)
        deferred_deps: list[tuple[str, str, list[str], str | None]] = []
        # Deferred reference extraction: (sha, content, path)
        deferred_refs: list[tuple[str, bytes, str]] = []

        for i, (path, oid) in enumerate(all_files):
            try:
                # Skip binary/large files
                ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
                if ext.lower() in _SKIP_EXTENSIONS:
                    stats["skipped_binary"] += 1
                    continue

                content = self._git.read_file(repo_id, ref, path)
                if path.endswith(("tsconfig.json", "jsconfig.json")):
                    config_contents[path] = content
                if len(content) > _MAX_FILE_SIZE:
                    stats["skipped_binary"] += 1
                    continue

                # Content-addressed storage — dedup across branches
                language = detect_language(path)
                sha = await content_store.store(content, language)
                overlay_updates.append((path, sha, "added"))
                path_to_sha[path] = sha

                # Extract symbols (skip if SHA already has symbols — cross-branch dedup)
                symbols = extract_symbols(content, path)
                if symbols:
                    count = await symbol_store.upsert_symbols(
                        sha, symbols, skip_if_exists=True
                    )
                    if count == 0:
                        stats["skipped_existing"] += 1
                    else:
                        stats["symbols_found"] += count

                # Extract imports (defer resolution until all paths are known)
                imports = extract_imports(content, path, language)
                if imports:
                    deferred_deps.append((path, sha, imports, language))

                # Defer reference extraction for third pass
                if language in ("python", "javascript", "typescript"):
                    deferred_refs.append((sha, content, path))

                stats["files_indexed"] += 1

                if (i + 1) % 100 == 0:
                    self._progress({"phase": "indexing", "total": total, "current": i + 1})
                    # Flush batch overlay updates periodically
                    if overlay_updates:
                        await overlay.set_files_batch(branch_id, overlay_updates)
                        overlay_updates = []
                    await self._session.flush()

            except Exception as e:
                logger.warning("Error indexing %s: %s", path, e)
                stats["errors"] += 1

        # Final batch
        if overlay_updates:
            await overlay.set_files_batch(branch_id, overlay_updates)

        # Resolve path aliases from tsconfig/jsconfig
        aliases = _load_path_aliases(known_paths, config_contents)

        # Second pass: resolve imports to dependencies
        self._progress({"phase": "resolving_dependencies", "total": len(deferred_deps), "current": 0})
        for idx, (source_path, source_sha, imports, language) in enumerate(deferred_deps):
            try:
                if await dep_store.has_dependencies(source_sha):
                    continue
                deps: list[dict] = []
                for imp in imports:
                    target_path = _resolve_import_path(imp, source_path, known_paths, language, aliases=aliases)
                    if target_path and target_path in path_to_sha:
                        deps.append({
                            "target_sha": path_to_sha[target_path],
                            "dep_type": "import",
                            "weight": 1.0,
                        })
                if deps:
                    await dep_store.upsert_dependencies(source_sha, deps)
                    stats["dependencies_found"] += len(deps)
            except Exception as e:
                logger.warning("Error resolving deps for %s: %s", source_path, e)

        # Third pass: extract symbol references (call sites)
        self._progress({"phase": "extracting_references", "total": len(deferred_refs), "current": 0})
        from attocode.code_intel.db.models import SymbolReference

        refs_seen_shas: set[str] = set()
        for idx, (sha, content, file_path) in enumerate(deferred_refs):
            if sha in refs_seen_shas:
                continue
            refs_seen_shas.add(sha)
            try:
                refs = extract_references(content, file_path)
                for r in refs:
                    self._session.add(SymbolReference(
                        content_sha=sha,
                        symbol_name=r["symbol_name"],
                        ref_kind=r["ref_kind"],
                        line=r["line"],
                        caller_qualified_name=r.get("caller_qualified_name", ""),
                    ))
                stats["references_found"] += len(refs)
            except Exception as e:
                logger.warning("Error extracting refs for %s: %s", file_path, e)

        await self._session.commit()

        duration_ms = int((time.monotonic() - start) * 1000)
        stats["duration_ms"] = duration_ms

        self._progress({"phase": "completed", "stats": stats})
        logger.info(
            "Full index complete: %d files, %d symbols, %d refs, %d reused, %d errors in %dms",
            stats["files_indexed"], stats["symbols_found"], stats["references_found"],
            stats["skipped_existing"], stats["errors"], duration_ms,
        )
        return stats

    def _walk_tree(self, repo_id: str, ref: str, path: str = "") -> list[tuple[str, str]]:
        """Recursively walk the git tree and return (path, oid) pairs."""
        entries = self._git.get_tree(repo_id, ref, path)
        files: list[tuple[str, str]] = []

        for entry in entries:
            if entry.type == "blob":
                files.append((entry.path, entry.oid))
            elif entry.type == "tree":
                files.extend(self._walk_tree(repo_id, ref, entry.path))

        return files
