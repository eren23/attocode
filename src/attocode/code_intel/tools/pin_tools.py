"""Retrieval pin MCP tools — deterministic RAG for code-intel queries.

Every ranked-result tool (``semantic_search``, ``fast_search``, ``repo_map``,
etc.) is retrofitted to emit an ``index_pin`` footer on its response. A
caller can then:

  - ``pin_current``        : mint a fresh pin of the current index state.
  - ``pin_resolve``        : look up an existing pin's manifest.
  - ``pin_list``           : list all active pins.
  - ``pin_delete``         : drop a pin.
  - ``verify_pin``         : compare a pin's recorded state to the current
                             state and return a drift report.

Phase 1 delivers the pin primitive + verification flow. Phase 2 layers on
``retrieve_with_pin`` (re-run a tool against pinned state) once the stacked
overlay machinery lands.
"""

from __future__ import annotations

import logging
import sqlite3

from attocode.code_intel._shared import mcp
from attocode.code_intel.artifacts import RetrievalPin

# Pure helpers live in ``pin_store`` so they can be imported without
# dragging the MCP runtime in — critical for the HTTP API providers
# (see Codex P2 finding on ``local_provider.py`` round 3). This module
# layers the MCP ``@mcp.tool()`` decorators and the ``_stamp_pin``
# footer helper on top of those pure helpers.
from attocode.code_intel.tools.pin_store import (  # noqa: F401
    _STORE_DEFS,
    PinStore,
    _compute_current_manifest_hashes,
    _get_pin_store,
    _get_project_dir,
    _hash_for_store,
    _hash_for_trigrams,
    compute_and_persist_pin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# _stamp_pin helper — used by all ranked-result tools
# ---------------------------------------------------------------------------


def pin_stamped(fn):  # type: ignore[no-untyped-def]
    """Decorator: append an ``index_pin`` footer to a tool's string return.

    Apply *below* ``@mcp.tool()`` so the registered function is the
    wrapped one::

        @mcp.tool()
        @pin_stamped
        def semantic_search(...) -> str:
            ...

    Non-string returns pass through unchanged — defensive against tools
    that might return structured data in the future.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = fn(*args, **kwargs)
        if isinstance(result, str):
            return _stamp_pin(result)
        return result

    return wrapper


def _stamp_pin(result_text: str, *, persist: bool = True, ttl_seconds: int = 0) -> str:
    """Append an ``index_pin`` footer to a tool response.

    Computes the current per-store manifest hashes, derives a
    content-addressed deterministic pin id (``pin_<hex20>`` of the
    manifest hash), persists it via the :class:`PinStore`, and appends
    the full 64-char manifest hash to the response footer so callers
    can later look the pin up via ``verify_pin`` or ``pin_resolve``.

    Pin persistence is the default and the ``manifest_hash`` printed in
    the footer is the complete hex string (verifiable via ``verify_pin``
    / ``pin_resolve``).

    project_dir is resolved via ``_get_project_dir()`` in this module's
    namespace and passed *explicitly* into the pin_store helpers, so
    monkeypatching ``pin_tools._get_project_dir`` flows through to both
    the manifest-hash computation and the PinStore path.

    Idempotent: calling twice with no intervening writes produces the
    same deterministic id, which collapses to a single upserted row in
    the pin store.
    """
    project_dir = _get_project_dir()
    try:
        hashes = _compute_current_manifest_hashes(project_dir)
    except Exception as exc:
        logger.debug("pin: hash computation failed: %s", exc)
        return result_text

    pin = RetrievalPin.create(manifest_hashes=hashes, ttl_seconds=ttl_seconds)
    # Use a deterministic id derived from the manifest_hash so repeat calls
    # on an unchanged state yield the same pin_id. The prefix length (20
    # hex chars = 80 bits) is collision-resistant for single-project use
    # while staying short enough to paste into an MCP prompt.
    deterministic_id = f"pin_{pin.manifest_hash[:20]}"

    if persist:
        pin_to_save = RetrievalPin(
            pin_id=deterministic_id,
            schema_version=pin.schema_version,
            manifest_hashes=pin.manifest_hashes,
            manifest_hash=pin.manifest_hash,
            overlay_id=pin.overlay_id,
            branch_id=pin.branch_id,
            created_at=pin.created_at,
            expires_at=pin.expires_at,
        )
        try:
            _get_pin_store(project_dir).save(pin_to_save)
        except sqlite3.Error as exc:
            logger.debug("pin: persist failed: %s", exc)

    # Codex M3: no more truncation. The footer includes the full
    # ``manifest_hash`` so downstream tools can look up or hand-verify
    # the pin without round-tripping through pin_resolve.
    footer = (
        f"\n\n---\nindex_pin: {deterministic_id}\n"
        f"manifest_hash: {pin.manifest_hash}"
    )
    if result_text.endswith("\n"):
        return result_text + footer.lstrip("\n")
    return result_text + footer


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pin_current(ttl_seconds: int = 86400) -> str:
    """Mint a retrieval pin capturing the current code-intel state.

    A pin is a content-addressed snapshot of every local store's manifest
    hash (symbols, embeddings, learnings, ADRs, trigrams, etc.). Later you
    can call ``verify_pin(pin_id)`` to check whether the state has drifted
    since the pin was minted.

    Args:
        ttl_seconds: Pin expires after this many seconds. 0 = never expires.
                     Default 86400 (24h).

    Returns:
        The pin_id + a summary of hashed stores.

    The ``pin_id`` is derived deterministically from the manifest hash
    (``pin_<hex20>``), matching ``_stamp_pin`` and HTTP search-response
    pins. Two calls on unchanged state collapse to the same id, so the
    PinStore upsert never accumulates duplicates.
    """
    project_dir = _get_project_dir()
    hashes = _compute_current_manifest_hashes(project_dir)
    raw = RetrievalPin.create(manifest_hashes=hashes, ttl_seconds=ttl_seconds)
    deterministic_id = f"pin_{raw.manifest_hash[:20]}"
    pin = RetrievalPin(
        pin_id=deterministic_id,
        schema_version=raw.schema_version,
        manifest_hashes=raw.manifest_hashes,
        manifest_hash=raw.manifest_hash,
        overlay_id=raw.overlay_id,
        branch_id=raw.branch_id,
        created_at=raw.created_at,
        expires_at=raw.expires_at,
    )
    _get_pin_store(project_dir).save(pin)
    lines = [f"Pinned: {pin.pin_id}", f"manifest_hash: {pin.manifest_hash}"]
    if pin.expires_at > 0:
        import time
        remaining = int(pin.expires_at - time.time())
        lines.append(f"expires_in: {remaining}s")
    else:
        lines.append("expires_in: never")
    lines.append("stores:")
    for name, h in sorted(hashes.items()):
        short = h[:16] + "…" if len(h) > 20 else h
        lines.append(f"  - {name}: {short}")
    return "\n".join(lines)


@mcp.tool()
def pin_resolve(pin_id: str) -> str:
    """Look up a previously-minted retrieval pin by id."""
    pin = _get_pin_store(_get_project_dir()).get(pin_id)
    if pin is None:
        return f"No pin with id {pin_id!r}"
    lines = [
        f"pin_id: {pin.pin_id}",
        f"manifest_hash: {pin.manifest_hash}",
        f"created_at: {pin.created_at}",
        f"expires_at: {pin.expires_at if pin.expires_at > 0 else 'never'}",
        f"expired: {pin.is_expired()}",
        "stores:",
    ]
    for name, h in sorted(pin.manifest_hashes.items()):
        lines.append(f"  - {name}: {h}")
    return "\n".join(lines)


@mcp.tool()
def pin_list() -> str:
    """List all retrieval pins, most recent first."""
    store = _get_pin_store(_get_project_dir())
    store.gc_expired()
    pins = store.list_all()
    if not pins:
        return "No pins."
    lines = [f"{len(pins)} pin(s):"]
    for pin in pins:
        status = "expired" if pin.is_expired() else "active"
        lines.append(
            f"  - {pin.pin_id}  ({status})  manifest={pin.manifest_hash[:12]}…"
        )
    return "\n".join(lines)


@mcp.tool()
def pin_delete(pin_id: str) -> str:
    """Delete a retrieval pin by id."""
    deleted = _get_pin_store(_get_project_dir()).delete(pin_id)
    return f"Deleted pin {pin_id}" if deleted else f"No pin with id {pin_id!r}"


@mcp.tool()
def verify_pin(pin_id: str) -> str:
    """Check whether the code-intel state has drifted since a pin was minted.

    Returns a drift report: for each store, whether its hash matches the
    pinned value. If there is no drift, a query re-run against the current
    state is guaranteed to produce the same ranked results as when the pin
    was minted (assuming the tool is deterministic for a fixed index state —
    which is the whole point of these pins).
    """
    project_dir = _get_project_dir()
    pin = _get_pin_store(project_dir).get(pin_id)
    if pin is None:
        return f"No pin with id {pin_id!r}"
    if pin.is_expired():
        return f"Pin {pin_id} has expired."

    current = _compute_current_manifest_hashes(project_dir)
    drift = pin.drift_from(current)
    if not drift:
        return f"Pin {pin_id}: no drift. State is identical to the pinned snapshot."

    lines = [f"Pin {pin_id}: DRIFT in {len(drift)} store(s):"]
    for name, (pinned_hash, current_hash) in sorted(drift.items()):
        lines.append(
            f"  - {name}: pinned={pinned_hash[:16]}… current={current_hash[:16]}…"
        )
    return "\n".join(lines)
