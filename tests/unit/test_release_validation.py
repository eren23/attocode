from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "validate_release_version.py"
    )
    spec = importlib.util.spec_from_file_location("validate_release_version", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_release_files(root: Path, version: str, *, bumpversion_version: str | None = None) -> None:
    (root / "src" / "attocode").mkdir(parents=True)
    (root / "src" / "attoswarm").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                f'version = "{version}"',
                "",
                "[tool.bumpversion]",
                f'current_version = "{bumpversion_version or version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "src" / "attocode" / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "attoswarm" / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )


def test_collect_versions_reads_all_sources(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_files(tmp_path, "1.2.3")

    versions = module.collect_versions(tmp_path)

    assert versions == {
        "pyproject.project.version": "1.2.3",
        "pyproject.bumpversion.current_version": "1.2.3",
        "src.attocode.__version__": "1.2.3",
        "src.attoswarm.__version__": "1.2.3",
    }


def test_validate_versions_accepts_matching_tag(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_files(tmp_path, "0.2.17")

    versions = module.collect_versions(tmp_path)
    errors = module.validate_versions(versions, expected_tag="refs/tags/v0.2.17")

    assert errors == []


def test_validate_versions_detects_v0217_release_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_files(tmp_path, "0.2.16")

    versions = module.collect_versions(tmp_path)
    errors = module.validate_versions(versions, expected_tag="v0.2.17")

    assert len(errors) == 1
    assert "v0.2.17" in errors[0]
    assert "0.2.16" in errors[0]


def test_validate_versions_detects_internal_disagreement(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_files(tmp_path, "0.2.17", bumpversion_version="0.2.16")

    versions = module.collect_versions(tmp_path)
    errors = module.validate_versions(versions)

    assert len(errors) == 1
    assert "Version sources disagree" in errors[0]
