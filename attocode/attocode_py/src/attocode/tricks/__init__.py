"""Context engineering tricks.

Techniques for optimizing LLM context usage:
- KV-cache aware context building
- Goal recitation for persistence
- Reversible compaction with reference preservation
- Failure evidence tracking
- Serialization diversity for cache-busting
- Recursive context retrieval
"""

from attocode.tricks.kv_cache import CacheAwareContext, CacheStats, CacheableContentBlock
from attocode.tricks.recitation import RecitationManager, RecitationState
from attocode.tricks.reversible_compaction import ReversibleCompactor, Reference
from attocode.tricks.failure_evidence import FailureTracker, Failure
from attocode.tricks.serialization_diversity import DiverseSerializer
from attocode.tricks.recursive_context import (
    ContextNode,
    RecursiveContextResult,
    RecursiveContextRetriever,
    extract_references,
)

__all__ = [
    "CacheAwareContext",
    "CacheStats",
    "CacheableContentBlock",
    "RecitationManager",
    "RecitationState",
    "ReversibleCompactor",
    "Reference",
    "FailureTracker",
    "Failure",
    "DiverseSerializer",
    "ContextNode",
    "RecursiveContextResult",
    "RecursiveContextRetriever",
    "extract_references",
]
