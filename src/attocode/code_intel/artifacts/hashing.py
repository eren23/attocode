"""Canonical action-hash computation for derived code-intel artifacts.

Given (artifact_type, indexer identity, input blob OID, config), produce a
deterministic SHA-256 that is byte-identical across machines, processes, and
the stdio-vs-HTTP split.

Any tool that caches or ships a derived artifact should key it by this hash.
The formula is frozen — changing it silently would invalidate every cached
artifact across the fleet, so callers should bump the ``v1`` suffix and write
a migration.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# Version tag baked into every action_hash. Bump only in a coordinated
# migration that also rebuilds the caches that depend on it.
ACTION_HASH_SCHEMA = "atto.artifact.v1"

# Allowed artifact types. Keeping this closed lets us catch typos at the
# boundary and gives us a reason to fail loudly on unknown derived artifacts
# rather than silently producing "works but not shared" hashes.
ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "symbols",
        "references",
        "embedding",
        "ast",
        "deps",
        "repo_map_entry",
        "stack_graph",
        "conventions",
        "learning_ref",
        # Aliases for server-side content_type values:
        "symbol_set_v1",
        "dep_graph_v1",
        "embedding_blob_v1",
        "stack_graph_partial_v1",
        "repo_map_slice_v1",
        "conventions_v1",
    }
)

# Whitelist of config keys that contribute to `config_digest` per artifact
# type. Anything not in the whitelist is intentionally *excluded* from the
# hash — it's meta (e.g. user preferences, display options) that doesn't
# affect the derived output.
CONFIG_SUBSET: Mapping[str, tuple[str, ...]] = {
    "symbols": (
        "language",
        "parser_kind",
        "parser_version",
        "extract_signatures",
        "extract_docstrings",
    ),
    "symbol_set_v1": (
        "language",
        "parser_kind",
        "parser_version",
        "extract_signatures",
        "extract_docstrings",
    ),
    "references": (
        "language",
        "parser_kind",
        "parser_version",
    ),
    "embedding": (
        "model_name",
        "model_version",
        "dimension",
        "normalize",
        "chunker",
        "chunk_size",
        "chunk_overlap",
        "preprocessor_version",
    ),
    "embedding_blob_v1": (
        "model_name",
        "model_version",
        "dimension",
        "normalize",
        "chunker",
        "chunk_size",
        "chunk_overlap",
        "preprocessor_version",
    ),
    "ast": (
        "language",
        "parser_kind",
        "parser_version",
    ),
    "deps": (
        "language",
        "resolver_strategy",
        "resolver_version",
        "follow_dynamic_imports",
    ),
    "dep_graph_v1": (
        "language",
        "resolver_strategy",
        "resolver_version",
        "follow_dynamic_imports",
    ),
    "repo_map_entry": (
        "indexer_version",
        "slice_root",
        "max_depth",
        "ranker_version",
        "max_tokens",
    ),
    "repo_map_slice_v1": (
        "indexer_version",
        "slice_root",
        "max_depth",
        "ranker_version",
        "max_tokens",
    ),
    "stack_graph": (
        "language",
        "sg_grammar_version",
        "rules_version",
    ),
    "stack_graph_partial_v1": (
        "language",
        "sg_grammar_version",
        "rules_version",
    ),
    "conventions": (
        "rule_pack_version",
    ),
    "conventions_v1": (
        "rule_pack_version",
    ),
    "learning_ref": ("schema_version",),
}


def canonical_json(obj: Any) -> bytes:
    """Stable JSON encoding for hashing.

    Sorts dict keys, disables non-ASCII escaping (so all bytes are stable
    regardless of locale), no whitespace, no NaN/Infinity. The resulting
    bytes are a canonical form — two processes on different machines
    always produce the same output for equivalent Python objects.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def compute_config_digest(artifact_type: str, config: Mapping[str, Any]) -> str:
    """Hash a config dict down to a hex digest, using only the whitelisted keys.

    Unknown keys are *silently ignored* (not an error) because callers legitimately
    pass richer config objects than the hash cares about. Keys in the whitelist
    that are missing from ``config`` default to ``None`` — so adding a new
    config knob is a non-breaking change only when it starts as ``None``.
    """
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(
            f"unknown artifact_type {artifact_type!r}; allowed: {sorted(ARTIFACT_TYPES)}"
        )
    allowed = CONFIG_SUBSET.get(artifact_type, ())
    subset = {key: config.get(key) for key in allowed}
    return hashlib.sha256(canonical_json(subset)).hexdigest()


def compute_action_hash(
    artifact_type: str,
    *,
    indexer_name: str,
    indexer_version: str,
    input_blob_oid: str,
    config: Mapping[str, Any],
    input_tree_oid: str | None = None,
) -> str:
    """Compute the canonical action hash for a derived artifact.

    Formula::

        sha256(
            "atto.artifact.v1" || "\\n" ||
            "type="     || artifact_type    || "\\n" ||
            "indexer="  || indexer_name     || "\\n" ||
            "iversion=" || indexer_version  || "\\n" ||
            "input="    || input_blob_oid   || "\\n" ||
            "tree="     || input_tree_oid   || "\\n" ||
            "config="   || config_digest    || "\\n"
        )

    The delimiter is ``\\n`` and values are passed through unchanged — that's
    fine because every field is either a short identifier or an already-hex
    digest, so there is no delimiter ambiguity in practice.
    """
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(
            f"unknown artifact_type {artifact_type!r}; allowed: {sorted(ARTIFACT_TYPES)}"
        )
    config_digest = compute_config_digest(artifact_type, config)
    payload = (
        f"{ACTION_HASH_SCHEMA}\n"
        f"type={artifact_type}\n"
        f"indexer={indexer_name}\n"
        f"iversion={indexer_version}\n"
        f"input={input_blob_oid}\n"
        f"tree={input_tree_oid or ''}\n"
        f"config={config_digest}\n"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
