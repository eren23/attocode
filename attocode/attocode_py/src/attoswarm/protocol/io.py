"""Protocol IO helpers with atomic writes and lock support."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, sort_keys=False) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, item: Any) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item) + "\n")
