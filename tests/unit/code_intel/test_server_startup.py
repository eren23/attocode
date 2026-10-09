"""Code-intel server startup: project root discovery and client watchdog."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from attocode_intel.project_dir import find_project_root

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_home_settings_folder_is_not_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ~/.attocode holds user settings. A folder without markers stays its own
    # root instead of turning the whole home directory into the project.
    home = tmp_path / "home"
    (home / ".attocode").mkdir(parents=True)
    site = home / "Documents" / "site"
    site.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    assert find_project_root(str(site)) == str(site)

    (site / ".attocode").mkdir()
    (site / "blog").mkdir()
    assert find_project_root(str(site / "blog")) == str(site)


def test_worktree_git_file_marks_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")

    assert find_project_root(str(worktree / "src")) == str(worktree)


# The server process starts the watchdog, reports it on stderr, then waits.
_SERVER = """
import sys, time
from attocode_intel.server import _exit_when_client_exits
_exit_when_client_exits(interval=0.1)
print("ready", file=sys.stderr, flush=True)
time.sleep(120)
"""
# The client starts the server, waits for the watchdog, then exits.
_CLIENT = f"""
import subprocess, sys
server = subprocess.Popen([sys.executable, "-c", {_SERVER!r}], stderr=subprocess.PIPE)
server.stderr.readline()
"""


def test_stdio_server_exits_when_its_client_exits() -> None:
    # The server shares the client's stdout pipe, so reading it to the end
    # also waits for the server. Without the watchdog the server sleeps 120 s.
    subprocess.run([sys.executable, "-c", _CLIENT], stdout=subprocess.PIPE, timeout=60, check=True)
