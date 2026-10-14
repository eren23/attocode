"""Real process contention and crash recovery on a disposable shared index."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import SNAPSHOT_KEY, IndexStore
from test_edit_restart import evidence, populate
from test_index_sequences import close

# Only the pause/observation hooks are synthetic. Both children use the real
# gateway, operation lock, filesystem, index repair and SQLite transactions.
WORKER = r'''
import asyncio, json, sys, time
from pathlib import Path
from filelock import FileLock, Timeout
import attocode_intel.gateway as module
from attocode_intel._internal.integrations.context.index_store import IndexStore

root, control, role = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

class ObservedLock(FileLock):
    def acquire(self, *args, **kwargs):
        if role == 'second' and str(self.lock_file).endswith('operations.lock'):
            try:
                return super().acquire(timeout=0)
            except Timeout:
                (control/'second-blocked').touch()
        return super().acquire(*args, **kwargs)

module.FileLock = ObservedLock
original = IndexStore.save_files_batch
def pause_after_committed_file_rows(self, files):
    original(self, files)
    # The repair has already invalidated its complete-snapshot marker. Hold an
    # additional uncommitted write to verify OS lock release and WAL rollback.
    connection = self._get_conn()
    connection.execute('BEGIN IMMEDIATE')
    connection.execute("UPDATE files SET content_hash = 'uncommitted-sentinel'")
    marker = control/'first-paused.tmp'
    marker.write_text(json.dumps({'db':self.db_path}))
    marker.replace(control/'first-paused')
    deadline = time.monotonic() + 20
    try:
        while not (control/'release-first').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Parent did not release paused index writer')
            time.sleep(.01)
    finally:
        connection.rollback()
    IndexStore.save_files_batch = original

if role == 'first':
    IndexStore.save_files_batch = pause_after_committed_file_rows

async def main():
    gateway = module.OperationGateway(str(root), 'daily', watch=False)
    try:
        result = await gateway.execute_mcp('search_symbols', {'name':'revised'})
        assert not result.isError, result
        data = json.loads(result.content[0].text)
        assert [(r['file_path'],r['name']) for r in data['data']] == [('helper.py','revised')], data
        old = await gateway.execute_mcp('search_symbols', {'name':'helper'})
        assert json.loads(old.content[0].text)['data'] == [], old
        print(json.dumps({'role':role,'status':'passed'}))
    finally:
        await gateway.close()
asyncio.run(main())
'''


def wait_for(path, child):
    deadline = time.monotonic() + 15
    while not path.exists():
        if child.poll() is not None:
            stdout, stderr = child.communicate(timeout=2)
            pytest.fail(f"Child exited before {path.name}: {stdout[-2000:]} {stderr[-2000:]}")
        if time.monotonic() >= deadline:
            pytest.fail(f"Child did not reach {path.name} within 15 seconds")
        time.sleep(.01)


def finish(child):
    stdout, stderr = child.communicate(timeout=15)
    assert child.returncode == 0, (stdout[-2000:], stderr[-2000:])
    assert json.loads(stdout)["status"] == "passed"


@pytest.mark.parametrize("interrupt", [False, True], ids=["serialize", "kill-writer"])
def test_shared_gateway_processes_recover_complete_index(tmp_path, interrupt):
    root, control = tmp_path / "workspace", tmp_path / "control"
    root.mkdir()
    control.mkdir()
    populate(root)
    initial = ASTService(str(root))
    try:
        initial.initialize_skeleton()
        db = Path(initial._store.db_path)
        assert initial._store.get_meta(SNAPSHOT_KEY)
    finally:
        close(initial)
    (root / "helper.py").write_text("def revised():\n    return 2\n")
    env = dict(os.environ, ATTOCODE_INTEL_PRECISION="off", ATTOCODE_EMBEDDING_MODEL="")
    children = []

    def start(role):
        child = subprocess.Popen([sys.executable, "-c", WORKER, str(root), str(control), role],
                                 env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        children.append(child)
        return child

    try:
        first = start("first")
        wait_for(control / "first-paused", first)
        assert json.loads((control / "first-paused").read_text())["db"] == str(db)
        with sqlite3.connect(db, timeout=2) as reader:
            assert reader.execute("SELECT value FROM metadata WHERE key=?", (SNAPSHOT_KEY,)).fetchone() == ("",)
            assert reader.execute("SELECT COUNT(*) FROM files WHERE content_hash='uncommitted-sentinel'").fetchone() == (0,)
        second = start("second")
        wait_for(control / "second-blocked", second)
        assert first.poll() is None and second.poll() is None
        if interrupt:
            first.kill()
            first.communicate(timeout=5)
            assert first.returncode != 0
        else:
            (control / "release-first").touch()
            finish(first)
        finish(second)
        reopened = ASTService(str(root))
        clean = ASTService(str(root), store=IndexStore(db_path=":memory:"))
        try:
            reopened.initialize_skeleton()
            clean.initialize_skeleton()
            assert evidence(reopened) == evidence(clean)
            assert reopened.find_symbol("revised") and not reopened.find_symbol("helper")
            assert reopened._store.get_meta(SNAPSHOT_KEY)
        finally:
            close(reopened)
            close(clean)
        with sqlite3.connect(db, timeout=2) as reader:
            assert reader.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert reader.execute("SELECT COUNT(*) FROM files WHERE content_hash='uncommitted-sentinel'").fetchone() == (0,)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        assert all(child.poll() is not None for child in children)
