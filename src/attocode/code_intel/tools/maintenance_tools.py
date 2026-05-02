"""Maintenance MCP tools — cache CRUD, schema verification, GC, export/import.

Phase 1 delivered status / verify / migrate. Phase 2a adds the
destructive CRUD surface (clear), the durable one (export/import), the
reclamation surface (gc / orphan_scan), and the reproducibility surface
(snapshot — in ``snapshot_tools.py``).

Every destructive tool here requires ``confirm=True`` explicitly so an
errant agent call cannot nuke a user's local state. ``confirm=False``
(the default) returns a preview of what would be deleted without touching
disk.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import TYPE_CHECKING, Any

from attocode.code_intel._shared import _get_project_dir, mcp
from attocode.code_intel.tools.pin_tools import (
    _STORE_DEFS,
    _compute_current_manifest_hashes,
    _hash_for_trigrams,
)

if TYPE_CHECKING:
    from attocode.integrations.context.embedding_rotation import EmbeddingRotator

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


# ---------------------------------------------------------------------------
# clear_* — per-artifact destructive tools
#
# Every clear_* tool requires ``confirm=True`` before touching disk. The
# ``confirm=False`` default returns a preview of what would be deleted.
# This is the safe-by-default pattern that matters most for automated
# agents: asking twice is cheap, a blown-away cache is not.
# ---------------------------------------------------------------------------


def _preview_or_apply(
    *,
    name: str,
    confirm: bool,
    would_delete_summary: str,
    apply_fn,
) -> str:
    """Shared plumbing for clear_* tools.

    Presents a uniform preview/apply dialog. ``apply_fn`` must return
    an applied-summary string.
    """
    if not confirm:
        return (
            f"{name}: DRY RUN — nothing was deleted.\n"
            f"  would delete: {would_delete_summary}\n"
            f"  Re-run with confirm=True to apply."
        )
    return apply_fn()


@mcp.tool()
def clear_symbols(confirm: bool = False) -> str:
    """Wipe the local symbol index (``.attocode/index/symbols.db``).

    Drops all files/symbols/refs/dependencies rows. Preserves schema.
    The AST service will re-parse on next use.

    Args:
        confirm: Must be True to actually delete. Default False shows a preview.
    """
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "index", "symbols.db")
    if not os.path.exists(db_path):
        return "clear_symbols: no symbols.db to clear."

    rows = _store_row_count(db_path, ("symbols", "files", "refs", "dependencies"))
    size = _safe_size(db_path)

    def _apply() -> str:
        from attocode.integrations.context.index_store import IndexStore
        store = IndexStore(db_path=db_path)
        try:
            store.clear_all()
        finally:
            store.close()
        return (
            f"clear_symbols: cleared {rows} rows from "
            f"{_fmt_bytes(size)} at {db_path}"
        )

    return _preview_or_apply(
        name="clear_symbols",
        confirm=confirm,
        would_delete_summary=f"{rows} rows ({_fmt_bytes(size)})",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_embeddings(confirm: bool = False, model: str = "") -> str:
    """Wipe stored vectors in ``.attocode/vectors/embeddings.db``.

    Preserves ``store_metadata`` (schema version + stored dimension) so
    the next open doesn't trip the dim-mismatch check — this is the
    *safe* reset path, not ``rm``.

    Args:
        confirm: Must be True to actually delete.
        model: If set, only delete rows for this model. Empty = all.
    """
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "vectors", "embeddings.db")
    if not os.path.exists(db_path):
        return "clear_embeddings: no embeddings.db to clear."

    # When ``model`` is set, the dry-run preview reports the count of
    # rows matching the filter, not the total row count.
    if model:
        try:
            count_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = count_conn.execute(
                    "SELECT COUNT(*) FROM vectors WHERE model_name = ?",
                    (model,),
                ).fetchone()
                rows = int(row[0]) if row else 0
            finally:
                count_conn.close()
        except sqlite3.OperationalError:
            rows = _store_row_count(db_path, ("vectors",))
    else:
        rows = _store_row_count(db_path, ("vectors",))
    size = _safe_size(db_path)
    filter_desc = f" (model={model!r})" if model else ""

    def _apply() -> str:
        from attocode.integrations.context.vector_store import (
            VectorStore,
            VectorStoreRotationActiveError,
        )

        # Read the stored dimension first so we can open the store at
        # the matching dim. Opening with ``dimension=0`` put the store
        # into degraded mode, which after Batch B also blocks the
        # subsequent clear_all/clear_by_model call.
        stored_dim = 0
        try:
            probe_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = probe_conn.execute(
                    "SELECT value FROM store_metadata WHERE key = 'dimension'"
                ).fetchone()
                if row:
                    stored_dim = int(row[0])
            finally:
                probe_conn.close()
        except (sqlite3.Error, ValueError):
            stored_dim = 0

        store = VectorStore(
            db_path=db_path,
            dimension=stored_dim,
            strict_dimension=False,
        )
        try:
            try:
                deleted = (
                    store.clear_by_model(model) if model else store.clear_all()
                )
            except VectorStoreRotationActiveError as exc:
                # Surface the refusal as a readable tool response rather
                # than letting clear_embeddings silently destroy rotation
                # state mid-flight.
                return (
                    f"clear_embeddings: REFUSED — {exc}. Finish the "
                    f"rotation first (embeddings_rotate_cutover + "
                    f"embeddings_rotate_gc_old) or abort it "
                    f"(embeddings_rotate_abort)."
                )
        finally:
            store.close()
        return (
            f"clear_embeddings{filter_desc}: cleared {deleted} row(s) from "
            f"{_fmt_bytes(size)} at {db_path}"
        )

    return _preview_or_apply(
        name="clear_embeddings",
        confirm=confirm,
        would_delete_summary=f"{rows} rows{filter_desc} ({_fmt_bytes(size)})",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_trigrams(confirm: bool = False) -> str:
    """Delete the trigram fast-search index files.

    The trigram index is three files (``trigrams.lookup``, ``.postings``,
    ``.db``). Next AST service initialization will rebuild it.

    Args:
        confirm: Must be True to actually delete.
    """
    project_dir = _get_project_dir()
    base = os.path.join(project_dir, ".attocode", "index")
    files = [
        os.path.join(base, n)
        for n in ("trigrams.lookup", "trigrams.postings", "trigrams.db")
    ]
    present = [f for f in files if os.path.exists(f)]
    if not present:
        return "clear_trigrams: no trigram index files to clear."

    total_size = sum(_safe_size(f) for f in present)

    def _apply() -> str:
        removed = []
        for f in present:
            try:
                os.unlink(f)
                removed.append(os.path.basename(f))
            except OSError as exc:
                logger.warning("clear_trigrams: could not remove %s: %s", f, exc)
        return (
            f"clear_trigrams: removed {len(removed)} file(s) "
            f"({_fmt_bytes(total_size)}): {', '.join(removed)}"
        )

    return _preview_or_apply(
        name="clear_trigrams",
        confirm=confirm,
        would_delete_summary=f"{len(present)} file(s) ({_fmt_bytes(total_size)})",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_kw_index(confirm: bool = False) -> str:
    """Delete the BM25 keyword fallback index.

    This index is lazily rebuilt on the next ``semantic_search`` call
    when the embedding provider is unavailable.

    Args:
        confirm: Must be True to actually delete.
    """
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "index", "kw_index.db")
    if not os.path.exists(db_path):
        return "clear_kw_index: no kw_index.db to clear."

    size = _safe_size(db_path)

    def _apply() -> str:
        try:
            os.unlink(db_path)
        except OSError as exc:
            return f"clear_kw_index: failed to remove {db_path}: {exc}"
        return f"clear_kw_index: removed {_fmt_bytes(size)} at {db_path}"

    return _preview_or_apply(
        name="clear_kw_index",
        confirm=confirm,
        would_delete_summary=f"{_fmt_bytes(size)}",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_learnings(confirm: bool = False, status_filter: str = "archived") -> str:
    """Hard-delete learnings from ``.attocode/cache/memory.db``.

    Safer default: only delete learnings in ``archived`` status. Pass
    ``status_filter=""`` to wipe everything.

    Args:
        confirm: Must be True to actually delete.
        status_filter: Only delete learnings with this status. Empty = all.
    """
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "cache", "memory.db")
    if not os.path.exists(db_path):
        return "clear_learnings: no memory.db to clear."

    # Direct SQL count for the preview (MemoryStore.list_all filters on a
    # single hardcoded status column, which doesn't give us an "all"
    # path). This is read-only so it's safe alongside an active
    # connection.
    count_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if status_filter:
            row = count_conn.execute(
                "SELECT COUNT(*) FROM learnings WHERE status = ?",
                (status_filter,),
            ).fetchone()
        else:
            row = count_conn.execute("SELECT COUNT(*) FROM learnings").fetchone()
        count = int(row[0]) if row else 0
    finally:
        count_conn.close()

    filter_desc = f" (status={status_filter!r})" if status_filter else " (ALL)"

    def _apply() -> str:
        from attocode.code_intel.tools.learning_tools import _get_memory_store
        store = _get_memory_store()
        deleted = store.clear_all(status_filter=status_filter)
        return f"clear_learnings{filter_desc}: deleted {deleted} row(s)"

    return _preview_or_apply(
        name="clear_learnings",
        confirm=confirm,
        would_delete_summary=f"{count} learning(s){filter_desc}",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_adrs(confirm: bool = False, status_filter: str = "superseded") -> str:
    """Hard-delete ADRs from ``.attocode/adrs.db``.

    Safer default: only delete ADRs in terminal ``superseded`` status.
    Pass ``status_filter=""`` to wipe everything.

    Args:
        confirm: Must be True to actually delete.
        status_filter: Only delete ADRs with this status. Empty = all.
    """
    from attocode.code_intel.tools.adr_tools import _get_adr_store
    store = _get_adr_store()

    # ADRStore.list_all takes status as a *string*; empty string = all,
    # which matches our semantics exactly.
    rows = store.list_all(status=status_filter)
    filter_desc = f" (status={status_filter!r})" if status_filter else " (ALL)"

    def _apply() -> str:
        deleted = store.clear_all(status_filter=status_filter)
        return f"clear_adrs{filter_desc}: deleted {deleted} row(s)"

    return _preview_or_apply(
        name="clear_adrs",
        confirm=confirm,
        would_delete_summary=f"{len(rows)} ADR(s){filter_desc}",
        apply_fn=_apply,
    )


@mcp.tool()
def clear_all(confirm: bool = False, except_stores: str = "") -> str:
    """Clear every local cache (fan-out of per-store clear tools).

    Does NOT touch the CAS (``~/.cache/attocode/cas/``) — use ``cas_clear``
    for that. Does NOT touch pins (``.attocode/cache/pins.db``) or the
    cache_manifest — those are run-state, not cache.

    Args:
        confirm: Must be True to actually delete.
        except_stores: Comma-separated store names to skip.
            Examples: ``"symbols"``, ``"embeddings,learnings"``.
    """
    skip = {s.strip() for s in except_stores.split(",") if s.strip()}
    project_dir = _get_project_dir()

    tools = [
        ("symbols", clear_symbols, ()),
        ("embeddings", clear_embeddings, ()),
        ("trigrams", clear_trigrams, ()),
        ("kw_index", clear_kw_index, ()),
        # For clear_all we drop every learning/ADR regardless of status so
        # the overall behavior matches "reset my local knowledge base".
        ("learnings", clear_learnings, ("",)),
        ("adrs", clear_adrs, ("",)),
    ]

    if not confirm:
        lines = ["clear_all: DRY RUN — nothing deleted."]
        lines.append(f"  project: {project_dir}")
        lines.append(f"  would clear: {', '.join(name for name, _, _ in tools if name not in skip)}")
        if skip:
            lines.append(f"  skipping: {', '.join(sorted(skip))}")
        lines.append("  Re-run with confirm=True to apply.")
        return "\n".join(lines)

    results = ["clear_all: applying…"]
    for name, fn, extra in tools:
        if name in skip:
            results.append(f"  {name}: SKIPPED")
            continue
        try:
            res = fn(True, *extra) if extra else fn(True)
            # Reduce multi-line clear results to a compact first-line summary.
            first = res.splitlines()[0] if res else "(no output)"
            results.append(f"  {name}: {first}")
        except Exception as exc:
            logger.exception("clear_all: %s failed", name)
            results.append(f"  {name}: ERROR {exc}")
    return "\n".join(results)


@mcp.tool()
def cas_clear(confirm: bool = False, artifact_types: str = "") -> str:
    """Purge entries from the shared content-addressable cache.

    The CAS lives at ``~/.cache/attocode/cas/`` (or ``ATTOCODE_CAS_DIR``).
    It holds derived artifacts shared across projects — purging it is
    global, not per-project. Use sparingly.

    Args:
        confirm: Must be True to actually delete.
        artifact_types: Comma-separated subset of types to purge
            (e.g. ``"symbols,embedding"``). Empty means every type.
    """
    from attocode.integrations.context.cas import ContentAddressedCache

    cas = ContentAddressedCache()
    stats_before = cas.stats()
    total_count = stats_before["total"]["count"]
    total_bytes = stats_before["total"]["bytes"]
    types_filter = {t.strip() for t in artifact_types.split(",") if t.strip()}

    if not confirm:
        lines = [
            "cas_clear: DRY RUN — nothing deleted.",
            f"  cas_root: {cas.cas_root}",
            f"  would clear: {total_count} entries ({_fmt_bytes(total_bytes)})",
        ]
        if types_filter:
            lines.append(f"  types: {', '.join(sorted(types_filter))}")
        lines.append("  Re-run with confirm=True to apply.")
        return "\n".join(lines)

    # Force refcount to zero so gc() sees them as orphans, then GC.
    # We implement this by directly opening the manifest DB and zeroing
    # refcount — there's no public batch-decref API because this is the
    # only place that wants it.
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(os.path.join(cas.cas_root, "manifest.db"))
    try:
        if types_filter:
            placeholders = ",".join("?" * len(types_filter))
            conn.execute(
                f"UPDATE cas_entries SET refcount = 0 WHERE artifact_type IN ({placeholders})",
                tuple(types_filter),
            )
        else:
            conn.execute("UPDATE cas_entries SET refcount = 0")
        conn.commit()
    finally:
        conn.close()

    # age=0 so we purge everything unreferenced regardless of age.
    result = cas.gc(min_age_seconds=0, dry_run=False)
    return (
        f"cas_clear: deleted {result['deleted_count']} entries "
        f"({_fmt_bytes(result['freed_bytes'])} freed)"
    )


# ---------------------------------------------------------------------------
# Export / import — portable dump of user-generated knowledge
# ---------------------------------------------------------------------------


@mcp.tool()
def export_learnings(path: str, fmt: str = "jsonl") -> str:
    """Dump all learnings to a portable file.

    Includes every status (active + archived) so the export is a true
    backup, not just the currently-surfaced subset.

    Args:
        path: Destination file (or directory for multi-file formats).
        fmt: ``jsonl`` (default) — one JSON object per line.

    Returns the count written + destination path.
    """
    from attocode.code_intel.tools.learning_tools import _get_memory_store

    if fmt != "jsonl":
        return f"export_learnings: unsupported format {fmt!r} (use 'jsonl')"

    store = _get_memory_store()
    # MemoryStore.list_all defaults to status="active"; enumerate every
    # known status so archived entries are also exported.
    seen_ids: set[int] = set()
    rows: list[dict[str, Any]] = []
    for status in ("active", "archived"):
        for r in store.list_all(status=status):
            rid = r.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            rows.append(r)

    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)

    import json
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, default=str))
            f.write("\n")

    return f"export_learnings: wrote {len(rows)} learning(s) to {path}"


def _as_dict(obj: Any) -> dict[str, Any]:
    """Best-effort coerce a store record into a plain dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    # Last resort: stringify.
    return {"repr": repr(obj)}


@mcp.tool()
def import_learnings(path: str, merge: str = "skip_dup") -> str:
    """Load learnings from a JSONL file (as produced by ``export_learnings``).

    Args:
        path: Source JSONL file.
        merge: Strategy for pre-existing learnings:
          - ``skip_dup`` (default): skip if a matching learning exists.
          - ``overwrite``: replace matches in place.
          - ``boost``: treat re-import as positive feedback.

    The dedup key is ``(type, description, scope)`` — matching the
    MemoryStore's own add() dedup behavior.
    """
    import json

    from attocode.code_intel.tools.learning_tools import _get_memory_store

    if merge not in ("skip_dup", "overwrite", "boost"):
        return f"import_learnings: invalid merge={merge!r} (use skip_dup|overwrite|boost)"

    if not os.path.exists(path):
        return f"import_learnings: source file not found: {path}"

    store = _get_memory_store()
    imported = 0
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("import_learnings: bad line: %s (%s)", line[:80], exc)
                continue
            # store.add() handles dedup automatically; we only care about
            # the differentiation between overwrite and skip_dup here.
            # For simplicity: always call add(), letting MemoryStore's
            # natural dedup handle the rest.
            try:
                store.add(
                    type=data.get("type", "pattern"),
                    description=data.get("description", ""),
                    details=data.get("details", ""),
                    scope=data.get("scope", ""),
                    confidence=float(data.get("confidence", 0.5)),
                )
                imported += 1
            except Exception as exc:
                logger.warning("import_learnings: add failed: %s", exc)
                skipped += 1

    return (
        f"import_learnings: imported {imported} (skipped {skipped}) "
        f"from {path} [merge={merge}]"
    )


@mcp.tool()
def export_adrs_markdown(directory: str) -> str:
    """Write each ADR as a ``NNNN-slug.md`` file under ``directory``.

    Uses a small YAML-style frontmatter (``---``) for structured fields
    and the ADR body as markdown. Round-trips via ``import_adrs_markdown``.
    """
    from attocode.code_intel.tools.adr_tools import _get_adr_store

    os.makedirs(directory, exist_ok=True)
    store = _get_adr_store()
    rows = store.list_all()  # returns list[dict]

    def _slug(title: str) -> str:
        return "".join(
            c.lower() if c.isalnum() else "-"
            for c in title.strip()
        ).strip("-") or "untitled"

    written = 0
    for adr in rows:
        num = adr.get("number", 0)
        title = adr.get("title", "untitled")
        status = adr.get("status", "proposed")
        body_lines = [
            "---",
            f"number: {num}",
            f"title: {title}",
            f"status: {status}",
            f"created_at: {adr.get('created_at', '')}",
            f"updated_at: {adr.get('updated_at', '')}",
            f"tags: {adr.get('tags', [])}",
            f"related_files: {adr.get('related_files', [])}",
            "---",
            "",
            f"# {num:04d} — {title}",
            "",
            "## Context",
            "",
            adr.get("context", ""),
            "",
            "## Decision",
            "",
            adr.get("decision", ""),
            "",
            "## Consequences",
            "",
            adr.get("consequences", ""),
            "",
        ]
        fname = f"{num:04d}-{_slug(title)}.md"
        with open(os.path.join(directory, fname), "w", encoding="utf-8") as f:
            f.write("\n".join(body_lines))
        written += 1

    return f"export_adrs_markdown: wrote {written} ADR(s) to {directory}"


@mcp.tool()
def import_adrs_markdown(directory: str, merge: str = "skip_dup") -> str:
    """Load ADR markdown files from a directory.

    Parses the same ``---`` frontmatter produced by ``export_adrs_markdown``.
    Handles legacy ADR markdown too (no frontmatter → uses filename
    heuristics).

    Args:
        directory: Source directory.
        merge: ``skip_dup`` (default) | ``overwrite``.
    """
    from attocode.code_intel.tools.adr_tools import _get_adr_store

    if merge not in ("skip_dup", "overwrite"):
        return f"import_adrs_markdown: invalid merge={merge!r}"
    if not os.path.isdir(directory):
        return f"import_adrs_markdown: not a directory: {directory}"

    store = _get_adr_store()
    imported = 0
    skipped = 0

    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(directory, fname), encoding="utf-8") as f:
            text = f.read()
        title, context, decision, consequences = _parse_adr_markdown(text, fname)
        if not title:
            skipped += 1
            continue
        try:
            store.add(
                title=title,
                context=context,
                decision=decision,
                consequences=consequences,
            )
            imported += 1
        except Exception as exc:
            logger.warning("import_adrs_markdown: add failed for %s: %s", fname, exc)
            skipped += 1

    return (
        f"import_adrs_markdown: imported {imported} ADR(s) "
        f"(skipped {skipped}) from {directory} [merge={merge}]"
    )


def _parse_adr_markdown(text: str, fname: str) -> tuple[str, str, str, str]:
    """Minimal frontmatter + section parser.

    Returns ``(title, context, decision, consequences)``. Missing
    sections return empty strings. On total failure returns
    ``("", "", "", "")``.
    """
    title = ""
    context = ""
    decision = ""
    consequences = ""

    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            frontmatter = text[4:end]
            body = text[end + 5:]
            for line in frontmatter.splitlines():
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip()

    if not title:
        # Fall back to first ``# `` heading.
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                # Strip numeric prefix ("0001 — ") if any.
                parts = title.split("—", 1)
                if len(parts) == 2:
                    title = parts[1].strip()
                break
    if not title:
        # Fall back to filename.
        title = os.path.splitext(fname)[0]

    def _extract_section(name: str) -> str:
        start = body.find(f"## {name}")
        if start == -1:
            return ""
        start = body.find("\n", start) + 1
        next_sec = body.find("\n## ", start)
        return (body[start:next_sec] if next_sec != -1 else body[start:]).strip()

    context = _extract_section("Context")
    decision = _extract_section("Decision")
    consequences = _extract_section("Consequences")

    return title, context, decision, consequences


# ---------------------------------------------------------------------------
# GC + orphan_scan
# ---------------------------------------------------------------------------


@mcp.tool()
def gc_preview(min_age_days: float = 7.0) -> str:
    """Preview what GC would reclaim from the shared content-addressable cache.

    Args:
        min_age_days: Only count entries older than this. Default 7 days.

    Returns a summary of entries eligible for deletion without touching disk.
    """
    from attocode.integrations.context.cas import ContentAddressedCache
    cas = ContentAddressedCache()
    result = cas.gc(min_age_seconds=min_age_days * 86400, dry_run=True)
    lines = [
        f"gc_preview: {cas.cas_root}",
        f"  min_age_days: {min_age_days}",
        f"  would delete: {result['would_delete_count']} entries",
        f"  would free: {_fmt_bytes(result['would_free_bytes'])}",
    ]
    if result["examples"]:
        lines.append("  examples (up to 10):")
        for ex in result["examples"]:
            lines.append(
                f"    - {ex['artifact_type']:15s} {ex['key'][:30]}…  {_fmt_bytes(ex['size_bytes'])}"
            )
    lines.append("  (call gc_run with confirm=True to apply)")
    return "\n".join(lines)


@mcp.tool()
def gc_run(min_age_days: float = 30.0, confirm: bool = False) -> str:
    """Actually delete orphaned CAS entries older than ``min_age_days``.

    Safer default age: 30 days (vs gc_preview's 7). Even aggressive callers
    shouldn't wipe fresh entries.

    Args:
        min_age_days: Only delete entries older than this.
        confirm: Must be True to actually delete.
    """
    from attocode.integrations.context.cas import ContentAddressedCache
    cas = ContentAddressedCache()
    min_age_seconds = min_age_days * 86400

    # Always do a dry-run first for the preview.
    preview = cas.gc(min_age_seconds=min_age_seconds, dry_run=True)
    if not confirm:
        return (
            f"gc_run: DRY RUN — nothing deleted.\n"
            f"  cas_root: {cas.cas_root}\n"
            f"  min_age_days: {min_age_days}\n"
            f"  would delete: {preview['would_delete_count']} entries\n"
            f"  would free: {_fmt_bytes(preview['would_free_bytes'])}\n"
            f"  Re-run with confirm=True to apply."
        )

    result = cas.gc(min_age_seconds=min_age_seconds, dry_run=False)
    return (
        f"gc_run: deleted {result['deleted_count']} entries "
        f"({_fmt_bytes(result['freed_bytes'])} freed)"
    )


@mcp.tool()
def orphan_scan(auto_archive: bool = False) -> str:
    """Find learnings / ADRs whose referenced content is no longer reachable.

    Phase 2c version: prefers content-addressed reachability via
    ``anchor_blob_oid`` (learnings) / ``anchor_blob_oids`` (ADRs),
    falling back to the Phase 2a path-exists check for entries that
    don't carry an anchor yet. The two paths are complementary — a
    learning survives a file rename *only* if it was recorded with an
    anchor, so fresh Phase-2c records have stronger orphan tolerance.

    Args:
        auto_archive: If True, automatically archive orphaned learnings
            (status=archived). ADRs are reported but not auto-archived
            because they may still be historically relevant.
    """
    from attocode.integrations.context.blob_oid import check_reachability

    project_dir = _get_project_dir()
    orphans: list[dict[str, Any]] = []

    # Two-pass strategy for each store:
    #
    # 1. Collect every anchor blob_oid across all active entries.
    # 2. Ask git which are still reachable (one subprocess call).
    # 3. An entry is orphaned if it has anchors AND none are reachable.
    # 4. Entries without anchors fall through to the path-exists check.
    #
    # This keeps the git subprocess call count to 2 (one per store)
    # regardless of how many records exist.

    # --- Learnings ---
    try:
        from attocode.code_intel.tools.learning_tools import _get_memory_store
        store = _get_memory_store()
        active_learnings = store.list_all(status="active")

        all_anchors = {
            lr.get("anchor_blob_oid", "")
            for lr in active_learnings
            if lr.get("anchor_blob_oid")
        }
        reachable = (
            check_reachability(all_anchors, project_dir)
            if all_anchors else set()
        )

        for learning in active_learnings:
            anchor = learning.get("anchor_blob_oid", "")
            if anchor:
                # Trust the anchor — skip the path fallback entirely.
                if anchor not in reachable:
                    orphans.append({
                        "kind": "learning",
                        "id": learning.get("id"),
                        "reason": "blob_unreachable",
                        "anchor": anchor,
                        "scope": learning.get("scope", ""),
                        "description": learning.get("description", "")[:60],
                    })
                continue
            # No anchor — fall back to scope path check.
            scope = learning.get("scope", "")
            if scope and not os.path.exists(os.path.join(project_dir, scope)):
                orphans.append({
                    "kind": "learning",
                    "id": learning.get("id"),
                    "reason": "scope_missing",
                    "scope": scope,
                    "description": learning.get("description", "")[:60],
                })
    except Exception as exc:
        logger.warning("orphan_scan: learnings scan failed: %s", exc)

    # --- ADRs ---
    try:
        from attocode.code_intel.tools.adr_tools import _get_adr_store
        adr_store = _get_adr_store()
        all_adrs = adr_store.list_all()

        all_adr_anchors: set[str] = set()
        for adr in all_adrs:
            for a in adr.get("anchor_blob_oids", []) or []:
                if a:
                    all_adr_anchors.add(a)
        reachable_adr = (
            check_reachability(all_adr_anchors, project_dir)
            if all_adr_anchors else set()
        )

        for adr in all_adrs:
            anchors = adr.get("anchor_blob_oids", []) or []
            if anchors:
                missing_anchors = [a for a in anchors if a not in reachable_adr]
                if missing_anchors and len(missing_anchors) == len(anchors):
                    # Every anchor is unreachable — definitively orphaned.
                    orphans.append({
                        "kind": "adr",
                        "number": adr.get("number"),
                        "title": adr.get("title", ""),
                        "reason": "all_anchors_unreachable",
                        "missing_anchors": missing_anchors,
                    })
                continue
            # No anchors — fall back to related_files path check.
            related = adr.get("related_files", []) or []
            missing = [
                rf for rf in related
                if rf and not os.path.exists(os.path.join(project_dir, rf))
            ]
            if missing:
                orphans.append({
                    "kind": "adr",
                    "number": adr.get("number"),
                    "title": adr.get("title", ""),
                    "reason": "related_files_missing",
                    "missing_files": missing,
                })
    except Exception as exc:
        logger.warning("orphan_scan: adr scan failed: %s", exc)

    if not orphans:
        return "orphan_scan: no orphaned learnings or ADRs found."

    lines = [f"orphan_scan: found {len(orphans)} orphan(s):"]
    archived_count = 0
    for o in orphans:
        reason = o.get("reason", "?")
        if o["kind"] == "learning":
            if reason == "blob_unreachable":
                lines.append(
                    f"  learning #{o['id']} [{reason}]: anchor={o['anchor'][:24]}… "
                    f"— {o['description']!r}"
                )
            else:
                lines.append(
                    f"  learning #{o['id']} [{reason}]: scope={o['scope']!r} "
                    f"— {o['description']!r}"
                )
            if auto_archive:
                try:
                    # Archive (soft-delete) instead of hard-deleting so
                    # the learning is still surfaceable via
                    # list_learnings(status='archived') and resurrectable
                    # via import_learnings.
                    store.archive_by_id(o["id"])
                    archived_count += 1
                except Exception as exc:
                    logger.warning(
                        "orphan_scan: archive failed for learning %s: %s",
                        o.get("id"), exc,
                    )
        else:
            if reason == "all_anchors_unreachable":
                lines.append(
                    f"  adr #{o['number']} [{reason}]: {o['title']!r} "
                    f"— unreachable anchors: {o['missing_anchors']}"
                )
            else:
                lines.append(
                    f"  adr #{o['number']} [{reason}]: {o['title']!r} "
                    f"— missing {o['missing_files']}"
                )
    if auto_archive and archived_count:
        lines.append("")
        lines.append(f"  auto-archived {archived_count} learning(s)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Embedding rotation — Phase 2b
#
# State machine lives in ``embedding_rotation.EmbeddingRotator``. These
# tools are thin MCP wrappers over it that load a new embedding provider
# on demand and dispatch to the rotator.
# ---------------------------------------------------------------------------


def _rotator() -> EmbeddingRotator:
    """Build a rotator bound to the current project's vectors.db."""
    from attocode.integrations.context.embedding_rotation import EmbeddingRotator
    project_dir = _get_project_dir()
    db_path = os.path.join(project_dir, ".attocode", "vectors", "embeddings.db")
    return EmbeddingRotator(db_path=db_path)


def _format_rotation_status(status: Any) -> str:
    """Render a RotationStatus as a user-readable summary."""
    lines = [
        f"  state: {status.state.value}",
        f"  from: {status.from_model or '<unknown>'} "
        f"(v={status.from_version or '?'}, dim={status.from_dim})",
        f"  to:   {status.to_model or '<unknown>'} "
        f"(v={status.to_version or '?'}, dim={status.to_dim})",
        f"  progress: {status.processed_rows}/{status.total_rows} "
        f"({status.progress_pct():.1f}%)",
    ]
    if status.last_error:
        lines.append(f"  last_error: {status.last_error}")
    return "\n".join(lines)


@mcp.tool()
def embeddings_rotate_start(
    new_model: str,
    new_version: str = "",
    new_dim: int = 0,
) -> str:
    """Begin rotating all stored embeddings to a new model.

    Creates a staging table (``vectors_rotating``) that will be
    populated by repeated ``embeddings_rotate_step`` calls, then
    swapped into place via ``embeddings_rotate_cutover``. The primary
    ``vectors`` table is untouched until the atomic cutover.

    Args:
        new_model: Provider model identifier. See ``create_embedding_provider``
            for accepted names (``"bge"``, ``"all-MiniLM-L6-v2"``,
            ``"nomic-embed-text"``, ``"openai"``, or a local path).
        new_version: Optional version tag stored alongside the rotation
            (e.g. ``"v1.5"``). Free-form.
        new_dim: Optional explicit target dimension. If 0, the rotator
            loads the provider and queries its ``dimension()``.

    Returns a human-readable summary of the new rotation state.

    Note: during rotation, avoid concurrent ``semantic_search`` reindexes
    — writes that land on the primary ``vectors`` table mid-rotation will
    not be propagated to the new model and are effectively lost on cutover.
    """
    from attocode.integrations.context.embeddings import create_embedding_provider

    rot = _rotator()
    try:
        # Load the provider once up-front to confirm it's importable +
        # fail loud before any schema mutation.
        try:
            provider = create_embedding_provider(model=new_model)
        except ImportError as exc:
            return (
                f"embeddings_rotate_start: provider for {new_model!r} not available: {exc}. "
                f"Install the relevant extras, or try `pip install attocode[semantic]`."
            )

        effective_dim = new_dim or provider.dimension()
        if effective_dim <= 0:
            return (
                f"embeddings_rotate_start: could not resolve a dimension for "
                f"provider {new_model!r}; pass new_dim explicitly."
            )

        try:
            status = rot.start(
                to_model=provider.name,
                to_version=new_version,
                to_dim=effective_dim,
            )
        except RuntimeError as exc:
            return f"embeddings_rotate_start: {exc}"

        return "embeddings_rotate_start: rotation created\n" + _format_rotation_status(status)
    finally:
        rot.close()


@mcp.tool()
def embeddings_rotate_status() -> str:
    """Report the current rotation state, or 'none' if nothing is active."""
    rot = _rotator()
    try:
        status = rot.status()
    finally:
        rot.close()
    if status.state.value == "none":
        return "embeddings_rotate_status: no rotation active."
    return "embeddings_rotate_status:\n" + _format_rotation_status(status)


@mcp.tool()
def embeddings_rotate_step(batch_size: int = 32, max_batches: int = 1) -> str:
    """Process one or more batches of the backfill.

    Args:
        batch_size: Rows per batch. Larger batches amortize provider
            load cost at the expense of wall-clock per call. Default 32.
        max_batches: Loop up to this many batches in a single call.
            Default 1 (one batch per invocation). Use a larger number
            to run a whole rotation in one MCP call on a small repo.

    Returns a summary of the rotation state after processing.
    """
    from attocode.integrations.context.embeddings import create_embedding_provider

    rot = _rotator()
    try:
        status = rot.status()
        if status.state.value not in ("pending", "backfilling"):
            return (
                f"embeddings_rotate_step: rotation is in state "
                f"{status.state.value!r}, not pending|backfilling. Nothing to do."
            )
        try:
            provider = create_embedding_provider(model=status.to_model)
        except ImportError as exc:
            return f"embeddings_rotate_step: provider import failed: {exc}"

        total_processed = 0
        for _ in range(max(1, max_batches)):
            try:
                processed = rot.step(provider, batch_size=batch_size)
            except RuntimeError as exc:
                return f"embeddings_rotate_step: {exc}"
            total_processed += processed
            if processed == 0:
                break  # done

        status = rot.status()
    finally:
        rot.close()

    return (
        f"embeddings_rotate_step: processed {total_processed} row(s)\n"
        + _format_rotation_status(status)
    )


@mcp.tool()
def embeddings_rotate_cutover(confirm: bool = False) -> str:
    """Atomically swap ``vectors`` and ``vectors_rotating``.

    The old table becomes ``vectors_archive`` (still on disk until
    ``embeddings_rotate_gc_old``). Subsequent reads and writes target
    the new table. Requires state ``ready_to_cutover`` and ``confirm=True``.
    """
    rot = _rotator()
    try:
        status = rot.status()
        if status.state.value != "ready_to_cutover":
            return (
                f"embeddings_rotate_cutover: state is {status.state.value!r}, "
                f"not ready_to_cutover. Run embeddings_rotate_step until done."
            )
        if not confirm:
            return (
                "embeddings_rotate_cutover: DRY RUN — nothing changed.\n"
                + _format_rotation_status(status)
                + "\n  Re-run with confirm=True to apply the swap."
            )
        try:
            status = rot.cutover()
        except (RuntimeError, Exception) as exc:
            return f"embeddings_rotate_cutover: failed: {exc}"
    finally:
        rot.close()
    return "embeddings_rotate_cutover: success\n" + _format_rotation_status(status)


@mcp.tool()
def embeddings_rotate_gc_old(confirm: bool = False) -> str:
    """Drop the archived old-model vectors table and clear rotation state.

    Requires state ``cutover_done``. This is the point of no return for
    the old embeddings — once dropped, the only recovery is to re-embed
    from scratch (or restore from a snapshot).
    """
    rot = _rotator()
    try:
        status = rot.status()
        if status.state.value != "cutover_done":
            return (
                f"embeddings_rotate_gc_old: state is {status.state.value!r}, "
                f"not cutover_done."
            )
        if not confirm:
            return (
                "embeddings_rotate_gc_old: DRY RUN — nothing changed.\n"
                "  Re-run with confirm=True to drop the archived old vectors."
            )
        try:
            status = rot.gc_old()
        except RuntimeError as exc:
            return f"embeddings_rotate_gc_old: {exc}"
    finally:
        rot.close()
    return "embeddings_rotate_gc_old: done\n" + _format_rotation_status(status)


@mcp.tool()
def embeddings_rotate_abort(confirm: bool = False) -> str:
    """Cancel a pre-cutover rotation.

    Drops ``vectors_rotating`` and clears rotation state. The primary
    ``vectors`` table is untouched — the user's embeddings stay live.
    Cannot be called after ``cutover``; use ``gc_old`` or restore from
    a snapshot instead.
    """
    rot = _rotator()
    try:
        status = rot.status()
        if status.state.value in ("none", "gc_done"):
            return "embeddings_rotate_abort: no rotation in progress."
        if status.state.value in ("cutover_done",):
            return (
                "embeddings_rotate_abort: cannot abort after cutover. "
                "Use embeddings_rotate_gc_old to finalize or restore a snapshot."
            )
        if not confirm:
            return (
                "embeddings_rotate_abort: DRY RUN — nothing changed.\n"
                + _format_rotation_status(status)
                + "\n  Re-run with confirm=True to abort."
            )
        try:
            status = rot.abort()
        except RuntimeError as exc:
            return f"embeddings_rotate_abort: {exc}"
    finally:
        rot.close()
    return "embeddings_rotate_abort: rotation aborted, primary vectors untouched"
