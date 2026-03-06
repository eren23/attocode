"""Tests for SwarmMessageBus."""

from __future__ import annotations

from attocode.integrations.swarm.message_bus import (
    FileLock,
    MessageType,
    SwarmMessage,
    SwarmMessageBus,
)


class TestSwarmMessageBus:
    """Test the SQLite-backed message bus."""

    def test_send_and_receive(self) -> None:
        bus = SwarmMessageBus(":memory:")
        msg_id = bus.send("task-1", MessageType.CONTEXT_SHARE, {"data": "hello"}, recipient="task-2")
        assert msg_id > 0

        messages = bus.receive("task-2")
        assert len(messages) == 1
        assert messages[0].sender == "task-1"
        assert messages[0].type == MessageType.CONTEXT_SHARE
        assert messages[0].payload["data"] == "hello"
        bus.close()

    def test_broadcast(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.send("task-1", MessageType.WORKER_DONE, {"summary": "done"}, recipient="all")

        # Any recipient should get broadcast messages
        msgs = bus.receive("task-2")
        assert len(msgs) == 1
        assert msgs[0].payload["summary"] == "done"

        # Already marked read
        msgs2 = bus.receive("task-2")
        assert len(msgs2) == 0
        bus.close()

    def test_broadcast_done_helper(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.broadcast_done("task-1", "All tests pass", ["src/main.py"])

        msgs = bus.receive("task-3")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.WORKER_DONE
        assert msgs[0].payload["files_modified"] == ["src/main.py"]
        bus.close()

    def test_file_locking(self) -> None:
        bus = SwarmMessageBus(":memory:")

        # Acquire lock
        assert bus.lock_file("src/main.py", "task-1") is True

        # Same holder can re-lock
        assert bus.lock_file("src/main.py", "task-1") is True

        # Different holder blocked
        assert bus.lock_file("src/main.py", "task-2") is False

        # Release
        assert bus.unlock_file("src/main.py", "task-1") is True

        # Now task-2 can lock
        assert bus.lock_file("src/main.py", "task-2") is True
        bus.close()

    def test_get_file_locks(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.lock_file("a.py", "task-1")
        bus.lock_file("b.py", "task-2")

        locks = bus.get_file_locks()
        assert len(locks) == 2
        paths = {lock.path for lock in locks}
        assert paths == {"a.py", "b.py"}
        bus.close()

    def test_release_all_locks(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.lock_file("a.py", "task-1")
        bus.lock_file("b.py", "task-1")
        bus.lock_file("c.py", "task-2")

        released = bus.release_all_locks("task-1")
        assert released == 2

        locks = bus.get_file_locks()
        assert len(locks) == 1
        assert locks[0].holder == "task-2"
        bus.close()

    def test_escalation(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.escalate("task-1", "Cannot find dependency", severity="high")

        escalations = bus.get_escalations()
        assert len(escalations) == 1
        assert escalations[0].payload["issue"] == "Cannot find dependency"
        assert escalations[0].payload["severity"] == "high"
        bus.close()

    def test_share_context(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.share_context("task-1", "task-2", "Found API endpoint at /users", context_type="finding")

        msgs = bus.receive("task-2", msg_type=MessageType.CONTEXT_SHARE)
        assert len(msgs) == 1
        assert msgs[0].payload["context"] == "Found API endpoint at /users"
        bus.close()

    def test_unread_only(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.send("task-1", MessageType.CONTEXT_SHARE, {"data": "1"}, recipient="task-2")

        # First receive marks as read
        msgs = bus.receive("task-2")
        assert len(msgs) == 1

        # Second receive returns nothing (unread_only=True)
        msgs = bus.receive("task-2")
        assert len(msgs) == 0

        # With unread_only=False, get it back
        msgs = bus.receive("task-2", unread_only=False)
        assert len(msgs) == 1
        bus.close()

    def test_message_count(self) -> None:
        bus = SwarmMessageBus(":memory:")
        assert bus.get_message_count() == 0

        bus.send("a", "worker_done", {}, recipient="all")
        bus.send("b", "context_share", {}, recipient="c")
        assert bus.get_message_count() == 2
        assert bus.get_message_count(unread_only=True) == 2

        bus.receive("c")
        # "c" read 2 messages (direct + broadcast)
        assert bus.get_message_count(unread_only=True) == 0
        bus.close()

    def test_clear(self) -> None:
        bus = SwarmMessageBus(":memory:")
        bus.send("a", "worker_done", {}, recipient="all")
        bus.lock_file("x.py", "a")

        bus.clear()
        assert bus.get_message_count() == 0
        assert len(bus.get_file_locks()) == 0
        bus.close()
