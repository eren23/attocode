"""Cross-reference index for codebase symbol analysis.

Builds a bidirectional index of symbol definitions and references,
file-level import dependencies, and dependents from parsed AST data.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.integrations.context.index_store import IndexStore

logger = logging.getLogger(__name__)


def _split_name_tokens(name: str) -> list[str]:
    """Split a symbol name into lowercase tokens.

    Handles camelCase, PascalCase, snake_case, UPPER_CASE, and mixtures.

    Examples::

        "parseConfig"  -> ["parse", "config"]
        "parse_config" -> ["parse", "config"]
        "HTTPServer"   -> ["http", "server"]
        "HTMLParser"   -> ["html", "parser"]
        "_main"        -> ["main"]
        "IO"           -> ["io"]
    """
    # First split on underscores
    parts = name.split("_")
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        # Split camelCase / PascalCase: insert boundary before uppercase
        # that follows lowercase, or before uppercase followed by lowercase
        # (to handle "HTTPServer" -> "HTTP", "Server")
        sub = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", part)
        sub = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", sub)
        for s in sub.split("_"):
            if s:
                tokens.append(s.lower())
    return tokens


@dataclass(slots=True)
class SymbolRef:
    """A reference (call site, import, or attribute access) to a symbol."""

    symbol_name: str        # "parse_file" or "CodeIndex.build"
    ref_kind: str           # "call" | "import" | "attribute"
    file_path: str
    line: int
    source: str = "tree-sitter"  # "tree-sitter" | "lsp"
    # Qualified name of the function/method enclosing this reference. Empty
    # when the reference is at module top level or the enclosing symbol
    # could not be resolved. Populated for call-graph construction.
    caller_qualified_name: str = ""


@dataclass(slots=True)
class SymbolLocation:
    """Location where a symbol is defined."""

    name: str
    qualified_name: str     # "CodebaseContextManager.discover_files"
    kind: str               # "function" | "class" | "method"
    file_path: str
    start_line: int
    end_line: int
    source: str = "tree-sitter"  # "tree-sitter" | "lsp"


@dataclass(slots=True)
class CrossRefIndex:
    """Bidirectional cross-reference index for a codebase.

    Tracks symbol definitions, call sites, file-level import dependencies,
    and reverse dependents.  Includes an inverted name index for fast
    multi-strategy symbol search.

    Optionally backed by an ``IndexStore`` for persistence across restarts.
    """

    # qualified_name -> list of definition locations
    definitions: dict[str, list[SymbolLocation]] = field(default_factory=dict)
    # symbol name -> list of reference sites
    references: dict[str, list[SymbolRef]] = field(default_factory=dict)
    # file path -> set of qualified symbol names defined in that file
    file_symbols: dict[str, set[str]] = field(default_factory=dict)
    # file path -> set of file paths it imports from
    file_dependencies: dict[str, set[str]] = field(default_factory=dict)
    # file path -> set of file paths that import it
    file_dependents: dict[str, set[str]] = field(default_factory=dict)
    # caller qualified name -> set of callee bare/qualified names
    call_edges: dict[str, set[str]] = field(default_factory=dict)
    # callee bare/qualified name -> set of caller qualified names (reverse)
    callers_of: dict[str, set[str]] = field(default_factory=dict)

    # --- Inverted name indexes (populated by add_definition) ---
    # bare name -> set of qualified names
    _name_to_qnames: dict[str, set[str]] = field(default_factory=dict)
    # lowercased bare name -> set of qualified names
    _lower_to_qnames: dict[str, set[str]] = field(default_factory=dict)
    # individual token -> set of qualified names
    _tokens_to_qnames: dict[str, set[str]] = field(default_factory=dict)

    # Optional persistent store (set via set_store)
    _store: Any = field(default=None, repr=False)

    # Re-entrant lock guarding all mutating methods plus the iterating
    # reads that need a consistent snapshot. Reentrancy matters because
    # ``add_reference`` may call ``add_call_edge`` and ``remove_file``
    # walks every other map. Background hydration (``ASTService``'s
    # daemon thread) and LSP/MCP request threads can mutate the index
    # concurrently, so the lock prevents corrupted dicts and torn lists.
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False,
    )

    def set_store(self, store: IndexStore) -> None:
        """Attach an IndexStore for write-through persistence."""
        self._store = store

    def persist_file(self, file_path: str) -> None:
        """Write-through: save current in-memory symbols/refs for a file to the store."""
        if self._store is None:
            return
        with self._lock:
            self._persist_file_locked(file_path)

    def _persist_file_locked(self, file_path: str) -> None:
        if self._store is None:
            return
        # Collect symbols for this file
        sym_dicts: list[dict[str, Any]] = []
        for qname in self.file_symbols.get(file_path, set()):
            for loc in self.definitions.get(qname, []):
                if loc.file_path == file_path:
                    sym_dicts.append({
                        "name": loc.name,
                        "qualified_name": loc.qualified_name,
                        "kind": loc.kind,
                        "line": loc.start_line,
                        "end_line": loc.end_line,
                        "source": loc.source,
                    })
        self._store.save_symbols(file_path, sym_dicts)

        # Collect references originating from this file
        ref_dicts: list[dict[str, Any]] = []
        for ref_name, refs in self.references.items():
            for ref in refs:
                if ref.file_path == file_path:
                    ref_dicts.append({
                        "symbol_name": ref.symbol_name,
                        "ref_kind": ref.ref_kind,
                        "line": ref.line,
                        "column": 0,
                        "source": ref.source,
                        "caller_qualified_name": ref.caller_qualified_name,
                    })
        self._store.save_references(file_path, ref_dicts)

    def load_from_store(self) -> int:
        """Bulk-load symbols, references, and dependencies from the store.

        Returns the number of files loaded.
        """
        if self._store is None:
            return 0
        with self._lock:
            return self._load_from_store_locked()

    def _load_from_store_locked(self) -> int:
        if self._store is None:
            return 0

        stored_symbols = self._store.load_symbols()
        stored_refs = self._store.load_references()
        stored_deps = self._store.load_dependencies()

        files_loaded: set[str] = set()

        for s in stored_symbols:
            loc = SymbolLocation(
                name=s.name,
                qualified_name=s.qualified_name,
                kind=s.kind,
                file_path=s.file_path,
                start_line=s.line,
                end_line=s.end_line,
                source=s.source,
            )
            self.add_definition(loc)
            files_loaded.add(s.file_path)

        for r in stored_refs:
            ref = SymbolRef(
                symbol_name=r.symbol_name,
                ref_kind=r.ref_kind,
                file_path=r.file_path,
                line=r.line,
                source=r.source,
                caller_qualified_name=getattr(r, "caller_qualified_name", ""),
            )
            self.add_reference(ref)

        for src, targets in stored_deps.items():
            for tgt in targets:
                self.add_file_dependency(src, tgt)

        logger.debug(
            "CrossRefIndex loaded from store: %d files, %d symbols, %d refs",
            len(files_loaded), len(stored_symbols), len(stored_refs),
        )
        return len(files_loaded)

    def merge_lsp_results(
        self,
        file_path: str,
        definitions: list[SymbolLocation],
        references: list[SymbolRef],
    ) -> int:
        """Merge LSP-sourced results into the index.

        Deduplicates by (qualified_name, file, line) — LSP wins on conflict.
        Returns the number of new entries added.
        """
        with self._lock:
            return self._merge_lsp_results_locked(file_path, definitions, references)

    def _merge_lsp_results_locked(
        self,
        file_path: str,
        definitions: list[SymbolLocation],
        references: list[SymbolRef],
    ) -> int:
        added = 0

        for loc in definitions:
            # Create a copy with source="lsp" — don't mutate caller's input
            lsp_loc = SymbolLocation(
                name=loc.name, qualified_name=loc.qualified_name,
                kind=loc.kind, file_path=loc.file_path,
                start_line=loc.start_line, end_line=loc.end_line,
                source="lsp",
            )
            existing = self.definitions.get(lsp_loc.qualified_name, [])
            # Check for duplicate at same location
            dup = False
            for i, ex in enumerate(existing):
                if ex.file_path == lsp_loc.file_path and ex.start_line == lsp_loc.start_line:
                    # LSP wins: replace tree-sitter entry
                    existing[i] = lsp_loc
                    dup = True
                    break
            if not dup:
                self.add_definition(lsp_loc)
                added += 1

        for ref in references:
            lsp_ref = SymbolRef(
                symbol_name=ref.symbol_name, ref_kind=ref.ref_kind,
                file_path=ref.file_path, line=ref.line,
                source="lsp",
                caller_qualified_name=ref.caller_qualified_name,
            )
            # LSP wins on (file, line) collision — but ONLY when the
            # incoming ref carries a resolved caller. Without one, the
            # legacy ``ingest_lsp_results`` fallback path stores the
            # *enclosing function* in ``symbol_name`` (not the callee),
            # so replacing a tree-sitter entry would invert the edge.
            # In that case we dedupe-skip, preserving the existing
            # higher-precision tree-sitter ref.
            existing = self.references.get(lsp_ref.symbol_name, [])
            dup_index: int | None = None
            for i, ex in enumerate(existing):
                if ex.file_path == lsp_ref.file_path and ex.line == lsp_ref.line:
                    dup_index = i
                    break

            if dup_index is not None:
                if lsp_ref.caller_qualified_name:
                    existing[dup_index] = lsp_ref
                    if lsp_ref.ref_kind == "call":
                        self.add_call_edge(
                            lsp_ref.caller_qualified_name,
                            lsp_ref.symbol_name,
                        )
                # else: no caller info — leave the tree-sitter entry alone.
            else:
                self.add_reference(lsp_ref)
                added += 1

        # Persist if store is available
        self.persist_file(file_path)
        return added

    def add_definition(self, loc: SymbolLocation) -> None:
        """Register a symbol definition."""
        with self._lock:
            self.definitions.setdefault(loc.qualified_name, []).append(loc)
            self.file_symbols.setdefault(loc.file_path, set()).add(loc.qualified_name)
            # Populate inverted indexes
            bare = loc.qualified_name.rsplit(".", 1)[-1]
            self._name_to_qnames.setdefault(bare, set()).add(loc.qualified_name)
            self._lower_to_qnames.setdefault(bare.lower(), set()).add(loc.qualified_name)
            for token in _split_name_tokens(bare):
                self._tokens_to_qnames.setdefault(token, set()).add(loc.qualified_name)

    def add_reference(self, ref: SymbolRef) -> None:
        """Register a symbol reference."""
        with self._lock:
            self.references.setdefault(ref.symbol_name, []).append(ref)
            if ref.ref_kind == "call" and ref.caller_qualified_name:
                self.add_call_edge(ref.caller_qualified_name, ref.symbol_name)

    def add_call_edge(self, caller: str, callee: str) -> None:
        """Record that ``caller`` calls ``callee``.

        ``caller`` should be a qualified name (e.g. ``MyClass.do_thing`` or a
        bare top-level function name). ``callee`` is whatever the source
        wrote — bare name when type/scope resolution is unavailable; the
        consumer can disambiguate against ``self.definitions``.
        """
        if not caller or not callee:
            return
        with self._lock:
            self.call_edges.setdefault(caller, set()).add(callee)
            self.callers_of.setdefault(callee, set()).add(caller)

    def add_file_dependency(self, source: str, target: str) -> None:
        """Record that *source* imports from *target*."""
        with self._lock:
            self.file_dependencies.setdefault(source, set()).add(target)
            self.file_dependents.setdefault(target, set()).add(source)

    def remove_file(self, file_path: str) -> None:
        """Remove all index entries for a file (in-memory and store)."""
        with self._lock:
            self._remove_file_locked(file_path)

    def _remove_file_locked(self, file_path: str) -> None:
        if self._store is not None:
            self._store.remove_file(file_path)
        # Snapshot callers defined here BEFORE we mutate file_symbols below.
        callers_in_file = set(self.file_symbols.get(file_path, set()))
        # Remove definitions and clean up inverted indexes
        for qname in list(self.file_symbols.get(file_path, [])):
            defs = self.definitions.get(qname, [])
            self.definitions[qname] = [d for d in defs if d.file_path != file_path]
            if not self.definitions[qname]:
                del self.definitions[qname]
                # Clean up inverted indexes — qname fully gone
                bare = qname.rsplit(".", 1)[-1]
                s = self._name_to_qnames.get(bare)
                if s:
                    s.discard(qname)
                    if not s:
                        del self._name_to_qnames[bare]
                s = self._lower_to_qnames.get(bare.lower())
                if s:
                    s.discard(qname)
                    if not s:
                        del self._lower_to_qnames[bare.lower()]
                for token in _split_name_tokens(bare):
                    s = self._tokens_to_qnames.get(token)
                    if s:
                        s.discard(qname)
                        if not s:
                            del self._tokens_to_qnames[token]
        self.file_symbols.pop(file_path, None)

        # Remove references originating from this file
        for name, refs in list(self.references.items()):
            self.references[name] = [r for r in refs if r.file_path != file_path]
            if not self.references[name]:
                del self.references[name]

        # Drop call edges whose caller was defined in this file. We can't
        # reliably attribute callees from the file path alone (callees are
        # bare names), so this is a best-effort scrub keyed on caller.
        for caller in callers_in_file:
            for callee in self.call_edges.pop(caller, set()):
                rev = self.callers_of.get(callee)
                if rev is not None:
                    rev.discard(caller)
                    if not rev:
                        del self.callers_of[callee]

        # Remove dependency edges
        for dep in self.file_dependencies.pop(file_path, set()):
            dependents = self.file_dependents.get(dep)
            if dependents:
                dependents.discard(file_path)
                if not dependents:
                    del self.file_dependents[dep]

        # Remove as a dependent target
        for src in list(self.file_dependents.get(file_path, [])):
            deps = self.file_dependencies.get(src)
            if deps:
                deps.discard(file_path)
                if not deps:
                    del self.file_dependencies[src]
        self.file_dependents.pop(file_path, None)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def get_definitions(self, symbol_name: str) -> list[SymbolLocation]:
        """Look up definitions for a symbol (exact or suffix match)."""
        # Try exact qualified name first
        if symbol_name in self.definitions:
            return self.definitions[symbol_name]
        # Try suffix match (e.g. "discover_files" matches "CodebaseContextManager.discover_files")
        results: list[SymbolLocation] = []
        for qname, locs in self.definitions.items():
            if qname == symbol_name or qname.endswith(f".{symbol_name}"):
                results.extend(locs)
        return results

    def search_definitions(
        self,
        symbol_name: str,
        *,
        limit: int = 50,
        kind_filter: str = "",
    ) -> list[tuple[SymbolLocation, float]]:
        """Multi-strategy symbol search returning (location, score) pairs.

        Search strategies (in priority order):
        1. Exact qualified name match (score 1.0)
        2. Exact bare name match via index (score 0.95)
        3. Case-insensitive bare name match (score 0.85)
        4. Prefix match on bare name (score 0.75)
        5. Substring match on bare name (score 0.60)
        6. Token overlap (camelCase/snake_case) (score 0.50)
        """
        # Collect candidates as {qualified_name: best_match_score}
        candidates: dict[str, float] = {}

        # 1. Exact qualified name
        if symbol_name in self.definitions:
            candidates[symbol_name] = 1.0

        # 2. Exact bare name via inverted index — O(1)
        bare_qnames = self._name_to_qnames.get(symbol_name, set())
        for qn in bare_qnames:
            if qn not in candidates:
                candidates[qn] = 0.95

        # 3. Case-insensitive bare name — O(1)
        lower_qnames = self._lower_to_qnames.get(symbol_name.lower(), set())
        for qn in lower_qnames:
            if qn not in candidates:
                candidates[qn] = 0.85

        name_lower = symbol_name.lower()

        # 4. Prefix match on bare names — scan index keys
        for bare, qnames in self._name_to_qnames.items():
            if bare.lower().startswith(name_lower) and len(bare) > len(symbol_name):
                for qn in qnames:
                    if qn not in candidates:
                        candidates[qn] = 0.75

        # 5. Substring match on bare names
        if len(symbol_name) >= 2:
            for bare, qnames in self._name_to_qnames.items():
                if name_lower in bare.lower() and bare.lower() != name_lower:
                    for qn in qnames:
                        if qn not in candidates:
                            candidates[qn] = 0.60

        # 6. Token overlap (camelCase/snake_case)
        query_tokens = set(_split_name_tokens(symbol_name))
        if query_tokens:
            token_hits: dict[str, int] = {}
            for token in query_tokens:
                for qn in self._tokens_to_qnames.get(token, set()):
                    if qn not in candidates:
                        token_hits[qn] = token_hits.get(qn, 0) + 1
            for qn, hit_count in token_hits.items():
                # Score proportional to fraction of query tokens matched
                score = 0.50 * (hit_count / len(query_tokens))
                if score >= 0.25:  # at least half the tokens must match
                    candidates[qn] = score

        if not candidates:
            return []

        # Resolve candidates to SymbolLocations and compute composite scores
        scored: list[tuple[SymbolLocation, float]] = []
        for qname, match_score in candidates.items():
            locs = self.definitions.get(qname, [])
            for loc in locs:
                if kind_filter and loc.kind != kind_filter:
                    continue
                score = _rank_score(loc, match_score)
                scored.append((loc, score))

        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def get_references(self, symbol_name: str) -> list[SymbolRef]:
        """Look up all call sites / references for a symbol (exact or suffix match)."""
        # Exact match first
        if symbol_name in self.references:
            return self.references[symbol_name]
        # Suffix match (e.g. "clear" matches refs keyed as "MCPMetaTools.clear")
        results: list[SymbolRef] = []
        for ref_name, refs in self.references.items():
            if ref_name == symbol_name or ref_name.endswith(f".{symbol_name}"):
                results.extend(refs)
        return results

    def get_dependents(self, file_path: str) -> set[str]:
        """Files that import from *file_path*."""
        return self.file_dependents.get(file_path, set())

    def get_dependencies(self, file_path: str) -> set[str]:
        """Files that *file_path* imports from."""
        return self.file_dependencies.get(file_path, set())

    # ------------------------------------------------------------------
    # Call graph
    # ------------------------------------------------------------------

    def get_callees(self, caller: str, *, depth: int = 1) -> set[str]:
        """Return symbols called by ``caller`` up to ``depth`` hops.

        depth=1 returns direct callees only; depth=N follows up to N hops
        through the in-memory ``call_edges`` map. Cycles are handled by
        an internal visited set so the traversal always terminates.
        """
        if depth < 1:
            return set()
        with self._lock:
            visited: set[str] = set()
            frontier: set[str] = {caller}
            result: set[str] = set()
            for _ in range(depth):
                next_frontier: set[str] = set()
                for node in frontier:
                    if node in visited:
                        continue
                    visited.add(node)
                    callees = self.call_edges.get(node, set())
                    result.update(callees)
                    next_frontier.update(callees - visited)
                if not next_frontier:
                    break
                frontier = next_frontier
            return result

    def get_callers(self, callee: str, *, depth: int = 1) -> set[str]:
        """Return symbols that call ``callee`` up to ``depth`` hops back."""
        if depth < 1:
            return set()
        with self._lock:
            visited: set[str] = set()
            frontier: set[str] = {callee}
            result: set[str] = set()
            for _ in range(depth):
                next_frontier: set[str] = set()
                for node in frontier:
                    if node in visited:
                        continue
                    visited.add(node)
                    callers = self.callers_of.get(node, set())
                    result.update(callers)
                    next_frontier.update(callers - visited)
                if not next_frontier:
                    break
                frontier = next_frontier
            return result


def _rank_score(loc: SymbolLocation, match_score: float) -> float:
    """Composite ranking combining match quality and symbol importance."""
    importance = 0.0
    if not loc.name.startswith("_"):
        importance += 0.02
    kind_boost = {"class": 0.03, "interface": 0.03, "function": 0.01, "method": 0.0}
    importance += kind_boost.get(loc.kind, 0.0)
    # LSP-sourced entries are more precise
    if loc.source == "lsp":
        importance += 0.05
    return match_score + importance
