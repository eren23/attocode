"""Context engineering integrations."""

from attocode.integrations.context.ast_client import ASTClient
from attocode.integrations.context.ast_server import ASTServer
from attocode.integrations.context.ast_service import ASTService
from attocode.integrations.context.auto_compaction import (
    AutoCompactionManager,
    CompactionCheckResult,
    CompactionStats,
    CompactionStatus,
    CompactionStrategy,
)
from attocode.integrations.context.code_analyzer import (
    CodeAnalyzer,
    CodeChunk,
    FileAnalysis,
)
from attocode.integrations.context.code_selector import (
    CodeSelector,
    SelectionConfig,
    SelectionResult,
    SelectionStrategy,
)
from attocode.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    ImportDef,
    detect_language,
    parse_file,
    parse_javascript,
    parse_python,
)
from attocode.integrations.context.codebase_context import (
    CodebaseContextManager,
    DependencyGraph,
    FileInfo,
    RepoMap,
    build_dependency_graph,
)
from attocode.integrations.context.compaction import (
    CompactionResult,
    compact_tool_outputs,
    emergency_truncation,
    truncate_tool_output,
)
from attocode.integrations.context.context_engineering import (
    AssemblyResult,
    ContextBlock,
    ContextEngineeringManager,
    ContextPriority,
    FailureRecord,
    InjectionBudget,
)
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)
from attocode.integrations.context.index_store import (
    IndexStore,
    StoredFile,
    StoredReference,
    StoredSymbol,
)
from attocode.integrations.context.temporal_coupling import (
    ChurnEntry,
    CoChangeEntry,
    MergeRiskEntry,
    TemporalCouplingAnalyzer,
)
from attocode.integrations.context.embeddings import (
    EmbeddingProvider,
    NullEmbeddingProvider,
    create_embedding_provider,
)
from attocode.integrations.context.file_cache import (
    CacheEntry,
    FileCache,
    FileCacheStats,
)
from attocode.integrations.context.hierarchical_explorer import (
    DirectoryNode,
    ExplorerResult,
    FileNode,
    HierarchicalExplorer,
)
from attocode.integrations.context.memory_store import MemoryStore
from attocode.integrations.context.trigram_index import QueryResult, TrigramIndex
from attocode.integrations.context.semantic_cache import (
    SemanticCacheConfig,
    SemanticCacheManager,
)
from attocode.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode.integrations.context.vector_store import (
    SearchResult as VectorSearchResult,
)
from attocode.integrations.context.vector_store import (
    VectorEntry,
    VectorStore,
)

__all__ = [
    # auto_compaction
    "AutoCompactionManager",
    "CompactionCheckResult",
    "CompactionStats",
    "CompactionStatus",
    "CompactionStrategy",
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
    "CompactionResult",
    "compact_tool_outputs",
    "emergency_truncation",
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
