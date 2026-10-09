"""Code-intel server startup: project root discovery and client watchdog."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from attocode_intel.project_dir import find_project_root
from attocode_intel.request_context import resolve_workspace

if TYPE_CHECKING:
    from pathlib import Path


def test_home_settings_folder_is_not_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ~/.attocode holds user settings. A folder without markers stays its own
    # root instead of turning the whole home directory into the project.
    home = tmp_path / "home"
    (home / ".attocode").mkdir(parents=True)
    (home / "package.json").write_text("{}", encoding="utf-8")
    site = home / "Documents" / "site"
    site.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    assert find_project_root(str(site)) == str(site)
    # The console script's server selects its workspace with resolve_workspace.
    monkeypatch.chdir(site)
    with pytest.raises(ValueError, match="No repository selected"):
        resolve_workspace()
    monkeypatch.chdir(home)
    with pytest.raises(ValueError, match="No repository selected"):
        resolve_workspace()
    assert resolve_workspace(default=str(home)) == str(home.resolve())

    (site / ".attocode").mkdir()
    (site / "blog").mkdir()
    assert find_project_root(str(site / "blog")) == str(site)
    monkeypatch.chdir(site / "blog")
    assert resolve_workspace() == str(site.resolve())


def test_worktree_git_file_marks_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")

    assert find_project_root(str(worktree / "src")) == str(worktree)


# The server process starts the watchdog, reports it on stderr, then waits.
_SERVER = """
import sys, time
from attocode_intel.entrypoint import exit_when_client_exits
exit_when_client_exits(interval=0.1)
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


def test_stdio_server_refuses_home_as_its_workspace(tmp_path: Path) -> None:
    # The client runs in the home folder and advertises it as its only root.
    home = tmp_path / "home"
    (home / ".attocode").mkdir(parents=True)
    site = home / "site"
    site.mkdir()
    # Other tests can leave ATTOCODE_PROJECT_DIR set, which selects a project.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ATTOCODE_")}
    env["HOME"] = str(home)
    server = subprocess.Popen(
        [sys.executable, "-m", "attocode_intel.entrypoint", "--profile", "daily", "--local-only"],
        cwd=site, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def send(message: dict) -> None:
        server.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        server.stdin.flush()

    def reply(request_id: int) -> dict:
        while True:
            message = json.loads(server.stdout.readline())
            if message.get("method") == "roots/list":
                send({"id": message["id"], "result": {"roots": [{"uri": home.as_uri()}]}})
            elif message.get("id") == request_id:
                return message

    try:
        send({"id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "0"},
            "capabilities": {"roots": {}}}})
        reply(1)
        send({"method": "notifications/initialized"})
        send({"id": 2, "method": "tools/call", "params": {"name": "bootstrap", "arguments": {}}})
        result = reply(2)["result"]
    finally:
        server.kill()
        server.wait()

    assert result["isError"]
    assert "No repository selected" in result["content"][0]["text"]
    assert not (home / ".attocode" / "index").exists()
