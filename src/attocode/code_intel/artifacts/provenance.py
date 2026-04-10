"""Provenance records describe how a derived code-intel artifact was produced.

Every symbol set, embedding, repo-map slice, etc. should carry a ``Provenance``
record so we can answer:

- Which model + version produced this embedding?
- Which indexer + version extracted these symbols?
- What blob (and optional tree) was the input?
- When, and on what host, was it produced?

This lets us detect staleness (indexer bumped, model swapped) and provides
the audit trail for retrieval determinism.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# Sentinel indexer_name used by the one-shot migration that backfills
# provenance onto pre-existing rows. Searching for this string is an easy
# way to find everything that still needs a real indexer pass.
LEGACY_INDEXER_NAME = "legacy-pre-v2"

PROVENANCE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Provenance:
    """A record of how one derived artifact was produced.

    Frozen + slotted so it's cheap to build many of these during an index
    run and so accidental mutation is a TypeError.
    """

    schema_version: int
    artifact_type: str
    action_hash: str
    input_blob_oid: str
    indexer_name: str
    indexer_version: str
    producer_host: str
    produced_at: float
    # Embeddings-specific; None for other artifact types.
    model_name: str | None = None
    model_version: str | None = None
    dimension: int | None = None
    preprocessing_digest: str | None = None
    # Optional contextual IDs — server-side sets these, local side leaves None.
    producer_service: str = "attocode-local"
    producer_user_id: str | None = None
    producer_job_id: str | None = None
    input_tree_oid: str | None = None
    # Original config subset that went into the action_hash, as canonical JSON
    # text — kept as a string so the dataclass stays hashable/frozen.
    config_json: str = "{}"

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        artifact_type: str,
        action_hash: str,
        input_blob_oid: str,
        indexer_name: str,
        indexer_version: str,
        config: Mapping[str, Any] | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        dimension: int | None = None,
        preprocessing_digest: str | None = None,
        producer_service: str = "attocode-local",
        producer_user_id: str | None = None,
        producer_job_id: str | None = None,
        input_tree_oid: str | None = None,
    ) -> Provenance:
        """Build a fresh provenance record with ``produced_at`` set to now."""
        config_json = json.dumps(
            dict(config or {}),
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return cls(
            schema_version=PROVENANCE_SCHEMA_VERSION,
            artifact_type=artifact_type,
            action_hash=action_hash,
            input_blob_oid=input_blob_oid,
            indexer_name=indexer_name,
            indexer_version=indexer_version,
            producer_host=socket.gethostname(),
            produced_at=time.time(),
            model_name=model_name,
            model_version=model_version,
            dimension=dimension,
            preprocessing_digest=preprocessing_digest,
            producer_service=producer_service,
            producer_user_id=producer_user_id,
            producer_job_id=producer_job_id,
            input_tree_oid=input_tree_oid,
            config_json=config_json,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON / JSONB storage."""
        return asdict(self)

    def to_json(self) -> str:
        """Canonical JSON text — stable for hashing."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Provenance:
        """Rebuild a Provenance from its dict form (tolerant of missing fields)."""
        # Copy known fields; unknown keys are silently dropped. Missing
        # required fields get sensible defaults matching a "legacy" marker
        # so we can still roundtrip rows that were inserted with a very old
        # schema.
        return cls(
            schema_version=int(data.get("schema_version", PROVENANCE_SCHEMA_VERSION)),
            artifact_type=str(data.get("artifact_type", "unknown")),
            action_hash=str(data.get("action_hash", "")),
            input_blob_oid=str(data.get("input_blob_oid", "")),
            indexer_name=str(data.get("indexer_name", LEGACY_INDEXER_NAME)),
            indexer_version=str(data.get("indexer_version", "0")),
            producer_host=str(data.get("producer_host", "unknown")),
            produced_at=float(data.get("produced_at", 0.0)),
            model_name=data.get("model_name"),
            model_version=data.get("model_version"),
            dimension=data.get("dimension"),
            preprocessing_digest=data.get("preprocessing_digest"),
            producer_service=str(data.get("producer_service", "attocode-local")),
            producer_user_id=data.get("producer_user_id"),
            producer_job_id=data.get("producer_job_id"),
            input_tree_oid=data.get("input_tree_oid"),
            config_json=str(data.get("config_json", "{}")),
        )


def legacy_provenance(
    artifact_type: str,
    *,
    input_blob_oid: str = "",
    produced_at: float | None = None,
    action_hash: str = "",
) -> Provenance:
    """Build a sentinel provenance record for the one-shot backfill.

    Use this when you have existing rows in a store that pre-date provenance
    tracking. Downstream tools can filter on ``indexer_name == LEGACY_INDEXER_NAME``
    to find rows that still need a real re-index pass.
    """
    return Provenance(
        schema_version=PROVENANCE_SCHEMA_VERSION,
        artifact_type=artifact_type,
        action_hash=action_hash,
        input_blob_oid=input_blob_oid,
        indexer_name=LEGACY_INDEXER_NAME,
        indexer_version="0",
        producer_host=socket.gethostname(),
        produced_at=produced_at if produced_at is not None else time.time(),
        model_name=None,
        model_version=None,
        dimension=None,
        preprocessing_digest=None,
        producer_service="attocode-backfill",
        producer_user_id=None,
        producer_job_id=None,
        input_tree_oid=None,
        config_json="{}",
    )
