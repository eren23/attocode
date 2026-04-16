"""Shared code-intel reproducibility primitives.

This package holds substrate shared by both the local stdio MCP side and the
server HTTP side:

- ``hashing``: canonical ``action_hash`` computation for derived artifacts.
- ``provenance``: ``Provenance`` dataclass recording how an artifact was produced.
- ``retrieval_pin``: ``RetrievalPin`` format + per-store manifest-hash helpers
  used to make ranked-result tools deterministic.

Everything here is pure Python with stdlib-only imports so it can be imported
from either the local ``attocode.integrations.context.*`` modules or the
server ``attocode.code_intel.storage.*`` modules without pulling in SQL,
FastAPI, or FastMCP dependencies.
"""

from __future__ import annotations

from .hashing import (
    ARTIFACT_TYPES,
    canonical_json,
    compute_action_hash,
    compute_config_digest,
    sha256_file,
)
from .provenance import LEGACY_INDEXER_NAME, Provenance, legacy_provenance
from .retrieval_pin import (
    RetrievalPin,
    compute_store_hash,
    make_pin_id,
)

__all__ = [
    "ARTIFACT_TYPES",
    "LEGACY_INDEXER_NAME",
    "Provenance",
    "RetrievalPin",
    "canonical_json",
    "compute_action_hash",
    "compute_config_digest",
    "compute_store_hash",
    "legacy_provenance",
    "make_pin_id",
    "sha256_file",
]
