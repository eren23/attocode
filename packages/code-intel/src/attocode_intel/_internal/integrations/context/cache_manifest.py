"""Per-project cache manifest — central schema-version registry for .attocode/.

A single ``.attocode/cache_manifest.json`` records the current schema version
of every local store (symbols, embeddings, kw_index, trigrams, learnings,
ADRs, frecency, query_history, CAS). Stores consult the manifest on open
and trigger their own migration hooks if they're behind.

This replaces the status-quo "half the DBs have a schema_version row, half
don't" by giving them one place to declare what version they're at and one
way to ask "do I need to migrate?".
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1


@dataclass(slots=True)
class StoreEntry:
    """One row in the cache manifest, describing one store."""

    path: str
    schema_version: int
    last_migrated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CacheManifest:
    """Read-write wrapper around ``<project>/.attocode/cache_manifest.json``.

    Usage::

        m = CacheManifest.load(project_dir="/path/to/project")
        if m.needs_migration("embeddings", target=2):
            ... # run your store's migration hook
            m.bump("embeddings", new_schema_version=2)
            m.save()
    """

    project_dir: str
    manifest_version: int = MANIFEST_SCHEMA_VERSION
    stores: dict[str, StoreEntry] = field(default_factory=dict)
    cas_root: str = ""
    active_overlay: str = "main"
    last_full_verify_at: str = ""

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.project_dir, ".attocode", "cache_manifest.json")

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_dir: str) -> CacheManifest:
        """Load the manifest, or return a fresh empty one if missing.

        Never raises on a missing file — callers should treat "missing" and
        "present but empty" as identical, because a brand-new ``.attocode/``
        directory is indistinguishable from "we forgot to write the manifest".
        """
        path = os.path.join(project_dir, ".attocode", "cache_manifest.json")
        if not os.path.exists(path):
            return cls(project_dir=project_dir)
        try:
            with open(path, "rb") as f:
                raw = json.loads(f.read())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "cache_manifest: failed to parse %s (%s); starting fresh",
                path, exc,
            )
            return cls(project_dir=project_dir)

        stores_raw = raw.get("stores", {})
        stores = {
            name: StoreEntry(
                path=str(entry.get("path", "")),
                schema_version=int(entry.get("schema_version", 0)),
                last_migrated_at=str(entry.get("last_migrated_at", "")),
                extra={k: v for k, v in entry.items()
                       if k not in {"path", "schema_version", "last_migrated_at"}},
            )
            for name, entry in stores_raw.items()
        }
        return cls(
            project_dir=project_dir,
            manifest_version=int(raw.get("manifest_version", MANIFEST_SCHEMA_VERSION)),
            stores=stores,
            cas_root=str(raw.get("cas_root", "")),
            active_overlay=str(raw.get("active_overlay", "main")),
            last_full_verify_at=str(raw.get("last_full_verify_at", "")),
        )

    def save(self) -> None:
        """Atomically write the manifest to disk via tempfile + rename."""
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        payload = self.to_dict()
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        fd, tmp = tempfile.mkstemp(
            prefix="cache_manifest_",
            suffix=".json.tmp",
            dir=os.path.dirname(self.manifest_path),
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)
            os.replace(tmp, self.manifest_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "project_dir": self.project_dir,
            "cas_root": self.cas_root,
            "active_overlay": self.active_overlay,
            "last_full_verify_at": self.last_full_verify_at,
            "stores": {
                name: {
                    "path": entry.path,
                    "schema_version": entry.schema_version,
                    "last_migrated_at": entry.last_migrated_at,
                    **entry.extra,
                }
                for name, entry in sorted(self.stores.items())
            },
        }

    # ------------------------------------------------------------------
    # Store registration + migration hooks
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        *,
        path: str,
        schema_version: int,
        extra: Mapping[str, Any] | None = None,
    ) -> StoreEntry:
        """Idempotently register a store.

        If the store is already present, update its recorded path/version
        but do NOT reset last_migrated_at (that's a migration event).
        """
        existing = self.stores.get(name)
        if existing is None:
            entry = StoreEntry(
                path=path,
                schema_version=schema_version,
                last_migrated_at="",
                extra=dict(extra or {}),
            )
        else:
            existing.path = path
            existing.schema_version = schema_version
            if extra:
                existing.extra.update(extra)
            entry = existing
        self.stores[name] = entry
        return entry

    def get_store(self, name: str) -> StoreEntry | None:
        return self.stores.get(name)

    def needs_migration(self, name: str, *, target: int) -> bool:
        """Return True if the named store is missing OR below ``target`` schema."""
        entry = self.stores.get(name)
        if entry is None:
            return True
        return entry.schema_version < target

    def bump(self, name: str, *, new_schema_version: int) -> None:
        """Record that a store migrated to ``new_schema_version``."""
        entry = self.stores.get(name)
        if entry is None:
            raise KeyError(f"store {name!r} not registered; call register() first")
        entry.schema_version = new_schema_version
        entry.last_migrated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a compact dict useful for `cache_status_all`."""
        return {
            "manifest_version": self.manifest_version,
            "project_dir": self.project_dir,
            "cas_root": self.cas_root,
            "active_overlay": self.active_overlay,
            "last_full_verify_at": self.last_full_verify_at,
            "stores": {
                name: asdict(entry)
                for name, entry in sorted(self.stores.items())
            },
        }
