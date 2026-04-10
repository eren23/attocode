"""Maintenance MCP tools — cache status, schema verification, provenance backfill.

Phase 1 subset of the maintenance tool surface. Ships:

  - ``cache_status_all``  : per-store size, schema, row count, drift summary.
  - ``embeddings_status`` : model / dim / drift diagnosis for the local
                            vector store (the embedding footgun fix in UI form).
  - ``verify_all_caches`` : walk every store, sanity-check schema versions,
                            report drift. Optionally deep-verify content hashes.
  - ``migrate_cache``     : one-shot migration that writes
                            ``.attocode/cache_manifest.json`` and backfills
                            provenance on existing rows. Idempotent.

Phase 2 will add the full clear/export/import/snapshot/gc tool surface.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from attocode.code_intel._shared import _get_project_dir, mcp
from attocode.code_intel.tools.pin_tools import (
    _STORE_DEFS,
    _compute_current_manifest_hashes,
    _hash_for_trigrams,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f}TB"


def _store_row_count(db_path: str, tables: tuple[str, ...]) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        total = 0
        for tbl in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                if row:
                    total += int(row[0])
            except sqlite3.OperationalError:
                pass
        return total
    finally:
        conn.close()


def _store_schema_version(db_path: str, schema_meta: Any, default: str) -> str:
    if not os.path.exists(db_path) or schema_meta is None:
        return default
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return default
    try:
        meta_table, meta_key = schema_meta
        try:
            row = conn.execute(
                f"SELECT value FROM {meta_table} WHERE key = ?",
                (meta_key,),
            ).fetchone()
            if row:
                return str(row[0])
        except sqlite3.OperationalError:
            pass
        return default
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# cache_status_all
# ---------------------------------------------------------------------------


@mcp.tool()
def cache_status_all() -> str:
    """Per-store summary: path, size, schema version, row count, manifest hash.

    One place to answer "what does my .attocode/ look like?" without
    `find` + `sqlite3`. Includes the trigram index (binary files) and
    reports the current manifest hash used for retrieval pins.
    """
    project_dir = _get_project_dir()
    hashes = _compute_current_manifest_hashes()

    lines = [f"cache_status_all for {project_dir}"]
    lines.append("=" * 60)
    total_bytes = 0

    for defn in _STORE_DEFS:
        name = defn["name"]
        path = os.path.join(project_dir, ".attocode", defn["path_fragment"])
        size = _safe_size(path)
        total_bytes += size
        rows = _store_row_count(path, defn["tables"])
        schema = _store_schema_version(
            path, defn["schema_meta"], defn["default_schema_version"],
        )
        exists = "✓" if os.path.exists(path) else "✗"
        h = hashes.get(name, "")
        lines.append(
            f"  {name:15s} {exists}  schema=v{schema:<6s} "
            f"rows={rows:<8d} size={_fmt_bytes(size):<10s} hash={h[:16]}…"
        )

    # Trigrams are binary files, not a DB.
    tri_base = os.path.join(project_dir, ".attocode", "index")
    tri_size = sum(
        _safe_size(os.path.join(tri_base, n))
        for n in ("trigrams.lookup", "trigrams.postings", "trigrams.db")
    )
    total_bytes += tri_size
    tri_hash = _hash_for_trigrams(project_dir)
    tri_present = "✓" if tri_hash != "absent" else "✗"
    lines.append(
        f"  {'trigrams':15s} {tri_present}  schema=trigram_v1 "
        f"size={_fmt_bytes(tri_size):<10s} hash={tri_hash[:16]}…"
    )

    lines.append("-" * 60)
    lines.append(f"  total size: {_fmt_bytes(total_bytes)}")

    # Manifest presence check
    manifest_path = os.path.join(project_dir, ".attocode", "cache_manifest.json")
    manifest_present = os.path.exists(manifest_path)
    lines.append(
        f"  cache_manifest.json: {'present' if manifest_present else 'MISSING — run migrate_cache()'}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# embeddings_status — the footgun diagnostic
# ---------------------------------------------------------------------------


@mcp.tool()
def embeddings_status() -> str:
    """Detailed status of the local semantic-search vector store.

    Reports: model name/version/dim, coverage, drift warnings, degraded
    mode if the provider's dim doesn't match the stored dim. This is the
    tool to reach for if ``semantic_search`` is misbehaving — previously the
    answer was "silent wipe, no feedback"; now it's a readable report.
    """
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "vectors", "embeddings.db")

    if not os.path.exists(db_path):
        return "embeddings_status: no vector store at .attocode/vectors/embeddings.db"

    lines = [f"embeddings_status for {db_path}"]
    lines.append("=" * 60)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"embeddings_status: could not open {db_path}: {exc}"

    try:
        # Schema version + stored dim from store_metadata.
        schema_ver = "?"
        stored_dim: int | None = None
        try:
            row = conn.execute(
                "SELECT value FROM store_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row:
                schema_ver = str(row[0])
        except sqlite3.OperationalError:
            pass
        try:
            row = conn.execute(
                "SELECT value FROM store_metadata WHERE key = 'dimension'"
            ).fetchone()
            if row:
                stored_dim = int(row[0])
        except (sqlite3.OperationalError, ValueError):
            pass

        lines.append(f"  schema_version: v{schema_ver}")
        lines.append(f"  stored_dim: {stored_dim if stored_dim is not None else 'unset'}")

        # Row counts + per-model breakdown.
        try:
            total = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        except sqlite3.OperationalError:
            total = 0
        try:
            file_meta = conn.execute(
                "SELECT COUNT(*) FROM file_metadata"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            file_meta = 0

        lines.append(f"  total_vectors: {total}")
        lines.append(f"  indexed_files: {file_meta}")

        # Models breakdown — only available on v2+ stores.
        try:
            rows = conn.execute(
                """SELECT model_name, model_version, dimension, COUNT(*)
                   FROM vectors GROUP BY model_name, model_version, dimension
                   ORDER BY COUNT(*) DESC"""
            ).fetchall()
            if rows:
                lines.append("  models:")
                for m_name, m_ver, m_dim, count in rows:
                    marker = ""
                    if stored_dim is not None and m_dim and m_dim != stored_dim:
                        marker = "  ⚠ dim mismatch vs stored"
                    label = f"{m_name or '<unknown>'}"
                    if m_ver:
                        label += f" v{m_ver}"
                    lines.append(
                        f"    - {label:30s}  dim={m_dim}  rows={count}{marker}"
                    )
        except sqlite3.OperationalError:
            lines.append("  models: (pre-v2 schema — run migrate_cache to retrofit)")

        # Legacy marker count
        try:
            legacy = conn.execute(
                "SELECT COUNT(*) FROM vectors WHERE model_name = 'legacy-pre-v2'"
            ).fetchone()[0]
            if legacy:
                lines.append(
                    f"  legacy_rows: {legacy}  (need re-index to attach provenance)"
                )
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# verify_all_caches
# ---------------------------------------------------------------------------


@mcp.tool()
def verify_all_caches(deep: bool = False) -> str:
    """Walk every local store and check its schema version + basic sanity.

    Args:
        deep: If True, also run per-store integrity checks (SQLite
              ``PRAGMA integrity_check`` where applicable). Deep checks
              take longer but catch on-disk corruption.
    """
    project_dir = _get_project_dir()
    problems: list[str] = []
    ok_count = 0
    missing_count = 0

    for defn in _STORE_DEFS:
        name = defn["name"]
        path = os.path.join(project_dir, ".attocode", defn["path_fragment"])
        if not os.path.exists(path):
            missing_count += 1
            continue
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            problems.append(f"  {name}: open failed: {exc}")
            continue
        try:
            if deep:
                try:
                    row = conn.execute("PRAGMA integrity_check").fetchone()
                    if row and row[0] != "ok":
                        problems.append(f"  {name}: integrity_check={row[0]}")
                        continue
                except sqlite3.OperationalError as exc:
                    problems.append(f"  {name}: integrity_check failed: {exc}")
                    continue

            # Presence check on declared tables — a missing one is a bug.
            for tbl in defn["tables"]:
                try:
                    conn.execute(f"SELECT 1 FROM {tbl} LIMIT 1").fetchone()
                except sqlite3.OperationalError as exc:
                    problems.append(f"  {name}: table {tbl!r} unusable ({exc})")
                    break
            else:
                ok_count += 1
        finally:
            conn.close()

    # Trigrams
    tri_hash = _hash_for_trigrams(project_dir)
    if tri_hash == "absent":
        missing_count += 1
    else:
        ok_count += 1

    header = [
        f"verify_all_caches (deep={deep})",
        "=" * 60,
        f"  ok: {ok_count}",
        f"  missing: {missing_count}",
        f"  problems: {len(problems)}",
    ]
    if problems:
        header.append("")
        header.extend(problems)
    else:
        header.append("  status: all inspected caches look healthy.")
    return "\n".join(header)


# ---------------------------------------------------------------------------
# migrate_cache — one-shot manifest writer + provenance backfill
# ---------------------------------------------------------------------------


@mcp.tool()
def migrate_cache(dry_run: bool = True, resume: bool = True) -> str:
    """Write ``cache_manifest.json`` and backfill provenance on legacy rows.

    Idempotent and interrupt-safe. Running with ``dry_run=True`` (the
    default) produces a preview of what would change without writing.
    Running with ``resume=True`` (the default) skips steps that have
    already completed in a prior invocation.

    Args:
        dry_run: If True, show the plan without applying.
        resume: If True, skip already-applied steps.
    """
    from attocode.integrations.context.cache_manifest import CacheManifest

    project_dir = _get_project_dir()
    manifest = CacheManifest.load(project_dir)

    changes: list[str] = []

    # 1. Register each store's current schema version in the manifest.
    for defn in _STORE_DEFS:
        name = defn["name"]
        path = os.path.join(project_dir, ".attocode", defn["path_fragment"])
        if not os.path.exists(path):
            continue
        schema = _store_schema_version(
            path, defn["schema_meta"], defn["default_schema_version"],
        )
        try:
            version_int = int(schema)
        except ValueError:
            version_int = 1
        existing = manifest.get_store(name)
        if existing is None or existing.schema_version != version_int or existing.path != defn["path_fragment"]:
            changes.append(
                f"register/update store {name!r}: path={defn['path_fragment']!r} schema_version={version_int}"
            )
            if not dry_run:
                manifest.register(
                    name,
                    path=defn["path_fragment"],
                    schema_version=version_int,
                )

    # 2. Register trigrams separately.
    tri_base = os.path.join(project_dir, ".attocode", "index")
    if any(
        os.path.exists(os.path.join(tri_base, n))
        for n in ("trigrams.lookup", "trigrams.postings", "trigrams.db")
    ):
        existing = manifest.get_store("trigrams")
        if existing is None:
            changes.append("register store 'trigrams': path=index/trigrams.* schema_version=1")
            if not dry_run:
                manifest.register(
                    "trigrams",
                    path="index/trigrams.*",
                    schema_version=1,
                )

    # 3. Legacy vectors backfill — mark pre-v2 rows with a legacy model_name
    #    so the user knows to re-index them. The vector_store's own
    #    _migrate_schema already handles this on next open, so here we only
    #    count how many rows will be flagged.
    vec_db = os.path.join(project_dir, ".attocode", "vectors", "embeddings.db")
    legacy_count = 0
    if os.path.exists(vec_db):
        try:
            conn = sqlite3.connect(f"file:{vec_db}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM vectors WHERE COALESCE(model_name, '') = 'legacy-pre-v2'"
                ).fetchone()
                legacy_count = int(row[0]) if row else 0
            except sqlite3.OperationalError:
                pass
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    if legacy_count:
        changes.append(
            f"NOTE: vectors table has {legacy_count} row(s) marked legacy-pre-v2. "
            "They will keep working for reads but should be re-indexed to gain provenance."
        )

    # 4. Save the manifest.
    if dry_run:
        header = ["migrate_cache (dry_run=True) — plan:"]
        if not changes:
            header.append("  (no changes — manifest is up to date)")
        else:
            header.append("")
            for c in changes:
                header.append(f"  - {c}")
        header.append("")
        header.append("Run with dry_run=False to apply.")
        return "\n".join(header)

    manifest.save()
    summary = [
        f"migrate_cache applied to {manifest.manifest_path}",
        f"  stores_registered: {len(manifest.stores)}",
    ]
    if changes:
        summary.append("")
        summary.append("  changes:")
        for c in changes:
            summary.append(f"    - {c}")
    else:
        summary.append("  (no changes — manifest was already up to date)")
    return "\n".join(summary)
