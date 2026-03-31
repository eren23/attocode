from __future__ import annotations

from pathlib import Path

from eval.benchmark_3way_catalog import (
    PUBLISHED_20,
    REPOS,
    SLICES,
    clone_repo_if_missing,
    default_repo_roots,
    resolve_repo_path,
)


def test_published_20_slice_is_stable() -> None:
    assert len(PUBLISHED_20) == 20
    assert SLICES["published_20"] == PUBLISHED_20
    assert SLICES["published_20_plus_linux"][-1] == "linux"


def test_default_repo_roots_prefers_env(monkeypatch) -> None:
    custom_root = "/tmp/bench-root"
    monkeypatch.setenv("BENCHMARK_REPOS_DIR", custom_root)

    roots = default_repo_roots(["/tmp/bench-root", "/tmp/other-root"])
    assert roots[0] == Path(custom_root).resolve()
    assert roots[1] == Path("/tmp/other-root").resolve()


def test_resolve_repo_path_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("eval.benchmark_3way_catalog.PROJECT_ROOT", tmp_path)
    resolved = resolve_repo_path("attocode", REPOS["attocode"], [tmp_path / "unused"])
    assert resolved == tmp_path


def test_resolve_repo_path_searches_roots(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos"
    repo_path = repo_root / "fastapi"
    repo_path.mkdir(parents=True)

    resolved = resolve_repo_path("fastapi", REPOS["fastapi"], [repo_root])
    assert resolved == repo_path


def test_clone_repo_if_missing_clones_into_first_root(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repos"
    cfg = dict(REPOS["linux"])
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs):
        calls.append(cmd)
        target = Path(cmd[-1])
        target.mkdir(parents=True)
        return None

    monkeypatch.setattr("eval.benchmark_3way_catalog.subprocess.run", fake_run)

    cloned = clone_repo_if_missing("linux", cfg, [repo_root])
    assert cloned == repo_root / "linux"
    assert calls == [["git", "clone", "--depth", "1", cfg["clone_url"], str(repo_root / "linux")]]
