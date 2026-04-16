"""Unit tests for ``eval.rule_harness.import_pack``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eval.rule_harness.import_pack import (
    LICENSE_FILES,
    LICENSE_TEMPLATE_DIR,
    SOURCES,
    scaffold_pack,
    write_license,
    write_manifest,
    write_notice,
    write_porting_md,
)


class TestSources:
    def test_sources_are_permissive_only(self) -> None:
        # No copyleft licenses — keeps redistribution simple.
        for source, defaults in SOURCES.items():
            assert defaults["license"] in {"Apache-2.0", "MIT"}, (
                f"{source} declares non-permissive license {defaults['license']!r}"
            )

    def test_each_source_has_porting_targets(self) -> None:
        for source, defaults in SOURCES.items():
            assert len(defaults["porting_targets"]) >= 5, (
                f"{source} has too few porting targets to be useful"
            )

    def test_all_license_templates_exist(self) -> None:
        for license_id in {d["license"] for d in SOURCES.values()}:
            template = LICENSE_TEMPLATE_DIR / LICENSE_FILES[license_id]
            assert template.is_file(), f"Missing license template: {template}"


class TestWriteLicense:
    def test_writes_apache(self, tmp_path: Path) -> None:
        ok = write_license(tmp_path, "Apache-2.0")
        assert ok is True
        license_file = tmp_path / "LICENSE"
        assert license_file.is_file()
        content = license_file.read_text(encoding="utf-8")
        assert "Apache License" in content

    def test_writes_mit(self, tmp_path: Path) -> None:
        ok = write_license(tmp_path, "MIT")
        assert ok is True
        content = (tmp_path / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in content

    def test_unknown_license_returns_false(self, tmp_path: Path) -> None:
        assert write_license(tmp_path, "GPL-3.0") is False
        assert not (tmp_path / "LICENSE").exists()


class TestWriteNotice:
    def test_notice_includes_attribution(self, tmp_path: Path) -> None:
        write_notice(
            tmp_path,
            pack_name="bandit-python",
            source_url="https://github.com/PyCQA/bandit",
            source_commit="abc123",
            license_id="Apache-2.0",
            attribution="Adapted from Bandit. Copyright PyCQA.",
        )
        text = (tmp_path / "NOTICE").read_text(encoding="utf-8")
        assert "bandit-python" in text
        assert "Adapted from Bandit" in text
        assert "abc123" in text
        assert "Apache-2.0" in text


class TestWriteManifest:
    def test_manifest_round_trip(self, tmp_path: Path) -> None:
        write_manifest(
            tmp_path,
            pack_name="bandit-python",
            languages=["python"],
            description="hand-port",
            source_url="https://github.com/PyCQA/bandit",
            source_commit="abc",
            source_license="Apache-2.0",
            attribution="Bandit attribution",
            upstream_count=10,
            imported_count=0,
        )
        manifest = yaml.safe_load((tmp_path / "manifest.yaml").read_text())
        assert manifest["name"] == "bandit-python"
        assert manifest["languages"] == ["python"]
        assert manifest["source"] == "community"
        assert manifest["source_license"] == "Apache-2.0"
        assert manifest["upstream_rule_count"] == 10
        assert manifest["imported_rule_count"] == 0
        assert "imported_at" in manifest


class TestWritePortingMd:
    def test_lists_targets_as_checklist(self, tmp_path: Path) -> None:
        write_porting_md(
            tmp_path,
            pack_name="bandit-python",
            source="bandit",
            source_url="https://github.com/PyCQA/bandit",
            porting_targets=["B105 hardcoded_password", "B602 subprocess"],
        )
        text = (tmp_path / "PORTING.md").read_text(encoding="utf-8")
        assert "B105 hardcoded_password" in text
        assert "B602 subprocess" in text
        assert "- [ ]" in text  # checkbox format
        assert "attribution comment header" in text


class TestScaffoldPack:
    def test_scaffolds_bandit(self, tmp_path: Path) -> None:
        output = tmp_path / "bandit-python"
        summary = scaffold_pack(
            source="bandit",
            output_dir=output,
            pack_name="bandit-python",
            language="python",
            commit="deadbeef",
        )
        assert summary.source == "bandit"
        assert summary.license == "Apache-2.0"
        assert summary.upstream_count == 10
        assert (output / "LICENSE").is_file()
        assert (output / "NOTICE").is_file()
        assert (output / "manifest.yaml").is_file()
        assert (output / "PORTING.md").is_file()
        assert (output / "rules").is_dir()  # empty dir for human porting

    def test_scaffolds_gosec(self, tmp_path: Path) -> None:
        output = tmp_path / "gosec-go"
        summary = scaffold_pack(
            source="gosec",
            output_dir=output,
            pack_name="gosec-go",
            language="go",
        )
        manifest = yaml.safe_load((output / "manifest.yaml").read_text())
        assert manifest["languages"] == ["go"]
        assert manifest["source_license"] == "Apache-2.0"

    def test_scaffolds_eslint(self, tmp_path: Path) -> None:
        output = tmp_path / "eslint-typescript"
        summary = scaffold_pack(
            source="eslint",
            output_dir=output,
            pack_name="eslint-typescript",
            language="typescript",
        )
        assert summary.license == "MIT"
        license_text = (output / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in license_text

    def test_unknown_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown source"):
            scaffold_pack(
                source="rubocop",
                output_dir=tmp_path / "x",
                pack_name="x",
                language="ruby",
            )
