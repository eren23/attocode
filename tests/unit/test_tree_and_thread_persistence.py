"""Tests for /tree visualization (QW2) and thread/fork persistence (QW3)."""

from __future__ import annotations

import pytest

from attocode.commands import CommandResult, render_thread_tree
from attocode.integrations.utilities.thread_manager import ThreadManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mgr_with_forks() -> ThreadManager:
    """Create a ThreadManager with a simple tree structure:
    main
      |- fork-a (Feature exploration)
      |    |- fork-b (Sub-experiment)
      |- fork-c (Bug investigation)
    """
    mgr = ThreadManager(session_id="test-session")

    # Add some messages to main
    for i in range(12):
        mgr.add_message({"role": "user", "content": f"msg-{i}"})

    # Create fork-a from main
    fork_a = mgr.create_fork(label="Feature exploration")

    # Switch to fork-a and add messages
    mgr.switch_thread(fork_a.thread_id)
    for i in range(5):
        mgr.add_message({"role": "user", "content": f"fork-a-msg-{i}"})

    # Create fork-b from fork-a
    fork_b = mgr.create_fork(label="Sub-experiment")

    # Add messages to fork-b
    mgr.switch_thread(fork_b.thread_id)
    for i in range(3):
        mgr.add_message({"role": "user", "content": f"fork-b-msg-{i}"})

    # Switch back to main and create fork-c
    mgr.switch_thread("main")
    fork_c = mgr.create_fork(label="Bug investigation")

    # Add messages to fork-c
    mgr.switch_thread(fork_c.thread_id)
    for i in range(8):
        mgr.add_message({"role": "user", "content": f"fork-c-msg-{i}"})

    # Switch back to main
    mgr.switch_thread("main")

    return mgr


class _FakeCtx:
    """Minimal context stub for command testing."""

    def __init__(self, thread_manager: ThreadManager | None = None) -> None:
        self.thread_manager = thread_manager
        self.messages: list[dict] = []


class _FakeAgent:
    """Minimal agent stub for command testing."""

    def __init__(self, ctx: _FakeCtx | None = None) -> None:
        self.context = ctx


# ===========================================================================
# QW2: render_thread_tree
# ===========================================================================


class TestRenderThreadTree:
    def test_main_only(self) -> None:
        mgr = ThreadManager()
        mgr.add_message({"role": "user", "content": "hi"})
        result = render_thread_tree(mgr)
        assert "main" in result
        assert "(1 messages)" in result

    def test_single_fork(self) -> None:
        mgr = ThreadManager()
        mgr.add_message({"role": "user", "content": "hi"})
        fork = mgr.create_fork(label="Experiment")
        result = render_thread_tree(mgr)
        assert "main" in result
        assert fork.thread_id in result
        assert '"Experiment"' in result

    def test_active_marker_on_current_thread(self) -> None:
        mgr = ThreadManager()
        result = render_thread_tree(mgr)
        assert "[active]" in result
        # main should be marked active
        assert "main" in result

    def test_active_marker_follows_switch(self) -> None:
        mgr = ThreadManager()
        fork = mgr.create_fork(label="Alt")
        mgr.switch_thread(fork.thread_id)
        result = render_thread_tree(mgr)
        # The fork line should have [active], main should not
        for line in result.splitlines():
            if fork.thread_id in line:
                assert "[active]" in line
            elif "main" in line:
                assert "[active]" not in line

    def test_nested_forks_show_hierarchy(self) -> None:
        mgr = _mgr_with_forks()
        result = render_thread_tree(mgr)
        lines = result.splitlines()
        # Should have tree connectors
        assert any("\u251c" in line or "\u2514" in line for line in lines)
        # All threads should appear
        assert "main" in result
        assert "Feature exploration" in result
        assert "Sub-experiment" in result
        assert "Bug investigation" in result

    def test_message_counts_displayed(self) -> None:
        mgr = ThreadManager()
        for i in range(5):
            mgr.add_message({"role": "user", "content": f"m{i}"})
        result = render_thread_tree(mgr)
        assert "(5 messages)" in result

    def test_tree_connectors_correct(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="A")
        mgr.create_fork(label="B")
        result = render_thread_tree(mgr)
        lines = result.splitlines()
        # First child should use |- connector, last child should use L connector
        connector_lines = [l for l in lines if "\u251c" in l or "\u2514" in l]
        assert len(connector_lines) == 2
        # Last child should use L connector
        assert "\u2514" in connector_lines[-1]

    def test_deep_nesting(self) -> None:
        mgr = ThreadManager()
        # Create 3-level deep nesting
        f1 = mgr.create_fork(label="L1")
        mgr.switch_thread(f1.thread_id)
        f2 = mgr.create_fork(label="L2")
        mgr.switch_thread(f2.thread_id)
        f3 = mgr.create_fork(label="L3")
        result = render_thread_tree(mgr)
        # All three forks should appear
        assert f1.thread_id in result
        assert f2.thread_id in result
        assert f3.thread_id in result
        # Should have increasing indentation
        lines = result.splitlines()
        assert len(lines) == 4  # main + 3 forks

    def test_label_in_quotes(self) -> None:
        mgr = ThreadManager()
        mgr.create_fork(label="My label")
        result = render_thread_tree(mgr)
        assert '"My label"' in result

    def test_no_label_omits_quotes(self) -> None:
        mgr = ThreadManager()
        # Main thread has label "Main" so it shows
        result = render_thread_tree(mgr)
        assert '"Main"' in result


# ===========================================================================
# QW2: _tree_command integration
# ===========================================================================


class TestTreeCommand:
    def test_tree_command_no_thread_manager(self) -> None:
        from attocode.commands import _tree_command
        agent = _FakeAgent(_FakeCtx(thread_manager=None))
        result = _tree_command(agent)
        assert isinstance(result, CommandResult)
        assert "not available" in result.output

    def test_tree_command_with_manager(self) -> None:
        from attocode.commands import _tree_command
        mgr = _mgr_with_forks()
        agent = _FakeAgent(_FakeCtx(thread_manager=mgr))
        result = _tree_command(agent)
        assert isinstance(result, CommandResult)
        assert "main" in result.output
        assert "[active]" in result.output

    def test_tree_command_no_context(self) -> None:
        from attocode.commands import _tree_command
        agent = _FakeAgent(ctx=None)
        result = _tree_command(agent)
        assert "not available" in result.output


# ===========================================================================
# QW3: Thread/fork persistence via SessionAPI
# ===========================================================================


class TestThreadPersistence:
    @pytest.fixture
    async def session_api(self, tmp_path):
        from attocode.agent.session_api import SessionAPI
        api = SessionAPI(tmp_path)
        yield api
        await api.close()

    @pytest.mark.asyncio
    async def test_save_and_load_with_thread_manager(self, session_api) -> None:
        """Thread manager state round-trips through save/load."""
        mgr = ThreadManager(session_id="s1")
        mgr.add_message({"role": "user", "content": "hello"})
        fork = mgr.create_fork(label="Branch")
        mgr.switch_thread(fork.thread_id)
        mgr.add_message({"role": "user", "content": "branched"})

        # Save session with thread manager
        await session_api.save_session(
            session_id="s1",
            task="test task",
            messages=[{"role": "user", "content": "hello"}],
            thread_manager=mgr,
        )

        # Load session
        snapshot = await session_api.load_session("s1")
        assert snapshot is not None
        assert snapshot.metadata is not None
        assert "thread_manager" in snapshot.metadata

        # Restore thread manager from metadata
        restored_mgr = ThreadManager.from_dict(snapshot.metadata["thread_manager"])
        assert restored_mgr._session_id == "s1"
        assert restored_mgr.active_thread_id == fork.thread_id
        assert restored_mgr.thread_count == 2
        assert len(restored_mgr.get_messages("main")) == 1
        # Fork inherited "hello" + added "branched"
        assert len(restored_mgr.get_messages(fork.thread_id)) == 2

    @pytest.mark.asyncio
    async def test_save_without_thread_manager(self, session_api) -> None:
        """Saving without thread_manager does not add thread_manager key."""
        await session_api.save_session(
            session_id="s2",
            task="no threads",
            messages=[{"role": "user", "content": "hi"}],
        )

        snapshot = await session_api.load_session("s2")
        assert snapshot is not None
        # metadata should be None or not contain thread_manager
        if snapshot.metadata:
            assert "thread_manager" not in snapshot.metadata

    @pytest.mark.asyncio
    async def test_thread_state_survives_multiple_saves(self, session_api) -> None:
        """Thread state updates correctly across multiple saves."""
        mgr = ThreadManager(session_id="s3")
        mgr.add_message({"role": "user", "content": "msg1"})

        # First save - just main thread
        await session_api.save_session(
            session_id="s3",
            task="evolving",
            messages=[{"role": "user", "content": "msg1"}],
            thread_manager=mgr,
        )

        # Create a fork and save again
        fork = mgr.create_fork(label="New branch")
        mgr.switch_thread(fork.thread_id)
        mgr.add_message({"role": "user", "content": "fork msg"})

        await session_api.save_session(
            session_id="s3",
            task="evolving",
            messages=[{"role": "user", "content": "msg1"}],
            thread_manager=mgr,
        )

        # Load and verify latest state
        snapshot = await session_api.load_session("s3")
        assert snapshot is not None
        assert snapshot.metadata is not None
        restored = ThreadManager.from_dict(snapshot.metadata["thread_manager"])
        assert restored.thread_count == 2
        assert restored.active_thread_id == fork.thread_id

    @pytest.mark.asyncio
    async def test_complex_tree_persists(self, session_api) -> None:
        """A complex tree structure round-trips correctly."""
        mgr = _mgr_with_forks()
        tree_before = mgr.get_thread_tree()

        await session_api.save_session(
            session_id="s4",
            task="complex tree",
            messages=[],
            thread_manager=mgr,
        )

        snapshot = await session_api.load_session("s4")
        assert snapshot is not None
        assert snapshot.metadata is not None
        restored = ThreadManager.from_dict(snapshot.metadata["thread_manager"])

        tree_after = restored.get_thread_tree()
        # Same structure: same parents map to same number of children
        assert set(tree_before.keys()) == set(tree_after.keys())
        for parent, children in tree_before.items():
            assert len(children) == len(tree_after[parent])

    @pytest.mark.asyncio
    async def test_session_snapshot_metadata_field(self, session_api) -> None:
        """SessionSnapshot.metadata field is populated from DB."""
        from attocode.agent.session_api import SessionSnapshot
        mgr = ThreadManager(session_id="s5")

        await session_api.save_session(
            session_id="s5",
            task="meta test",
            messages=[],
            thread_manager=mgr,
        )

        snapshot = await session_api.load_session("s5")
        assert snapshot is not None
        assert isinstance(snapshot, SessionSnapshot)
        assert snapshot.metadata is not None
        assert isinstance(snapshot.metadata, dict)
