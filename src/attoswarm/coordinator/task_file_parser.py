"""Parse task definition files (YAML or Markdown) into TaskSpec lists.

Supports two formats:
- YAML: structured ``tasks:`` list with typed fields
- Markdown: ``## task-id: Title`` headings with metadata lines

Usage::

    from attoswarm.coordinator.task_file_parser import load_tasks_file
    tasks = load_tasks_file(Path("tasks.yaml"))
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from attoswarm.protocol.models import TaskSpec

_KNOWN_KINDS = frozenset({
    "implement", "test", "integrate", "analysis",
    "design", "judge", "critic", "merge",
})

_MD_HEADING_RE = re.compile(r"^##\s+([\w-]+):\s*(.+)$")
_MD_META_RE = re.compile(r"^([\w\s]+):\s*(.+)$")


def load_tasks_file(path: Path) -> list[TaskSpec]:
    """Load and validate a task file, returning TaskSpec objects.

    Auto-detects format by file extension (``.yaml``/``.yml`` → YAML,
    ``.md`` → Markdown).

    Raises ``ValueError`` on validation failures.
    """
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        raw = _load_yaml(path)
    elif suffix == ".md":
        raw = _load_markdown(path)
    else:
        raise ValueError(f"Unsupported task file extension: {suffix!r} (expected .yaml, .yml, or .md)")

    errors = validate_tasks(raw)
    if errors:
        raise ValueError(f"Task file validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    return [
        TaskSpec(
            task_id=t["task_id"],
            title=t.get("title", t["task_id"]),
            description=t.get("description", ""),
            deps=t.get("deps", []),
            role_hint=t.get("role_hint") or None,
            task_kind=t.get("task_kind", "implement"),
            target_files=t.get("target_files", []),
            read_files=t.get("read_files", []),
            priority=int(t.get("priority", 50)),
        )
        for t in raw
    ]


def _load_yaml(path: Path) -> list[dict[str, Any]]:
    """Parse YAML task file."""
    import yaml

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "tasks" not in data:
        raise ValueError("YAML task file must have a top-level 'tasks' key")
    tasks = data["tasks"]
    if not isinstance(tasks, list):
        raise ValueError("'tasks' must be a list")
    return tasks


def _load_markdown(path: Path) -> list[dict[str, Any]]:
    """Parse Markdown task file.

    Format::

        ## task-id: Title
        Kind: implement
        Role: impl
        Depends on: task-1, task-2
        Target files: src/foo.ts, src/bar.ts
        Read files: src/baz.ts
        Priority: 80

        Description text (everything after the first blank line).
    """
    text = path.read_text(encoding="utf-8")
    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_description = False
    desc_lines: list[str] = []

    def _flush() -> None:
        nonlocal current, in_description, desc_lines
        if current is not None:
            current["description"] = "\n".join(desc_lines).strip()
            tasks.append(current)
        current = None
        in_description = False
        desc_lines = []

    for line in text.splitlines():
        heading = _MD_HEADING_RE.match(line)
        if heading:
            _flush()
            current = {
                "task_id": heading.group(1),
                "title": heading.group(2).strip(),
            }
            continue

        if current is None:
            continue

        if in_description:
            desc_lines.append(line)
            continue

        # Blank line transitions from metadata to description
        if not line.strip():
            in_description = True
            continue

        meta = _MD_META_RE.match(line)
        if meta:
            key = meta.group(1).strip().lower()
            value = meta.group(2).strip()
            _apply_meta(current, key, value)
        else:
            # Non-metadata line before blank line — treat as start of description
            in_description = True
            desc_lines.append(line)

    _flush()
    return tasks


def _apply_meta(task: dict[str, Any], key: str, value: str) -> None:
    """Apply a parsed metadata key-value to a task dict."""
    if key == "kind":
        task["task_kind"] = value
    elif key == "role":
        task["role_hint"] = value
    elif key in ("depends on", "deps"):
        task["deps"] = [d.strip() for d in value.split(",") if d.strip()]
    elif key in ("target files", "target_files"):
        task["target_files"] = [f.strip() for f in value.split(",") if f.strip()]
    elif key in ("read files", "read_files"):
        task["read_files"] = [f.strip() for f in value.split(",") if f.strip()]
    elif key == "priority":
        try:
            task["priority"] = int(value)
        except ValueError:
            pass


def validate_tasks(tasks: list[dict[str, Any]]) -> list[str]:
    """Validate a list of raw task dicts, returning error messages."""
    errors: list[str] = []

    if not tasks:
        errors.append("No tasks defined")
        return errors

    # Unique IDs
    ids = [t.get("task_id", "") for t in tasks]
    seen: set[str] = set()
    for tid in ids:
        if not tid:
            errors.append("Task missing 'task_id'")
        elif tid in seen:
            errors.append(f"Duplicate task_id: {tid!r}")
        seen.add(tid)

    id_set = set(ids)

    # Dep references
    for t in tasks:
        for dep in t.get("deps", []):
            if dep not in id_set:
                errors.append(f"Task {t.get('task_id', '?')!r} depends on unknown task {dep!r}")

    # task_kind validation
    for t in tasks:
        kind = t.get("task_kind", "implement")
        if kind not in _KNOWN_KINDS:
            errors.append(f"Task {t.get('task_id', '?')!r}: unknown task_kind {kind!r}")

    # Circular dependency check (topological sort)
    if not errors:
        cycle_err = _check_cycles(tasks)
        if cycle_err:
            errors.append(cycle_err)

    return errors


def _check_cycles(tasks: list[dict[str, Any]]) -> str | None:
    """Detect circular dependencies via topological sort. Returns error message or None."""
    adj: dict[str, list[str]] = {}
    in_degree: dict[str, int] = {}
    for t in tasks:
        tid = t["task_id"]
        adj.setdefault(tid, [])
        in_degree.setdefault(tid, 0)

    for t in tasks:
        for dep in t.get("deps", []):
            adj.setdefault(dep, []).append(t["task_id"])
            in_degree[t["task_id"]] = in_degree.get(t["task_id"], 0) + 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited < len(tasks):
        return "Circular dependency detected in task graph"
    return None
