"""File dependency graph utilities built from CodeIndex."""

from __future__ import annotations

from dataclasses import dataclass, field

from attocode_core.ast_index.indexer import CodeIndex


@dataclass(slots=True)
class DependencyGraph:
    edges: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_index(cls, idx: CodeIndex) -> "DependencyGraph":
        graph = cls()
        for f in idx.files:
            graph.edges.setdefault(f.file_path, set())
            for imp in f.imports:
                graph.edges[f.file_path].add(imp)
        return graph

    def impacted_files(self, seeds: list[str]) -> set[str]:
        impacted = set(seeds)
        changed = True
        while changed:
            changed = False
            for src, deps in self.edges.items():
                if src in impacted:
                    continue
                if any(dep in impacted for dep in deps):
                    impacted.add(src)
                    changed = True
        return impacted
