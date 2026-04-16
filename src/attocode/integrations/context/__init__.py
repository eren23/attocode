"""Context engineering integrations.

Exports are lazy-loaded to avoid pulling in heavy dependencies (tree-sitter,
numpy, sentence-transformers, AST parsing) at import time.  Basic sessions
that only use grep/glob tools pay no startup cost for context integrations.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    # auto_compaction
    "AutoCompactionManager",
    "CompactionCheckResult",
    "CompactionStats",
    "CompactionStatus",
    "CompactionStrategy",
    "POST_COMPACT_MAX_FILES",
    "POST_COMPACT_TOKEN_BUDGET",
    # codebase_context
    "CodebaseContextManager",
    "DependencyGraph",
    "FileInfo",
    "RepoMap",
    "build_dependency_graph",
    # code_analyzer
    "CodeAnalyzer",
    "CodeChunk",
    "FileAnalysis",
    # compaction
    "CODE_INTEL_TOOLS",
    "CompactionResult",
    "ContentReplacementState",
    "ReplacedContent",
    "ToolDecayProfile",
    "TOOL_DECAY_PROFILES",
    "compact_tool_outputs",
    "emergency_truncation",
    "microcompact",
    "truncate_tool_output",
    # context_engineering
    "AssemblyResult",
    "ContextBlock",
    "ContextEngineeringManager",
    "ContextPriority",
    "FailureRecord",
    "InjectionBudget",
    # code_selector
    "CodeSelector",
    "SelectionConfig",
    "SelectionResult",
    "SelectionStrategy",
    # file_cache
    "CacheEntry",
    "FileCache",
    "FileCacheStats",
    # codebase_ast
    "ClassDef",
    "FileAST",
    "FunctionDef",
    "ImportDef",
    "detect_language",
    "parse_file",
    "parse_javascript",
    "parse_python",
    # semantic_cache
    "SemanticCacheConfig",
    "SemanticCacheManager",
    # ast_service
    "ASTService",
    # ast_server
    "ASTServer",
    # ast_client
    "ASTClient",
    # cross_references
    "CrossRefIndex",
    "SymbolLocation",
    "SymbolRef",
    # index_store
    "IndexStore",
    "StoredFile",
    "StoredReference",
    "StoredSymbol",
    # temporal_coupling
    "ChurnEntry",
    "CoChangeEntry",
    "MergeRiskEntry",
    "TemporalCouplingAnalyzer",
    # hierarchical_explorer
    "DirectoryNode",
    "ExplorerResult",
    "FileNode",
    "HierarchicalExplorer",
    # semantic_search
    "ContextAssemblyConfig",
    "SearchScoringConfig",
    "SemanticSearchManager",
    "SemanticSearchResult",
    # vector_store
    "VectorSearchResult",
    "VectorEntry",
    "VectorStore",
    # embeddings
    "EmbeddingProvider",
    "NullEmbeddingProvider",
    "create_embedding_provider",
    # memory_store
    "MemoryStore",
    # trigram_index
    "QueryResult",
    "TrigramIndex",
]

# ---------------------------------------------------------------------------
# Lazy-load map: attribute name -> (module_path, attribute_name)
# ---------------------------------------------------------------------------
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # ast_client
    "ASTClient": ("attocode.integrations.context.ast_client", "ASTClient"),
    # ast_server
    "ASTServer": ("attocode.integrations.context.ast_server", "ASTServer"),
    # ast_service
    "ASTService": ("attocode.integrations.context.ast_service", "ASTService"),
    # auto_compaction
    "AutoCompactionManager": ("attocode.integrations.context.auto_compaction", "AutoCompactionManager"),
    "CompactionCheckResult": ("attocode.integrations.context.auto_compaction", "CompactionCheckResult"),
    "CompactionStats": ("attocode.integrations.context.auto_compaction", "CompactionStats"),
    "CompactionStatus": ("attocode.integrations.context.auto_compaction", "CompactionStatus"),
    "CompactionStrategy": ("attocode.integrations.context.auto_compaction", "CompactionStrategy"),
    "POST_COMPACT_MAX_FILES": ("attocode.integrations.context.auto_compaction", "POST_COMPACT_MAX_FILES"),
    "POST_COMPACT_TOKEN_BUDGET": ("attocode.integrations.context.auto_compaction", "POST_COMPACT_TOKEN_BUDGET"),
    # code_analyzer
    "CodeAnalyzer": ("attocode.integrations.context.code_analyzer", "CodeAnalyzer"),
    "CodeChunk": ("attocode.integrations.context.code_analyzer", "CodeChunk"),
    "FileAnalysis": ("attocode.integrations.context.code_analyzer", "FileAnalysis"),
    # code_selector
    "CodeSelector": ("attocode.integrations.context.code_selector", "CodeSelector"),
    "SelectionConfig": ("attocode.integrations.context.code_selector", "SelectionConfig"),
    "SelectionResult": ("attocode.integrations.context.code_selector", "SelectionResult"),
    "SelectionStrategy": ("attocode.integrations.context.code_selector", "SelectionStrategy"),
    # codebase_ast
    "ClassDef": ("attocode.integrations.context.codebase_ast", "ClassDef"),
    "FileAST": ("attocode.integrations.context.codebase_ast", "FileAST"),
    "FunctionDef": ("attocode.integrations.context.codebase_ast", "FunctionDef"),
    "ImportDef": ("attocode.integrations.context.codebase_ast", "ImportDef"),
    "detect_language": ("attocode.integrations.context.codebase_ast", "detect_language"),
    "parse_file": ("attocode.integrations.context.codebase_ast", "parse_file"),
    "parse_javascript": ("attocode.integrations.context.codebase_ast", "parse_javascript"),
    "parse_python": ("attocode.integrations.context.codebase_ast", "parse_python"),
    # codebase_context
    "CodebaseContextManager": ("attocode.integrations.context.codebase_context", "CodebaseContextManager"),
    "DependencyGraph": ("attocode.integrations.context.codebase_context", "DependencyGraph"),
    "FileInfo": ("attocode.integrations.context.codebase_context", "FileInfo"),
    "RepoMap": ("attocode.integrations.context.codebase_context", "RepoMap"),
    "build_dependency_graph": ("attocode.integrations.context.codebase_context", "build_dependency_graph"),
    # compaction
    "CODE_INTEL_TOOLS": ("attocode.integrations.context.compaction", "CODE_INTEL_TOOLS"),
    "CompactionResult": ("attocode.integrations.context.compaction", "CompactionResult"),
    "ContentReplacementState": ("attocode.integrations.context.compaction", "ContentReplacementState"),
    "ReplacedContent": ("attocode.integrations.context.compaction", "ReplacedContent"),
    "TOOL_DECAY_PROFILES": ("attocode.integrations.context.compaction", "TOOL_DECAY_PROFILES"),
    "ToolDecayProfile": ("attocode.integrations.context.compaction", "ToolDecayProfile"),
    "compact_tool_outputs": ("attocode.integrations.context.compaction", "compact_tool_outputs"),
    "emergency_truncation": ("attocode.integrations.context.compaction", "emergency_truncation"),
    "microcompact": ("attocode.integrations.context.compaction", "microcompact"),
    "truncate_tool_output": ("attocode.integrations.context.compaction", "truncate_tool_output"),
    # context_engineering
    "AssemblyResult": ("attocode.integrations.context.context_engineering", "AssemblyResult"),
    "ContextBlock": ("attocode.integrations.context.context_engineering", "ContextBlock"),
    "ContextEngineeringManager": ("attocode.integrations.context.context_engineering", "ContextEngineeringManager"),
    "ContextPriority": ("attocode.integrations.context.context_engineering", "ContextPriority"),
    "FailureRecord": ("attocode.integrations.context.context_engineering", "FailureRecord"),
    "InjectionBudget": ("attocode.integrations.context.context_engineering", "InjectionBudget"),
    # cross_references
    "CrossRefIndex": ("attocode.integrations.context.cross_references", "CrossRefIndex"),
    "SymbolLocation": ("attocode.integrations.context.cross_references", "SymbolLocation"),
    "SymbolRef": ("attocode.integrations.context.cross_references", "SymbolRef"),
    # embeddings
    "EmbeddingProvider": ("attocode.integrations.context.embeddings", "EmbeddingProvider"),
    "NullEmbeddingProvider": ("attocode.integrations.context.embeddings", "NullEmbeddingProvider"),
    "create_embedding_provider": ("attocode.integrations.context.embeddings", "create_embedding_provider"),
    # file_cache
    "CacheEntry": ("attocode.integrations.context.file_cache", "CacheEntry"),
    "FileCache": ("attocode.integrations.context.file_cache", "FileCache"),
    "FileCacheStats": ("attocode.integrations.context.file_cache", "FileCacheStats"),
    # hierarchical_explorer
    "DirectoryNode": ("attocode.integrations.context.hierarchical_explorer", "DirectoryNode"),
    "ExplorerResult": ("attocode.integrations.context.hierarchical_explorer", "ExplorerResult"),
    "FileNode": ("attocode.integrations.context.hierarchical_explorer", "FileNode"),
    "HierarchicalExplorer": ("attocode.integrations.context.hierarchical_explorer", "HierarchicalExplorer"),
    # index_store
    "IndexStore": ("attocode.integrations.context.index_store", "IndexStore"),
    "StoredFile": ("attocode.integrations.context.index_store", "StoredFile"),
    "StoredReference": ("attocode.integrations.context.index_store", "StoredReference"),
    "StoredSymbol": ("attocode.integrations.context.index_store", "StoredSymbol"),
    # memory_store
    "MemoryStore": ("attocode.integrations.context.memory_store", "MemoryStore"),
    # semantic_cache
    "SemanticCacheConfig": ("attocode.integrations.context.semantic_cache", "SemanticCacheConfig"),
    "SemanticCacheManager": ("attocode.integrations.context.semantic_cache", "SemanticCacheManager"),
    # semantic_search
    "ContextAssemblyConfig": ("attocode.integrations.context.semantic_search", "ContextAssemblyConfig"),
    "SearchScoringConfig": ("attocode.integrations.context.semantic_search", "SearchScoringConfig"),
    "SemanticSearchManager": ("attocode.integrations.context.semantic_search", "SemanticSearchManager"),
    "SemanticSearchResult": ("attocode.integrations.context.semantic_search", "SemanticSearchResult"),
    # temporal_coupling
    "ChurnEntry": ("attocode.integrations.context.temporal_coupling", "ChurnEntry"),
    "CoChangeEntry": ("attocode.integrations.context.temporal_coupling", "CoChangeEntry"),
    "MergeRiskEntry": ("attocode.integrations.context.temporal_coupling", "MergeRiskEntry"),
    "TemporalCouplingAnalyzer": ("attocode.integrations.context.temporal_coupling", "TemporalCouplingAnalyzer"),
    # trigram_index
    "QueryResult": ("attocode.integrations.context.trigram_index", "QueryResult"),
    "TrigramIndex": ("attocode.integrations.context.trigram_index", "TrigramIndex"),
    # vector_store
    "VectorSearchResult": ("attocode.integrations.context.vector_store", "SearchResult"),
    "VectorEntry": ("attocode.integrations.context.vector_store", "VectorEntry"),
    "VectorStore": ("attocode.integrations.context.vector_store", "VectorStore"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        # Cache on the module so subsequent accesses are fast
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
