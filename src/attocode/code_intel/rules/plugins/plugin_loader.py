"""Plugin loader — discovers and loads user analysis plugins.

Plugins live in ``.attocode/plugins/<name>/`` and contain:
- ``plugin.yaml`` — manifest with name, version, description, rule paths
- ``rules/*.yaml`` — YAML rule definitions (same format as pack rules)

Example plugin structure::

    .attocode/plugins/my-company-rules/
    ├── plugin.yaml
    └── rules/
        ├── no-direct-db.yaml
        └── require-logging.yaml

Example plugin.yaml::

    name: my-company-rules
    version: 1.0.0
    description: "Internal coding standards"
    rules:
      - rules/*.yaml
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.loader import load_yaml_rules
from attocode.code_intel.rules.model import RuleSource, UnifiedRule

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginManifest:
    """Parsed plugin manifest."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    plugin_dir: str = ""
    rule_globs: list[str] = field(default_factory=list)


def _load_plugin_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load plugin.yaml from a plugin directory."""
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.is_file():
        # No manifest — try to load rules directly
        return PluginManifest(
            name=plugin_dir.name,
            plugin_dir=str(plugin_dir),
            rule_globs=["rules/*.yaml"],
        )

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return PluginManifest(
            name=plugin_dir.name,
            plugin_dir=str(plugin_dir),
            rule_globs=["rules/*.yaml"],
        )

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to parse plugin manifest %s: %s", manifest_path, exc)
        return None

    return PluginManifest(
        name=str(data.get("name", plugin_dir.name)),
        version=str(data.get("version", "1.0.0")),
        description=str(data.get("description", "")),
        plugin_dir=str(plugin_dir),
        rule_globs=data.get("rules", ["rules/*.yaml"]),
    )


def discover_plugins(project_dir: str) -> list[PluginManifest]:
    """Discover all plugins in .attocode/plugins/."""
    plugins_dir = Path(project_dir) / ".attocode" / "plugins"
    if not plugins_dir.is_dir():
        return []

    manifests: list[PluginManifest] = []
    for entry in sorted(plugins_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            m = _load_plugin_manifest(entry)
            if m:
                manifests.append(m)

    return manifests


def load_plugin(manifest: PluginManifest) -> list[UnifiedRule]:
    """Load all rules from a plugin."""
    plugin_dir = Path(manifest.plugin_dir)
    rules: list[UnifiedRule] = []

    # Load rules from each glob pattern
    for glob_pattern in manifest.rule_globs:
        # Resolve the glob relative to plugin dir
        parts = glob_pattern.rsplit("/", 1)
        if len(parts) == 2:
            sub_dir = plugin_dir / parts[0]
        else:
            sub_dir = plugin_dir

        if sub_dir.is_dir():
            loaded = load_yaml_rules(
                sub_dir,
                source=RuleSource.USER,
                pack=f"plugin:{manifest.name}",
            )
            rules.extend(loaded)

    if rules:
        logger.info("Plugin '%s': loaded %d rules", manifest.name, len(rules))

    return rules


def load_all_plugins(project_dir: str) -> tuple[list[PluginManifest], list[UnifiedRule]]:
    """Discover and load all plugins. Returns (manifests, all_rules)."""
    manifests = discover_plugins(project_dir)
    all_rules: list[UnifiedRule] = []
    for m in manifests:
        all_rules.extend(load_plugin(m))
    return manifests, all_rules
