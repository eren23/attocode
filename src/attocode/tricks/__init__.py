"""Context engineering tricks.

Techniques for optimizing LLM context usage:
- KV-cache aware context building
- Goal recitation for persistence
- Reversible compaction with reference preservation
- Failure evidence tracking
- Serialization diversity for cache-busting
- JSON extraction utilities
"""

from attocode.tricks.failure_evidence import Failure, FailureTracker
from attocode.tricks.json_utils import (
    extract_json,
    extract_json_array,
    extract_json_objects,
    fix_trailing_commas,
    safe_parse,
    truncate_json,
)
from attocode.tricks.kv_cache import CacheableContentBlock, CacheAwareContext, CacheStats
from attocode.tricks.recitation import RecitationManager, RecitationState
from attocode.tricks.recursive_context import (
    ContextNode,
    RecursiveContextResult,
    RecursiveContextRetriever,
)
from attocode.tricks.reversible_compaction import Reference, ReversibleCompactor
from attocode.tricks.serialization_diversity import DiverseSerializer

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
    # recursive_context
    "ContextNode",
    "RecursiveContextResult",
    "RecursiveContextRetriever",
    # json_utils
    "extract_json",
    "extract_json_array",
    "extract_json_objects",
    "fix_trailing_commas",
    "safe_parse",
    "truncate_json",
]
