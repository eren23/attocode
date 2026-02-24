"""Compatibility bridge for importing prior attocode swarm state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attoswarm.protocol.io import read_json, write_json_atomic


def import_attocode_state(source_state: str | Path, target_run_dir: str | Path) -> dict[str, Any]:
    src = Path(source_state)
    dst = Path(target_run_dir)
    raw = read_json(src, default={})
    migrated = {
        "migration": {"source": str(src), "status": "imported"},
        "source_state": raw,
    }
    write_json_atomic(dst / "migration.import.json", migrated)
    return migrated
