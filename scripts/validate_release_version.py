#!/usr/bin/env python3
"""Validate that release metadata matches the expected tag."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

_VERSION_PATTERN = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def normalize_expected_tag(tag: str) -> str:
    """Convert a git tag/ref into the package version string."""
    normalized = tag.strip()
    if normalized.startswith("refs/tags/"):
        normalized = normalized[len("refs/tags/"):]
    if normalized.startswith("v"):
        normalized = normalized[1:]
    return normalized


def _read_dunder_version(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = _VERSION_PATTERN.search(content)
    if match is None:
        raise ValueError(f"Could not find __version__ in {path}")
    return match.group(1)


def collect_versions(repo_root: Path) -> dict[str, str]:
    """Collect all repo-managed version strings."""
    pyproject_path = repo_root / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project_version = pyproject["project"]["version"]
    bumpversion = pyproject.get("tool", {}).get("bumpversion", {})
    bumpversion_version = bumpversion["current_version"]

    return {
        "pyproject.project.version": project_version,
        "pyproject.bumpversion.current_version": bumpversion_version,
        "src.attocode.__version__": _read_dunder_version(
            repo_root / "src" / "attocode" / "__init__.py"
        ),
        "src.attoswarm.__version__": _read_dunder_version(
            repo_root / "src" / "attoswarm" / "__init__.py"
        ),
    }


def validate_versions(
    versions: dict[str, str],
    *,
    expected_tag: str | None = None,
) -> list[str]:
    """Return validation errors for release metadata mismatches."""
    errors: list[str] = []
    distinct_versions = sorted(set(versions.values()))

    if len(distinct_versions) != 1:
        errors.append(
            "Version sources disagree: "
            + ", ".join(f"{source}={value}" for source, value in versions.items())
        )

    if expected_tag:
        expected_version = normalize_expected_tag(expected_tag)
        mismatches = [
            f"{source}={value}"
            for source, value in versions.items()
            if value != expected_version
        ]
        if mismatches:
            errors.append(
                f"Expected tag {expected_tag!r} to resolve to version "
                f"{expected_version!r}, but found: {', '.join(mismatches)}"
            )

    return errors


def _format_report(versions: dict[str, str], errors: list[str]) -> str:
    lines = ["Release version report:", ""]
    width = max(len(source) for source in versions)
    for source, value in versions.items():
        lines.append(f"  {source.ljust(width)} : {value}")

    if errors:
        lines.extend(["", "Validation failed:"])
        lines.extend(f"  - {error}" for error in errors)
    else:
        lines.extend(["", "Validation passed."])

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that repo version files match an expected release tag."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to validate (default: current directory).",
    )
    parser.add_argument(
        "--expected-tag",
        default=None,
        help="Optional git tag or ref, e.g. v0.2.17 or refs/tags/v0.2.17.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    versions = collect_versions(repo_root)
    errors = validate_versions(versions, expected_tag=args.expected_tag)
    print(_format_report(versions, errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
