"""Tests for quality module: LearningStore, SelfImprovementProtocol, AutoCheckpointManager, HealthChecker."""

from __future__ import annotations

import asyncio
import time

import pytest

from attocode.integrations.quality.learning_store import (
    Learning,
    LearningProposal,
    LearningStatus,
    LearningStore,
    LearningStoreConfig,
    LearningType,
    _extract_keywords,
    format_learnings_context,
)
from attocode.integrations.quality.self_improvement import (
    FailureCategory,
    SelfImprovementConfig,
    SelfImprovementProtocol,
)
from attocode.integrations.quality.auto_checkpoint import (
    AutoCheckpointManager,
    Checkpoint,
    CheckpointConfig,
)
from attocode.integrations.quality.health_check import (
    HealthChecker,
    HealthCheckerConfig,
    HealthCheckResult,
    HealthReport,
    format_health_report,
)


# ──────────────────────────────────────────────────────────────────────
# LearningStore
# ──────────────────────────────────────────────────────────────────────


class TestLearningStore:
    """Tests for LearningStore."""

    def _make_store(self, **kwargs) -> LearningStore:
        """Create an in-memory LearningStore for testing."""
        cfg = LearningStoreConfig(in_memory=True, **kwargs)
        return LearningStore(cfg)

    def _make_proposal(self, **kwargs) -> LearningProposal:
        """Create a default LearningProposal for testing."""
        defaults = {
            "type": LearningType.PATTERN,
            "description": "Always verify file path exists before editing",
            "details": "Use glob or list_files to confirm existence.",
            "confidence": 0.5,
        }
        defaults.update(kwargs)
        return LearningProposal(**defaults)

    # --- propose_learning ---

    def test_propose_learning_creates_learning(self) -> None:
        store = self._make_store()
        proposal = self._make_proposal()
        learning = store.propose_learning(proposal)

        assert learning.id.startswith("learn-")
        assert learning.type == LearningType.PATTERN
        assert learning.description == proposal.description
        assert learning.details == proposal.details
        assert learning.confidence == 0.5
        assert learning.apply_count == 0
        assert learning.help_count == 0
        store.close()

    def test_propose_learning_default_status_proposed(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(confidence=0.5))
        assert learning.status == LearningStatus.PROPOSED
        store.close()

    def test_propose_learning_auto_validate_high_confidence(self) -> None:
        store = self._make_store(auto_validate_threshold=0.9)
        learning = store.propose_learning(self._make_proposal(confidence=0.95))
        assert learning.status == LearningStatus.VALIDATED
        store.close()

    def test_propose_learning_auto_validate_at_threshold(self) -> None:
        store = self._make_store(auto_validate_threshold=0.9)
        learning = store.propose_learning(self._make_proposal(confidence=0.9))
        assert learning.status == LearningStatus.VALIDATED
        store.close()

    def test_propose_learning_below_threshold_stays_proposed(self) -> None:
        store = self._make_store(auto_validate_threshold=0.9)
        learning = store.propose_learning(self._make_proposal(confidence=0.89))
        assert learning.status == LearningStatus.PROPOSED
        store.close()

    def test_propose_learning_no_validation_required(self) -> None:
        store = self._make_store(require_validation=False)
        learning = store.propose_learning(self._make_proposal(confidence=0.1))
        assert learning.status == LearningStatus.VALIDATED
        store.close()

    def test_propose_learning_auto_extracts_keywords(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(
            description="Always verify file path exists before editing",
            keywords=None,
        ))
        assert len(learning.keywords) > 0
        assert "always" in learning.keywords
        store.close()

    def test_propose_learning_with_explicit_keywords(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(
            keywords=["file", "path", "verify"],
        ))
        assert learning.keywords == ["file", "path", "verify"]
        store.close()

    def test_propose_learning_with_categories_and_actions(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(
            categories=["file_ops"],
            actions=["edit_file", "read_file"],
        ))
        assert learning.categories == ["file_ops"]
        assert learning.actions == ["edit_file", "read_file"]
        store.close()

    # --- validate_learning ---

    def test_validate_learning_approve(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal())
        assert learning.status == LearningStatus.PROPOSED

        result = store.validate_learning(learning.id, approved=True)
        assert result is True

        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.status == LearningStatus.VALIDATED
        store.close()

    def test_validate_learning_reject(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal())

        result = store.validate_learning(learning.id, approved=False, reason="Not useful")
        assert result is True

        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.status == LearningStatus.REJECTED
        assert updated.user_notes == "Not useful"
        store.close()

    def test_validate_learning_nonexistent_returns_false(self) -> None:
        store = self._make_store()
        result = store.validate_learning("nonexistent-id", approved=True)
        assert result is False
        store.close()

    def test_validate_learning_already_validated_returns_false(self) -> None:
        store = self._make_store(auto_validate_threshold=0.5)
        learning = store.propose_learning(self._make_proposal(confidence=0.95))
        assert learning.status == LearningStatus.VALIDATED

        result = store.validate_learning(learning.id, approved=True)
        assert result is False
        store.close()

    # --- record_apply ---

    def test_record_apply_increments_count(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal())

        store.record_apply(learning.id, context="test context")
        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.apply_count == 1

        store.record_apply(learning.id)
        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.apply_count == 2
        store.close()

    def test_record_apply_nonexistent_returns_false(self) -> None:
        store = self._make_store()
        result = store.record_apply("nonexistent-id")
        assert result is False
        store.close()

    # --- record_helped ---

    def test_record_helped_increments_help_count(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(confidence=0.5))

        store.record_helped(learning.id)
        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.help_count == 1
        store.close()

    def test_record_helped_boosts_confidence(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(confidence=0.5))

        store.record_helped(learning.id)
        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.55, abs=0.001)
        store.close()

    def test_record_helped_caps_confidence_at_1(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal(confidence=0.98))

        store.record_helped(learning.id)
        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.confidence <= 1.0
        store.close()

    def test_record_helped_nonexistent_returns_false(self) -> None:
        store = self._make_store()
        result = store.record_helped("nonexistent-id")
        assert result is False
        store.close()

    # --- get_validated_learnings / get_pending_learnings ---

    def test_get_validated_learnings(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(description="Learning 1"))
        l2 = store.propose_learning(self._make_proposal(description="Learning 2"))
        store.validate_learning(l1.id, approved=True)

        validated = store.get_validated_learnings()
        assert len(validated) == 1
        assert validated[0].id == l1.id
        store.close()

    def test_get_pending_learnings(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(description="Learning 1"))
        l2 = store.propose_learning(self._make_proposal(description="Learning 2"))
        store.validate_learning(l1.id, approved=True)

        pending = store.get_pending_learnings()
        assert len(pending) == 1
        assert pending[0].id == l2.id
        store.close()

    def test_get_validated_ordered_by_confidence_desc(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(confidence=0.6, description="Low"))
        l2 = store.propose_learning(self._make_proposal(confidence=0.8, description="High"))
        store.validate_learning(l1.id, approved=True)
        store.validate_learning(l2.id, approved=True)

        validated = store.get_validated_learnings()
        assert len(validated) == 2
        assert validated[0].confidence >= validated[1].confidence
        store.close()

    # --- retrieve_relevant ---

    def test_retrieve_relevant_with_like_fallback(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(
            description="Fix file permission errors on macOS",
        ))
        store.validate_learning(l1.id, approved=True)

        results = store.retrieve_relevant("permission")
        assert len(results) >= 1
        assert any("permission" in r.description.lower() for r in results)
        store.close()

    def test_retrieve_relevant_empty_query(self) -> None:
        store = self._make_store()
        store.propose_learning(self._make_proposal())
        results = store.retrieve_relevant("")
        # Empty query with LIKE %% matches everything validated
        # But our learning is proposed, not validated
        assert isinstance(results, list)
        store.close()

    def test_retrieve_relevant_no_match(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(description="About file paths"))
        store.validate_learning(l1.id, approved=True)

        results = store.retrieve_relevant("quantum_physics_xyz_nonexistent")
        assert len(results) == 0
        store.close()

    def test_retrieve_relevant_respects_limit(self) -> None:
        store = self._make_store()
        for i in range(5):
            l = store.propose_learning(self._make_proposal(
                description=f"Common pattern number {i}",
            ))
            store.validate_learning(l.id, approved=True)

        results = store.retrieve_relevant("pattern", limit=2)
        assert len(results) <= 2
        store.close()

    # --- retrieve_by_category / retrieve_by_action ---

    def test_retrieve_by_category(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(
            categories=["file_ops", "editing"],
        ))
        store.validate_learning(l1.id, approved=True)
        l2 = store.propose_learning(self._make_proposal(
            categories=["networking"],
        ))
        store.validate_learning(l2.id, approved=True)

        results = store.retrieve_by_category("file_ops")
        assert len(results) == 1
        assert results[0].id == l1.id
        store.close()

    def test_retrieve_by_action(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(
            actions=["edit_file", "read_file"],
        ))
        store.validate_learning(l1.id, approved=True)

        results = store.retrieve_by_action("edit_file")
        assert len(results) == 1
        assert results[0].id == l1.id
        store.close()

    def test_retrieve_by_action_no_match(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(actions=["bash"]))
        store.validate_learning(l1.id, approved=True)

        results = store.retrieve_by_action("edit_file")
        assert len(results) == 0
        store.close()

    # --- get_learning_context ---

    def test_get_learning_context_by_query(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(
            description="Always check path before editing files",
        ))
        store.validate_learning(l1.id, approved=True)

        ctx = store.get_learning_context(query="path editing")
        assert "path" in ctx.lower() or "editing" in ctx.lower()
        store.close()

    def test_get_learning_context_by_category(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(categories=["testing"]))
        store.validate_learning(l1.id, approved=True)

        ctx = store.get_learning_context(categories=["testing"])
        assert len(ctx) > 0
        store.close()

    def test_get_learning_context_by_action(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(actions=["bash"]))
        store.validate_learning(l1.id, approved=True)

        ctx = store.get_learning_context(actions=["bash"])
        assert len(ctx) > 0
        store.close()

    def test_get_learning_context_empty(self) -> None:
        store = self._make_store()
        ctx = store.get_learning_context(query="nothing_here")
        assert ctx == ""
        store.close()

    def test_get_learning_context_deduplicates(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(
            description="File path checking pattern",
            categories=["file_ops"],
            actions=["edit_file"],
        ))
        store.validate_learning(l1.id, approved=True)

        # Query + category + action all match the same learning
        ctx = store.get_learning_context(
            query="file path",
            categories=["file_ops"],
            actions=["edit_file"],
        )
        # Should appear only once in output (dedup by dict key)
        lines = [line for line in ctx.split("\n") if line.startswith("- ")]
        assert len(lines) == 1
        store.close()

    # --- archive_learning / delete_learning ---

    def test_archive_learning(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal())

        result = store.archive_learning(learning.id)
        assert result is True

        updated = store.get_learning(learning.id)
        assert updated is not None
        assert updated.status == LearningStatus.ARCHIVED
        store.close()

    def test_archive_nonexistent_returns_false(self) -> None:
        store = self._make_store()
        result = store.archive_learning("nonexistent-id")
        assert result is False
        store.close()

    def test_delete_learning(self) -> None:
        store = self._make_store()
        learning = store.propose_learning(self._make_proposal())

        result = store.delete_learning(learning.id)
        assert result is True

        assert store.get_learning(learning.id) is None
        store.close()

    def test_delete_nonexistent_returns_false(self) -> None:
        store = self._make_store()
        result = store.delete_learning("nonexistent-id")
        assert result is False
        store.close()

    # --- get_stats ---

    def test_get_stats(self) -> None:
        store = self._make_store()
        l1 = store.propose_learning(self._make_proposal(description="L1"))
        l2 = store.propose_learning(self._make_proposal(
            description="L2", type=LearningType.WORKAROUND,
        ))
        store.validate_learning(l1.id, approved=True)

        stats = store.get_stats()
        assert stats["total"] == 2
        assert LearningStatus.VALIDATED in stats["by_status"]
        assert stats["by_status"][LearningStatus.VALIDATED] == 1
        assert stats["by_status"][LearningStatus.PROPOSED] == 1
        assert LearningType.PATTERN in stats["by_type"]
        assert LearningType.WORKAROUND in stats["by_type"]
        store.close()

    def test_get_stats_empty_store(self) -> None:
        store = self._make_store()
        stats = store.get_stats()
        assert stats["total"] == 0
        assert stats["by_status"] == {}
        assert stats["by_type"] == {}
        store.close()

    # --- event listener ---

    def test_on_event_listener_proposed(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        store.on(lambda event, data: events.append((event, data)))
        store.propose_learning(self._make_proposal(confidence=0.5))

        assert len(events) == 1
        assert events[0][0] == "learning.proposed"
        store.close()

    def test_on_event_listener_validated(self) -> None:
        store = self._make_store(auto_validate_threshold=0.5)
        events: list[tuple[str, dict]] = []

        store.on(lambda event, data: events.append((event, data)))
        store.propose_learning(self._make_proposal(confidence=0.95))

        assert len(events) == 1
        assert events[0][0] == "learning.validated"
        store.close()

    def test_on_event_listener_validate_approve(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        learning = store.propose_learning(self._make_proposal())
        store.on(lambda event, data: events.append((event, data)))
        store.validate_learning(learning.id, approved=True)

        assert any(e[0] == "learning.validated" for e in events)
        store.close()

    def test_on_event_listener_validate_reject(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        learning = store.propose_learning(self._make_proposal())
        store.on(lambda event, data: events.append((event, data)))
        store.validate_learning(learning.id, approved=False)

        assert any(e[0] == "learning.rejected" for e in events)
        store.close()

    def test_on_event_listener_applied(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        learning = store.propose_learning(self._make_proposal())
        store.on(lambda event, data: events.append((event, data)))
        store.record_apply(learning.id, context="test")

        assert any(e[0] == "learning.applied" for e in events)
        store.close()

    def test_on_event_listener_helped(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        learning = store.propose_learning(self._make_proposal())
        store.on(lambda event, data: events.append((event, data)))
        store.record_helped(learning.id)

        assert any(e[0] == "learning.helped" for e in events)
        store.close()

    def test_on_unsubscribe(self) -> None:
        store = self._make_store()
        events: list[tuple[str, dict]] = []

        unsub = store.on(lambda event, data: events.append((event, data)))
        store.propose_learning(self._make_proposal(description="Before unsub"))
        assert len(events) == 1

        unsub()
        store.propose_learning(self._make_proposal(description="After unsub"))
        assert len(events) == 1  # No new event
        store.close()

    def test_on_listener_exception_does_not_crash(self) -> None:
        store = self._make_store()

        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("Listener error")

        store.on(bad_listener)
        # Should not raise
        store.propose_learning(self._make_proposal())
        store.close()

    # --- close ---

    def test_close(self) -> None:
        store = self._make_store()
        store.propose_learning(self._make_proposal())
        store.close()
        # After close, operations should raise
        with pytest.raises(Exception):
            store.propose_learning(self._make_proposal())

    # --- _extract_keywords ---

    def test_extract_keywords_removes_stop_words(self) -> None:
        keywords = _extract_keywords("the file should be verified before editing")
        assert "the" not in keywords
        assert "should" not in keywords
        # Words with len <= 3 are also removed
        assert "be" not in keywords

    def test_extract_keywords_filters_short_words(self) -> None:
        keywords = _extract_keywords("a big cat is on the mat")
        # "a", "is", "on", "the" are stop words or <= 3 chars
        # "big" and "cat" and "mat" are 3 chars, so filtered (>3 check)
        assert "big" not in keywords
        assert "cat" not in keywords

    def test_extract_keywords_deduplicates(self) -> None:
        keywords = _extract_keywords("verify the path, verify the file path")
        assert keywords.count("verify") == 1
        assert keywords.count("path") == 1

    def test_extract_keywords_max_10(self) -> None:
        text = " ".join(f"longword{i}" for i in range(20))
        keywords = _extract_keywords(text)
        assert len(keywords) <= 10

    # --- format_learnings_context ---

    def test_format_learnings_context_empty(self) -> None:
        result = format_learnings_context([])
        assert result == ""

    def test_format_learnings_context_with_learnings(self) -> None:
        learnings = [
            Learning(
                id="learn-001",
                created_at=time.time(),
                updated_at=time.time(),
                type=LearningType.PATTERN,
                status=LearningStatus.VALIDATED,
                description="Check paths before editing",
                details="Use glob to verify existence.",
                confidence=0.85,
            ),
            Learning(
                id="learn-002",
                created_at=time.time(),
                updated_at=time.time(),
                type=LearningType.GOTCHA,
                status=LearningStatus.VALIDATED,
                description="macOS sandbox blocks network",
                confidence=0.7,
            ),
        ]
        result = format_learnings_context(learnings)
        assert "[Previous Learnings]" in result
        assert "[pattern]" in result
        assert "[gotcha]" in result
        assert "85%" in result
        assert "70%" in result
        assert "Check paths before editing" in result
        assert "Use glob to verify existence." in result

    def test_format_learnings_context_all_types(self) -> None:
        for ltype in LearningType:
            learning = Learning(
                id=f"learn-{ltype.value}",
                created_at=time.time(),
                updated_at=time.time(),
                type=ltype,
                status=LearningStatus.VALIDATED,
                description=f"Learning of type {ltype.value}",
                confidence=0.5,
            )
            result = format_learnings_context([learning])
            assert f"[{ltype.value}]" in result


# ──────────────────────────────────────────────────────────────────────
# SelfImprovementProtocol
# ──────────────────────────────────────────────────────────────────────


class TestSelfImprovementProtocol:
    """Tests for SelfImprovementProtocol."""

    def _make_protocol(self, **kwargs) -> SelfImprovementProtocol:
        config = SelfImprovementConfig(**kwargs)
        return SelfImprovementProtocol(config)

    # --- diagnose_tool_failure ---

    def test_diagnose_file_not_found(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "edit_file",
            {"path": "/nonexistent.py"},
            "ENOENT: no such file or directory",
        )
        assert diag.category == FailureCategory.FILE_NOT_FOUND
        assert "does not exist" in diag.diagnosis.lower()

    def test_diagnose_permission_error(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "bash",
            {"command": "rm /root/file"},
            "PermissionError: permission denied",
        )
        assert diag.category == FailureCategory.PERMISSION

    def test_diagnose_timeout(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "bash",
            {"command": "sleep 1000"},
            "Command timed out after 60s",
        )
        assert diag.category == FailureCategory.TIMEOUT

    def test_diagnose_syntax_error(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "bash",
            {"command": "python -c 'def'"},
            "SyntaxError: unexpected EOF while parsing",
        )
        assert diag.category == FailureCategory.SYNTAX_ERROR

    def test_diagnose_missing_args(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "edit_file",
            {"path": "/file.py"},
            "required field 'new_string' is missing",
        )
        assert diag.category == FailureCategory.MISSING_ARGS

    def test_diagnose_wrong_args(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "edit_file",
            {"path": 123},
            "TypeError: expected string, got int",
        )
        assert diag.category == FailureCategory.WRONG_ARGS

    def test_diagnose_state_error(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "edit_file",
            {"path": "/file.py", "old_string": "abc"},
            "old_string not found in file",
        )
        assert diag.category == FailureCategory.STATE_ERROR

    def test_diagnose_blocked_command(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "bash",
            {"command": "sudo rm -rf /"},
            "command blocked by security policy",
        )
        assert diag.category == FailureCategory.PERMISSION

    def test_diagnose_schema_validation_error(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "edit_file",
            {"path": 42},
            "Expected string, received number",
        )
        assert diag.category == FailureCategory.WRONG_ARGS

    def test_diagnose_unknown_error(self) -> None:
        proto = self._make_protocol()
        diag = proto.diagnose_tool_failure(
            "custom_tool",
            {},
            "Something completely unexpected happened",
        )
        assert diag.category == FailureCategory.UNKNOWN

    def test_diagnose_increments_failure_count(self) -> None:
        proto = self._make_protocol()
        proto.diagnose_tool_failure("bash", {}, "error1")
        proto.diagnose_tool_failure("bash", {}, "error2")
        assert proto.get_failure_count("bash") == 2

    def test_diagnose_caches_results(self) -> None:
        proto = self._make_protocol()
        d1 = proto.diagnose_tool_failure("bash", {}, "ENOENT: no such file")
        d2 = proto.diagnose_tool_failure("bash", {}, "ENOENT: no such file")
        # Same object from cache
        assert d1 is d2

    # --- record_success ---

    def test_record_success_resets_failure_count(self) -> None:
        proto = self._make_protocol()
        proto.diagnose_tool_failure("bash", {}, "error1")
        proto.diagnose_tool_failure("bash", {}, "error2")
        assert proto.get_failure_count("bash") == 2

        proto.record_success("bash", {"command": "ls"})
        assert proto.get_failure_count("bash") == 0

    def test_record_success_tracks_pattern(self) -> None:
        proto = self._make_protocol()
        proto.record_success("bash", {"command": "ls", "timeout": 60})

        patterns = proto.get_success_patterns("bash")
        assert len(patterns) == 1
        assert patterns[0].arg_pattern == {"command": "str", "timeout": "int"}
        assert patterns[0].count == 1

    def test_record_success_increments_existing_pattern(self) -> None:
        proto = self._make_protocol()
        proto.record_success("bash", {"command": "ls"})
        proto.record_success("bash", {"command": "pwd"})  # Same arg types

        patterns = proto.get_success_patterns("bash")
        assert len(patterns) == 1
        assert patterns[0].count == 2

    def test_record_success_different_patterns(self) -> None:
        proto = self._make_protocol()
        proto.record_success("bash", {"command": "ls"})
        proto.record_success("bash", {"command": "ls", "timeout": 30})

        patterns = proto.get_success_patterns("bash")
        assert len(patterns) == 2

    # --- is_repeatedly_failing ---

    def test_is_repeatedly_failing_false_initially(self) -> None:
        proto = self._make_protocol()
        assert proto.is_repeatedly_failing("bash") is False

    def test_is_repeatedly_failing_false_under_threshold(self) -> None:
        proto = self._make_protocol()
        proto.diagnose_tool_failure("bash", {}, "error")
        proto.diagnose_tool_failure("bash", {}, "error")
        assert proto.is_repeatedly_failing("bash") is False

    def test_is_repeatedly_failing_true_at_3(self) -> None:
        proto = self._make_protocol()
        for _ in range(3):
            proto.diagnose_tool_failure("bash", {}, "error")
        assert proto.is_repeatedly_failing("bash") is True

    def test_is_repeatedly_failing_true_above_3(self) -> None:
        proto = self._make_protocol()
        for _ in range(5):
            proto.diagnose_tool_failure("bash", {}, "error")
        assert proto.is_repeatedly_failing("bash") is True

    # --- enhance_error_message ---

    def test_enhance_error_message_adds_diagnosis(self) -> None:
        proto = self._make_protocol()
        enhanced = proto.enhance_error_message(
            "edit_file",
            "ENOENT: no such file or directory",
            {"path": "/missing.py"},
        )
        assert "ENOENT" in enhanced
        assert "Diagnosis:" in enhanced
        assert "Suggestion:" in enhanced

    def test_enhance_error_message_unknown_error(self) -> None:
        proto = self._make_protocol()
        enhanced = proto.enhance_error_message(
            "custom",
            "Very weird error without known pattern",
            {},
        )
        # Unknown errors still return the original error, no Diagnosis line
        assert "Very weird error" in enhanced
        assert "Diagnosis:" not in enhanced

    def test_enhance_error_message_with_repeated_failures(self) -> None:
        proto = self._make_protocol()
        # Pre-fail 3 times
        for _ in range(3):
            proto.diagnose_tool_failure("bash", {}, "timeout error")

        enhanced = proto.enhance_error_message(
            "bash",
            "timeout error",
            {},
        )
        assert "Warning:" in enhanced
        assert "failed" in enhanced.lower()
        assert "different approach" in enhanced.lower()

    def test_enhance_error_message_disabled(self) -> None:
        proto = self._make_protocol(enable_diagnosis=False)
        error = "ENOENT: file not found"
        enhanced = proto.enhance_error_message("bash", error, {})
        assert enhanced == error

    # --- get_success_patterns ---

    def test_get_success_patterns_empty(self) -> None:
        proto = self._make_protocol()
        assert proto.get_success_patterns("unknown_tool") == []

    # --- cache eviction ---

    def test_cache_eviction_after_max(self) -> None:
        proto = self._make_protocol(max_diagnosis_cache=15)

        # Fill cache beyond max
        for i in range(20):
            proto.diagnose_tool_failure("tool", {}, f"unique_error_{i}")

        # Cache should have been evicted down
        assert len(proto._diagnosis_cache) <= 15


# ──────────────────────────────────────────────────────────────────────
# AutoCheckpointManager
# ──────────────────────────────────────────────────────────────────────


class TestAutoCheckpointManager:
    """Tests for AutoCheckpointManager."""

    def _make_manager(self, **config_kwargs) -> AutoCheckpointManager:
        config = CheckpointConfig(**config_kwargs)
        return AutoCheckpointManager(config=config)

    # --- check_and_save ---

    def test_check_and_save_respects_interval(self) -> None:
        mgr = self._make_manager(interval_seconds=999)
        # First call: not enough time elapsed
        result = mgr.check_and_save(iteration=1)
        assert result is None

    def test_check_and_save_after_interval(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        # interval_seconds=0 means always save
        result = mgr.check_and_save(iteration=1, description="test")
        assert result is not None
        assert isinstance(result, Checkpoint)
        assert result.iteration == 1

    def test_check_and_save_force(self) -> None:
        mgr = self._make_manager(interval_seconds=999)
        result = mgr.check_and_save(iteration=5, description="Forced", force=True)
        assert result is not None
        assert "Forced" in result.description

    def test_check_and_save_default_description(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        result = mgr.check_and_save(iteration=3)
        assert result is not None
        assert "iteration 3" in result.description

    def test_check_and_save_updates_last_checkpoint_time(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        mgr.check_and_save(iteration=1)

        # Second call with long interval should not trigger
        mgr._config.interval_seconds = 999
        result = mgr.check_and_save(iteration=2)
        assert result is None

    # --- on_milestone ---

    def test_on_milestone_triggers_checkpoint(self) -> None:
        mgr = self._make_manager()
        result = mgr.on_milestone(iteration=10, description="Task completed")
        assert result is not None
        assert "Milestone:" in result.description
        assert "Task completed" in result.description

    def test_on_milestone_disabled(self) -> None:
        mgr = self._make_manager(on_milestone=False)
        result = mgr.on_milestone(iteration=10, description="Task completed")
        assert result is None

    # --- on_tool_batch_complete ---

    def test_on_tool_batch_complete_triggers_for_3_plus_tools(self) -> None:
        mgr = self._make_manager()
        result = mgr.on_tool_batch_complete(iteration=5, tool_count=3)
        assert result is not None
        assert "3 tool calls" in result.description

    def test_on_tool_batch_complete_skips_under_3_tools(self) -> None:
        mgr = self._make_manager()
        result = mgr.on_tool_batch_complete(iteration=5, tool_count=2)
        assert result is None

    def test_on_tool_batch_complete_disabled(self) -> None:
        mgr = self._make_manager(on_tool_batch=False)
        result = mgr.on_tool_batch_complete(iteration=5, tool_count=10)
        assert result is None

    # --- max_checkpoints eviction ---

    def test_max_checkpoints_eviction(self) -> None:
        mgr = self._make_manager(max_checkpoints=3, interval_seconds=0.0)

        for i in range(5):
            mgr.check_and_save(iteration=i, force=True)

        assert mgr.checkpoint_count == 3
        # Oldest should have been evicted
        ids = [cp.iteration for cp in mgr.checkpoints]
        assert 0 not in ids
        assert 1 not in ids
        assert 4 in ids

    # --- set_saver ---

    def test_set_saver_callback(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        saved_calls: list[tuple[int, str]] = []

        def my_saver(iteration: int, description: str) -> str:
            saved_calls.append((iteration, description))
            return f"custom-cp-{iteration}"

        mgr.set_saver(my_saver)
        result = mgr.check_and_save(iteration=42, description="Custom save")
        assert result is not None
        assert result.id == "custom-cp-42"
        assert len(saved_calls) == 1
        assert saved_calls[0] == (42, "Custom save")

    def test_saver_exception_returns_none(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)

        def failing_saver(iteration: int, description: str) -> str:
            raise RuntimeError("Save failed!")

        mgr.set_saver(failing_saver)
        result = mgr.check_and_save(iteration=1, force=True)
        assert result is None

    # --- properties ---

    def test_checkpoints_property(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        mgr.check_and_save(iteration=1, force=True)
        mgr.check_and_save(iteration=2, force=True)

        cps = mgr.checkpoints
        assert len(cps) == 2
        # Returned list should be a copy
        cps.clear()
        assert mgr.checkpoint_count == 2

    def test_last_checkpoint_property(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        assert mgr.last_checkpoint is None

        mgr.check_and_save(iteration=1, force=True)
        mgr.check_and_save(iteration=2, force=True)
        assert mgr.last_checkpoint is not None
        assert mgr.last_checkpoint.iteration == 2

    # --- clear ---

    def test_clear(self) -> None:
        mgr = self._make_manager(interval_seconds=0.0)
        mgr.check_and_save(iteration=1, force=True)
        mgr.check_and_save(iteration=2, force=True)
        assert mgr.checkpoint_count == 2

        mgr.clear()
        assert mgr.checkpoint_count == 0
        assert mgr.last_checkpoint is None


# ──────────────────────────────────────────────────────────────────────
# HealthChecker
# ──────────────────────────────────────────────────────────────────────


class TestHealthChecker:
    """Tests for HealthChecker."""

    def _make_checker(self, **kwargs) -> HealthChecker:
        config = HealthCheckerConfig(**kwargs)
        return HealthChecker(config)

    # --- register / unregister ---

    def test_register_check(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        assert "db" in hc.get_check_names()

    def test_unregister_check(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        result = hc.unregister("db")
        assert result is True
        assert "db" not in hc.get_check_names()

    def test_unregister_nonexistent(self) -> None:
        hc = self._make_checker()
        result = hc.unregister("nonexistent")
        assert result is False

    # --- check (async) ---

    @pytest.mark.asyncio
    async def test_check_healthy(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        result = await hc.check("db")
        assert result.healthy is True
        assert result.name == "db"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_unhealthy(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: False)
        result = await hc.check("db")
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_check_async_callable(self) -> None:
        hc = self._make_checker()

        async def async_check() -> bool:
            return True

        hc.register("async_db", async_check)
        result = await hc.check("async_db")
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_check_async_unhealthy(self) -> None:
        hc = self._make_checker()

        async def async_check() -> bool:
            return False

        hc.register("async_db", async_check)
        result = await hc.check("async_db")
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_check_exception(self) -> None:
        hc = self._make_checker()

        def failing_check() -> bool:
            raise ConnectionError("Connection refused")

        hc.register("db", failing_check)
        result = await hc.check("db")
        assert result.healthy is False
        assert "Connection refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_check_async_timeout(self) -> None:
        hc = self._make_checker()

        async def slow_check() -> bool:
            await asyncio.sleep(10)
            return True

        hc.register("slow", slow_check, timeout=0.1)
        result = await hc.check("slow")
        assert result.healthy is False
        assert "Timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_check_not_registered(self) -> None:
        hc = self._make_checker()
        result = await hc.check("nonexistent")
        assert result.healthy is False
        assert "not registered" in (result.error or "")

    # --- check_all ---

    @pytest.mark.asyncio
    async def test_check_all_parallel(self) -> None:
        hc = self._make_checker(parallel=True)
        hc.register("db", lambda: True)
        hc.register("cache", lambda: True)
        hc.register("disk", lambda: False)

        report = await hc.check_all()
        assert isinstance(report, HealthReport)
        assert report.total_count == 3
        assert report.healthy_count == 2
        assert report.healthy is False  # disk is unhealthy

    @pytest.mark.asyncio
    async def test_check_all_serial(self) -> None:
        hc = self._make_checker(parallel=False)
        hc.register("db", lambda: True)
        hc.register("cache", lambda: True)

        report = await hc.check_all()
        assert report.total_count == 2
        assert report.healthy_count == 2
        assert report.healthy is True

    @pytest.mark.asyncio
    async def test_check_all_empty(self) -> None:
        hc = self._make_checker()
        report = await hc.check_all()
        assert report.total_count == 0
        assert report.healthy is True  # Vacuously true

    @pytest.mark.asyncio
    async def test_check_all_latency(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        report = await hc.check_all()
        assert report.total_latency_ms >= 0

    # --- is_healthy ---

    @pytest.mark.asyncio
    async def test_is_healthy_no_results(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True, critical=True)
        # No checks run yet, no last results -> healthy by default
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_critical_failing(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: False, critical=True)
        await hc.check("db")
        assert hc.is_healthy() is False

    @pytest.mark.asyncio
    async def test_is_healthy_non_critical_failing(self) -> None:
        hc = self._make_checker()
        hc.register("cache", lambda: False, critical=False)
        await hc.check("cache")
        # Non-critical failure doesn't affect is_healthy
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_mixed(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True, critical=True)
        hc.register("cache", lambda: False, critical=False)
        await hc.check_all()
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_critical_mixed(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True, critical=True)
        hc.register("queue", lambda: False, critical=True)
        await hc.check_all()
        assert hc.is_healthy() is False

    # --- get_unhealthy_checks ---

    @pytest.mark.asyncio
    async def test_get_unhealthy_checks(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        hc.register("cache", lambda: False)
        hc.register("disk", lambda: False)
        await hc.check_all()

        unhealthy = hc.get_unhealthy_checks()
        assert "cache" in unhealthy
        assert "disk" in unhealthy
        assert "db" not in unhealthy

    @pytest.mark.asyncio
    async def test_get_unhealthy_checks_empty(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        await hc.check_all()

        unhealthy = hc.get_unhealthy_checks()
        assert len(unhealthy) == 0

    # --- status change detection events ---

    @pytest.mark.asyncio
    async def test_status_change_event(self) -> None:
        hc = self._make_checker()
        events: list[tuple[str, dict]] = []
        hc.on(lambda event, data: events.append((event, data)))

        healthy_state = {"value": True}

        def toggle_check() -> bool:
            return healthy_state["value"]

        hc.register("db", toggle_check)

        # First check: healthy
        await hc.check("db")
        status_changes = [e for e in events if e[0] == "status.changed"]
        assert len(status_changes) == 0  # No previous result, no change

        # Second check: unhealthy
        healthy_state["value"] = False
        events.clear()
        await hc.check("db")
        status_changes = [e for e in events if e[0] == "status.changed"]
        assert len(status_changes) == 1
        assert status_changes[0][1]["from_healthy"] is True
        assert status_changes[0][1]["to_healthy"] is False

        # Third check: healthy again
        healthy_state["value"] = True
        events.clear()
        await hc.check("db")
        status_changes = [e for e in events if e[0] == "status.changed"]
        assert len(status_changes) == 1
        assert status_changes[0][1]["from_healthy"] is False
        assert status_changes[0][1]["to_healthy"] is True

    @pytest.mark.asyncio
    async def test_check_started_and_completed_events(self) -> None:
        hc = self._make_checker()
        events: list[tuple[str, dict]] = []
        hc.on(lambda event, data: events.append((event, data)))

        hc.register("db", lambda: True)
        await hc.check("db")

        event_types = [e[0] for e in events]
        assert "check.started" in event_types
        assert "check.completed" in event_types

    @pytest.mark.asyncio
    async def test_report_generated_event(self) -> None:
        hc = self._make_checker()
        events: list[tuple[str, dict]] = []
        hc.on(lambda event, data: events.append((event, data)))

        hc.register("db", lambda: True)
        await hc.check_all()

        event_types = [e[0] for e in events]
        assert "report.generated" in event_types

    def test_on_unsubscribe(self) -> None:
        hc = self._make_checker()
        events: list[tuple[str, dict]] = []
        unsub = hc.on(lambda event, data: events.append((event, data)))
        unsub()
        # Listener should be removed
        assert len(hc._listeners) == 0

    # --- format_health_report ---

    @pytest.mark.asyncio
    async def test_format_health_report_healthy(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        hc.register("cache", lambda: True)
        report = await hc.check_all()

        formatted = format_health_report(report)
        assert "HEALTHY" in formatted
        assert "2/2" in formatted
        assert "[ok] db" in formatted
        assert "[ok] cache" in formatted

    @pytest.mark.asyncio
    async def test_format_health_report_unhealthy(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)

        def failing() -> bool:
            raise ConnectionError("refused")

        hc.register("cache", failing)
        report = await hc.check_all()

        formatted = format_health_report(report)
        assert "UNHEALTHY" in formatted
        assert "1/2" in formatted
        assert "[FAIL] cache" in formatted
        assert "refused" in formatted

    @pytest.mark.asyncio
    async def test_format_health_report_empty(self) -> None:
        hc = self._make_checker()
        report = await hc.check_all()
        formatted = format_health_report(report)
        assert "HEALTHY" in formatted
        assert "0/0" in formatted

    # --- dispose ---

    def test_dispose(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        hc.on(lambda event, data: None)

        hc.dispose()
        assert len(hc.get_check_names()) == 0
        assert len(hc._listeners) == 0
        assert len(hc._last_results) == 0

    # --- get_last_result / get_all_last_results ---

    @pytest.mark.asyncio
    async def test_get_last_result(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        await hc.check("db")

        result = hc.get_last_result("db")
        assert result is not None
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_get_last_result_not_run(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        result = hc.get_last_result("db")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_last_results(self) -> None:
        hc = self._make_checker()
        hc.register("db", lambda: True)
        hc.register("cache", lambda: False)
        await hc.check_all()

        results = hc.get_all_last_results()
        assert len(results) == 2
        assert results["db"].healthy is True
        assert results["cache"].healthy is False

    # --- listener exception safety ---

    @pytest.mark.asyncio
    async def test_listener_exception_does_not_crash(self) -> None:
        hc = self._make_checker()

        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("Listener kaboom")

        hc.on(bad_listener)
        hc.register("db", lambda: True)
        # Should not raise
        result = await hc.check("db")
        assert result.healthy is True
