"""Snapshot / restore MCP tools — portable code-intel state bundles.

Phase 2a ships the local snapshot surface. A snapshot is a ``.tar.gz``
under ``.attocode/snapshots/`` containing:

  - ``manifest.json`` at the archive root (see :data:`MANIFEST_SCHEMA_VERSION`
    below) listing every component + its SHA-256.
  - ``stores/<name>`` — live-consistent copies of every local DB
    (SQLite backup API) plus the trigram binary files.
  - ``cache_manifest.json`` — the project's current cache manifest.

Restore uses an atomic ``.attocode.staging/`` → ``rename`` dance so a
failed extraction cannot corrupt the live store.

This is the **local-only** form — it does not yet push to an OCI
registry or the HTTP server. Phase 3 will add those paths on top of the
same manifest format, so the snapshot file produced here is forward
compatible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from dataclasses import dataclass
from typing import Any

from attocode.code_intel._shared import _get_project_dir, mcp

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1
SNAPSHOT_SUFFIX = ".atsnap.tar.gz"
SNAPSHOT_DIR_NAME = "snapshots"

# Everything under .attocode/ that's worth capturing. Each tuple is
# (source relative path, archive relative path under "stores/").
_SQLITE_STORES: tuple[tuple[str, str], ...] = (
    ("index/symbols.db", "symbols.db"),
    ("vectors/embeddings.db", "embeddings.db"),
    ("index/kw_index.db", "kw_index.db"),
    ("cache/memory.db", "memory.db"),
    ("adrs.db", "adrs.db"),
    ("frecency/frecency.db", "frecency.db"),
    ("query_history/query_history.db", "query_history.db"),
)

# Binary files that we copy as-is (no SQLite backup dance).
_BINARY_FILES: tuple[tuple[str, str], ...] = (
    ("index/trigrams.lookup", "trigrams.lookup"),
    ("index/trigrams.postings", "trigrams.postings"),
    ("index/trigrams.db", "trigrams.db"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshots_dir(project_dir: str) -> str:
    return os.path.join(project_dir, ".attocode", SNAPSHOT_DIR_NAME)


def _attocode_dir(project_dir: str) -> str:
    return os.path.join(project_dir, ".attocode")


def _backup_sqlite(source: str, dest: str) -> None:
    """Use the SQLite backup API for a consistent live copy.

    Copying a SQLite database file while another connection has it open
    can produce a corrupt snapshot. The backup API serializes reads on
    the source and writes a consistent image to the destination even if
    the source is actively being mutated.
    """
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n //= 1024
    return f"{n}TB"


def _list_snapshot_files(project_dir: str) -> list[str]:
    sdir = _snapshots_dir(project_dir)
    if not os.path.isdir(sdir):
        return []
    return sorted(
        os.path.join(sdir, f)
        for f in os.listdir(sdir)
        if f.endswith(SNAPSHOT_SUFFIX)
    )


def _resolve_snapshot(project_dir: str, name: str) -> str | None:
    """Resolve ``name`` to a snapshot path. Accepts bare names, base names,
    and full paths."""
    if os.path.isabs(name) and os.path.exists(name):
        return name
    sdir = _snapshots_dir(project_dir)
    candidates = [
        os.path.join(sdir, name),
        os.path.join(sdir, name + SNAPSHOT_SUFFIX),
    ]
    # Also allow matching any existing snapshot whose basename starts with name.
    for f in _list_snapshot_files(project_dir):
        if os.path.basename(f).startswith(name):
            candidates.append(f)
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


@dataclass(slots=True)
class _Component:
    name: str
    archive_path: str  # relative path inside the tar
    source_path: str
    size_bytes: int
    digest: str  # sha256 of the staged copy (not the live file)


# ---------------------------------------------------------------------------
# Build manifest + staging
# ---------------------------------------------------------------------------


def _stage_snapshot(
    project_dir: str,
    staging_dir: str,
    include_patterns: set[str] | None,
) -> list[_Component]:
    """Copy every store (SQLite via backup, binaries via shutil) into
    ``staging_dir/stores/`` and return a list of :class:`_Component`.

    ``include_patterns`` is a set of component logical names (e.g.
    ``{"symbols", "embeddings"}``). Empty / None means "include everything".
    """
    attocode = _attocode_dir(project_dir)
    stores_dir = os.path.join(staging_dir, "stores")
    os.makedirs(stores_dir, exist_ok=True)
    components: list[_Component] = []

    def _include(name: str) -> bool:
        if not include_patterns:
            return True
        return name in include_patterns

    # SQLite stores.
    for src_rel, out_name in _SQLITE_STORES:
        logical = out_name.split(".")[0]  # "symbols.db" → "symbols"
        if not _include(logical):
            continue
        src = os.path.join(attocode, src_rel)
        if not os.path.exists(src):
            continue
        dest = os.path.join(stores_dir, out_name)
        try:
            _backup_sqlite(src, dest)
        except sqlite3.Error as exc:
            logger.warning(
                "snapshot: SQLite backup of %s failed (%s); falling back to file copy",
                src, exc,
            )
            shutil.copy2(src, dest)
        size = os.path.getsize(dest)
        components.append(_Component(
            name=logical,
            archive_path=f"stores/{out_name}",
            source_path=src_rel,
            size_bytes=size,
            digest=_sha256_file(dest),
        ))

    # Binary / non-SQLite files (trigrams).
    if _include("trigrams"):
        for src_rel, out_name in _BINARY_FILES:
            src = os.path.join(attocode, src_rel)
            if not os.path.exists(src):
                continue
            dest = os.path.join(stores_dir, out_name)
            shutil.copy2(src, dest)
            components.append(_Component(
                name="trigrams",
                archive_path=f"stores/{out_name}",
                source_path=src_rel,
                size_bytes=os.path.getsize(dest),
                digest=_sha256_file(dest),
            ))

    # cache_manifest.json (top level of the archive)
    mpath = os.path.join(attocode, "cache_manifest.json")
    if os.path.exists(mpath):
        dest = os.path.join(staging_dir, "cache_manifest.json")
        shutil.copy2(mpath, dest)
        components.append(_Component(
            name="cache_manifest",
            archive_path="cache_manifest.json",
            source_path="cache_manifest.json",
            size_bytes=os.path.getsize(dest),
            digest=_sha256_file(dest),
        ))

    return components


def _write_manifest(
    staging_dir: str,
    *,
    project_dir: str,
    name: str,
    components: list[_Component],
) -> dict[str, Any]:
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "schema": "atto.snapshot.v1",
        "snapshot_name": name,
        "project_dir": project_dir,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "producer": {
            "service": "attocode-local",
            "version": "phase-2a",
        },
        "components": [
            {
                "name": c.name,
                "archive_path": c.archive_path,
                "source_path": c.source_path,
                "size_bytes": c.size_bytes,
                "digest": f"sha256:{c.digest}",
                "media_type": _media_type_for(c.name, c.archive_path),
            }
            for c in components
        ],
        "total_size_bytes": sum(c.size_bytes for c in components),
    }
    with open(os.path.join(staging_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    return manifest


def _media_type_for(name: str, archive_path: str) -> str:
    if archive_path.endswith(".db"):
        return f"application/vnd.attocode.sqlite.{name}.v1+sqlite"
    if name == "trigrams":
        return "application/vnd.attocode.trigram.v1+bin"
    if archive_path == "cache_manifest.json":
        return "application/vnd.attocode.cache_manifest.v1+json"
    return "application/vnd.attocode.blob.v1+bin"


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def snapshot_create(name: str = "", include: str = "") -> str:
    """Create a portable snapshot of the current code-intel state.

    Bundles SQLite stores (via the live SQLite backup API — safe while
    the stores are open) + trigram files + cache_manifest.json into a
    single ``.atsnap.tar.gz`` file under ``.attocode/snapshots/``.

    Args:
        name: Human-friendly name. If empty, uses a timestamp.
        include: Comma-separated list of component logical names to
            include (e.g. ``"symbols,embeddings,learnings"``). Empty
            means "include everything".

    Returns a summary of the produced snapshot file.
    """
    project_dir = _get_project_dir()
    sdir = _snapshots_dir(project_dir)
    os.makedirs(sdir, exist_ok=True)

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base_name = (name or f"snapshot_{timestamp}").replace("/", "_").replace(" ", "_")
    if not base_name.endswith("_" + timestamp) and not name:
        base_name = f"{base_name}"
    out_file = os.path.join(sdir, f"{base_name}{SNAPSHOT_SUFFIX}")

    include_set = {s.strip() for s in include.split(",") if s.strip()} if include else None

    with tempfile.TemporaryDirectory(prefix="atto-snap-", dir=sdir) as staging:
        components = _stage_snapshot(project_dir, staging, include_set)
        if not components:
            return (
                f"snapshot_create: nothing to snapshot "
                f"(no components matched include={include!r})"
            )
        manifest = _write_manifest(
            staging, project_dir=project_dir, name=base_name, components=components,
        )

        # Build the tar.
        tmp_tar = out_file + ".tmp"
        with tarfile.open(tmp_tar, "w:gz") as tar:
            # manifest.json first so it's cheap to read without extracting.
            tar.add(os.path.join(staging, "manifest.json"), arcname="manifest.json")
            if os.path.exists(os.path.join(staging, "cache_manifest.json")):
                tar.add(
                    os.path.join(staging, "cache_manifest.json"),
                    arcname="cache_manifest.json",
                )
            stores_dir = os.path.join(staging, "stores")
            if os.path.isdir(stores_dir):
                tar.add(stores_dir, arcname="stores")
        os.replace(tmp_tar, out_file)

    size = os.path.getsize(out_file)
    return (
        f"snapshot_create: {out_file}\n"
        f"  components: {len(manifest['components'])}\n"
        f"  total_size_uncompressed: {_fmt_bytes(manifest['total_size_bytes'])}\n"
        f"  archive_size: {_fmt_bytes(size)}"
    )


@mcp.tool()
def snapshot_list() -> str:
    """List all snapshots under ``.attocode/snapshots/``."""
    project_dir = _get_project_dir()
    snaps = _list_snapshot_files(project_dir)
    if not snaps:
        return "snapshot_list: no snapshots in .attocode/snapshots/"
    lines = [f"snapshot_list: {len(snaps)} snapshot(s):"]
    for path in snaps:
        size = os.path.getsize(path)
        mtime = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(os.path.getmtime(path)),
        )
        lines.append(f"  {os.path.basename(path):45s} {_fmt_bytes(size):>10s}  {mtime}")
    return "\n".join(lines)


@mcp.tool()
def snapshot_delete(name: str, confirm: bool = False) -> str:
    """Delete a snapshot.

    Args:
        name: Snapshot filename or bare prefix (see ``snapshot_list``).
        confirm: Must be True to actually delete.
    """
    project_dir = _get_project_dir()
    path = _resolve_snapshot(project_dir, name)
    if path is None:
        return f"snapshot_delete: no snapshot matching {name!r}"
    size = os.path.getsize(path)
    if not confirm:
        return (
            f"snapshot_delete: DRY RUN — would delete {path} ({_fmt_bytes(size)}). "
            f"Re-run with confirm=True."
        )
    os.unlink(path)
    return f"snapshot_delete: removed {path} ({_fmt_bytes(size)})"


@mcp.tool()
def snapshot_restore(name: str, confirm: bool = False) -> str:
    """Restore a snapshot into ``.attocode/``.

    Uses a staging directory + atomic rename so a partial extraction
    can't corrupt the live state. On failure the live state is preserved.

    **Caution:** this overwrites the current ``.attocode/`` store files.
    Pre-existing snapshots, the ``snapshots/`` directory itself, and any
    files not covered by the snapshot are preserved.

    Args:
        name: Snapshot filename or bare prefix.
        confirm: Must be True to actually restore.
    """
    project_dir = _get_project_dir()
    path = _resolve_snapshot(project_dir, name)
    if path is None:
        return f"snapshot_restore: no snapshot matching {name!r}"

    # Preview — read manifest without extracting the whole archive.
    try:
        with tarfile.open(path, "r:gz") as tar:
            mfile = tar.extractfile("manifest.json")
            if mfile is None:
                return "snapshot_restore: malformed snapshot (no manifest.json)"
            manifest = json.loads(mfile.read().decode("utf-8"))
    except (tarfile.TarError, json.JSONDecodeError, KeyError) as exc:
        return f"snapshot_restore: could not read snapshot manifest: {exc}"

    components = manifest.get("components", [])
    if not confirm:
        lines = [
            "snapshot_restore: DRY RUN — nothing written.",
            f"  source: {path}",
            f"  created: {manifest.get('created_at', '?')}",
            f"  components: {len(components)}",
        ]
        for c in components:
            lines.append(
                f"    - {c.get('name', '?'):15s} "
                f"{_fmt_bytes(c.get('size_bytes', 0)):>10s}  {c.get('archive_path', '?')}"
            )
        lines.append("  Re-run with confirm=True to apply.")
        return "\n".join(lines)

    # Apply: extract to a staging directory, then atomic move of each
    # individual store file. We do NOT atomic-rename the whole .attocode
    # directory because that would wipe files that aren't in the snapshot.
    attocode = _attocode_dir(project_dir)
    with tempfile.TemporaryDirectory(prefix="atto-restore-", dir=attocode) as staging:
        try:
            with tarfile.open(path, "r:gz") as tar:
                # ``filter="data"`` (Python 3.12+) rejects absolute paths,
                # path traversal, and symlinks escaping the staging dir —
                # safer than the legacy default and future-proof against
                # Python 3.14's stricter behavior.
                tar.extractall(staging, filter="data")  # noqa: S202
        except tarfile.TarError as exc:
            return f"snapshot_restore: extraction failed: {exc}"

        # Verify component digests.
        bad: list[str] = []
        for c in components:
            ap = c.get("archive_path", "")
            staged_path = os.path.join(staging, ap)
            if not os.path.exists(staged_path):
                bad.append(f"missing: {ap}")
                continue
            expected = c.get("digest", "")
            if expected.startswith("sha256:"):
                actual = "sha256:" + _sha256_file(staged_path)
                if actual != expected:
                    bad.append(f"digest mismatch: {ap}")
        if bad:
            return "snapshot_restore: integrity check failed:\n  " + "\n  ".join(bad)

        # Move each component into place. Atomic per-file; the whole
        # operation is not atomic but any single file's replacement is.
        restored: list[str] = []
        failed: list[str] = []
        for c in components:
            ap = c.get("archive_path", "")
            src = os.path.join(staging, ap)
            if ap == "cache_manifest.json":
                dest = os.path.join(attocode, "cache_manifest.json")
            elif ap.startswith("stores/"):
                # Map back to the original .attocode-relative path.
                out_name = ap.split("/", 1)[1]
                dest_rel = _dest_for_store(out_name)
                if dest_rel is None:
                    failed.append(f"{ap}: unknown store name")
                    continue
                dest = os.path.join(attocode, dest_rel)
            else:
                failed.append(f"{ap}: unknown archive layout")
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                os.replace(src, dest)
                restored.append(ap)
            except OSError as exc:
                failed.append(f"{ap}: {exc}")

    lines = [
        f"snapshot_restore: restored from {path}",
        f"  restored: {len(restored)} component(s)",
    ]
    if failed:
        lines.append(f"  failed: {len(failed)}")
        for f in failed:
            lines.append(f"    - {f}")
    return "\n".join(lines)


def _dest_for_store(out_name: str) -> str | None:
    """Map a snapshot's ``stores/<out_name>`` back to a .attocode-relative path."""
    for src_rel, candidate in _SQLITE_STORES:
        if candidate == out_name:
            return src_rel
    for src_rel, candidate in _BINARY_FILES:
        if candidate == out_name:
            return src_rel
    return None


@mcp.tool()
def snapshot_diff(a: str, b: str) -> str:
    """Diff two snapshots at the component-digest level.

    Args:
        a: First snapshot name or path.
        b: Second snapshot name or path.

    Returns a summary of which components changed, were added, or removed.
    """
    project_dir = _get_project_dir()
    path_a = _resolve_snapshot(project_dir, a)
    path_b = _resolve_snapshot(project_dir, b)
    if path_a is None:
        return f"snapshot_diff: no snapshot matching {a!r}"
    if path_b is None:
        return f"snapshot_diff: no snapshot matching {b!r}"

    def _manifest_of(path: str) -> dict[str, Any]:
        with tarfile.open(path, "r:gz") as tar:
            mfile = tar.extractfile("manifest.json")
            assert mfile is not None
            return json.loads(mfile.read().decode("utf-8"))

    try:
        ma = _manifest_of(path_a)
        mb = _manifest_of(path_b)
    except (tarfile.TarError, json.JSONDecodeError, KeyError, AssertionError) as exc:
        return f"snapshot_diff: manifest read failed: {exc}"

    def _digest_map(m: dict[str, Any]) -> dict[str, str]:
        return {c.get("name", "?"): c.get("digest", "") for c in m.get("components", [])}

    da = _digest_map(ma)
    db = _digest_map(mb)

    added = [k for k in db if k not in da]
    removed = [k for k in da if k not in db]
    changed = [k for k in da if k in db and da[k] != db[k]]
    same = [k for k in da if k in db and da[k] == db[k]]

    lines = [
        f"snapshot_diff: {os.path.basename(path_a)} → {os.path.basename(path_b)}",
        f"  same: {len(same)}",
        f"  changed: {len(changed)}",
        f"  added: {len(added)}",
        f"  removed: {len(removed)}",
    ]
    if changed:
        lines.append("  changed components:")
        for n in sorted(changed):
            lines.append(f"    - {n}: {da[n][:16]}… → {db[n][:16]}…")
    if added:
        lines.append("  added components:")
        for n in sorted(added):
            lines.append(f"    + {n}")
    if removed:
        lines.append("  removed components:")
        for n in sorted(removed):
            lines.append(f"    - {n}")
    return "\n".join(lines)
