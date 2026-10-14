"""Bounded, lossless report export; large pretty JSON is compacted, not truncated."""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path


def export_reports(root, destination):
    total = 0
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(Path(root).glob("*/*")):
            if not path.is_file() or path.is_symlink() or path.suffix not in {".json", ".log", ".xml"}:
                continue
            limit = 8 * 2**20 if path.suffix == ".json" else 2**21
            if path.stat().st_size > limit:
                raise ValueError("Report input exceeds export limit")
            body = path.read_bytes()
            if path.suffix == ".json":
                body = json.dumps(json.loads(body), separators=(",", ":"), ensure_ascii=False).encode()
            total += len(body)
            if len(body) > 2**21 or total > 20 * 2**20:
                raise ValueError("Report export exceeds limit")
            info = tarfile.TarInfo(str(Path(".attocode/quality/runs") / path.relative_to(root)))
            info.size = len(body)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(body))


if __name__ == "__main__":
    export_reports(".attocode/quality/runs", "/root/results.tar.gz")
