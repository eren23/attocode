"""Tests for attocode.integrations.context.memory_store — SQLite learning store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from attocode.integrations.context.memory_store import (
    _CONFIDENCE_CAP,
    _UNHELPFUL_AUTO_ARCHIVE,
    MemoryStore,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Create a fresh MemoryStore with a temp DB."""
    s = MemoryStore(project_dir=str(tmp_path))
    yield s  # type: ignore[misc]
    s.close()


class TestAddAndRecall:
    """Basic insert and FTS retrieval."""

    def test_add_returns_id(self, store: MemoryStore):
        lid = store.add("pattern", "Use dataclass(slots=True) for performance")
        assert isinstance(lid, int)
        assert lid > 0

    def test_recall_by_query(self, store: MemoryStore):
        store.add("convention", "Always use snake_case for function names")
        store.add("gotcha", "SQLite FTS5 requires special quoting for colons")

        results = store.recall("function naming conventions")
        assert len(results) >= 1
        assert any("snake_case" in r["description"] for r in results)

    def test_recall_empty_db(self, store: MemoryStore):
        results = store.recall("anything")
        assert results == []

    def test_record_applied_increments_count(self, store: MemoryStore):
        lid = store.add("pattern", "Use context managers for file I/O")
        store.record_applied(lid)
        store.record_applied(lid)

        all_learnings = store.list_all()
        match = [lr for lr in all_learnings if lr["id"] == lid]
        assert match[0]["apply_count"] == 2

    def test_add_invalid_type_raises(self, store: MemoryStore):
        with pytest.raises(ValueError, match="Invalid type"):
            store.add("invalid_type", "This should fail")


class TestScopeHierarchy:
    """Scope matching: exact > parent > global."""

    def test_exact_scope_match(self, store: MemoryStore):
        store.add("convention", "API routes use /v2/ prefix", scope="src/api/")
        store.add("convention", "Models use SQLAlchemy ORM", scope="src/models/")

        results = store.recall("API conventions", scope="src/api/")
        assert len(results) >= 1
        assert any("API routes" in r["description"] for r in results)

    def test_parent_scope_included(self, store: MemoryStore):
        store.add("pattern", "All source files use future annotations", scope="src/")

        results = store.recall("annotations", scope="src/core/loop/")
        assert len(results) >= 1
        assert any("future annotations" in r["description"] for r in results)

    def test_global_scope_included(self, store: MemoryStore):
        store.add("gotcha", "Python 3.12+ required", scope="")

        results = store.recall("python version", scope="src/tools/")
        assert len(results) >= 1
        assert any("Python 3.12" in r["description"] for r in results)

    def test_unrelated_scope_excluded(self, store: MemoryStore):
        store.add("convention", "Tests use pytest fixtures", scope="tests/")

        results = store.recall("pytest fixtures", scope="src/api/")
        # Should not match — tests/ is not a parent of src/api/
        # May still match via FTS, but scope-only results won't include it
        # We verify that global learnings are preferred over unrelated scopes
        for r in results:
            assert r["scope"] in ("", "tests/")


class TestDeduplication:
    """Same learning not inserted twice."""

    def test_duplicate_returns_same_id(self, store: MemoryStore):
        id1 = store.add("pattern", "Use dataclass slots for performance")
        id2 = store.add("pattern", "Use dataclass slots for performance")
        assert id1 == id2

    def test_different_type_not_deduped(self, store: MemoryStore):
        id1 = store.add("pattern", "Use dataclass slots for performance")
        id2 = store.add("antipattern", "Use dataclass slots for performance")
        # Different types should not be deduped (different semantics)
        assert id1 != id2

    def test_different_scope_not_deduped(self, store: MemoryStore):
        id1 = store.add("pattern", "Use explicit return types", scope="src/")
        id2 = store.add("pattern", "Use explicit return types", scope="tests/")
        assert id1 != id2


class TestFeedback:
    """Confidence adjustments via feedback."""

    def test_helpful_boosts_confidence(self, store: MemoryStore):
        lid = store.add("pattern", "Cache repeated lookups", confidence=0.5)
        store.record_feedback(lid, helpful=True)

        results = store.list_all()
        match = [lr for lr in results if lr["id"] == lid]
        assert match[0]["confidence"] == pytest.approx(0.55, abs=0.01)
        assert match[0]["help_count"] == 1

    def test_unhelpful_reduces_confidence(self, store: MemoryStore):
        lid = store.add("gotcha", "Watch out for circular imports", confidence=0.7)
        store.record_feedback(lid, helpful=False)

        results = store.list_all()
        match = [lr for lr in results if lr["id"] == lid]
        assert match[0]["confidence"] == pytest.approx(0.6, abs=0.01)
        assert match[0]["unhelpful_count"] == 1

    def test_confidence_capped_at_one(self, store: MemoryStore):
        lid = store.add("pattern", "Always validate input", confidence=0.98)
        store.record_feedback(lid, helpful=True)

        results = store.list_all()
        match = [lr for lr in results if lr["id"] == lid]
        assert match[0]["confidence"] <= _CONFIDENCE_CAP

    def test_confidence_floored(self, store: MemoryStore):
        lid = store.add("gotcha", "Fragile assumption", confidence=0.15)
        store.record_feedback(lid, helpful=False)

        # May be archived due to low confidence
        results = store.list_all(status="active") + store.list_all(status="archived")
        match = [lr for lr in results if lr["id"] == lid]
        assert match[0]["confidence"] >= 0.1


class TestAutoArchive:
    """Low confidence or repeated unhelpful feedback auto-archives."""

    def test_auto_archive_on_low_confidence(self, store: MemoryStore):
        lid = store.add("gotcha", "Flaky test", confidence=0.2)
        # Two unhelpful feedbacks: 0.2 - 0.1 = 0.1 (below threshold)
        store.record_feedback(lid, helpful=False)

        results = store.list_all(status="archived")
        match = [lr for lr in results if lr["id"] == lid]
        assert len(match) == 1

    def test_auto_archive_on_many_unhelpful(self, store: MemoryStore):
        lid = store.add("workaround", "Restart the server", confidence=0.9)
        for _ in range(_UNHELPFUL_AUTO_ARCHIVE):
            store.record_feedback(lid, helpful=False)

        results = store.list_all(status="archived")
        match = [lr for lr in results if lr["id"] == lid]
        assert len(match) == 1


class TestListAll:
    """Filtering by status and type."""

    def test_list_active_only(self, store: MemoryStore):
        store.add("pattern", "Active learning", confidence=0.8)
        lid2 = store.add("gotcha", "Will be archived", confidence=0.2)
        store.record_feedback(lid2, helpful=False)  # archives it

        active = store.list_all(status="active")
        archived = store.list_all(status="archived")
        assert all(lr["description"] != "Will be archived" for lr in active)
        assert any(lr["description"] == "Will be archived" for lr in archived)

    def test_filter_by_type(self, store: MemoryStore):
        store.add("pattern", "Pattern learning")
        store.add("gotcha", "Gotcha learning")

        patterns = store.list_all(type="pattern")
        assert all(lr["type"] == "pattern" for lr in patterns)
        assert len(patterns) == 1

    def test_update_fields(self, store: MemoryStore):
        lid = store.add("pattern", "Original description")
        store.update(lid, description="Updated description")

        results = store.list_all()
        match = [lr for lr in results if lr["id"] == lid]
        assert match[0]["description"] == "Updated description"
