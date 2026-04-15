"""Portable local artifact bundles for code-intel state."""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from attocode import __version__
from attocode.code_intel.artifacts.hashing import sha256_file

_SCHEMA_VERSION = 1
_ARTIFACTS = (
    ("artifacts/index/symbols.db", ".attocode/index/symbols.db"),
    ("artifacts/vectors/embeddings.db", ".attocode/vectors/embeddings.db"),
    ("artifacts/cache/memory.db", ".attocode/cache/memory.db"),
    ("artifacts/adrs.db", ".attocode/adrs.db"),
)


def _metadata(project_dir: Path) -> dict[str, object]:
    artifacts: list[dict[str, object]] = []
    for bundle_path, rel_path in _ARTIFACTS:
        source = project_dir / rel_path
        present = source.exists()
        artifacts.append({
            "path": bundle_path,
            "present": present,
            "size_bytes": source.stat().st_size if present else 0,
            "sha256": sha256_file(source) if present else None,
        })

    return {
        "schema_version": _SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_name": project_dir.name,
        "project_root_basename": project_dir.name,
        "attocode_version": __version__,
        "artifacts": artifacts,
    }


def export_bundle(project_dir: str, output_path: str) -> Path:
    """Export local code-intel artifacts into a tar.gz bundle."""
    project_root = Path(project_dir).resolve()
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(project_root)

    with TemporaryDirectory(prefix="attocode-bundle-") as tmpdir:
        root = Path(tmpdir) / "attocode-bundle"
        root.mkdir(parents=True, exist_ok=True)
        metadata_path = root / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        for bundle_path, rel_path in _ARTIFACTS:
            source = project_root / rel_path
            if not source.exists():
                continue
            target = root / bundle_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

        with tarfile.open(destination, "w:gz") as archive:
            archive.add(root, arcname="attocode-bundle")

    return destination


def inspect_bundle(bundle_path: str) -> dict[str, object]:
    """Read bundle metadata without touching local project state."""
    bundle = Path(bundle_path).resolve()
    with tarfile.open(bundle, "r:gz") as archive:
        metadata_member = archive.getmember("attocode-bundle/metadata.json")
        fh = archive.extractfile(metadata_member)
        if fh is None:
            raise FileNotFoundError("metadata.json missing from bundle")
        return json.loads(fh.read().decode("utf-8"))
