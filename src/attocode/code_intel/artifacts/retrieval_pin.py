"""Retrieval pins — make ranked-result tools deterministic across calls.

A ``RetrievalPin`` is a content-addressed snapshot of the state of every
code-intel store at a moment in time. Every ranked-result tool
(``semantic_search``, ``fast_search``, ``repo_map``, etc.) emits one in its
response; a caller can then pass the pin back to ``retrieve_with_pin`` to
re-run the same query against the same state, with a loud drift error if
the underlying stores have changed.

The per-store hash is cheap: ``sha256(max(updated_at) || row_count || schema_version)``.
That's stable under no-op reads and changes on any write.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

PIN_SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 86_400  # 24 hours


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def compute_store_hash(
    *,
    schema_version: str | int,
    row_count: int,
    max_updated_at: float | None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Compute a cheap, stable content hash for one store's current state.

    Intentionally only uses three fields (schema version, row count, latest
    ``updated_at``) so the hash can be computed with a single cheap SQL
    aggregate query. ``extra`` is for stores that need to mix in something
    else (e.g. active embedding model pointer) — pass a small dict, it goes
    through canonical JSON.

    Two stores on two machines with exactly the same rows should produce
    the same hash; mutations (insert/update/delete) change it; pure reads
    do not.
    """
    body = {
        "schema": str(schema_version),
        "rows": int(row_count),
        "max_updated_at": float(max_updated_at or 0.0),
        "extra": dict(extra or {}),
    }
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def make_pin_id() -> str:
    """Return a short, URL-safe, unguessable pin id: ``pin_<22 base32 chars>``."""
    raw = secrets.token_bytes(16)
    token = base64.b32encode(raw).decode("ascii").rstrip("=").lower()
    return f"pin_{token}"


@dataclass(frozen=True, slots=True)
class RetrievalPin:
    """Immutable snapshot of code-intel state.

    Fields:
      - ``pin_id``: short identifier (see :func:`make_pin_id`).
      - ``schema_version``: for forward-compat.
      - ``manifest_hashes``: per-store name → hex store hash.
      - ``manifest_hash``: sha256 of the canonical JSON of ``manifest_hashes``
        (plus overlay_id). This is the thing to compare when checking drift.
      - ``overlay_id``: optional branch/overlay identifier (local side).
      - ``branch_id``: optional DB branch id (server side).
      - ``created_at``, ``expires_at``: unix seconds; 0 for no expiry.
    """

    pin_id: str
    schema_version: int
    manifest_hashes: dict[str, str] = field(default_factory=dict)
    manifest_hash: str = ""
    overlay_id: str | None = None
    branch_id: str | None = None
    created_at: float = 0.0
    expires_at: float = 0.0

    @classmethod
    def create(
        cls,
        *,
        manifest_hashes: Mapping[str, str],
        overlay_id: str | None = None,
        branch_id: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        pin_id: str | None = None,
    ) -> RetrievalPin:
        """Build a new pin from a dict of per-store hashes."""
        manifest = {str(k): str(v) for k, v in sorted(manifest_hashes.items())}
        manifest_hash = hashlib.sha256(
            _canonical_json({"manifest": manifest, "overlay": overlay_id, "branch": branch_id})
        ).hexdigest()
        now = time.time()
        return cls(
            pin_id=pin_id or make_pin_id(),
            schema_version=PIN_SCHEMA_VERSION,
            manifest_hashes=dict(manifest),
            manifest_hash=manifest_hash,
            overlay_id=overlay_id,
            branch_id=branch_id,
            created_at=now,
            expires_at=now + ttl_seconds if ttl_seconds > 0 else 0.0,
        )

    def is_expired(self, now: float | None = None) -> bool:
        """Whether the pin has passed its TTL. Pins with expires_at == 0 never expire."""
        if self.expires_at <= 0:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def drift_from(self, current_hashes: Mapping[str, str]) -> dict[str, tuple[str, str]]:
        """Return a map of store_name -> (pinned_hash, current_hash) for any store that
        changed vs the pinned state. Empty dict means no drift.

        Stores present in one side but not the other are reported with the
        missing side as ``""`` — this is usually a schema change and should
        be treated as drift.
        """
        drift: dict[str, tuple[str, str]] = {}
        all_keys = set(self.manifest_hashes) | set(current_hashes)
        for key in all_keys:
            pinned = self.manifest_hashes.get(key, "")
            current = current_hashes.get(key, "")
            if pinned != current:
                drift[key] = (pinned, current)
        return drift

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RetrievalPin:
        return cls(
            pin_id=str(data["pin_id"]),
            schema_version=int(data.get("schema_version", PIN_SCHEMA_VERSION)),
            manifest_hashes=dict(data.get("manifest_hashes", {})),
            manifest_hash=str(data.get("manifest_hash", "")),
            overlay_id=data.get("overlay_id"),
            branch_id=data.get("branch_id"),
            created_at=float(data.get("created_at", 0.0)),
            expires_at=float(data.get("expires_at", 0.0)),
        )
