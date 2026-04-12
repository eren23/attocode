"""Language pack loader — discovers and loads user-activated analysis packs.

Packs provide language-specific rules, taint definitions, and few-shot
examples. Example packs ship with attocode under ``packs/examples/``
but are NOT auto-loaded. Users activate packs by copying them to
``.attocode/packs/<name>/`` in their project.

Each pack directory contains:
- ``manifest.yaml`` — metadata (name, version, languages, description)
- ``rules/*.yaml`` — YAML rule definitions
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.loader import load_yaml_rules
from attocode.code_intel.rules.model import RuleSource, UnifiedRule

logger = logging.getLogger(__name__)

# Example packs ship here — NOT auto-loaded
_EXAMPLES_DIR = Path(__file__).parent / "examples"


@dataclass(slots=True)
class PackManifest:
    """Parsed pack manifest."""

    name: str
    version: str = "1.0.0"
    languages: list[str] = field(default_factory=list)
    description: str = ""
    pack_dir: str = ""


def _load_manifest(pack_dir: Path) -> PackManifest | None:
    """Load manifest.yaml from a pack directory."""
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return PackManifest(
            name=pack_dir.name,
            languages=[pack_dir.name],
            pack_dir=str(pack_dir),
        )

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return PackManifest(
            name=pack_dir.name,
            languages=[pack_dir.name],
            pack_dir=str(pack_dir),
        )

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to parse manifest %s: %s", manifest_path, exc)
        return None

    return PackManifest(
        name=str(data.get("name", pack_dir.name)),
        version=str(data.get("version", "1.0.0")),
        languages=data.get("languages", [pack_dir.name]),
        description=str(data.get("description", "")),
        pack_dir=str(pack_dir),
    )


def _load_pack_rules(pack_dir: Path, manifest: PackManifest) -> list[UnifiedRule]:
    """Load all rules from a pack's rules/ directory."""
    rules_dir = pack_dir / "rules"
    if not rules_dir.is_dir():
        rules_dir = pack_dir

    return load_yaml_rules(
        rules_dir,
        source=RuleSource.PACK,
        pack=manifest.name,
    )


def discover_packs(project_dir: str = "") -> list[PackManifest]:
    """Discover user-activated packs from ``.attocode/packs/``.

    Only loads packs the user has explicitly placed in their project.
    Example packs under ``packs/examples/`` are NOT auto-loaded.

    Returns:
        List of pack manifests sorted by name.
    """
    manifests: list[PackManifest] = []

    if project_dir:
        user_packs = Path(project_dir) / ".attocode" / "packs"
        if user_packs.is_dir():
            for entry in sorted(user_packs.iterdir()):
                if entry.is_dir() and not entry.name.startswith("_"):
                    m = _load_manifest(entry)
                    if m:
                        manifests.append(m)

    return manifests


def list_example_packs() -> list[PackManifest]:
    """List available example packs (shipped but not auto-loaded).

    These can be installed into a project via ``install_pack()``.
    """
    manifests: list[PackManifest] = []
    if _EXAMPLES_DIR.is_dir():
        for entry in sorted(_EXAMPLES_DIR.iterdir()):
            if entry.is_dir() and not entry.name.startswith("_"):
                m = _load_manifest(entry)
                if m:
                    manifests.append(m)
    return manifests


def install_pack(pack_name: str, project_dir: str) -> str:
    """Copy an example pack into ``.attocode/packs/<name>/``.

    Args:
        pack_name: Name of the example pack (go, python, typescript, rust, java).
        project_dir: Project root directory.

    Returns:
        Status message.
    """
    source = _EXAMPLES_DIR / pack_name
    if not source.is_dir():
        available = [d.name for d in _EXAMPLES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")]
        return f"Pack '{pack_name}' not found. Available: {', '.join(available)}"

    dest = Path(project_dir) / ".attocode" / "packs" / pack_name
    if dest.is_dir():
        return f"Pack '{pack_name}' already installed at {dest}. Delete it first to reinstall."

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(source), str(dest))

    manifest = _load_manifest(dest)
    rule_count = len(_load_pack_rules(dest, manifest)) if manifest else 0

    return (
        f"Installed pack '{pack_name}' to {dest}\n"
        f"  Rules: {rule_count}\n"
        f"  Languages: {', '.join(manifest.languages) if manifest else pack_name}\n"
        f"  Customize rules in {dest}/rules/*.yaml"
    )


def load_pack(manifest: PackManifest) -> list[UnifiedRule]:
    """Load all rules from a single pack."""
    pack_dir = Path(manifest.pack_dir)
    rules = _load_pack_rules(pack_dir, manifest)
    if rules:
        logger.info(
            "Pack '%s': loaded %d rules for %s",
            manifest.name, len(rules), ", ".join(manifest.languages),
        )
    return rules


def load_all_packs(project_dir: str = "") -> tuple[list[PackManifest], list[UnifiedRule]]:
    """Discover and load all user-activated packs."""
    manifests = discover_packs(project_dir)
    all_rules: list[UnifiedRule] = []
    for m in manifests:
        all_rules.extend(load_pack(m))
    return manifests, all_rules
