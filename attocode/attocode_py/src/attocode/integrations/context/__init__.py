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
    FileInfo,
    RepoMap,
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

__all__ = [
    # auto_compaction
    "AutoCompactionManager",
    "CompactionCheckResult",
    "CompactionStats",
    "CompactionStatus",
    "CompactionStrategy",
    # codebase_context
    "CodebaseContextManager",
    "FileInfo",
    "RepoMap",
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
]
