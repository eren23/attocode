"""Context engineering integrations."""

from attocode.integrations.context.auto_compaction import (
    AutoCompactionManager,
    CompactionCheckResult,
    CompactionStats,
    CompactionStatus,
    CompactionStrategy,
)
from attocode.integrations.context.codebase_context import (
    CodebaseContextManager,
    DependencyGraph,
    FileInfo,
    RepoMap,
    build_dependency_graph,
)
from attocode.integrations.context.code_analyzer import (
    CodeAnalyzer,
    CodeChunk,
    FileAnalysis,
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
from attocode.integrations.context.code_selector import (
    CodeSelector,
    SelectionConfig,
    SelectionResult,
    SelectionStrategy,
)
from attocode.integrations.context.file_cache import (
    CacheEntry,
    FileCache,
    FileCacheStats,
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
from attocode.integrations.context.semantic_cache import (
    SemanticCacheConfig,
    SemanticCacheManager,
)
from attocode.integrations.context.ast_service import ASTService
from attocode.integrations.context.ast_server import ASTServer
from attocode.integrations.context.ast_client import ASTClient
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
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
]
