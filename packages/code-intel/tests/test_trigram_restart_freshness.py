"""A new raw search session must qualify the persisted trigram snapshot."""

import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.tools import search_tools

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


async def test_old_index_without_source_proof_rebuilds(tmp_path):
    target = tmp_path / ROOT
    target.write_text(f'VALUE = "{OLD}"\n')
    assert "built index" in await first_search(tmp_path, OLD)
    with closing(sqlite3.connect(tmp_path / ".attocode" / "index" / "trigrams.db")) as conn, conn:
        conn.execute("DROP TABLE IF EXISTS trigram_snapshot")
    target.write_text(f'VALUE = "{NEW}"\n')
    reopened = await first_search(tmp_path, NEW)
    assert f"{ROOT}:1:" in reopened and "built index" in reopened
    assert "built index" not in await first_search(tmp_path, NEW)


async def test_mixed_saved_index_files_are_not_reused(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / ROOT).write_text(f'VALUE = "{OLD}"\n')
    (second / ROOT).write_text(f'VALUE = "{NEW}"\n')
    assert "built index" in await first_search(first, OLD)
    assert "built index" in await first_search(second, NEW)
    # The binary files were replaced, but SQLite still describes the old generation.
    for name in ("trigrams.lookup", "trigrams.postings"):
        path = ".attocode/index/" + name
        (first / path).write_bytes((second / path).read_bytes())
    reopened = await first_search(first, OLD)
    assert f"{ROOT}:1:" in reopened and "built index" in reopened


async def test_direct_regex_reopen_rejects_a_stale_saved_index(tmp_path, monkeypatch):
    target = tmp_path / ROOT
    target.write_text(f'VALUE = "{OLD}"\n')
    for i in range(12):
        (tmp_path / f"control{i}.py").write_text("VALUE = 1\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "out_of_scope.py").write_text(f'VALUE = "{NEW}"\n')
    assert "built index" in await first_search(tmp_path, OLD)
    target.write_text(f'VALUE = "{NEW}"\n')
    monkeypatch.setattr(search_tools, "_trigram_index", None)
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    try:
        for _ in range(2):
            result = search_tools.regex_search(NEW)
            assert f"{ROOT}:1:" in result and "trigram-indexed" in result
            assert "out_of_scope.py" not in result
    finally:
        if search_tools._trigram_index is not None:
            search_tools._trigram_index.close()


async def test_failed_restart_rebuild_preserves_fallback_and_retries(tmp_path, monkeypatch):
    target = tmp_path / ROOT
    target.write_text(f'VALUE = "{OLD}"\n')
    assert "built index" in await first_search(tmp_path, OLD)
    target.write_text(f'VALUE = "{NEW}"\n')
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "out_of_scope.py").write_text(f'VALUE = "{NEW}"\n')
    real_read = Path.read_bytes
    failed = False

    def fail_once(path):
        nonlocal failed
        if path == target and not failed:
            failed = True
            raise OSError("transient fixture read failure")
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", fail_once)
    gateway = OperationGateway(str(tmp_path), profile="full", watch=False)
    try:
        args = {"pattern": NEW, "explain": True}
        fallback = (await gateway.execute("fast_search", args)).content[0].text
        assert failed and f"{ROOT}:1:" in fallback
        assert "index-build-failed" in fallback and "out_of_scope.py" not in fallback
        rebuilt = (await gateway.execute("fast_search", args)).content[0].text
        assert f"{ROOT}:1:" in rebuilt and "built index" in rebuilt
    finally:
        await gateway.close()


async def test_saved_file_map_from_another_generation_is_rejected(tmp_path):
    directory = tmp_path / "src"
    directory.mkdir()
    target = directory / ROOT
    target.write_text(f'VALUE = "{NEW}"\n')
    assert "built index" in await first_search(tmp_path, NEW)
    database = tmp_path / ".attocode" / "index" / "trigrams.db"
    # An older writer can replace the path map without touching a newer
    # proof or changing the binary artifacts when file IDs and bytes match.
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE trigram_files SET path = 'moved/target.py'")
    reopened = await first_search(tmp_path, NEW)
    assert f"src/{ROOT}:1:" in reopened and "built index" in reopened


async def test_cold_build_skips_unreadable_input_without_widening_scope(tmp_path, monkeypatch):
    (tmp_path / ROOT).write_text(f'VALUE = "{NEW}"\n')
    unreadable = tmp_path / "unreadable.py"
    unreadable.write_text("VALUE = 1\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "out_of_scope.py").write_text(f'VALUE = "{NEW}"\n')
    real_read = Path.read_bytes

    def cannot_read(path):
        if path == unreadable:
            raise PermissionError("fixture file is unavailable")
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", cannot_read)
    text = await first_search(tmp_path, NEW)
    assert f"{ROOT}:1:" in text and "out_of_scope.py" not in text
