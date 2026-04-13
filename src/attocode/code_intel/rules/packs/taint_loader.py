"""Taint definition loader — loads sources, sinks, and sanitizers from pack YAML.

Extends the existing dataflow.py engine by making taint definitions
data-driven: each language pack can ship its own source/sink/sanitizer
definitions in taint/*.yaml files.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from attocode.code_intel.rules.model import (
    TaintSanitizerDef,
    TaintSinkDef,
    TaintSourceDef,
)

logger = logging.getLogger(__name__)


def load_taint_sources(taint_dir: Path) -> list[TaintSourceDef]:
    """Load taint sources from sources.yaml."""
    path = taint_dir / "sources.yaml"
    if not path.is_file():
        return []

    data = _load_yaml(path)
    if not data or "sources" not in data:
        return []

    results: list[TaintSourceDef] = []
    for entry in data["sources"]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        patterns = entry.get("patterns", [])
        language = str(entry.get("language", ""))
        if name and patterns:
            results.append(TaintSourceDef(
                name=name,
                patterns=[str(p) for p in patterns],
                language=language,
            ))
    return results


def load_taint_sinks(taint_dir: Path) -> list[TaintSinkDef]:
    """Load taint sinks from sinks.yaml."""
    path = taint_dir / "sinks.yaml"
    if not path.is_file():
        return []

    data = _load_yaml(path)
    if not data or "sinks" not in data:
        return []

    results: list[TaintSinkDef] = []
    for entry in data["sinks"]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        patterns = entry.get("patterns", [])
        cwe = str(entry.get("cwe", ""))
        message = str(entry.get("message", ""))
        language = str(entry.get("language", ""))
        if name and patterns:
            results.append(TaintSinkDef(
                name=name,
                patterns=[str(p) for p in patterns],
                cwe=cwe,
                message=message,
                language=language,
            ))
    return results


def load_taint_sanitizers(taint_dir: Path) -> list[TaintSanitizerDef]:
    """Load taint sanitizers from sanitizers.yaml."""
    path = taint_dir / "sanitizers.yaml"
    if not path.is_file():
        return []

    data = _load_yaml(path)
    if not data or "sanitizers" not in data:
        return []

    results: list[TaintSanitizerDef] = []
    for entry in data["sanitizers"]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        patterns = entry.get("patterns", [])
        language = str(entry.get("language", ""))
        if name and patterns:
            results.append(TaintSanitizerDef(
                name=name,
                patterns=[str(p) for p in patterns],
                language=language,
            ))
    return results


def load_pack_taint_defs(
    pack_dir: str | Path,
) -> tuple[list[TaintSourceDef], list[TaintSinkDef], list[TaintSanitizerDef]]:
    """Load all taint definitions from a pack's taint/ directory.

    Returns:
        (sources, sinks, sanitizers) tuple.
    """
    taint_dir = Path(pack_dir) / "taint"
    if not taint_dir.is_dir():
        return [], [], []

    sources = load_taint_sources(taint_dir)
    sinks = load_taint_sinks(taint_dir)
    sanitizers = load_taint_sanitizers(taint_dir)

    if sources or sinks or sanitizers:
        logger.info(
            "Loaded taint defs from %s: %d sources, %d sinks, %d sanitizers",
            pack_dir, len(sources), len(sinks), len(sanitizers),
        )
    return sources, sinks, sanitizers


def compile_taint_patterns(
    sources: list[TaintSourceDef],
    sinks: list[TaintSinkDef],
    sanitizers: list[TaintSanitizerDef],
) -> tuple[
    list[tuple[str, re.Pattern[str], str]],
    list[tuple[str, re.Pattern[str], str, str, str]],
    list[tuple[str, re.Pattern[str], str]],
]:
    """Compile taint definitions into regex patterns for the dataflow engine.

    Returns:
        (compiled_sources, compiled_sinks, compiled_sanitizers) where each is
        a list of tuples compatible with the dataflow.py engine.
    """
    compiled_sources = []
    for src in sources:
        combined = "|".join(f"(?:{p})" for p in src.patterns)
        try:
            compiled_sources.append((src.name, re.compile(combined), src.language))
        except re.error as exc:
            logger.warning("Invalid taint source pattern '%s': %s", src.name, exc)

    compiled_sinks = []
    for sink in sinks:
        combined = "|".join(f"(?:{p})" for p in sink.patterns)
        try:
            compiled_sinks.append((
                sink.name, re.compile(combined), sink.cwe, sink.message, sink.language,
            ))
        except re.error as exc:
            logger.warning("Invalid taint sink pattern '%s': %s", sink.name, exc)

    compiled_sanitizers = []
    for san in sanitizers:
        combined = "|".join(f"(?:{p})" for p in san.patterns)
        try:
            compiled_sanitizers.append((san.name, re.compile(combined), san.language))
        except re.error as exc:
            logger.warning("Invalid taint sanitizer pattern '%s': %s", san.name, exc)

    return compiled_sources, compiled_sinks, compiled_sanitizers


def _load_yaml(path: Path) -> dict | None:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return None
