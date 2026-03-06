"""Tests for TaskManager with DAG-based dependency tracking."""

from __future__ import annotations

from attocode.integrations.tasks.task_manager import TaskManager
from attocode.types.agent import PlanTask, TaskStatus


class TestCreateTask:
    def test_returns_task_id(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Do something")
        assert tid == "task-1"

    def test_sequential_ids(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second")
        t3 = tm.create_task("Third")
        assert t1 == "task-1"
        assert t2 == "task-2"
        assert t3 == "task-3"

    def test_task_has_pending_status(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Do something")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.PENDING

    def test_task_has_description(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Write unit tests")
        task = tm.get_task(tid)
        assert task is not None
        assert task.description == "Write unit tests"

    def test_task_with_metadata(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Task", metadata={"priority": "high"})
        node = tm.get_node(tid)
        assert node is not None
        assert node.metadata == {"priority": "high"}

    def test_get_task_nonexistent(self) -> None:
        tm = TaskManager()
        assert tm.get_task("task-999") is None

    def test_get_node_nonexistent(self) -> None:
        tm = TaskManager()
        assert tm.get_node("task-999") is None


class TestTaskStateTransitions:
    def test_pending_to_in_progress(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Work on it")
        assert tm.start_task(tid)
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.IN_PROGRESS

    def test_in_progress_to_completed(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Work on it")
        tm.start_task(tid)
        assert tm.complete_task(tid, result="Done!")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "Done!"

    def test_complete_without_starting(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Shortcut")
        # complete_task does not require IN_PROGRESS status
        assert tm.complete_task(tid, result="Skipped ahead")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED

    def test_start_task_records_agent_id(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Assigned work")
        tm.start_task(tid, agent_id="agent-42")
        node = tm.get_node(tid)
        assert node is not None
        assert node.agent_id == "agent-42"

    def test_start_task_records_started_at(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Timed")
        tm.start_task(tid)
        node = tm.get_node(tid)
        assert node is not None
        assert node.started_at is not None

    def test_complete_task_records_completed_at(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Timed")
        tm.start_task(tid)
        tm.complete_task(tid)
        node = tm.get_node(tid)
        assert node is not None
        assert node.completed_at is not None

    def test_start_nonexistent_returns_false(self) -> None:
        tm = TaskManager()
        assert tm.start_task("task-999") is False

    def test_complete_nonexistent_returns_false(self) -> None:
        tm = TaskManager()
        assert tm.complete_task("task-999") is False

    def test_cannot_start_completed_task(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Once")
        tm.start_task(tid)
        tm.complete_task(tid)
        assert tm.start_task(tid) is False

    def test_cannot_start_failed_task(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Broken")
        tm.start_task(tid)
        tm.fail_task(tid, error="Oops")
        assert tm.start_task(tid) is False


class TestDependencies:
    def test_task_with_unmet_dependency_is_blocked(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        task2 = tm.get_task(t2)
        assert task2 is not None
        assert task2.status == TaskStatus.BLOCKED

    def test_blocked_task_cannot_start(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        assert tm.start_task(t2) is False

    def test_completing_dependency_unblocks_dependent(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        # Before completing t1, t2 is blocked
        assert tm.get_task(t2).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        # Complete t1
        tm.start_task(t1)
        tm.complete_task(t1)
        # Now t2 should be unblocked (PENDING)
        assert tm.get_task(t2).status == TaskStatus.PENDING  # type: ignore[union-attr]

    def test_skipping_dependency_unblocks_dependent(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        tm.skip_task(t1)
        assert tm.get_task(t2).status == TaskStatus.PENDING  # type: ignore[union-attr]

    def test_chain_of_three(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Step 1")
        t2 = tm.create_task("Step 2", dependencies=[t1])
        t3 = tm.create_task("Step 3", dependencies=[t2])
        # t2 and t3 are blocked
        assert tm.get_task(t2).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        assert tm.get_task(t3).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        # Complete t1 -> t2 unblocks, t3 still blocked
        tm.complete_task(t1)
        assert tm.get_task(t2).status == TaskStatus.PENDING  # type: ignore[union-attr]
        assert tm.get_task(t3).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        # Complete t2 -> t3 unblocks
        tm.start_task(t2)
        tm.complete_task(t2)
        assert tm.get_task(t3).status == TaskStatus.PENDING  # type: ignore[union-attr]

    def test_multiple_dependencies(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Dep A")
        t2 = tm.create_task("Dep B")
        t3 = tm.create_task("Needs both", dependencies=[t1, t2])
        assert tm.get_task(t3).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        # Complete only t1 -> still blocked
        tm.complete_task(t1)
        assert tm.get_task(t3).status == TaskStatus.BLOCKED  # type: ignore[union-attr]
        # Complete t2 -> now unblocked
        tm.complete_task(t2)
        assert tm.get_task(t3).status == TaskStatus.PENDING  # type: ignore[union-attr]

    def test_missing_dependency_treated_as_met(self) -> None:
        tm = TaskManager()
        # Reference a dependency that doesn't exist
        tid = tm.create_task("Orphan dep", dependencies=["task-999"])
        # Missing deps are treated as met, so status should be PENDING
        assert tm.get_task(tid).status == TaskStatus.PENDING  # type: ignore[union-attr]


class TestGetReadyTasks:
    def test_returns_pending_with_no_deps(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Ready 1")
        t2 = tm.create_task("Ready 2")
        ready = tm.get_ready_tasks()
        ids = {t.id for t in ready}
        assert t1 in ids
        assert t2 in ids

    def test_excludes_blocked_tasks(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        ready = tm.get_ready_tasks()
        ids = {t.id for t in ready}
        assert t1 in ids
        assert t2 not in ids

    def test_excludes_in_progress_tasks(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Working")
        tm.start_task(t1)
        ready = tm.get_ready_tasks()
        assert len(ready) == 0

    def test_excludes_completed_tasks(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Done")
        tm.complete_task(t1)
        ready = tm.get_ready_tasks()
        assert len(ready) == 0

    def test_newly_unblocked_appears_ready(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        tm.complete_task(t1)
        ready = tm.get_ready_tasks()
        ids = {t.id for t in ready}
        assert t2 in ids

    def test_empty_manager_returns_empty(self) -> None:
        tm = TaskManager()
        assert tm.get_ready_tasks() == []


class TestFailAndSkip:
    def test_fail_task(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Will fail")
        tm.start_task(tid)
        assert tm.fail_task(tid, error="Boom")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        node = tm.get_node(tid)
        assert node is not None
        assert node.error == "Boom"

    def test_fail_nonexistent(self) -> None:
        tm = TaskManager()
        assert tm.fail_task("task-999") is False

    def test_fail_records_completed_at(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Fail timing")
        tm.fail_task(tid)
        node = tm.get_node(tid)
        assert node is not None
        assert node.completed_at is not None

    def test_skip_task(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Skippable")
        assert tm.skip_task(tid)
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.SKIPPED

    def test_skip_nonexistent(self) -> None:
        tm = TaskManager()
        assert tm.skip_task("task-999") is False

    def test_skip_records_completed_at(self) -> None:
        tm = TaskManager()
        tid = tm.create_task("Skip timing")
        tm.skip_task(tid)
        node = tm.get_node(tid)
        assert node is not None
        assert node.completed_at is not None


class TestGetAllAndByStatus:
    def test_get_all_tasks(self) -> None:
        tm = TaskManager()
        tm.create_task("A")
        tm.create_task("B")
        tm.create_task("C")
        all_tasks = tm.get_all_tasks()
        assert len(all_tasks) == 3
        assert [t.description for t in all_tasks] == ["A", "B", "C"]

    def test_get_tasks_by_status(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("Pending")
        t2 = tm.create_task("Will complete")
        t3 = tm.create_task("Also pending")
        tm.complete_task(t2)
        pending = tm.get_tasks_by_status(TaskStatus.PENDING)
        assert len(pending) == 2
        completed = tm.get_tasks_by_status(TaskStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].id == t2


class TestProperties:
    def test_total_tasks(self) -> None:
        tm = TaskManager()
        assert tm.total_tasks == 0
        tm.create_task("A")
        tm.create_task("B")
        assert tm.total_tasks == 2

    def test_completed_count(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        assert tm.completed_count == 0
        tm.complete_task(t1)
        assert tm.completed_count == 1
        tm.complete_task(t2)
        assert tm.completed_count == 2

    def test_pending_count_includes_blocked(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        tm.create_task("B", dependencies=[t1])
        # t1 is PENDING, t2 is BLOCKED, both counted as pending
        assert tm.pending_count == 2

    def test_in_progress_count(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        assert tm.in_progress_count == 0
        tm.start_task(t1)
        assert tm.in_progress_count == 1
        tm.start_task(t2)
        assert tm.in_progress_count == 2

    def test_failed_count(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        assert tm.failed_count == 0
        tm.fail_task(t1)
        assert tm.failed_count == 1

    def test_progress_empty(self) -> None:
        tm = TaskManager()
        assert tm.progress == 1.0

    def test_progress_none_complete(self) -> None:
        tm = TaskManager()
        tm.create_task("A")
        tm.create_task("B")
        assert tm.progress == 0.0

    def test_progress_partial(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        tm.create_task("B")
        tm.complete_task(t1)
        assert tm.progress == 0.5

    def test_progress_all_complete(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        tm.complete_task(t1)
        tm.complete_task(t2)
        assert tm.progress == 1.0

    def test_progress_includes_skipped(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        tm.complete_task(t1)
        tm.skip_task(t2)
        assert tm.progress == 1.0

    def test_is_complete_true(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        tm.complete_task(t1)
        tm.skip_task(t2)
        assert tm.is_complete is True

    def test_is_complete_false(self) -> None:
        tm = TaskManager()
        tm.create_task("A")
        assert tm.is_complete is False

    def test_is_complete_empty(self) -> None:
        tm = TaskManager()
        # All tasks (vacuously) are complete
        assert tm.is_complete is True


class TestSummaryAndClear:
    def test_summary_no_tasks(self) -> None:
        tm = TaskManager()
        assert tm.get_summary() == "No tasks."

    def test_summary_with_tasks(self) -> None:
        tm = TaskManager()
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        t3 = tm.create_task("C")
        tm.start_task(t1)
        tm.complete_task(t1)
        tm.start_task(t2)
        summary = tm.get_summary()
        assert "1/3 complete" in summary
        assert "1 in progress" in summary
        assert "1 pending" in summary
        assert "0 failed" in summary

    def test_clear(self) -> None:
        tm = TaskManager()
        tm.create_task("A")
        tm.create_task("B")
        tm.clear()
        assert tm.total_tasks == 0
        assert tm.get_all_tasks() == []

    def test_clear_resets_id_counter(self) -> None:
        tm = TaskManager()
        tm.create_task("A")
        tm.create_task("B")
        tm.clear()
        tid = tm.create_task("Fresh")
        assert tid == "task-1"
