"""Structured adapter over the existing local SQLite stores."""

from __future__ import annotations

import hashlib
from pathlib import Path

LEARNING_TOOLS = {
    "recall",
    "record_learning",
    "list_learnings",
    "learning_feedback",
    "update_learning",
}


def execute_local_knowledge(context, operation, arguments):
    args = dict(arguments)
    store = context.service._get_memory_store()

    def rows(status="active", kind=None):
        result = store.list_all(status=status, type=kind)
        for row in result:
            row.update(status=status, author_id="local", revision="working-tree", stale=False)
            anchor, scope = row.get("anchor_blob_oid", ""), row.get("scope", "")
            if anchor and scope:
                path = Path(context.project_dir) / scope
                if not path.is_file():
                    row["stale"] = True
                else:
                    data = path.read_bytes()
                    current = (
                        "git:"
                        + hashlib.sha1(
                            b"blob " + str(len(data)).encode() + b"\0" + data
                        ).hexdigest()
                        if anchor.startswith("git:")
                        else "sha256:" + hashlib.sha256(data).hexdigest()
                    )
                    row["stale"] = current != anchor
        return result

    if operation == "record_learning":
        if not args["description"].strip():
            raise ValueError("A non-empty description is required")
        if not 0 <= args.get("confidence", 0.7) <= 1:
            raise ValueError("confidence must be between zero and one")
        path = (Path(context.project_dir) / args.get("scope", "")).resolve()
        if not path.is_relative_to(Path(context.project_dir)):
            raise ValueError("Knowledge scope must remain inside the selected repository")
        if path.is_file() and not args.get("anchor_blob_oid"):
            args["anchor_blob_oid"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        number = store.add(**args)
        return next(row for row in rows() if row["id"] == number)
    if operation in {"update_learning", "learning_feedback"}:
        number = args.pop("learning_id")
        existing = next((r for r in rows() + rows("archived") if r["id"] == number), None)
        if existing is None:
            raise ValueError("Learning not found")
        if operation == "update_learning":
            if "description" in args and not args["description"].strip():
                raise ValueError("A non-empty description is required")
            store.update(number, **args)
        else:
            store.record_feedback(number, args["helpful"])
        return next(r for r in rows() + rows("archived") if r["id"] == number)
    if operation == "recall":
        matched = store.recall(**args)
        by_id = {row["id"]: row for row in rows()}
        return [by_id[r["id"]] for r in matched if r["id"] in by_id]
    result = rows(args.get("status", "active"), args.get("type") or None)
    scope = args.get("scope", "").rstrip("/")
    return [
        r
        for r in result
        if not scope or not r["scope"] or r["scope"] == scope or r["scope"].startswith(scope + "/")
    ]
