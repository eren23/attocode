"""License compliance check for community rule packs.

Walks ``src/attocode/code_intel/rules/packs/community/`` and verifies each
pack ships with a LICENSE file, NOTICE file, and a manifest declaring an
SPDX license from the allowlist. Exits non-zero on any error so the CI
job fails when a contributor forgets the legal scaffold.

Usage::

    python scripts/check_pack_licenses.py [--strict]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).parents[1]
COMMUNITY_DIR = (
    _PROJECT_ROOT
    / "src" / "attocode" / "code_intel" / "rules" / "packs" / "community"
)

# Permissive licenses only — copyleft sources are NOT shipped here.
ALLOWED_LICENSES = {
    "Apache-2.0",
    "MIT",
    "BSD-3-Clause",
    "BSD-2-Clause",
    "ISC",
}

REQUIRED_FILES = ("LICENSE", "NOTICE", "manifest.yaml")
REQUIRED_MANIFEST_FIELDS = ("name", "source_license", "source", "attribution")


def check_pack(pack_dir: Path) -> list[str]:
    """Return a list of error strings for *pack_dir*. Empty = compliant."""
    errors: list[str] = []
    pack_label = pack_dir.name

    for filename in REQUIRED_FILES:
        if not (pack_dir / filename).is_file():
            errors.append(f"{pack_label}: missing {filename}")

    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return errors  # Already reported above

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"{pack_label}: manifest unreadable ({exc})")
        return errors

    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            errors.append(f"{pack_label}: manifest missing {field!r}")

    license_id = str(manifest.get("source_license") or "")
    if license_id and license_id not in ALLOWED_LICENSES:
        errors.append(
            f"{pack_label}: license {license_id!r} not in allowlist "
            f"({sorted(ALLOWED_LICENSES)})"
        )

    license_file = pack_dir / "LICENSE"
    if license_file.is_file() and license_file.stat().st_size < 200:
        errors.append(
            f"{pack_label}: LICENSE looks truncated "
            f"({license_file.stat().st_size} bytes)"
        )

    return errors


def discover_packs(community_dir: Path = COMMUNITY_DIR) -> list[Path]:
    if not community_dir.is_dir():
        return []
    return [
        p for p in sorted(community_dir.iterdir())
        if p.is_dir() and not p.name.startswith("_")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.check_pack_licenses",
        description="Verify every community pack ships license + attribution",
    )
    parser.add_argument(
        "--community-dir", default=str(COMMUNITY_DIR),
        help="Override the community packs root (default: shipped location)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero even when no packs are found (CI guard)",
    )
    args = parser.parse_args()

    community_dir = Path(args.community_dir)
    packs = discover_packs(community_dir)
    if not packs:
        msg = f"No community packs found under {community_dir}"
        if args.strict:
            print(f"error: {msg}", file=sys.stderr)
            return 1
        print(msg)
        return 0

    all_errors: list[str] = []
    for pack in packs:
        all_errors.extend(check_pack(pack))

    if all_errors:
        print(f"License check FAILED — {len(all_errors)} issue(s):")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print(f"License check OK — {len(packs)} packs verified")
    for pack in packs:
        print(f"  ✓ {pack.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
