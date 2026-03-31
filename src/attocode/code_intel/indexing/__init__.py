"""Indexing pipeline -- full and delta indexing with progress tracking.

Exports are lazy-loaded to avoid pulling in tree-sitter and AST parsing
modules at import time.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["FullIndexer", "DeltaIndexer"]

# Lazy-load map: attribute name -> (module_path, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DeltaIndexer": ("attocode.code_intel.indexing.delta_indexer", "DeltaIndexer"),
    "FullIndexer": ("attocode.code_intel.indexing.full_indexer", "FullIndexer"),
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
