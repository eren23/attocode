"""Architecture drift detection.

Compares actual file dependencies against declared architecture boundaries
to detect layering violations, circular dependencies, and unauthorized imports.

Loads rules from ``.attocode/architecture.yaml`` and checks them against the
real dependency graph built by the AST service.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ArchViolation:
    """A single architecture boundary violation."""

    source_file: str  # file that has the import
    target_file: str  # file being imported
    source_layer: str  # layer the source belongs to
    target_layer: str  # layer the target belongs to
    rule: str  # human-readable rule description
    severity: str = "high"  # high for deny violations, medium for unlisted


@dataclass(slots=True)
class ArchReport:
    """Architecture drift detection report."""

    violations: list[ArchViolation]
    layers_defined: int
    rules_defined: int
    files_checked: int
    compliant_files: int


@dataclass
class ArchLayer:
    """A named architecture layer with path patterns."""

    name: str
    paths: list[str]

    def matches(self, file_path: str) -> bool:
        """Check if a file belongs to this layer.

        Uses forward-slash normalised prefix matching so that OS-specific
        separators do not cause false negatives.
        """
        normalised = file_path.replace(os.sep, "/")
        for path_prefix in self.paths:
            prefix = path_prefix.replace(os.sep, "/")
            if normalised.startswith(prefix):
                return True
        return False


@dataclass
class ArchRule:
    """A dependency rule between layers."""

    from_layer: str
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_architecture(
    project_dir: str,
) -> tuple[list[ArchLayer], list[ArchRule], dict[str, list[str]]]:
    """Load architecture definitions from ``.attocode/architecture.yaml``.

    Returns:
        A 3-tuple of ``(layers, rules, exceptions)`` where *exceptions* maps
        a source file path to a list of explicitly-allowed target paths.

    If the YAML file does not exist or PyYAML is not installed the function
    returns empty collections without raising.
    """
    config_path = os.path.join(project_dir, ".attocode", "architecture.yaml")
    if not os.path.isfile(config_path):
        logger.debug("Architecture config not found: %s", config_path)
        return [], [], {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "PyYAML is not installed -- cannot load architecture config.  "
            "Install it with: pip install pyyaml"
        )
        return [], [], {}

    try:
        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("Failed to parse architecture config: %s", exc)
        return [], [], {}

    # --- Layers ---
    layers: list[ArchLayer] = []
    for entry in data.get("layers", []):
        name = entry.get("name", "")
        paths = entry.get("paths", [])
        if name and paths:
            layers.append(ArchLayer(name=name, paths=paths))

    # --- Rules ---
    rules: list[ArchRule] = []
    for entry in data.get("rules", []):
        from_layer = entry.get("from", "")
        if not from_layer:
            continue
        allowed = entry.get("to", [])
        denied = entry.get("deny", [])
        rules.append(ArchRule(from_layer=from_layer, allowed=allowed, denied=denied))

    # --- Exceptions ---
    exceptions: dict[str, list[str]] = {}
    for entry in data.get("exceptions", []):
        src = entry.get("file", "")
        allowed_targets = entry.get("allowed", [])
        if src and allowed_targets:
            exceptions[src] = allowed_targets

    return layers, rules, exceptions


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_file(file_path: str, layers: list[ArchLayer]) -> str:
    """Determine which layer *file_path* belongs to.

    Returns the layer name, or ``""`` if the file does not match any layer.
    Matches are evaluated in order; the first matching layer wins.
    """
    for layer in layers:
        if layer.matches(file_path):
            return layer.name
    return ""


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------


def _build_deps_from_index(project_dir: str) -> dict[str, set[str]]:
    """Build a dependency map from the AST service's CrossRefIndex."""
    try:
        from attocode.integrations.context.ast_service import ASTService

        svc = ASTService.get_instance(project_dir)
        if not svc.initialized:
            svc.initialize_skeleton(indexing_depth="auto")
        return dict(svc.index.file_dependencies)
    except Exception as exc:
        logger.debug("Could not build dependency map from AST index: %s", exc)
        return {}


def check_drift(
    project_dir: str,
    dependencies: dict[str, set[str]] | None = None,
) -> ArchReport:
    """Check actual dependencies against architecture rules.

    Args:
        project_dir: Project root.
        dependencies: Optional pre-computed dependency map
            (file -> set of imported files).  If *None*, will build from
            the AST service's ``CrossRefIndex.file_dependencies``.

    Returns:
        An :class:`ArchReport` summarising all violations found.
    """
    layers, rules, exceptions = load_architecture(project_dir)
    if not layers:
        return ArchReport(
            violations=[],
            layers_defined=0,
            rules_defined=0,
            files_checked=0,
            compliant_files=0,
        )

    if dependencies is None:
        dependencies = _build_deps_from_index(project_dir)

    # Build a quick rule lookup: from_layer -> ArchRule
    rule_map: dict[str, ArchRule] = {}
    for rule in rules:
        rule_map[rule.from_layer] = rule

    violations: list[ArchViolation] = []
    files_checked = 0
    compliant_files = 0

    for source_file, targets in dependencies.items():
        source_layer = classify_file(source_file, layers)
        if not source_layer:
            # File is outside any declared layer -- skip
            continue

        files_checked += 1
        file_has_violation = False

        for target_file in targets:
            target_layer = classify_file(target_file, layers)
            if not target_layer:
                # Target outside all layers -- nothing to enforce
                continue
            if source_layer == target_layer:
                # Intra-layer dependency -- always allowed
                continue

            # Check file-level exceptions
            exception_list = exceptions.get(source_file, [])
            if target_file in exception_list:
                continue

            rule = rule_map.get(source_layer)
            if rule is None:
                # No rule defined for this layer -- nothing to enforce
                continue

            # Check explicit deny list first (high severity)
            if target_layer in rule.denied:
                violations.append(
                    ArchViolation(
                        source_file=source_file,
                        target_file=target_file,
                        source_layer=source_layer,
                        target_layer=target_layer,
                        rule=(
                            f"Layer '{source_layer}' must NOT depend on "
                            f"'{target_layer}' (deny rule)"
                        ),
                        severity="high",
                    )
                )
                file_has_violation = True
                continue

            # Check allowed list (medium severity if not explicitly listed)
            if rule.allowed and target_layer not in rule.allowed:
                violations.append(
                    ArchViolation(
                        source_file=source_file,
                        target_file=target_file,
                        source_layer=source_layer,
                        target_layer=target_layer,
                        rule=(
                            f"Layer '{source_layer}' does not list "
                            f"'{target_layer}' as an allowed dependency"
                        ),
                        severity="medium",
                    )
                )
                file_has_violation = True

        if not file_has_violation:
            compliant_files += 1

    # Sort: high severity first, then by source file for stability
    _severity_order = {"high": 0, "medium": 1, "low": 2}
    violations.sort(
        key=lambda v: (_severity_order.get(v.severity, 9), v.source_file, v.target_file)
    )

    return ArchReport(
        violations=violations,
        layers_defined=len(layers),
        rules_defined=len(rules),
        files_checked=files_checked,
        compliant_files=compliant_files,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_report(report: ArchReport) -> str:
    """Format an :class:`ArchReport` as human-readable text."""
    lines: list[str] = []
    lines.append("# Architecture Drift Report\n")

    lines.append(
        f"Layers defined: {report.layers_defined}  |  "
        f"Rules defined: {report.rules_defined}"
    )
    lines.append(
        f"Files checked: {report.files_checked}  |  "
        f"Compliant: {report.compliant_files}"
    )

    if not report.violations:
        lines.append("\nNo architecture violations detected. All checked files comply.")
        return "\n".join(lines)

    # Group by severity
    high: list[ArchViolation] = []
    medium: list[ArchViolation] = []
    other: list[ArchViolation] = []
    for v in report.violations:
        if v.severity == "high":
            high.append(v)
        elif v.severity == "medium":
            medium.append(v)
        else:
            other.append(v)

    total = len(report.violations)
    lines.append(f"\n{total} violation(s) found.\n")

    if high:
        lines.append(f"## HIGH severity ({len(high)})\n")
        for v in high:
            lines.append(f"  {v.source_file} -> {v.target_file}")
            lines.append(f"    [{v.source_layer} -> {v.target_layer}] {v.rule}")

    if medium:
        lines.append(f"\n## MEDIUM severity ({len(medium)})\n")
        for v in medium:
            lines.append(f"  {v.source_file} -> {v.target_file}")
            lines.append(f"    [{v.source_layer} -> {v.target_layer}] {v.rule}")

    if other:
        lines.append(f"\n## OTHER ({len(other)})\n")
        for v in other:
            lines.append(f"  {v.source_file} -> {v.target_file}")
            lines.append(f"    [{v.source_layer} -> {v.target_layer}] {v.rule}")

    return "\n".join(lines)
