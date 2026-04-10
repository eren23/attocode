"""Provenance write path for derived code-intel artifacts.

Codex review fix M7: migration 017 created the ``provenance`` table
months ago but nothing wrote to it — the ORM class was missing and
``EmbeddingStore.upsert_embeddings`` only stored inline
``embedding_provenance`` JSON. This module closes that gap by
providing a single entry point that normalizes a
``Provenance`` dataclass (from the shared ``artifacts/`` package) into
a row in the server-side ``provenance`` table.

Design:

- :func:`write_provenance_rows` accepts a list of dicts so batched
  writes (one per embedding chunk in the same upsert) are a single
  ``session.add_all`` call.
- The helper is deliberately loose about schema: any keys that don't
  match ``Provenance`` columns flow into the ``extra`` JSONB bucket, so
  callers from different phases (snapshots, rotations, future indexer
  runs) can tack on whatever contextual metadata they want without
  needing another migration.
- No commit — the caller owns the session lifecycle.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Columns that are first-class on the Provenance ORM (everything else
# in the input dict goes into ``extra``).
_TOP_LEVEL_COLS: frozenset[str] = frozenset({
    "action_hash",
    "artifact_type",
    "input_blob_oid",
    "input_tree_oid",
    "indexer_name",
    "indexer_version",
    "config_digest",
    "producer_service",
    "producer_user_id",
    "producer_job_id",
    "producer_host",
})


def _split_known(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Partition a raw dict into (top-level, extra) based on ORM columns."""
    top: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for k, v in data.items():
        if k in _TOP_LEVEL_COLS:
            top[k] = v
        else:
            extra[k] = v
    return top, extra


async def write_provenance_rows(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Insert provenance rows for a batch of derived artifacts.

    Each ``row`` is a dict whose keys are either Provenance ORM column
    names or arbitrary extras (which land in the ``extra`` JSONB bucket).
    Missing required fields are filled from sensible defaults so callers
    can write a provenance row with just an ``action_hash`` +
    ``input_blob_oid`` if that's all they know.

    Returns the number of rows inserted. Does NOT commit — the caller
    is expected to be inside a larger unit of work that commits at its
    own boundary.
    """
    if not rows:
        return 0

    from attocode.code_intel.db.models import Provenance

    default_host = socket.gethostname() or "unknown"
    _ = time  # keep import alive for future use (e.g. produced_at override)

    orm_rows: list[Provenance] = []
    for raw in rows:
        top, extra = _split_known(dict(raw))
        orm_rows.append(
            Provenance(
                action_hash=str(top.get("action_hash", "")),
                artifact_type=str(top.get("artifact_type", "unknown")),
                input_blob_oid=str(top.get("input_blob_oid", "")),
                input_tree_oid=top.get("input_tree_oid"),
                indexer_name=str(top.get("indexer_name", "unknown")),
                indexer_version=str(top.get("indexer_version", "0")),
                config_digest=str(top.get("config_digest", "")),
                producer_service=str(
                    top.get("producer_service", "attocode-server"),
                ),
                producer_user_id=top.get("producer_user_id"),
                producer_job_id=top.get("producer_job_id"),
                producer_host=str(top.get("producer_host") or default_host),
                extra=extra,
            )
        )

    session.add_all(orm_rows)
    return len(orm_rows)


def embedding_provenance_dict(
    *,
    action_hash: str,
    content_sha: str,
    model_name: str,
    model_version: str,
    dimension: int | None,
    indexer_name: str = "attocode-embedding-store",
    indexer_version: str = "1",
    config_digest: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build the dict that gets passed to :func:`write_provenance_rows`
    for an embedding chunk.

    Factored out so :class:`EmbeddingStore` doesn't have to hand-assemble
    the same dict in every insert path.
    """
    row: dict[str, Any] = {
        "action_hash": action_hash,
        "artifact_type": "embedding_blob_v1",
        "input_blob_oid": f"sha256:{content_sha}",
        "indexer_name": indexer_name,
        "indexer_version": indexer_version,
        "config_digest": config_digest,
        "model_name": model_name,
        "model_version": model_version,
        "dimension": dimension,
    }
    row.update(extra)
    return row
