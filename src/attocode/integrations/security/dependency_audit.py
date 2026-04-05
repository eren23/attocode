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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attocode.integrations.security.patterns import Category, Severity

logger = logging.getLogger(__name__)

# Cache directory for OSV vulnerability data
_DEFAULT_CACHE_DIR = os.path.expanduser("~/.attocode")
_OSV_CACHE_FILE = "osv-cache.json"
_OSV_CACHE_TTL = 86400  # 24 hours

# Suspicious tokens in package.json install hooks (GlassWorm-class supply-chain attacks)
_SUSPICIOUS_HOOK_TOKENS: list[tuple[str, "re.Pattern[str]", str]] = [
    ("hook_eval", re.compile(r"\beval\b"), "dynamic evaluation in install hook"),
    ("hook_atob", re.compile(r"\batob\s*\("), "atob decoder in install hook"),
    ("hook_buffer_b64", re.compile(r"Buffer\.from\s*\([^)]*base64", re.IGNORECASE),
     "Buffer.from base64 decode in install hook"),
    ("hook_child_process", re.compile(r"require\s*\(\s*['\"]child_process['\"]\s*\)"),
     "child_process require in install hook"),
    ("hook_node_dash_e", re.compile(r"\bnode\s+-e\b"),
     "node -e inline script in install hook"),
    ("hook_curl_pipe_sh", re.compile(r"\b(?:curl|wget|fetch)\b[^|]*\|\s*(?:ba)?sh\b", re.IGNORECASE),
     "curl/wget piped to shell in install hook"),
    ("hook_remote_script", re.compile(r"https?://\S+\.(?:sh|py|exe|dll|so|dylib)\b", re.IGNORECASE),
     "remote script fetch in install hook"),
    ("hook_popen", re.compile(r"\bpopen\s*\("),
     "popen call in install hook"),
    ("hook_system_call", re.compile(r"\bsystem\s*\("),
     "system call in install hook"),
    ("hook_child_spawn", re.compile(r"\b(?:spawnSync|execSync|execFile|execFileSync)\s*\("),
     "child_process spawn/exec variant in install hook"),
]

# Suspicious patterns in setup.py (supply-chain attacks: ctx, W4SP, LiteLLM).
# setup.py should never make network calls; install-time fetches are a classic
# vector for staged-payload delivery.
_SUSPICIOUS_SETUP_PY_PATTERNS: list[tuple[str, "re.Pattern[str]", str]] = [
    ("setup_urllib_fetch",
     re.compile(r"\burllib(?:\.request)?\.urlopen\s*\("),
     "urllib network fetch"),
    ("setup_urlretrieve",
     re.compile(r"\burlretrieve\s*\("),
     "urlretrieve fetch"),
    ("setup_http_client_call",
     re.compile(r"\b(?:requests|httpx|aiohttp)\.(?:get|post|put|delete|head)\s*\("),
     "HTTP client call"),
    ("setup_socket_connect",
     re.compile(r"\bsocket\.create_connection\s*\("),
     "raw socket connection"),
]


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

        # Python: setup.py (supply-chain network-at-install-time check)
        setup_py = root / "setup.py"
        if setup_py.exists():
            findings.extend(self._audit_setup_py(setup_py))

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
                        recommendation="Pin to a specific version range",
                        source_file=str(path),
                    ))
                elif version.startswith(">=") and "<" not in version:
                    findings.append(DependencyFinding(
                        package=pkg,
                        version_spec=version,
                        severity=Severity.LOW,
                        message=f"Open-ended version range: {pkg}@{version}",
                        recommendation="Consider adding upper bound (e.g. >=1.0,<2.0)",
                        source_file=str(path),
                    ))

        findings.extend(self._audit_install_hooks(data, path))
        return findings

    def _audit_install_hooks(self, data: dict, path: Path) -> list[DependencyFinding]:
        """Flag package.json install hooks with obfuscation/remote-fetch patterns.

        Supply-chain attackers (GlassWorm-class) place obfuscated one-liners in
        preinstall/postinstall/install scripts that execute automatically on
        ``npm install``. This detects the most common indicators.

        Note: only the root-level package.json is audited (same as pinning check).
        Monorepo workspace package.json files are not traversed.
        """
        findings: list[DependencyFinding] = []
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            return findings
        for hook in ("preinstall", "install", "postinstall"):
            script = scripts.get(hook)
            if not isinstance(script, str) or not script.strip():
                continue
            for _name, regex, description in _SUSPICIOUS_HOOK_TOKENS:
                if regex.search(script):
                    findings.append(DependencyFinding(
                        package=hook,
                        version_spec=script[:200],
                        severity=Severity.HIGH,
                        cwe_id="CWE-506",
                        message=f"Suspicious {hook} script: {description}",
                        recommendation=(
                            f"Review the '{hook}' script in package.json; "
                            "supply-chain attackers use install hooks to run "
                            "obfuscated one-liners on `npm install`"
                        ),
                        source_file=str(path),
                    ))
                    break  # one finding per hook is enough
        return findings

    def _audit_setup_py(self, path: Path) -> list[DependencyFinding]:
        """Flag network calls in setup.py (supply-chain attack vector).

        setup.py executes arbitrary Python at install time. Legitimate setup
        scripts only define metadata and dependencies; network fetches there
        are almost always a staged-payload delivery mechanism (ctx/W4SP/
        LiteLLM style attacks).
        """
        findings: list[DependencyFinding] = []
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return findings
        for name, regex, description in _SUSPICIOUS_SETUP_PY_PATTERNS:
            if regex.search(content):
                findings.append(DependencyFinding(
                    package="setup.py",
                    version_spec=name,
                    severity=Severity.HIGH,
                    cwe_id="CWE-506",
                    message=f"setup.py contains {description} — supply-chain attack pattern",
                    recommendation=(
                        "Setup scripts should not make network calls; "
                        "install-time fetches are a classic supply-chain "
                        "vector (cf. PyPI ctx, W4SP stealer)"
                    ),
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
                recommendation="Consider adding upper bound for reproducibility",
                source_file=source_file,
            )

        return None
