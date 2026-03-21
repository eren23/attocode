"""Shared archive logic for swarm coordinators.

Both ``SwarmOrchestrator`` (shared workspace) and ``HybridCoordinator``
(worktree) call ``archive_previous_run()`` to move old artifacts into
``history/{run_id}/`` before starting a fresh run.
"""

from __future__ import annotations

import logging
import shutil
import time as _time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _safe_move(src: Path, dest: Path) -> None:
    """Move src to dest, handling pre-existing destinations."""
    try:
        if not src.exists():
            return
        if dest.exists():
            if dest.is_dir() and src.is_dir():
                # Merge: move contents individually
                for child in src.iterdir():
                    _safe_move(child, dest / child.name)
                shutil.rmtree(src, ignore_errors=True)
            else:
                # File: overwrite
                dest.unlink(missing_ok=True)
                shutil.move(str(src), str(dest))
        else:
            shutil.move(str(src), str(dest))
    except Exception as exc:
        logger.warning("Archive move %s → %s failed: %s", src, dest, exc)


def archive_previous_run(layout: dict[str, Any]) -> None:
    """Move previous run artifacts to ``history/{run_id}/`` and start clean.

    Called on fresh (non-resume) runs only.  Preserves all prior data
    for later review while giving the new run a clean slate.

    Uses a marker file (``.archiving``) for crash safety — if the
    process dies mid-archive, the next run resumes the interrupted
    archive instead of creating a split archive.
    """
    root: Path = layout["root"]
    marker_path = root / ".archiving"

    # 1. Check for interrupted archive from a crash
    if marker_path.exists():
        try:
            target_dir = Path(marker_path.read_text(encoding="utf-8").strip())
            if target_dir.is_dir():
                _do_archive_moves(layout, target_dir)
                marker_path.unlink(missing_ok=True)
                return
        except Exception:
            marker_path.unlink(missing_ok=True)

    # 2. Determine old run_id
    old_run_id: str = ""
    old_state_path: Path = layout["state"]
    if old_state_path.exists():
        try:
            from attoswarm.protocol.io import read_json

            old_state = read_json(old_state_path, default={})
            old_run_id = old_state.get("run_id", "")
        except Exception:
            pass

    if not old_run_id:
        control_path = root / "control.jsonl"
        has_data = any(
            p.exists()
            for p in (
                layout["state"],
                layout["manifest"],
                layout["events"],
            )
        ) or (control_path.exists() and control_path.stat().st_size > 0) or any(
            d.is_dir() and any(d.iterdir())
            for d in (layout["agents"], layout["tasks"])
            if d.is_dir()
        )
        if not has_data:
            return  # First run ever
        old_run_id = f"unknown-{int(_time.time())}"

    # 3. Write marker BEFORE any moves
    history_dir = root / "history" / old_run_id
    history_dir.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(str(history_dir), encoding="utf-8")

    # 4. Move everything
    _do_archive_moves(layout, history_dir)

    # 5. Remove marker — archive complete
    marker_path.unlink(missing_ok=True)


def _do_archive_moves(layout: dict[str, Any], history_dir: Path) -> None:
    """Move remaining run artifacts into *history_dir*. Idempotent."""
    root: Path = layout["root"]

    # JSONL files
    for name in ("control.jsonl",):
        src = root / name
        if src.exists() and src.stat().st_size > 0:
            _safe_move(src, history_dir / name)

    if layout["events"].exists() and layout["events"].stat().st_size > 0:
        _safe_move(layout["events"], history_dir / "swarm.events.jsonl")

    for key, dest_name in (
        ("state", "swarm.state.json"),
        ("manifest", "swarm.manifest.json"),
    ):
        src = layout[key]
        if src.exists():
            _safe_move(src, history_dir / dest_name)

    git_safety = root / "git_safety.json"
    if git_safety.exists():
        _safe_move(git_safety, history_dir / "git_safety.json")

    # Additional root-level files that were previously lost
    for extra in ("changes.json", "coordinator.log", "swarm.yaml", "index.snapshot.json"):
        src = root / extra
        if src.exists() and src.stat().st_size > 0:
            _safe_move(src, history_dir / extra)

    for dir_key in ("agents", "tasks"):
        src_dir = layout[dir_key]
        if src_dir.is_dir() and any(src_dir.iterdir()):
            _safe_move(src_dir, history_dir / dir_key)
            src_dir.mkdir(parents=True, exist_ok=True)

    locks_dir = layout["locks"]
    if locks_dir.is_dir():
        shutil.rmtree(locks_dir, ignore_errors=True)
        locks_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        root / "control.jsonl",
        layout["events"],
    ):
        if not path.exists():
            path.write_text("", encoding="utf-8")


def ensure_clean_slate(layout: dict[str, Any]) -> int:
    """Guarantee no stale state remains. Called after archive on fresh runs.

    This is the nuclear option — if archive failed to move something,
    we delete it. Losing old review data is acceptable; starting with
    poisoned state is not.

    Returns the number of stale items removed.
    """
    root: Path = layout["root"]
    cleaned = 0

    # Remove stale root-level files
    for path in (
        layout["state"],
        layout["manifest"],
        root / "git_safety.json",
        root / "changes.json",
        root / "coordinator.log",
        root / "swarm.yaml",
        root / "index.snapshot.json",
        root / ".orchestrator.pid",
    ):
        if path.exists():
            logger.warning("Clean slate: removing stale %s", path.name)
            path.unlink(missing_ok=True)
            cleaned += 1

    # Remove .archiving marker
    marker = root / ".archiving"
    if marker.exists():
        logger.warning("Clean slate: removing stale .archiving marker")
        marker.unlink(missing_ok=True)
        cleaned += 1

    # Clear directories (don't delete — recreate empty)
    for dir_key in ("agents", "tasks", "locks"):
        d = layout[dir_key]
        if d.is_dir() and any(d.iterdir()):
            logger.warning("Clean slate: clearing stale %s/", dir_key)
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
            cleaned += 1

    # Ensure fresh empty JSONL files
    for path in (root / "control.jsonl", layout["events"]):
        path.write_text("", encoding="utf-8")

    return cleaned
