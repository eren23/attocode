"""Tests for FileLedger (optimistic concurrency control)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from attoswarm.workspace.file_ledger import FileLedger, FileVersion, WriteResult


@pytest.fixture
def ledger(tmp_path: Path) -> FileLedger:
    """Create a FileLedger with a temporary root directory."""
    # Create a sample file
    sample = tmp_path / "hello.py"
    sample.write_text("print('hello')\n")
    return FileLedger(root_dir=str(tmp_path), ast_service=None)


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_file(self, ledger: FileLedger, tmp_path: Path) -> None:
        ver = await ledger.snapshot_file("hello.py", "agent-1")
        assert isinstance(ver, FileVersion)
        assert ver.file_path == "hello.py"
        assert ver.content_snapshot == "print('hello')\n"
        assert ver.version_hash  # non-empty hash
        assert ver.reader_agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_snapshot_nonexistent(self, ledger: FileLedger) -> None:
        ver = await ledger.snapshot_file("does_not_exist.py", "agent-1")
        assert ver.content_snapshot == ""
        assert ver.version_hash  # hash of empty string


class TestClaims:
    @pytest.mark.asyncio
    async def test_claim_and_release(self, ledger: FileLedger) -> None:
        ok = await ledger.claim_file("hello.py", "agent-1", "task-1")
        assert ok
        claims = await ledger.get_active_claims()
        assert "hello.py" in claims
        assert claims["hello.py"].agent_id == "agent-1"

        await ledger.release_claim("hello.py", "agent-1")
        claims = await ledger.get_active_claims()
        assert "hello.py" not in claims

    @pytest.mark.asyncio
    async def test_claim_conflict(self, ledger: FileLedger) -> None:
        await ledger.claim_file("hello.py", "agent-1", "task-1")
        # Second agent trying to claim the same file
        ok = await ledger.claim_file("hello.py", "agent-2", "task-2")
        assert not ok

    @pytest.mark.asyncio
    async def test_release_all(self, ledger: FileLedger) -> None:
        await ledger.claim_file("hello.py", "agent-1", "task-1")
        await ledger.release_all_claims("agent-1")
        claims = await ledger.get_active_claims()
        assert len(claims) == 0


class TestAttemptWrite:
    @pytest.mark.asyncio
    async def test_successful_write(self, ledger: FileLedger, tmp_path: Path) -> None:
        ver = await ledger.snapshot_file("hello.py", "agent-1")
        result = await ledger.attempt_write(
            path="hello.py",
            agent_id="agent-1",
            task_id="task-1",
            content="print('world')\n",
            base_hash=ver.version_hash,
        )
        assert isinstance(result, WriteResult)
        assert result.success
        assert not result.conflict
        # Verify file was actually written
        assert (tmp_path / "hello.py").read_text() == "print('world')\n"

    @pytest.mark.asyncio
    async def test_conflict_detection(self, ledger: FileLedger, tmp_path: Path) -> None:
        ver = await ledger.snapshot_file("hello.py", "agent-1")

        # Simulate another agent writing first
        (tmp_path / "hello.py").write_text("print('changed')\n")
        # Update ledger's internal version tracking
        await ledger.snapshot_file("hello.py", "agent-2")

        # Now agent-1 tries to write with stale base hash
        result = await ledger.attempt_write(
            path="hello.py",
            agent_id="agent-1",
            task_id="task-1",
            content="print('agent1 version')\n",
            base_hash=ver.version_hash,
        )
        assert result.conflict

    @pytest.mark.asyncio
    async def test_write_new_file(self, ledger: FileLedger, tmp_path: Path) -> None:
        ver = await ledger.snapshot_file("new_file.py", "agent-1")
        result = await ledger.attempt_write(
            path="new_file.py",
            agent_id="agent-1",
            task_id="task-1",
            content="x = 1\n",
            base_hash=ver.version_hash,
        )
        assert result.success
        assert (tmp_path / "new_file.py").read_text() == "x = 1\n"
