"""Community rule pack importer.

Generates the legal scaffold (LICENSE + NOTICE + manifest) for a hand-ported
community pack so the porting work starts in a license-compliant state.

Supported sources (all permissive licenses — no copyleft entanglement):

- ``bandit``  — Python security scanner, Apache-2.0
- ``gosec``   — Go security scanner, Apache-2.0
- ``eslint``  — JS/TS linter core rules, MIT

Each source has a hand-curated list of high-value rule IDs that translate
cleanly to attocode regex patterns. The importer drops a ``PORTING.md``
checklist into the output dir; humans then write the actual YAML rules
under ``rules/`` (each with the attribution comment header).

We intentionally do NOT import semgrep-rules: semgrep ships under
LGPL-2.1, and its copyleft semantics aren't worth the friction relative
to the rule yield from pure-permissive sources.

Usage::

    python -m eval.rule_harness.import_pack \\
        --source bandit --lang python \\
        --output src/attocode/code_intel/rules/packs/community/bandit-python
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# License templates ship under packs/community/_license_templates/
LICENSE_TEMPLATE_DIR = (
    _PROJECT_ROOT
    / "src" / "attocode" / "code_intel" / "rules" / "packs"
    / "community" / "_license_templates"
)

# SPDX → license text filename. Only permissive licenses are bundled.
LICENSE_FILES = {
    "Apache-2.0": "Apache-2.0.txt",
    "MIT": "MIT.txt",
}


# Per-source defaults: URL, license, attribution boilerplate, porting targets.
# Each porting target is a short ID + human-readable name; the importer
# emits these into PORTING.md so the human porter knows what to write.
SOURCES: dict[str, dict] = {
    "bandit": {
        "url": "https://github.com/PyCQA/bandit",
        "license": "Apache-2.0",
        "attribution": (
            "Rule patterns adapted from Bandit (https://github.com/PyCQA/bandit). "
            "Original copyright PyCQA. Licensed under Apache-2.0."
        ),
        "default_language": "python",
        "porting_targets": [
            "B105 hardcoded_password_string",
            "B303 weak_md5_hash",
            "B304 weak_des_cipher",
            "B306 mktemp_temp_dir",
            "B307 use_of_eval",
            "B321 ftp_lib_used",
            "B324 weak_sha1_hash",
            "B501 request_with_no_cert_validation",
            "B602 subprocess_with_shell_true",
            "B608 hardcoded_sql_expressions",
        ],
    },
    "gosec": {
        "url": "https://github.com/securego/gosec",
        "license": "Apache-2.0",
        "attribution": (
            "Rule patterns adapted from gosec (https://github.com/securego/gosec). "
            "Original copyright securego authors. Licensed under Apache-2.0."
        ),
        "default_language": "go",
        "porting_targets": [
            "G101 hardcoded_credentials",
            "G102 bind_to_all_interfaces",
            "G103 unsafe_block",
            "G201 sql_format_string",
            "G203 unescaped_template_data",
            "G304 file_path_inclusion",
            "G401 weak_des_or_rc4_crypto",
            "G402 tls_min_version",
            "G501 weak_md5_hash",
            "G505 weak_sha1_hash",
        ],
    },
    "eslint": {
        "url": "https://github.com/eslint/eslint",
        "license": "MIT",
        "attribution": (
            "Rule patterns adapted from ESLint core rules "
            "(https://github.com/eslint/eslint). Original copyright OpenJS "
            "Foundation and contributors. Licensed under MIT."
        ),
        "default_language": "typescript",
        "porting_targets": [
            "no-eval",
            "no-implied-eval",
            "no-new-func",
            "no-script-url",
            "no-return-await",
            "no-var",
            "prefer-const",
            "eqeqeq",
            "no-with",
            "no-throw-literal",
        ],
    },
}


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_license(output_dir: Path, license_id: str) -> bool:
    """Copy the bundled license template into the output dir."""
    template_name = LICENSE_FILES.get(license_id)
    if not template_name:
        logger.warning("No bundled template for license %s", license_id)
        return False
    src = LICENSE_TEMPLATE_DIR / template_name
    if not src.is_file():
        logger.warning("License template missing: %s", src)
        return False
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, output_dir / "LICENSE")
    return True


def write_notice(
    output_dir: Path,
    *,
    pack_name: str,
    source_url: str,
    source_commit: str,
    license_id: str,
    attribution: str,
) -> None:
    """Write a NOTICE file with attribution + provenance."""
    output_dir.mkdir(parents=True, exist_ok=True)
    notice = (
        f"# NOTICE — {pack_name}\n\n"
        f"{attribution}\n\n"
        f"Upstream: {source_url}\n"
        f"Commit:   {source_commit or '(unspecified)'}\n"
        f"License:  {license_id}\n\n"
        f"Modifications:\n"
        f"- Translated rule patterns to attocode UnifiedRule schema\n"
        f"- Subset selection (high-value rules first)\n\n"
        f"See LICENSE for full license terms.\n"
    )
    (output_dir / "NOTICE").write_text(notice, encoding="utf-8")


def write_manifest(
    output_dir: Path,
    *,
    pack_name: str,
    languages: list[str],
    description: str,
    source_url: str,
    source_commit: str,
    source_license: str,
    attribution: str,
    upstream_count: int,
    imported_count: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": pack_name,
        "version": "1.0.0",
        "languages": languages,
        "description": description,
        "source": "community",
        "source_url": source_url,
        "source_commit": source_commit,
        "source_license": source_license,
        "attribution": attribution,
        "imported_at": _now_iso(),
        "upstream_rule_count": upstream_count,
        "imported_rule_count": imported_count,
    }
    (output_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8",
    )


def write_porting_md(
    output_dir: Path,
    *,
    pack_name: str,
    source: str,
    source_url: str,
    porting_targets: list[str],
) -> None:
    """Write the human porting checklist."""
    body = (
        f"# Porting checklist — {pack_name}\n\n"
        f"Rules from {source} ({source_url}) are not YAML-defined upstream\n"
        f"and require manual porting. Each ported rule MUST include the\n"
        f"attribution comment header at the top of its YAML file:\n\n"
        f"```yaml\n"
        f"# Adapted from {source} rule '<original-id>'\n"
        f"# See ../LICENSE and ../NOTICE for license terms.\n"
        f"```\n\n"
        f"Porting targets:\n\n"
        + "\n".join(f"- [ ] {target}" for target in porting_targets)
        + "\n"
    )
    (output_dir / "PORTING.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Importer driver
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ImportSummary:
    """Result of an import scaffold run."""

    pack_name: str
    output_dir: Path
    source: str
    license: str
    upstream_count: int = 0
    files_written: list[str] = field(default_factory=list)


def scaffold_pack(
    *,
    source: str,
    output_dir: Path,
    pack_name: str,
    language: str,
    commit: str = "",
) -> ImportSummary:
    """Build the legal + manifest + porting shell for a community pack.

    No rules are written — a ``PORTING.md`` checklist is left for a human
    to fill in. The pack ships in a license-compliant state from day one.
    """
    if source not in SOURCES:
        raise ValueError(
            f"Unknown source {source!r}; supported: {sorted(SOURCES)}"
        )
    defaults = SOURCES[source]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rules").mkdir(parents=True, exist_ok=True)

    summary = ImportSummary(
        pack_name=pack_name,
        output_dir=output_dir,
        source=source,
        license=defaults["license"],
        upstream_count=len(defaults["porting_targets"]),
    )

    if write_license(output_dir, defaults["license"]):
        summary.files_written.append("LICENSE")

    write_manifest(
        output_dir,
        pack_name=pack_name,
        languages=[language],
        description=(
            f"Hand-ported subset of {source} rules. "
            f"See PORTING.md for the porting checklist."
        ),
        source_url=defaults["url"],
        source_commit=commit,
        source_license=defaults["license"],
        attribution=defaults["attribution"],
        upstream_count=len(defaults["porting_targets"]),
        imported_count=0,
    )
    summary.files_written.append("manifest.yaml")

    write_notice(
        output_dir,
        pack_name=pack_name,
        source_url=defaults["url"],
        source_commit=commit,
        license_id=defaults["license"],
        attribution=defaults["attribution"],
    )
    summary.files_written.append("NOTICE")

    write_porting_md(
        output_dir,
        pack_name=pack_name,
        source=source,
        source_url=defaults["url"],
        porting_targets=defaults["porting_targets"],
    )
    summary.files_written.append("PORTING.md")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="eval.rule_harness.import_pack",
        description=(
            "Scaffold a community rule pack with proper license attribution. "
            "Ports are then written by hand into rules/."
        ),
    )
    parser.add_argument("--source", required=True, choices=list(SOURCES))
    parser.add_argument("--lang", default="",
                        help="Target language (defaults per source)")
    parser.add_argument("--output", required=True,
                        help="Output dir under packs/community/")
    parser.add_argument("--pack-name", default="",
                        help="Pack name (default: derived from --output)")
    parser.add_argument("--commit", default="",
                        help="Source commit SHA (recorded in NOTICE/manifest)")
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    pack_name = args.pack_name or output_dir.name
    language = args.lang or SOURCES[args.source]["default_language"]

    summary = scaffold_pack(
        source=args.source,
        output_dir=output_dir,
        pack_name=pack_name,
        language=language,
        commit=args.commit,
    )

    print(f"Pack: {summary.pack_name}")
    print(f"  Source:  {summary.source} ({summary.license})")
    print(f"  Output:  {summary.output_dir}")
    print(f"  Upstream targets: {summary.upstream_count}")
    print(f"  Files written:    {', '.join(summary.files_written)}")
    print(f"\nNext: hand-port rules listed in {summary.output_dir / 'PORTING.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
