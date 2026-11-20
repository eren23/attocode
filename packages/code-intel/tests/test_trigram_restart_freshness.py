"""A new raw search session must qualify the persisted trigram snapshot."""

import os
import subprocess
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway

OLD = "amberfreshneedle"
NEW = "jadefreshneedle"
ROOT = "target.py"


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


async def first_search(root, pattern):
    gateway = OperationGateway(str(root), profile="full", watch=False)
    try:
        result = await gateway.execute("fast_search", {"pattern": pattern, "explain": True})
        assert not result.isError
        return result.content[0].text
    finally:
        await gateway.close()


@pytest.mark.parametrize("change", ["edit", "same-mtime", "branch", "add", "rename"])
async def test_first_regex_search_finds_offline_changes(tmp_path, change):
    target = tmp_path / ROOT
    target.write_text(f'VALUE = "{OLD}"\n')
    (tmp_path / "control.py").write_text('VALUE = "stablefreshneedle"\n')
    if change == "branch":
        git(tmp_path, "init", "-b", "original")
        git(tmp_path, "config", "user.name", "Restart fixture")
        git(tmp_path, "config", "user.email", "fixture@example.invalid")
        (tmp_path / ".gitignore").write_text(".attocode/\n")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-m", "baseline")
        git(tmp_path, "switch", "-c", "changed")
        target.write_text(f'VALUE = "{NEW}"\n')
        git(tmp_path, "add", ROOT)
        git(tmp_path, "commit", "-m", "change source")
        git(tmp_path, "switch", "original")

    warm = await first_search(tmp_path, OLD)
    assert f"{ROOT}:1:" in warm and "built index" in warm
    if change == "branch":
        git(tmp_path, "switch", "changed")
    elif change == "add":
        target = tmp_path / "new.py"
        target.write_text(f'VALUE = "{NEW}"\n')
    elif change == "rename":
        target = target.rename(tmp_path / "renamed.py")
        target.write_text(f'VALUE = "{NEW}"\n')
    else:
        saved = target.stat()
        replacement = NEW if change == "edit" else "cobaltfreshneedl"
        target.write_text(f'VALUE = "{replacement}"\n')
        if change == "same-mtime":
            assert target.stat().st_size == saved.st_size
            os.utime(target, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            assert target.stat().st_mtime_ns == saved.st_mtime_ns

    pattern = "cobaltfreshneedl" if change == "same-mtime" else NEW
    reopened = await first_search(tmp_path, pattern)
    assert f"{target.name}:1:" in reopened, "REGRESSION: offline change hidden by saved trigram postings"


async def test_unchanged_reopen_reuses_valid_index(tmp_path):
    (tmp_path / ROOT).write_text(f'VALUE = "{OLD}"\n')
    warm = await first_search(tmp_path, OLD)
    assert "built index" in warm
    index_dir = tmp_path / ".attocode" / "index"
    index_files = [index_dir / f"trigrams.{suffix}" for suffix in ("lookup", "postings", "db")]
    before = [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in index_files]
    reopened = await first_search(tmp_path, OLD)
    assert f"{ROOT}:1:" in reopened and "built index" not in reopened
    assert [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in index_files] == before
