from __future__ import annotations

import subprocess
from pathlib import Path

from attoswarm.research.worktree_manager import WorktreeManager


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    for relative_path, content in files.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_worktree_manager_commit_all_returns_head_when_clean(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = _init_repo(repo, {"target.txt": "base\n"})

    manager = WorktreeManager(repo, tmp_path / "runs")
    worktree_path, branch = manager.create_worktree("exp-clean", head)
    try:
        assert manager.commit_all(worktree_path, "noop") == head
    finally:
        manager.remove_worktree(worktree_path, branch=branch)


def test_worktree_manager_apply_diff_and_remove_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = _init_repo(repo, {"target.txt": "base\n"})

    patch_repo = tmp_path / "patch_repo"
    subprocess.run(
        ["git", "clone", str(repo), str(patch_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    (patch_repo / "target.txt").write_text("base\npatched\n", encoding="utf-8")
    patch_text = _git(patch_repo, "diff", "--stat", "--patch")

    manager = WorktreeManager(repo, tmp_path / "runs")
    worktree_path, branch = manager.create_worktree("exp-patch", head)
    applied, detail = manager.apply_diff(worktree_path, patch_text)
    commit_hash = manager.commit_all(worktree_path, "apply patch")
    changed = manager.list_changed_files(worktree_path)

    assert applied is True
    assert "patch applied" in detail
    assert (Path(worktree_path) / "target.txt").read_text(encoding="utf-8") == "base\npatched\n"
    assert commit_hash != head
    assert changed == []

    manager.remove_worktree(worktree_path, branch=branch)
    assert not Path(worktree_path).exists()


def test_worktree_manager_apply_diff_failure_resets_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = _init_repo(repo, {"target.txt": "base\n"})

    manager = WorktreeManager(repo, tmp_path / "runs")
    worktree_path, branch = manager.create_worktree("exp-bad", head)
    try:
        applied, detail = manager.apply_diff(
            worktree_path,
            "diff --git a/nope.txt b/nope.txt\n@@\n-nope\n+still nope\n",
        )
        assert applied is False
        assert detail
        assert manager.list_changed_files(worktree_path) == []
        assert (Path(worktree_path) / "target.txt").read_text(encoding="utf-8") == "base\n"
    finally:
        manager.remove_worktree(worktree_path, branch=branch)


def test_worktree_manager_extract_patch_handles_stat_bundle_and_empty_text() -> None:
    diff_text = (
        " target.txt | 1 +\n"
        " 1 file changed, 1 insertion(+)\n\n"
        "diff --git a/target.txt b/target.txt\n"
        "index df967b9..fc48407 100644\n"
        "--- a/target.txt\n"
        "+++ b/target.txt\n"
        "@@ -1 +1,2 @@\n"
        " base\n"
        "+patched\n"
    )

    extracted = WorktreeManager._extract_patch(diff_text)
    assert extracted.startswith("diff --git ")
    assert WorktreeManager._extract_patch("") == ""
