"""Bounded Git source extraction for the quality corpus, without running repo code."""
from __future__ import annotations

import os
import zlib
from pathlib import PurePosixPath

from eval.matrix import run as matrix

MAX_PACK_BYTES = 512 * 1024**2


def scoped_entries(entries, spec):
    prefix = spec.get("subdir")
    includes = spec.get("include", [])
    if prefix and includes:
        raise ValueError("Use subdir or include scopes, not both")
    for path in ([prefix] if prefix else includes):
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
            raise ValueError("Invalid source scope")
    selected = []
    for path, mode, oid, size in entries:
        if prefix:
            if not path.startswith(prefix + "/"):
                continue
            path = path[len(prefix) + 1:]
        elif includes and not any(path == p or path.startswith(p + "/") for p in includes):
            continue
        selected.append([path, mode, oid, size])
    total = sum(e[3] for e in selected if matrix._stored(e))
    if total > MAX_PACK_BYTES:
        raise ValueError("Source pack exceeds 512 MiB; declare a smaller source scope")
    return selected


def read_tree(source, commit, cache, spec, *, remote=False):
    """Copy only selected small source blobs; never fetch omitted remote objects."""
    sha = matrix._git(source, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    if sha != commit:
        raise ValueError("Quality source requires an exact commit hash")
    entries = []
    scopes = [spec["subdir"]] if spec.get("subdir") else spec.get("include", [])
    # Scope is applied in Git before reading blob bodies, then rechecked below.
    for record in matrix._git(source, "ls-tree", "-r", "-z", sha, "--", *scopes).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, _, oid = meta.decode().split()
            entries.append([os.fsdecode(path), mode, oid, 0])
    oids = sorted({e[2] for e in entries if e[1] != "160000"})
    info = (matrix._git(source, "cat-file", "--batch-all-objects", "--batch-check") if remote else
            matrix._git(source, "cat-file", "--batch-check", data="".join(o + "\n" for o in oids).encode()))
    sizes = {}
    for line in info.splitlines():
        oid, *rest = line.decode().split()
        sizes[oid] = int(rest[1]) if rest[0] == "blob" else -1
    for entry in entries:
        entry[3] = sizes.get(entry[2], -1) if entry[1] != "160000" else 0
    entries = scoped_entries(entries, spec)
    if not remote and any(e[3] < 0 and matrix._stored([*e[:3], 0]) for e in entries):
        raise ValueError("Pinned local source is missing required blobs")
    need = sorted({e[2] for e in entries if matrix._stored(e)})
    for start in range(0, len(need), 64):
        out = matrix._git(source, "cat-file", "--batch", data="".join(o + "\n" for o in need[start:start + 64]).encode())
        pos = 0
        while pos < len(out):
            end = out.index(b"\n", pos)
            oid, kind, size = out[pos:end].decode().split()
            if kind != "blob":
                raise ValueError("Expected source blob")
            matrix._write(matrix._blob_file(cache, oid), zlib.compress(out[end + 1:end + 1 + int(size)]))
            pos = end + 1 + int(size) + 1
    return {"commit": sha, "tree": matrix._git(source, "rev-parse", f"{sha}^{{tree}}").decode().strip(),
            "entries": entries}
