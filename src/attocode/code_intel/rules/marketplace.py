"""Community rule registry — search, install, validate, and publish packs.

Phase 1: GitHub-based registry with a static YAML index.
Packs are Git repositories or subdirectories that follow the standard
pack structure (manifest.yaml + rules/*.yaml).
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.packs.pack_loader import _load_manifest

logger = logging.getLogger(__name__)

# Default registry index URL (GitHub raw)
DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/attocode/rules/main/index.yaml"
)


# ---------------------------------------------------------------------------
# Registry index
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RegistryEntry:
    """A pack listed in the community registry."""

    name: str
    url: str  # Git clone URL
    languages: list[str] = field(default_factory=list)
    rules_count: int = 0
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)


def fetch_registry_index(
    registry_url: str = DEFAULT_REGISTRY_URL,
) -> list[RegistryEntry]:
    """Fetch the community registry index.

    Returns:
        List of RegistryEntry from the remote index.
        Returns empty list on network errors (graceful degradation).
    """
    try:
        import urllib.request
        import yaml  # type: ignore[import-untyped]

        with urllib.request.urlopen(registry_url, timeout=10) as resp:
            data = yaml.safe_load(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Failed to fetch registry index: %s", exc)
        return []

    if not isinstance(data, dict) or "packs" not in data:
        return []

    entries: list[RegistryEntry] = []
    for item in data["packs"]:
        if not isinstance(item, dict) or "name" not in item:
            continue
        entries.append(RegistryEntry(
            name=str(item["name"]),
            url=str(item.get("url", "")),
            languages=list(item.get("languages", [])),
            rules_count=int(item.get("rules_count", 0)),
            description=str(item.get("description", "")),
            author=str(item.get("author", "")),
            version=str(item.get("version", "1.0.0")),
            tags=list(item.get("tags", [])),
        ))

    return entries


def search_packs(
    query: str = "",
    *,
    language: str = "",
    registry_url: str = DEFAULT_REGISTRY_URL,
) -> list[RegistryEntry]:
    """Search the community registry for packs matching a query.

    Args:
        query: Free-text search (matches name, description, tags).
        language: Filter to packs supporting this language.
        registry_url: Override registry URL.

    Returns:
        Matching registry entries.
    """
    entries = fetch_registry_index(registry_url)
    if not entries:
        return []

    results: list[RegistryEntry] = []
    query_lower = query.lower()

    for entry in entries:
        if language and language.lower() not in [l.lower() for l in entry.languages]:
            continue
        if query_lower:
            searchable = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()
            if query_lower not in searchable:
                continue
        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Remote pack installation
# ---------------------------------------------------------------------------


def install_remote_pack(
    pack_url: str,
    project_dir: str,
    *,
    pack_name: str = "",
) -> str:
    """Install a pack from a remote Git URL into .attocode/packs/.

    Clones the repository at depth=1 and validates the pack before installing.

    Args:
        pack_url: URL to clone or download.
        project_dir: Project root directory.
        pack_name: Override pack name (default: derived from URL).

    Returns:
        Status message.
    """
    if not pack_name:
        # Derive name from URL: github.com/user/repo -> repo
        pack_name = pack_url.rstrip("/").rsplit("/", 1)[-1]
        pack_name = pack_name.removesuffix(".git")

    # Sanitize pack_name to prevent path traversal
    pack_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pack_name)

    dest = Path(project_dir) / ".attocode" / "packs" / pack_name
    if dest.is_dir():
        return f"Pack '{pack_name}' already installed at {dest}. Delete to reinstall."

    # Try git clone first
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / pack_name
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", pack_url, str(clone_dir)],
                capture_output=True, text=True, timeout=60,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Failed to clone '{pack_url}': {exc}"

        # Validate before installing
        errors = validate_pack(str(clone_dir))
        if errors:
            return f"Pack validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        # Copy to destination
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(clone_dir), str(dest), dirs_exist_ok=True)
        # Remove .git directory
        git_dir = dest / ".git"
        if git_dir.is_dir():
            shutil.rmtree(str(git_dir))

    manifest = _load_manifest(dest)
    return (
        f"Installed community pack '{pack_name}' to {dest}\n"
        f"  Version: {manifest.version if manifest else 'unknown'}\n"
        f"  Languages: {', '.join(manifest.languages) if manifest else pack_name}"
    )


# ---------------------------------------------------------------------------
# Pack validation
# ---------------------------------------------------------------------------


def validate_pack(pack_dir: str) -> list[str]:
    """Validate a pack directory for correctness and completeness.

    Checks:
    1. manifest.yaml present and parseable
    2. At least one rule file in rules/
    3. All rule IDs are unique
    4. Required fields present (message, severity)
    5. All regex patterns compile
    6. Inline test_cases pass (if present)

    Returns:
        List of error messages (empty = valid).
    """
    errors: list[str] = []
    pack_path = Path(pack_dir)

    # 1. Manifest — check existence first
    manifest_file = pack_path / "manifest.yaml"
    if not manifest_file.is_file():
        errors.append("Missing manifest.yaml (create one with name, version, languages)")
        return errors

    manifest = _load_manifest(pack_path)
    if manifest is None:
        errors.append("Failed to parse manifest.yaml")
        return errors

    if not manifest.name:
        errors.append("Manifest missing 'name' field")

    # 2. Rules directory
    rules_dir = pack_path / "rules"
    if not rules_dir.is_dir():
        errors.append("Missing rules/ directory")
        return errors

    yaml_files = list(rules_dir.glob("*.yaml"))
    if not yaml_files:
        errors.append("No *.yaml rule files in rules/")
        return errors

    # 3-6. Load and validate rules
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        errors.append("PyYAML not installed — cannot validate rules")
        return errors

    seen_ids: set[str] = set()
    rule_count = 0

    for yaml_file in yaml_files:
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = _yaml.safe_load(content)
            if data is None:
                continue
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []

            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{yaml_file.name}[{i}]: expected dict, got {type(item).__name__}")
                    continue

                rule_id = item.get("id", "")
                if not rule_id:
                    errors.append(f"{yaml_file.name}[{i}]: missing 'id' field")
                    continue

                # 3. Unique IDs
                if rule_id in seen_ids:
                    errors.append(f"{yaml_file.name}[{i}]: duplicate rule ID '{rule_id}'")
                seen_ids.add(rule_id)

                # 4. Check required fields
                for req in ("pattern", "message", "severity"):
                    if req not in item and "patterns" not in item and "pattern-either" not in item:
                        if req == "pattern":
                            continue  # composite patterns don't need top-level pattern
                        errors.append(f"{yaml_file.name}[{i}]: missing '{req}' field")

                # 5. Regex compilation
                pattern_str = item.get("pattern", "")
                if pattern_str:
                    try:
                        re.compile(pattern_str)
                    except re.error as exc:
                        errors.append(f"{yaml_file.name}[{i}]: invalid regex '{pattern_str[:40]}': {exc}")

                # 6. Inline test_cases (per-line matching, consistent with executor)
                test_cases = item.get("test_cases", [])
                if test_cases and pattern_str:
                    try:
                        compiled = re.compile(pattern_str)
                        for j, tc in enumerate(test_cases):
                            code = str(tc.get("code", ""))
                            should_match = bool(tc.get("should_match", True))
                            matched = any(compiled.search(ln) for ln in code.splitlines()) if code else False
                            if should_match and not matched:
                                errors.append(
                                    f"{yaml_file.name}[{i}].test_cases[{j}]: "
                                    f"expected match on '{code[:40]}'"
                                )
                            elif not should_match and matched:
                                errors.append(
                                    f"{yaml_file.name}[{i}].test_cases[{j}]: "
                                    f"unexpected match on '{code[:40]}'"
                                )
                    except re.error:
                        pass  # already reported above

                rule_count += 1

        except Exception as exc:
            errors.append(f"Failed to parse {yaml_file.name}: {exc}")

    if rule_count == 0:
        errors.append("No valid rules found")

    return errors


# ---------------------------------------------------------------------------
# Pack publishing helper
# ---------------------------------------------------------------------------


def prepare_pack_for_publish(pack_dir: str) -> str:
    """Validate and prepare a pack for community sharing.

    Returns a status message with validation results and next steps.
    """
    errors = validate_pack(pack_dir)

    if errors:
        return (
            "Pack validation FAILED — fix these before publishing:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    manifest = _load_manifest(Path(pack_dir))
    from attocode.code_intel.rules.loader import load_yaml_rules

    rules_dir = Path(pack_dir) / "rules"
    rules = load_yaml_rules(str(rules_dir))

    return (
        f"Pack '{manifest.name}' is ready for publishing!\n"
        f"  Version: {manifest.version}\n"
        f"  Languages: {', '.join(manifest.languages)}\n"
        f"  Rules: {len(rules)}\n"
        f"\nNext steps:\n"
        f"  1. Push to a public Git repository\n"
        f"  2. Submit a PR to the attocode/rules registry to list your pack\n"
        f"  3. Others can install with: install_community_pack('{manifest.name}')"
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_registry_search(entries: list[RegistryEntry]) -> str:
    """Format registry search results as markdown."""
    if not entries:
        return "No packs found matching your query."

    lines = ["## Community Rule Packs\n"]
    for e in entries:
        langs = ", ".join(e.languages) if e.languages else "any"
        tags = " ".join(f"`{t}`" for t in e.tags) if e.tags else ""
        lines.append(
            f"- **{e.name}** v{e.version} ({langs}) — {e.description}\n"
            f"  {e.rules_count} rules | by {e.author or 'community'} {tags}\n"
            f"  Install: `install_community_pack('{e.name}')`"
        )

    return "\n".join(lines)
