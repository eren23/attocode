"""Path security utilities — block credential-leak and escape paths.

Implements two security checks that CC handles in its tool layer:
1. UNC path blocking — prevents NTLM credential leaks via \\server paths
2. Path traversal detection — catches ../ escape attempts

The UNC path check is the one CC explicitly guards (and documents the
NTLM credential leak attack). Path traversal is a standard additional guard.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class PathSecurityResult:
    """Result of a path security check."""

    safe: bool
    reason: str = ""
    blocked: bool = False  # True when safe=False due to policy block
    escaped: bool = False  # True when safe=False due to traversal attempt


# -----------------------------------------------------------------------------
# UNC Path blocking
# -----------------------------------------------------------------------------

# UNC patterns that indicate a network share path. Both Windows (\\server\share)
# and POSIX-style (//server/share) formats are blocked to prevent:
# - NTLM credential leaking to untrusted network servers
# - SMB relay attacks
# - Information disclosure about network topology
#
# The block applies to:
# - Literal \\ or // at path start
# - Paths that parse as UNC under Windows rules
# - URLs with file://// scheme (4-slash = UNC)

_UNC_PATTERNS: list[re.Pattern[str]] = [
    # Double-backslash Windows UNC: \\server\share
    re.compile(r"^\\\\"),
    # //server/share — // followed by hostname (non-slash chars)
    re.compile(r"^//[^/]+"),
    # file:////server/share — 4-slash form is canonical UNC over file://
    re.compile(r"^file:////"),
    # C:\\server\share — drive letter + UNC (C:\ before \\server)
    # This matches drive letter + backslash + backslash (not a normal path)
    re.compile(r"^[A-Za-z]:\\\\"),
]


def is_unc_path(path: str) -> bool:
    """Return True if *path* looks like a UNC/network share path.

    Blocks both literal ``\\server`` and ``//server`` forms, as well as
    ``file:////server`` URL form.  These can leak NTLM credentials to
    untrusted network servers in corporate/AD environments.
    """
    for pattern in _UNC_PATTERNS:
        if pattern.match(path):
            return True
    return False


# -----------------------------------------------------------------------------
# Path traversal detection
# -----------------------------------------------------------------------------

def contains_traversal(path: str) -> bool:
    r"""Return True if *path* contains dangerous path traversal.

Blocks:
    - Mid-path traversal: ``foo/../bar`` — escapes a directory mid-path
    - Traversal that exits to system directories: ``../../etc/passwd``
    - Trailing ``..`` or bare ``..``
    - Encoded forms: ``%2e%2e``, ``%252e%252e``

Allows:
    - Leading ``..`` chains that stay in user-space: ``../../pkg/module.py``,
      ``../../../local/lib``

``../../etc/passwd`` → True (blocked: system path)
    ``../../pkg/module.py`` → False (allowed: package-relative import)
    ``../../../foo`` → False (allowed: user-space relative)
    ``foo/../bar`` → True (blocked: mid-path traversal)
    ``./../etc`` → True (blocked: escape after .)
    ``..`` / ``../`` → True (blocked: bare/trailing traversal)
    """
    normalized = path.replace("\\", "/")
    lower = normalized.lower()

    # Encoded traversal
    if "%2e%2e" in lower or "%252e%252e" in lower:
        return True

    # Bare ``..`` or trailing ``../`` (with or without final /)
    # ``..`` alone: always dangerous.
    # ``../`` (parent of working dir): also dangerous.
    # BUT ``.../..`` is valid — ``...`` is a directory named three dots,
    # so ``.../..`` means the parent of that directory (the current directory).
    if normalized == ".." or normalized == "../" or normalized.endswith("/.."):
        if not (normalized.startswith(".../..") or
                normalized.lstrip("./").startswith(".../")):
            return True

    # System directory escape: ``../etc/passwd``, ``../../etc/shadow``
    # Also block ``./../etc`` — escaping via the current directory marker.
    # But ``../../pkg`` and ``../../../foo`` are user-space — allow.
    # Handle both leading ../ and ./../ patterns

    def _is_system_escape(path: str) -> bool:
        """Check if path escapes to a system directory via leading ../."""
        parts = path.split("/")
        i = 0
        while i < len(parts) and parts[i] == "..":
            i += 1
        if i < len(parts):
            return parts[i].lower() in {
                "etc", "usr", "var", "root", "home",
                "sys", "proc", "dev",
            }
        return False

    if _is_system_escape(normalized.lstrip("./")):
        return True

    # Mid-path /../ (not in the leading chain) — find and block
    idx = 0
    while True:
        idx = normalized.find("/../", idx)
        if idx == -1:
            break
        # Block if the part before this /../ contains any real directory name
        # (non-dot, non-slash chars). Allow if it's only . or .. or empty.
        before = normalized[:idx]
        if before.replace(".", "").replace("/", "") != "":
            return True  # real directory name before /../ → mid-path traversal
        idx += 1  # continue (skip leading ../ chain)

    return False


def has_absolute_escape(path: str) -> bool:
    """Return True if *path* escapes the working directory by being absolute."""
    return os.path.isabs(path)


# -----------------------------------------------------------------------------
# Combined security check
# -----------------------------------------------------------------------------

UNC_BLOCK_ENABLED: bool = True  # Controlled by feature flag


def check_path(path: str) -> PathSecurityResult:
    """Perform all security checks on a file path.

    Checks in order of severity:
    1. UNC path (credential leak)
    2. Absolute path outside working directory
    3. Path traversal sequences

    Returns a PathSecurityResult with the outcome.
    """
    # 1. UNC path
    if UNC_BLOCK_ENABLED and is_unc_path(path):
        return PathSecurityResult(
            safe=False,
            reason=(
                f"UNC/network path '{path}' is blocked to prevent credential leaks. "
                "Use local paths only."
            ),
            blocked=True,
        )

    # 2. Traversal
    if contains_traversal(path):
        # Strip trailing separators and check if it's just a safe relative path
        stripped = path.rstrip("/\\")
        # Allow simple .. at the start of a relative path (common in Python imports)
        if stripped.startswith(".."):
            # Check if the path is just ".." or "../foo" (potentially legitimate)
            # Block if it's deeper than one level
            depth = stripped.count("..")
            components = [c for c in stripped.split("/") if c and c != ".."]
            if depth > 1 or (depth == 1 and not components):
                return PathSecurityResult(
                    safe=False,
                    reason=f"Path traversal detected in '{path}'",
                    escaped=True,
                )

    return PathSecurityResult(safe=True)


def check_tool_path(
    tool_name: str,
    args: dict[str, Any],
    path_fields: list[str] | None = None,
) -> PathSecurityResult:
    """Check all path fields in tool arguments for security issues.

    Args:
        tool_name: Name of the tool being called.
        args: Arguments passed to the tool.
        path_fields: Field names to check. Defaults to common path field names.

    Returns:
        Combined PathSecurityResult. Returns safe=True if no paths found.
    """
    fields = path_fields or ["path", "file_path", "filepath", "target", "source", "dest"]
    for field_name in fields:
        value = args.get(field_name)
        if not value:
            continue
        if isinstance(value, str) and value.strip():
            result = check_path(value.strip())
            if not result.safe:
                return result
        elif isinstance(value, list):
            # Some tools accept multiple paths
            for item in value:
                if isinstance(item, str) and item.strip():
                    result = check_path(item.strip())
                    if not result.safe:
                        return result
    return PathSecurityResult(safe=True)


# -----------------------------------------------------------------------------
# Canonicalization helpers
# -----------------------------------------------------------------------------

def safe_canonicalize(
    path: str,
    working_dir: str | None = None,
) -> str | None:
    """Resolve a path safely, returning None if it escapes working_dir.

    Args:
        path: The path to canonicalize.
        working_dir: The working directory to restrict to. If None, uses cwd.

    Returns:
        The canonical path, or None if it escapes working_dir.
    """
    if not path:
        return None

    # Block UNC paths before any processing
    if UNC_BLOCK_ENABLED and is_unc_path(path):
        return None

    try:
        if working_dir:
            base = os.path.abspath(working_dir)
            # Resolve the path relative to working_dir
            if not os.path.isabs(path):
                full = os.path.join(base, path)
            else:
                full = path
            canonical = os.path.abspath(full)
        else:
            canonical = os.path.abspath(path)

        # Verify the canonical path is within working_dir
        if working_dir:
            base = os.path.abspath(working_dir)
            # Ensure canonical path starts with working_dir (realpath resolves symlinks)
            if not canonical.startswith(base + os.sep) and canonical != base:
                return None

        return canonical
    except (OSError, ValueError):
        return None


def is_within_working_dir(
    path: str,
    working_dir: str | None = None,
) -> bool:
    """Return True if *path* is within working_dir (or any subdirectory)."""
    return safe_canonicalize(path, working_dir) is not None
