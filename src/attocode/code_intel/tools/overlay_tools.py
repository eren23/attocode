"""Named-overlay MCP tools — directory-based working-state swap.

An overlay is a named copy of every local store file, stored under
``.attocode/overlays/<name>/``. Switching between branches / working sets
means calling ``overlay_activate(name)`` — an atomic per-file replacement
that preserves the current state as a fresh overlay if you ask it to.

Phase 2c-3 ships the minimal viable form: directory-based, no stacking,
no tombstones, no dedup across overlays. It's the simplest thing that
delivers the UX goal ("one command to swap code-intel state") and
forward-compatible with a later stacked-layer design.

Format of one overlay directory::

    .attocode/overlays/<name>/
        overlay.json                       # {created_at, description, source_hash}
        stores/symbols.db                  # live-consistent SQLite backup
        stores/embeddings.db
        stores/memory.db
        stores/adrs.db
        stores/frecency.db
        stores/query_history.db
        stores/kw_index.db                 # copy
        stores/trigrams.{lookup,postings,db}
        cache_manifest.json                # project manifest at capture time

Tools:

  - ``overlay_create(name, description)`` — capture current state
  - ``overlay_list``                      — enumerate all overlays
  - ``overlay_activate(name, save_current_as)`` — swap over live state
  - ``overlay_delete(name, confirm)``     — remove an overlay directory
  - ``overlay_status``                    — currently-active overlay tag
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from typing import Any

from attocode.code_intel._shared import _get_project_dir, mcp

logger = logging.getLogger(__name__)

OVERLAY_SCHEMA_VERSION = 1
OVERLAY_DIR_NAME = "overlays"
_OVERLAY_STATE_FILE = "_overlay_state.json"

# Same shape as snapshot_tools' _SQLITE_STORES / _BINARY_FILES so the two
# tool modules stay in lockstep. When a new store lands, update both lists.
_SQLITE_STORES: tuple[tuple[str, str], ...] = (
    ("index/symbols.db", "symbols.db"),
    ("vectors/embeddings.db", "embeddings.db"),
    ("index/kw_index.db", "kw_index.db"),
    ("cache/memory.db", "memory.db"),
    ("adrs.db", "adrs.db"),
    ("frecency/frecency.db", "frecency.db"),
    ("query_history/query_history.db", "query_history.db"),
)
_BINARY_FILES: tuple[tuple[str, str], ...] = (
    ("index/trigrams.lookup", "trigrams.lookup"),
    ("index/trigrams.postings", "trigrams.postings"),
    ("index/trigrams.db", "trigrams.db"),
)


# ---------------------------------------------------------------------------
# Paths + state helpers
# ---------------------------------------------------------------------------


def _attocode_dir(project_dir: str) -> str:
    return os.path.join(project_dir, ".attocode")


def _overlays_root(project_dir: str) -> str:
    return os.path.join(_attocode_dir(project_dir), OVERLAY_DIR_NAME)


def _overlay_dir(project_dir: str, name: str) -> str:
    return os.path.join(_overlays_root(project_dir), name)


def _state_path(project_dir: str) -> str:
    return os.path.join(_overlays_root(project_dir), _OVERLAY_STATE_FILE)


def _read_state(project_dir: str) -> dict[str, Any]:
    path = _state_path(project_dir)
    if not os.path.exists(path):
        return {"active": None, "history": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.loads(f.read())
    except (OSError, json.JSONDecodeError):
        return {"active": None, "history": []}


def _write_state(project_dir: str, state: dict[str, Any]) -> None:
    path = _state_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _is_valid_name(name: str) -> bool:
    """Overlay names must be short filesystem-friendly slugs.

    Rejected: empty strings, path separators, leading underscore
    (reserved for internal state like ``_overlay_state.json``), and
    anything with shell meta characters.
    """
    if not name or name.startswith("_") or name in (".", ".."):
        return False
    return all(c.isalnum() or c in ("-", "_", ".") for c in name)


# ---------------------------------------------------------------------------
# Store copy helpers (shared with snapshot_tools logic, inlined so the
# two modules can evolve independently)
# ---------------------------------------------------------------------------


def _backup_sqlite(source: str, dest: str) -> None:
    """Live-consistent SQLite backup via the online backup API."""
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _copy_store_to(dest_stores_dir: str, attocode: str) -> list[str]:
    """Copy every tracked store into ``dest_stores_dir``.

    Returns the list of copied store names (logical, not filenames).
    """
    os.makedirs(dest_stores_dir, exist_ok=True)
    copied: list[str] = []

    for src_rel, out_name in _SQLITE_STORES:
        src = os.path.join(attocode, src_rel)
        if not os.path.exists(src):
            continue
        dest = os.path.join(dest_stores_dir, out_name)
        try:
            _backup_sqlite(src, dest)
        except sqlite3.Error as exc:
            logger.warning(
                "overlay: sqlite backup of %s failed (%s); falling back to shutil.copy",
                src, exc,
            )
            shutil.copy2(src, dest)
        copied.append(out_name)

    for src_rel, out_name in _BINARY_FILES:
        src = os.path.join(attocode, src_rel)
        if not os.path.exists(src):
            continue
        shutil.copy2(src, os.path.join(dest_stores_dir, out_name))
        copied.append(out_name)

    return copied


def _copy_store_from(src_stores_dir: str, attocode: str) -> list[str]:
    """Copy every overlay store file back into the live ``.attocode/`` tree.

    Each destination is atomically replaced via rename-tmp → rename so a
    failure mid-copy can't produce a torn file. The overall restore is
    atomic per-file, not per-collection — which is good enough for
    Phase 2c-3 (single-user local).
    """
    restored: list[str] = []
    mapping: list[tuple[str, str]] = list(_SQLITE_STORES) + list(_BINARY_FILES)
    for src_rel, out_name in mapping:
        src = os.path.join(src_stores_dir, out_name)
        if not os.path.exists(src):
            continue
        dest = os.path.join(attocode, src_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
        restored.append(out_name)
    return restored


def _count_rows(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        # Sum across every user table so a newly-added store shows up too.
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        total = 0
        for t in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                if row:
                    total += int(row[0])
            except sqlite3.OperationalError:
                pass
        return total
    finally:
        conn.close()


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n //= 1024
    return f"{n}TB"


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def overlay_create(name: str, description: str = "") -> str:
    """Capture the current code-intel state as a named overlay.

    Args:
        name: Short filesystem-safe overlay name (e.g. ``"main"``,
            ``"feature-auth"``). Must be alphanumeric plus ``- _ .``.
        description: Optional human-readable description stored alongside
            the overlay for reference.

    Returns a summary of what was captured.
    """
    project_dir = _get_project_dir()
    if not _is_valid_name(name):
        return (
            f"overlay_create: invalid overlay name {name!r}. "
            f"Use alphanumeric plus '-', '_', '.'. Leading underscores reserved."
        )
    odir = _overlay_dir(project_dir, name)
    if os.path.exists(odir):
        return (
            f"overlay_create: overlay {name!r} already exists at {odir}. "
            f"Delete it first with overlay_delete, or pick a different name."
        )

    attocode = _attocode_dir(project_dir)
    if not os.path.exists(attocode):
        return "overlay_create: no .attocode/ directory to capture."

    stores_dir = os.path.join(odir, "stores")
    os.makedirs(stores_dir, exist_ok=True)
    try:
        copied = _copy_store_to(stores_dir, attocode)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(odir, ignore_errors=True)
        return f"overlay_create: copy failed, rolled back: {exc}"

    if not copied:
        shutil.rmtree(odir, ignore_errors=True)
        return "overlay_create: nothing to capture (no store files present)."

    # Copy cache_manifest.json if present (top-level — not in stores/).
    manifest_src = os.path.join(attocode, "cache_manifest.json")
    if os.path.exists(manifest_src):
        shutil.copy2(manifest_src, os.path.join(odir, "cache_manifest.json"))

    total_size = sum(
        _safe_size(os.path.join(stores_dir, n)) for n in copied
    )
    metadata = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "name": name,
        "description": description,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stores": copied,
        "total_bytes": total_size,
    }
    with open(os.path.join(odir, "overlay.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)

    return (
        f"overlay_create: captured {len(copied)} store(s) "
        f"({_fmt_bytes(total_size)}) as {name!r} at {odir}"
    )


@mcp.tool()
def overlay_list() -> str:
    """List all named overlays under ``.attocode/overlays/``."""
    project_dir = _get_project_dir()
    root = _overlays_root(project_dir)
    if not os.path.isdir(root):
        return "overlay_list: no overlays/ directory."

    state = _read_state(project_dir)
    active = state.get("active")

    entries: list[tuple[str, dict[str, Any]]] = []
    for name in sorted(os.listdir(root)):
        if name.startswith("_") or not _is_valid_name(name):
            continue
        odir = os.path.join(root, name)
        if not os.path.isdir(odir):
            continue
        meta_path = os.path.join(odir, "overlay.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.loads(f.read())
            except (OSError, json.JSONDecodeError):
                meta = {}
        else:
            meta = {}
        entries.append((name, meta))

    if not entries:
        return "overlay_list: no named overlays found."

    lines = [f"overlay_list: {len(entries)} overlay(s) (active={active or 'none'}):"]
    for name, meta in entries:
        marker = "*" if name == active else " "
        created = meta.get("created_at", "?")
        size = meta.get("total_bytes", 0)
        desc = meta.get("description", "")
        suffix = f"  {desc!r}" if desc else ""
        lines.append(
            f"  {marker} {name:20s}  "
            f"{_fmt_bytes(size):>10s}  {created}{suffix}"
        )
    return "\n".join(lines)


@mcp.tool()
def overlay_status() -> str:
    """Report which overlay (if any) is currently marked active.

    The live code-intel state is always whatever is in ``.attocode/``;
    the "active" marker just records the *name* of the overlay that
    was last activated. Creating an overlay does not change the active
    marker — activation does.
    """
    project_dir = _get_project_dir()
    state = _read_state(project_dir)
    active = state.get("active")
    history = state.get("history", [])

    if not active:
        return (
            "overlay_status: no overlay activated yet. "
            "Create one with overlay_create(name)."
        )

    lines = [f"overlay_status: active={active!r}"]
    if history:
        lines.append(f"  recent: {', '.join(history[-5:])}")
    return "\n".join(lines)


@mcp.tool()
def overlay_activate(
    name: str,
    save_current_as: str = "",
    confirm: bool = False,
) -> str:
    """Swap the live ``.attocode/`` state with an overlay.

    This copies every store file from ``.attocode/overlays/<name>/``
    into the live ``.attocode/`` tree, overwriting anything in place.
    Per-file atomic via tempfile + rename. If ``save_current_as`` is
    provided, the current live state is captured as a new overlay
    BEFORE the swap so you can return to it later.

    Args:
        name: Existing overlay name to restore.
        save_current_as: Optional name for a pre-swap backup overlay.
            Empty means "don't back up — just swap". Skipping this
            silently loses the pre-swap state if no prior overlay has it.
        confirm: Must be True to apply. Default False returns a dry run.
    """
    project_dir = _get_project_dir()
    if not _is_valid_name(name):
        return f"overlay_activate: invalid overlay name {name!r}"

    odir = _overlay_dir(project_dir, name)
    if not os.path.isdir(odir):
        return f"overlay_activate: no overlay named {name!r}"

    stores_src = os.path.join(odir, "stores")
    if not os.path.isdir(stores_src):
        return f"overlay_activate: overlay {name!r} missing stores/ directory"

    attocode = _attocode_dir(project_dir)
    state = _read_state(project_dir)

    if save_current_as and not _is_valid_name(save_current_as):
        return (
            f"overlay_activate: invalid save_current_as name "
            f"{save_current_as!r}"
        )

    # Preview the component list so the dry-run summary is useful.
    components = sorted(os.listdir(stores_src)) if os.path.isdir(stores_src) else []

    if not confirm:
        lines = [
            "overlay_activate: DRY RUN — nothing swapped.",
            f"  source: {odir}",
            f"  components: {len(components)}",
        ]
        if save_current_as:
            lines.append(f"  will save current live state as: {save_current_as!r}")
        else:
            lines.append("  will NOT save current live state (pass save_current_as to keep it)")
        lines.append("  Re-run with confirm=True to apply.")
        return "\n".join(lines)

    # 1. Save current state if requested.
    if save_current_as:
        save_dir = _overlay_dir(project_dir, save_current_as)
        if os.path.exists(save_dir):
            return (
                f"overlay_activate: save_current_as={save_current_as!r} already "
                f"exists. Delete it first or pick another name."
            )
        try:
            os.makedirs(os.path.join(save_dir, "stores"), exist_ok=True)
            saved = _copy_store_to(os.path.join(save_dir, "stores"), attocode)
            manifest_src = os.path.join(attocode, "cache_manifest.json")
            if os.path.exists(manifest_src):
                shutil.copy2(manifest_src, os.path.join(save_dir, "cache_manifest.json"))
            metadata = {
                "schema_version": OVERLAY_SCHEMA_VERSION,
                "name": save_current_as,
                "description": f"auto-saved before activating {name!r}",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stores": saved,
                "total_bytes": sum(
                    _safe_size(os.path.join(save_dir, "stores", n)) for n in saved
                ),
            }
            with open(os.path.join(save_dir, "overlay.json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, sort_keys=True)
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(save_dir, ignore_errors=True)
            return f"overlay_activate: failed to save current state: {exc}"

    # 2. Restore from target overlay.
    try:
        restored = _copy_store_from(stores_src, attocode)
    except Exception as exc:  # noqa: BLE001
        return f"overlay_activate: restore failed: {exc}"

    # 3. Copy cache_manifest.json if the overlay has one.
    manifest_src = os.path.join(odir, "cache_manifest.json")
    if os.path.exists(manifest_src):
        shutil.copy2(manifest_src, os.path.join(attocode, "cache_manifest.json"))

    # 4. Update state.
    history = state.get("history", [])
    prior_active = state.get("active")
    if prior_active and prior_active != name:
        history = [*history, prior_active][-10:]
    state["active"] = name
    state["history"] = history
    _write_state(project_dir, state)

    lines = [
        f"overlay_activate: activated {name!r}",
        f"  restored: {len(restored)} component(s)",
    ]
    if save_current_as:
        lines.append(f"  saved prior state as: {save_current_as!r}")
    return "\n".join(lines)


@mcp.tool()
def overlay_delete(name: str, confirm: bool = False) -> str:
    """Remove a named overlay directory.

    Args:
        name: Overlay to delete.
        confirm: Must be True to apply.
    """
    project_dir = _get_project_dir()
    if not _is_valid_name(name):
        return f"overlay_delete: invalid overlay name {name!r}"
    odir = _overlay_dir(project_dir, name)
    if not os.path.isdir(odir):
        return f"overlay_delete: no overlay named {name!r}"

    # Size preview.
    total = 0
    for root, _, files in os.walk(odir):
        for f in files:
            total += _safe_size(os.path.join(root, f))

    if not confirm:
        return (
            f"overlay_delete: DRY RUN — would delete {odir} "
            f"({_fmt_bytes(total)}). Re-run with confirm=True."
        )

    shutil.rmtree(odir, ignore_errors=False)

    # If this was the active overlay, clear the state marker (the live
    # .attocode/ tree is unaffected, but we no longer have a named
    # reference to the state it matches).
    state = _read_state(project_dir)
    if state.get("active") == name:
        state["active"] = None
        _write_state(project_dir, state)

    return f"overlay_delete: removed {name!r} ({_fmt_bytes(total)} freed)"
