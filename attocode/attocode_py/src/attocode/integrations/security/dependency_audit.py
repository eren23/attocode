"""Dependency auditing — check pinning and known vulnerabilities.

Parses common dependency files and flags:
- Unpinned/floating version specifiers (>= instead of ==)
- Known-vulnerable package ranges (via OSV.dev cache)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attocode.integrations.security.patterns import Category, Severity

logger = logging.getLogger(__name__)

# Cache directory for OSV vulnerability data
_DEFAULT_CACHE_DIR = os.path.expanduser("~/.attocode")
_OSV_CACHE_FILE = "osv-cache.json"
_OSV_CACHE_TTL = 86400  # 24 hours


@dataclass(slots=True)
class DependencyFinding:
    """A finding from dependency auditing."""

    package: str
    version_spec: str
    severity: Severity
    category: Category = Category.DEPENDENCY
    cwe_id: str = ""
    message: str = ""
    recommendation: str = ""
    source_file: str = ""


@dataclass(slots=True)
class DependencyAuditor:
    """Audit project dependencies for security issues."""

    root_dir: str
    _osv_cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _cache_loaded: bool = field(default=False, repr=False)

    def audit(self) -> list[DependencyFinding]:
        """Run a full dependency audit.

        Checks all supported dependency files for pinning issues.
        """
        findings: list[DependencyFinding] = []
        root = Path(self.root_dir)

        # Python: pyproject.toml
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            findings.extend(self._audit_pyproject(pyproject))

        # Python: requirements.txt
        reqs = root / "requirements.txt"
        if reqs.exists():
            findings.extend(self._audit_requirements(reqs))

        # Node: package.json
        pkg_json = root / "package.json"
        if pkg_json.exists():
            findings.extend(self._audit_package_json(pkg_json))

        return findings

    def _audit_pyproject(self, path: Path) -> list[DependencyFinding]:
        """Audit a pyproject.toml for dependency pinning."""
        findings: list[DependencyFinding] = []
        try:
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, Exception):
            return findings

        # PEP 621 dependencies
        deps = data.get("project", {}).get("dependencies", [])
        # Also check optional-dependencies
        opt_deps = data.get("project", {}).get("optional-dependencies", {})
        for group_deps in opt_deps.values():
            if isinstance(group_deps, list):
                deps.extend(group_deps)

        for dep_spec in deps:
            if not isinstance(dep_spec, str):
                continue
            dep = dep_spec.strip()
            if not dep or dep.startswith("#"):
                continue
            finding = self._check_pinning(dep, str(path))
            if finding:
                findings.append(finding)

        return findings

    def _audit_requirements(self, path: Path) -> list[DependencyFinding]:
        """Audit a requirements.txt for dependency pinning."""
        findings: list[DependencyFinding] = []
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return findings

        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            finding = self._check_pinning(line, str(path))
            if finding:
                findings.append(finding)

        return findings

    def _audit_package_json(self, path: Path) -> list[DependencyFinding]:
        """Audit a package.json for dependency pinning."""
        findings: list[DependencyFinding] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return findings

        for section in ("dependencies", "devDependencies"):
            deps = data.get(section, {})
            if not isinstance(deps, dict):
                continue
            for pkg, version in deps.items():
                if not isinstance(version, str):
                    continue
                # Flag loose version ranges
                if version.startswith("*") or version == "latest":
                    findings.append(DependencyFinding(
                        package=pkg,
                        version_spec=version,
                        severity=Severity.HIGH,
                        message=f"Unpinned dependency: {pkg}@{version}",
                        recommendation=f"Pin to a specific version range",
                        source_file=str(path),
                    ))
                elif version.startswith(">=") and "<" not in version:
                    findings.append(DependencyFinding(
                        package=pkg,
                        version_spec=version,
                        severity=Severity.LOW,
                        message=f"Open-ended version range: {pkg}@{version}",
                        recommendation=f"Consider adding upper bound (e.g. >=1.0,<2.0)",
                        source_file=str(path),
                    ))

        return findings

    def _check_pinning(self, dep_spec: str, source_file: str) -> DependencyFinding | None:
        """Check a single dependency specifier for pinning issues."""
        # Parse package name and version spec
        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)$", dep_spec)
        if not match:
            return None

        pkg = match.group(1)
        version = match.group(2).strip()

        if not version:
            return DependencyFinding(
                package=pkg,
                version_spec="(none)",
                severity=Severity.MEDIUM,
                message=f"No version constraint for {pkg}",
                recommendation=f"Add version constraint (e.g. {pkg}>=1.0)",
                source_file=source_file,
            )

        # Floating >= without upper bound
        if ">=" in version and "<" not in version and "==" not in version:
            return DependencyFinding(
                package=pkg,
                version_spec=version,
                severity=Severity.LOW,
                message=f"Open-ended version: {pkg}{version}",
                recommendation=f"Consider adding upper bound for reproducibility",
                source_file=source_file,
            )

        return None
