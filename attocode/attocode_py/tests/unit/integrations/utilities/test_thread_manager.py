"""Tests for session thread and fork management."""

from __future__ import annotations

import time

import pytest

from attocode.integrations.utilities.thread_manager import (
    ThreadInfo,
    ThreadManager,
    ThreadSnapshot,
    _serialize_msg,
)
from attocode.types.messages import Message, Role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(role: str = "user", content: str = "hello") -> Message:
    """Create a simple test message."""
    return Message(role=Role(role), content=content)


# ---------------------------------------------------------------------------
# ThreadInfo dataclass
# ---------------------------------------------------------------------------


class TestThreadInfo:
    def test_defaults(self) -> None:
        info = ThreadInfo(thread_id="t1", label="Test")
        assert info.thread_id == "t1"
        assert info.label == "Test"
        assert info.parent_id is None
        assert info.fork_point == 0
        assert info.message_count == 0
        assert info.is_active is True

    def test_created_at_auto_set(self) -> None:
        before = time.time()
        info = ThreadInfo(thread_id="t1", label="T")
        after = time.time()
        assert before <= info.created_at <= after

    def test_last_active_matches_created_at(self) -> None:
        info = ThreadInfo(thread_id="t1", label="T")
        assert info.last_active == info.created_at

    def test_explicit_timestamps_preserved(self) -> None:
        info = ThreadInfo(
            thread_id="t1",
            label="T",
            created_at=100.0,
            last_active=200.0,
        )
        assert info.created_at == 100.0
        assert info.last_active == 200.0


# ---------------------------------------------------------------------------
# ThreadManager creation & basic properties
# ---------------------------------------------------------------------------


class TestThreadManagerCreation:
    def test_default_main_thread_exists(self) -> None:
        mgr = ThreadManager()
        assert "main" in mgr._threads
        assert mgr._threads["main"].label == "Main"

    def test_active_thread_returns_main_initially(self) -> None:
        mgr = ThreadManager()
        active = mgr.active_thread
        assert active is not None
        assert active.thread_id == "main"
        assert active.label == "Main"

    def test_active_thread_id_returns_main(self) -> None:
        mgr = ThreadManager()
        assert mgr.active_thread_id == "main"

    def test_thread_count_starts_at_one(self) -> None:
        mgr = ThreadManager()
        assert mgr.thread_count == 1

    def test_session_id_stored(self) -> None:
        mgr = ThreadManager(session_id="sess-42")
        assert mgr._session_id == "sess-42"

    def test_empty_session_id_default(self) -> None:
        mgr = ThreadManager()
        assert mgr._session_id == ""


# ---------------------------------------------------------------------------
# create_fork
# ---------------------------------------------------------------------------


class TestCreateFork:
    def test_creates_new_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Experiment")
        assert fork.thread_id.startswith("fork-")
        assert fork.label == "Experiment"
        assert fork.parent_id == "main"
        assert mgr.thread_count == 2

    def test_default_label_includes_parent(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork()
        assert "main" in fork.label

    def test_fork_with_messages_copies_them(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "q1"), _msg("assistant", "a1"), _msg("user", "q2")]
        fork = mgr.create_fork(messages=msgs)
        copied = mgr.get_messages(fork.thread_id)
        assert len(copied) == 3
        assert copied[0].content == "q1"
        assert copied[2].content == "q2"

    def test_fork_with_fork_at_copies_up_to_point(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "q1"), _msg("assistant", "a1"), _msg("user", "q2")]
        fork = mgr.create_fork(messages=msgs, fork_at=2)
        copied = mgr.get_messages(fork.thread_id)
        assert len(copied) == 2
        assert copied[0].content == "q1"
        assert copied[1].content == "a1"

    def test_fork_at_zero_gives_empty(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "q1")]
        fork = mgr.create_fork(messages=msgs, fork_at=0)
        assert mgr.get_messages(fork.thread_id) == []
        assert fork.fork_point == 0
        assert fork.message_count == 0

    def test_fork_copies_from_active_thread_messages(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "hello"))
        mgr.add_message(_msg("assistant", "hi"))
        fork = mgr.create_fork(label="Branch")
        copied = mgr.get_messages(fork.thread_id)
        assert len(copied) == 2
        assert copied[0].content == "hello"

    def test_fork_sets_message_count(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "a"), _msg("assistant", "b")]
        fork = mgr.create_fork(messages=msgs)
        assert fork.message_count == 2

    def test_fork_does_not_switch_active(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="Side")
        assert mgr.active_thread_id == "main"

    def test_multiple_forks_increment_count(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="A")
        mgr.create_fork(label="B")
        assert mgr.thread_count == 3


# ---------------------------------------------------------------------------
# switch_thread
# ---------------------------------------------------------------------------


class TestSwitchThread:
    def test_switch_changes_active(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Alt")
        result = mgr.switch_thread(fork.thread_id)
        assert mgr.active_thread_id == fork.thread_id
        assert result.thread_id == fork.thread_id

    def test_switch_updates_last_active(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Alt")
        old_ts = fork.last_active
        time.sleep(0.01)
        mgr.switch_thread(fork.thread_id)
        assert fork.last_active >= old_ts

    def test_switch_back_to_main(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Alt")
        mgr.switch_thread(fork.thread_id)
        mgr.switch_thread("main")
        assert mgr.active_thread_id == "main"

    def test_switch_invalid_id_raises_key_error(self) -> None:
        mgr = ThreadManager()
        with pytest.raises(KeyError, match="nonexistent"):
            mgr.switch_thread("nonexistent")

    def test_active_thread_unchanged_on_error(self) -> None:
        mgr = ThreadManager()
        with pytest.raises(KeyError):
            mgr.switch_thread("bad")
        assert mgr.active_thread_id == "main"


# ---------------------------------------------------------------------------
# add_message
# ---------------------------------------------------------------------------


class TestAddMessage:
    def test_add_to_active_thread(self) -> None:
        mgr = ThreadManager()
        msg = _msg("user", "question")
        mgr.add_message(msg)
        messages = mgr.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "question"

    def test_add_updates_message_count(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "q1"))
        mgr.add_message(_msg("assistant", "a1"))
        info = mgr.active_thread
        assert info is not None
        assert info.message_count == 2

    def test_add_updates_last_active(self) -> None:
        mgr = ThreadManager()
        old_ts = mgr.active_thread.last_active
        time.sleep(0.01)
        mgr.add_message(_msg("user", "q1"))
        assert mgr.active_thread.last_active >= old_ts

    def test_add_to_specific_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Alt")
        mgr.add_message(_msg("user", "forked msg"), thread_id=fork.thread_id)
        # Active thread should still be main
        assert mgr.active_thread_id == "main"
        assert len(mgr.get_messages("main")) == 0
        assert len(mgr.get_messages(fork.thread_id)) == 1

    def test_add_to_nonexistent_thread_creates_messages_list(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "orphan"), thread_id="ghost")
        # Message added but no ThreadInfo for "ghost"
        assert len(mgr._thread_messages["ghost"]) == 1

    def test_add_dict_message(self) -> None:
        mgr = ThreadManager()
        mgr.add_message({"role": "user", "content": "raw dict"})
        messages = mgr.get_messages()
        assert len(messages) == 1
        assert messages[0]["content"] == "raw dict"


# ---------------------------------------------------------------------------
# get_messages
# ---------------------------------------------------------------------------


class TestGetMessages:
    def test_returns_copy(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "one"))
        msgs = mgr.get_messages()
        msgs.append(_msg("user", "extra"))
        # Original should be unchanged
        assert len(mgr.get_messages()) == 1

    def test_empty_for_new_thread(self) -> None:
        mgr = ThreadManager()
        assert mgr.get_messages() == []

    def test_for_specific_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="F")
        mgr.add_message(_msg("user", "in fork"), thread_id=fork.thread_id)
        assert len(mgr.get_messages(fork.thread_id)) == 1
        assert mgr.get_messages(fork.thread_id)[0].content == "in fork"

    def test_unknown_thread_returns_empty(self) -> None:
        mgr = ThreadManager()
        assert mgr.get_messages("no-such-thread") == []


# ---------------------------------------------------------------------------
# list_threads
# ---------------------------------------------------------------------------


class TestListThreads:
    def test_returns_all_threads(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="A")
        mgr.create_fork(label="B")
        threads = mgr.list_threads()
        assert len(threads) == 3

    def test_sorted_by_last_active_descending(self) -> None:
        mgr = ThreadManager()
        fork_a = mgr.create_fork(label="A")
        time.sleep(0.01)
        fork_b = mgr.create_fork(label="B")
        time.sleep(0.01)
        # Touch A so it becomes most recent
        mgr.switch_thread(fork_a.thread_id)
        threads = mgr.list_threads()
        assert threads[0].thread_id == fork_a.thread_id

    def test_active_only_filters_inactive(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Closed")
        mgr.close_thread(fork.thread_id)
        active_threads = mgr.list_threads(active_only=True)
        assert len(active_threads) == 1
        assert active_threads[0].thread_id == "main"

    def test_active_only_all_active(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="F1")
        assert len(mgr.list_threads(active_only=True)) == 2


# ---------------------------------------------------------------------------
# close_thread
# ---------------------------------------------------------------------------


class TestCloseThread:
    def test_marks_inactive(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Temp")
        result = mgr.close_thread(fork.thread_id)
        assert result is True
        assert fork.is_active is False

    def test_close_main(self) -> None:
        mgr = ThreadManager()
        result = mgr.close_thread("main")
        assert result is True
        assert mgr._threads["main"].is_active is False

    def test_close_nonexistent_returns_false(self) -> None:
        mgr = ThreadManager()
        assert mgr.close_thread("nope") is False

    def test_closed_thread_still_in_list(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="C")
        mgr.close_thread(fork.thread_id)
        all_threads = mgr.list_threads()
        assert any(t.thread_id == fork.thread_id for t in all_threads)


# ---------------------------------------------------------------------------
# delete_thread
# ---------------------------------------------------------------------------


class TestDeleteThread:
    def test_removes_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Del")
        result = mgr.delete_thread(fork.thread_id)
        assert result is True
        assert fork.thread_id not in mgr._threads
        assert fork.thread_id not in mgr._thread_messages
        assert mgr.thread_count == 1

    def test_cannot_delete_main(self) -> None:
        mgr = ThreadManager()
        result = mgr.delete_thread("main")
        assert result is False
        assert mgr.thread_count == 1

    def test_delete_nonexistent_returns_false(self) -> None:
        mgr = ThreadManager()
        assert mgr.delete_thread("ghost") is False

    def test_delete_active_reverts_to_main(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Active")
        mgr.switch_thread(fork.thread_id)
        assert mgr.active_thread_id == fork.thread_id
        mgr.delete_thread(fork.thread_id)
        assert mgr.active_thread_id == "main"

    def test_delete_non_active_keeps_current(self) -> None:
        mgr = ThreadManager()
        fork_a = mgr.create_fork(label="A")
        fork_b = mgr.create_fork(label="B")
        mgr.switch_thread(fork_a.thread_id)
        mgr.delete_thread(fork_b.thread_id)
        assert mgr.active_thread_id == fork_a.thread_id


# ---------------------------------------------------------------------------
# get_thread_tree
# ---------------------------------------------------------------------------


class TestGetThreadTree:
    def test_main_only(self) -> None:
        mgr = ThreadManager()
        tree = mgr.get_thread_tree()
        # main has no parent, so parent is "root"
        assert "root" in tree
        assert "main" in tree["root"]

    def test_single_fork(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Child")
        tree = mgr.get_thread_tree()
        assert "main" in tree
        assert fork.thread_id in tree["main"]

    def test_nested_forks(self) -> None:
        mgr = ThreadManager()
        fork1 = mgr.create_fork(label="Level1")
        mgr.switch_thread(fork1.thread_id)
        fork2 = mgr.create_fork(label="Level2")
        tree = mgr.get_thread_tree()
        assert "root" in tree
        assert "main" in tree["root"]
        assert fork1.thread_id in tree["main"]
        assert fork1.thread_id in tree
        assert fork2.thread_id in tree[fork1.thread_id]

    def test_multiple_children(self) -> None:
        mgr = ThreadManager()
        f1 = mgr.create_fork(label="A")
        f2 = mgr.create_fork(label="B")
        tree = mgr.get_thread_tree()
        children_of_main = tree.get("main", [])
        assert f1.thread_id in children_of_main
        assert f2.thread_id in children_of_main


# ---------------------------------------------------------------------------
# snapshot / snapshot_all
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_active_thread(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "hi"))
        snap = mgr.snapshot()
        assert snap is not None
        assert snap.info.thread_id == "main"
        assert len(snap.messages) == 1

    def test_snapshot_specific_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Snap")
        mgr.add_message(_msg("user", "forked"), thread_id=fork.thread_id)
        snap = mgr.snapshot(fork.thread_id)
        assert snap is not None
        assert snap.info.thread_id == fork.thread_id
        assert len(snap.messages) == 1

    def test_snapshot_nonexistent_returns_none(self) -> None:
        mgr = ThreadManager()
        assert mgr.snapshot("ghost") is None

    def test_snapshot_returns_copy_of_messages(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "original"))
        snap = mgr.snapshot()
        assert snap is not None
        snap.messages.append(_msg("user", "extra"))
        assert len(mgr.get_messages()) == 1

    def test_snapshot_all(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="A")
        mgr.create_fork(label="B")
        snapshots = mgr.snapshot_all()
        assert len(snapshots) == 3
        ids = {s.info.thread_id for s in snapshots}
        assert "main" in ids


# ---------------------------------------------------------------------------
# restore_snapshots
# ---------------------------------------------------------------------------


class TestRestoreSnapshots:
    def test_restores_threads(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "hello"))
        fork = mgr.create_fork(label="Fork1")
        # Fork inherited "hello" from main; now add one more to fork
        mgr.add_message(_msg("user", "forked"), thread_id=fork.thread_id)
        snapshots = mgr.snapshot_all()

        # Create a fresh manager and restore
        mgr2 = ThreadManager(session_id="restored")
        mgr2.restore_snapshots(snapshots)
        assert mgr2.thread_count == 2  # main was overwritten + fork
        assert len(mgr2.get_messages("main")) == 1
        # Fork has inherited "hello" + added "forked" = 2
        assert len(mgr2.get_messages(fork.thread_id)) == 2

    def test_restore_preserves_active_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Active")
        mgr.switch_thread(fork.thread_id)
        snapshots = mgr.snapshot_all()

        mgr2 = ThreadManager()
        mgr2._active_thread_id = fork.thread_id
        mgr2.restore_snapshots(snapshots)
        assert mgr2.active_thread_id == fork.thread_id

    def test_restore_resets_active_to_main_if_missing(self) -> None:
        mgr = ThreadManager()
        snap = mgr.snapshot_all()

        mgr2 = ThreadManager()
        mgr2._active_thread_id = "deleted-thread"
        mgr2.restore_snapshots(snap)
        assert mgr2.active_thread_id == "main"

    def test_restore_empty_snapshots(self) -> None:
        mgr = ThreadManager()
        mgr._active_thread_id = "missing"
        mgr.restore_snapshots([])
        # Should fall back to "main" since "missing" is not in threads
        assert mgr.active_thread_id == "main"


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_structure(self) -> None:
        mgr = ThreadManager(session_id="s1")
        data = mgr.to_dict()
        assert data["session_id"] == "s1"
        assert data["active_thread_id"] == "main"
        assert isinstance(data["threads"], list)
        assert len(data["threads"]) == 1
        thread_data = data["threads"][0]
        assert thread_data["thread_id"] == "main"
        assert thread_data["label"] == "Main"
        assert thread_data["messages"] == []

    def test_to_dict_with_messages(self) -> None:
        mgr = ThreadManager(session_id="s2")
        mgr.add_message(_msg("user", "q1"))
        mgr.add_message(_msg("assistant", "a1"))
        data = mgr.to_dict()
        messages = data["threads"][0]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "q1"

    def test_to_dict_preserves_fork_info(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "q1"), _msg("assistant", "a1")]
        fork = mgr.create_fork(label="Branch", messages=msgs, fork_at=1)
        data = mgr.to_dict()
        fork_data = [t for t in data["threads"] if t["thread_id"] == fork.thread_id]
        assert len(fork_data) == 1
        assert fork_data[0]["fork_point"] == 1
        assert fork_data[0]["parent_id"] == "main"
        assert fork_data[0]["label"] == "Branch"

    def test_from_dict_restores_manager(self) -> None:
        mgr = ThreadManager(session_id="round-trip")
        mgr.add_message(_msg("user", "question"))
        fork = mgr.create_fork(label="Side")
        # Fork inherited "question" from main; now add one more
        mgr.add_message(_msg("user", "side msg"), thread_id=fork.thread_id)
        mgr.switch_thread(fork.thread_id)
        data = mgr.to_dict()

        mgr2 = ThreadManager.from_dict(data)
        assert mgr2._session_id == "round-trip"
        assert mgr2.active_thread_id == fork.thread_id
        assert mgr2.thread_count == 2
        assert len(mgr2.get_messages("main")) == 1
        # Fork has inherited "question" + added "side msg" = 2
        assert len(mgr2.get_messages(fork.thread_id)) == 2

    def test_from_dict_missing_fields_use_defaults(self) -> None:
        data = {
            "threads": [
                {"thread_id": "main", "label": "Main"},
            ],
        }
        mgr = ThreadManager.from_dict(data)
        assert mgr._session_id == ""
        assert mgr.active_thread_id == "main"
        info = mgr._threads["main"]
        assert info.fork_point == 0
        assert info.is_active is True

    def test_from_dict_active_thread_fallback(self) -> None:
        data = {
            "active_thread_id": "deleted-branch",
            "threads": [
                {"thread_id": "main", "label": "Main"},
            ],
        }
        mgr = ThreadManager.from_dict(data)
        assert mgr.active_thread_id == "main"

    def test_from_dict_empty_threads(self) -> None:
        data = {"threads": []}
        mgr = ThreadManager.from_dict(data)
        # No threads restored, active falls back to "main" (which doesn't exist)
        # The implementation sets active to "main" but doesn't create it
        assert mgr.active_thread_id == "main"
        assert mgr.thread_count == 0

    def test_round_trip_preserves_timestamps(self) -> None:
        mgr = ThreadManager(session_id="ts-test")
        data = mgr.to_dict()
        created_at = data["threads"][0]["created_at"]
        last_active = data["threads"][0]["last_active"]

        mgr2 = ThreadManager.from_dict(data)
        info = mgr2._threads["main"]
        assert info.created_at == created_at
        assert info.last_active == last_active

    def test_round_trip_with_dict_messages(self) -> None:
        mgr = ThreadManager()
        mgr.add_message({"role": "user", "content": "raw"})
        data = mgr.to_dict()
        mgr2 = ThreadManager.from_dict(data)
        msgs = mgr2.get_messages("main")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_round_trip_inactive_thread(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Closed")
        mgr.close_thread(fork.thread_id)
        data = mgr.to_dict()
        mgr2 = ThreadManager.from_dict(data)
        restored = mgr2._threads[fork.thread_id]
        assert restored.is_active is False


# ---------------------------------------------------------------------------
# _serialize_msg helper
# ---------------------------------------------------------------------------


class TestSerializeMsg:
    def test_dict_passthrough(self) -> None:
        d = {"role": "user", "content": "hi"}
        assert _serialize_msg(d) is d

    def test_message_dataclass(self) -> None:
        msg = _msg("assistant", "reply")
        result = _serialize_msg(msg)
        assert result == {"role": "assistant", "content": "reply"}

    def test_object_without_role(self) -> None:
        class Bare:
            pass

        result = _serialize_msg(Bare())
        assert result["role"] == "user"
        assert result["content"] == ""


# ---------------------------------------------------------------------------
# Edge cases and integration-style scenarios
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_active_thread_none_fallback(self) -> None:
        mgr = ThreadManager()
        mgr._active_thread_id = None
        assert mgr.active_thread_id == "main"
        assert mgr.active_thread is None

    def test_fork_from_fork(self) -> None:
        mgr = ThreadManager()
        mgr.add_message(_msg("user", "root msg"))
        fork1 = mgr.create_fork(label="L1")
        mgr.switch_thread(fork1.thread_id)
        mgr.add_message(_msg("user", "l1 msg"))
        fork2 = mgr.create_fork(label="L2")
        assert fork2.parent_id == fork1.thread_id
        # L2 should have inherited L1's messages (root msg + l1 msg)
        msgs = mgr.get_messages(fork2.thread_id)
        assert len(msgs) == 2

    def test_delete_then_fork_still_works(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Temp")
        mgr.delete_thread(fork.thread_id)
        new_fork = mgr.create_fork(label="After delete")
        assert mgr.thread_count == 2
        assert new_fork.parent_id == "main"

    def test_many_messages_in_thread(self) -> None:
        mgr = ThreadManager()
        for i in range(100):
            mgr.add_message(_msg("user", f"msg-{i}"))
        assert mgr.active_thread.message_count == 100
        assert len(mgr.get_messages()) == 100

    def test_fork_at_beyond_message_count(self) -> None:
        mgr = ThreadManager()
        msgs = [_msg("user", "one")]
        fork = mgr.create_fork(messages=msgs, fork_at=999)
        # Should copy all available messages (only 1)
        assert len(mgr.get_messages(fork.thread_id)) == 1
        assert fork.fork_point == 999
        assert fork.message_count == 999
