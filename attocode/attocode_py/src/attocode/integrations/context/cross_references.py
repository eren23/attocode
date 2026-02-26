"""Cross-reference index for codebase symbol analysis.

Builds a bidirectional index of symbol definitions and references,
file-level import dependencies, and dependents from parsed AST data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SymbolRef:
    """A reference (call site, import, or attribute access) to a symbol."""

    symbol_name: str        # "parse_file" or "CodeIndex.build"
    ref_kind: str           # "call" | "import" | "attribute"
    file_path: str
    line: int


@dataclass(slots=True)
class SymbolLocation:
    """Location where a symbol is defined."""

    name: str
    qualified_name: str     # "CodebaseContextManager.discover_files"
    kind: str               # "function" | "class" | "method"
    file_path: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class CrossRefIndex:
    """Bidirectional cross-reference index for a codebase.

    Tracks symbol definitions, call sites, file-level import dependencies,
    and reverse dependents.
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

    def add_definition(self, loc: SymbolLocation) -> None:
        """Register a symbol definition."""
        self.definitions.setdefault(loc.qualified_name, []).append(loc)
        self.file_symbols.setdefault(loc.file_path, set()).add(loc.qualified_name)

    def add_reference(self, ref: SymbolRef) -> None:
        """Register a symbol reference."""
        self.references.setdefault(ref.symbol_name, []).append(ref)

    def add_file_dependency(self, source: str, target: str) -> None:
        """Record that *source* imports from *target*."""
        self.file_dependencies.setdefault(source, set()).add(target)
        self.file_dependents.setdefault(target, set()).add(source)

    def remove_file(self, file_path: str) -> None:
        """Remove all index entries for a file."""
        # Remove definitions
        for qname in list(self.file_symbols.get(file_path, [])):
            defs = self.definitions.get(qname, [])
            self.definitions[qname] = [d for d in defs if d.file_path != file_path]
            if not self.definitions[qname]:
                del self.definitions[qname]
        self.file_symbols.pop(file_path, None)

        # Remove references originating from this file
        for name, refs in list(self.references.items()):
            self.references[name] = [r for r in refs if r.file_path != file_path]
            if not self.references[name]:
                del self.references[name]

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

    def get_references(self, symbol_name: str) -> list[SymbolRef]:
        """Look up all call sites / references for a symbol."""
        return self.references.get(symbol_name, [])

    def get_dependents(self, file_path: str) -> set[str]:
        """Files that import from *file_path*."""
        return self.file_dependents.get(file_path, set())

    def get_dependencies(self, file_path: str) -> set[str]:
        """Files that *file_path* imports from."""
        return self.file_dependencies.get(file_path, set())
