"""Server-side retrieval pin computation.

HTTP search routes return ``pin_id`` + ``manifest_hash`` so clients can
track the state they queried against (matching the local stdio MCP
``_stamp_pin``). Per-store manifest hashes are computed via cheap
``SELECT COUNT + MAX(updated_at)`` probes; pins are ephemeral and not
persisted in a pins table.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from attocode.code_intel.artifacts import RetrievalPin, compute_store_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def compute_server_manifest_hashes(
    session: AsyncSession,
    *,
    repo_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """Compute cheap per-store content hashes for the server-side stores.

    Returns a ``{store_name: sha256hex}`` dict that matches the shape
    of :func:`attocode.code_intel.tools.pin_tools._compute_current_manifest_hashes`
    (the local-side equivalent). A store's hash changes whenever its
    row count or latest ``created_at`` / ``updated_at`` timestamp moves.

    ``repo_id`` / ``branch_id`` may scope the hash; the current
    implementation uses a global view — the returned hash is
    informational, not a cryptographic commitment to the repo's exact
    state.
    """
    from sqlalchemy import text

    results: dict[str, str] = {}

    # Each store is probed via a single cheap aggregate query. Failures
    # on any individual store fall through to ``absent`` so a missing
    # table (e.g. on an older schema) doesn't break the whole response.
    async def _probe(name: str, sql: str, params: dict) -> None:
        try:
            row = (await session.execute(text(sql), params)).fetchone()
        except Exception as exc:
            logger.debug("server pin: %s probe failed: %s", name, exc)
            results[name] = "absent"
            return
        if row is None:
            results[name] = "absent"
            return
        row_count = int(row[0] or 0)
        # Postgres MAX() on timestamptz returns a datetime; coerce to
        # float epoch for the hash so it matches the local format.
        ts = row[1]
        max_updated_at: float | None = None
        if ts is not None:
            try:
                max_updated_at = ts.timestamp()
            except AttributeError:
                max_updated_at = float(ts)
        results[name] = compute_store_hash(
            schema_version="1",
            row_count=row_count,
            max_updated_at=max_updated_at,
        )

    repo_clause = "" if repo_id is None else " (scoped)"
    branch_params: dict = {}
    if branch_id is not None:
        branch_params["branch_id"] = str(branch_id)

    # file_contents — global; repo scoping would require a join via
    # branch_files which is overkill here.
    await _probe(
        "file_contents",
        "SELECT COUNT(*), MAX(created_at) FROM file_contents",
        {},
    )
    await _probe(
        "symbols",
        "SELECT COUNT(*), MAX(created_at) FROM symbols",
        {},
    )
    await _probe(
        "embeddings",
        "SELECT COUNT(*), MAX(created_at) FROM embeddings",
        {},
    )
    await _probe(
        "dependencies",
        "SELECT COUNT(*), NULL::timestamptz FROM dependencies",
        {},
    )
    # branch_files scoped per branch if we have one, else global row count.
    if branch_id is not None:
        await _probe(
            "branch_files",
            "SELECT COUNT(*), NULL::timestamptz FROM branch_files "
            "WHERE branch_id = CAST(:branch_id AS uuid)",
            branch_params,
        )
    else:
        await _probe(
            "branch_files",
            "SELECT COUNT(*), NULL::timestamptz FROM branch_files",
            {},
        )

    logger.debug(
        "server pin%s: computed %d store hashes",
        repo_clause, len(results),
    )
    return results


async def build_retrieval_pin(
    session: AsyncSession,
    *,
    repo_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
) -> RetrievalPin:
    """Build a fresh :class:`RetrievalPin` for the current server state.

    Server pins are ephemeral (not persisted in a pins table). The
    ``pin_id`` is deterministic off the manifest hash so repeat calls
    on an unchanged state return an identical id, letting clients
    cheap-compare across requests.
    """
    hashes = await compute_server_manifest_hashes(
        session, repo_id=repo_id, branch_id=branch_id,
    )
    pin = RetrievalPin.create(
        manifest_hashes=hashes,
        branch_id=str(branch_id) if branch_id else None,
        ttl_seconds=0,
    )
    # Deterministic id — matches the local ``_stamp_pin`` format
    # (``pin_<hex20>``) so clients don't need to distinguish server
    # vs. local pins by format.
    deterministic_id = f"pin_{pin.manifest_hash[:20]}"
    return RetrievalPin(
        pin_id=deterministic_id,
        schema_version=pin.schema_version,
        manifest_hashes=pin.manifest_hashes,
        manifest_hash=pin.manifest_hash,
        overlay_id=pin.overlay_id,
        branch_id=pin.branch_id,
        created_at=pin.created_at,
        expires_at=pin.expires_at,
    )
