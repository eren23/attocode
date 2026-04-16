"""Unit tests for ``scripts/check_pack_licenses.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

# Path-import the script (it lives outside any package)
import importlib.util
import sys


def _import_script() -> object:
    project_root = Path(__file__).parents[3]
    script_path = project_root / "scripts" / "check_pack_licenses.py"
    spec = importlib.util.spec_from_file_location("check_pack_licenses", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pack_licenses"] = module
    spec.loader.exec_module(module)
    return module


cpl = _import_script()


def _write_pack(
    root: Path,
    name: str,
    *,
    license_text: str = "Apache License Version 2.0\n" * 20,
    notice_text: str = "NOTICE text",
    manifest: dict | None = None,
) -> Path:
    """Build a synthetic pack dir with the optional pieces written."""
    import yaml as _yaml

    pack = root / name
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "LICENSE").write_text(license_text, encoding="utf-8")
    (pack / "NOTICE").write_text(notice_text, encoding="utf-8")
    if manifest is None:
        manifest = {
            "name": name,
            "source": "community",
            "source_license": "Apache-2.0",
            "attribution": "test attribution",
        }
    (pack / "manifest.yaml").write_text(
        _yaml.safe_dump(manifest), encoding="utf-8",
    )
    return pack


class TestCheckPack:
    def test_complete_pack_passes(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, "good-pack")
        assert cpl.check_pack(pack) == []

    def test_missing_license_caught(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, "bad")
        (pack / "LICENSE").unlink()
        errors = cpl.check_pack(pack)
        assert any("LICENSE" in e for e in errors)

    def test_missing_notice_caught(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, "bad")
        (pack / "NOTICE").unlink()
        errors = cpl.check_pack(pack)
        assert any("NOTICE" in e for e in errors)

    def test_missing_manifest_caught(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, "bad")
        (pack / "manifest.yaml").unlink()
        errors = cpl.check_pack(pack)
        assert any("manifest.yaml" in e for e in errors)

    def test_unknown_license_caught(self, tmp_path: Path) -> None:
        pack = _write_pack(
            tmp_path, "bad",
            manifest={
                "name": "bad",
                "source": "community",
                "source_license": "GPL-3.0",
                "attribution": "x",
            },
        )
        errors = cpl.check_pack(pack)
        assert any("not in allowlist" in e for e in errors)

    def test_missing_required_field_caught(self, tmp_path: Path) -> None:
        pack = _write_pack(
            tmp_path, "bad",
            manifest={"name": "bad", "source_license": "MIT"},  # missing attribution
        )
        errors = cpl.check_pack(pack)
        assert any("attribution" in e for e in errors)

    def test_truncated_license_flagged(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, "thin", license_text="MIT")
        errors = cpl.check_pack(pack)
        assert any("truncated" in e for e in errors)


class TestDiscoverPacks:
    def test_skips_underscore_prefixed_dirs(self, tmp_path: Path) -> None:
        _write_pack(tmp_path, "real-pack")
        (tmp_path / "_internal").mkdir()
        (tmp_path / "_internal" / "manifest.yaml").write_text("name: _internal\n")
        packs = cpl.discover_packs(tmp_path)
        names = {p.name for p in packs}
        assert "real-pack" in names
        assert "_internal" not in names

    def test_handles_missing_dir(self, tmp_path: Path) -> None:
        assert cpl.discover_packs(tmp_path / "nope") == []


class TestIntegration:
    def test_real_community_packs_compliant(self) -> None:
        # The repo's actual community packs must all pass — guards against
        # someone landing a pack without LICENSE/NOTICE.
        packs = cpl.discover_packs()
        assert packs, "No community packs found in real repo"
        for pack in packs:
            errs = cpl.check_pack(pack)
            assert errs == [], f"{pack.name} has issues: {errs}"
