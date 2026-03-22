"""Tests for the unified model catalog with fuzzy search."""

from __future__ import annotations

import pytest

from attocode.providers.base import ModelInfo, ModelPricing
from attocode.providers.catalog import (
    CatalogEntry,
    ModelCatalog,
    format_model_table,
)


@pytest.fixture()
def catalog() -> ModelCatalog:
    """Create a fresh catalog and load it."""
    cat = ModelCatalog()
    cat.load()
    return cat


class TestModelCatalog:
    """Tests for ModelCatalog."""

    def test_load_populates_entries(self, catalog: ModelCatalog) -> None:
        """Catalog should have models after loading."""
        assert catalog.count > 0

    def test_list_all_models(self, catalog: ModelCatalog) -> None:
        """list_models returns entries."""
        entries = catalog.list_models()
        assert len(entries) > 0
        assert all(isinstance(e, CatalogEntry) for e in entries)

    def test_list_with_provider_filter(self, catalog: ModelCatalog) -> None:
        """list_models with provider filter returns only that provider's models."""
        entries = catalog.list_models(provider="anthropic")
        assert all(e.provider == "anthropic" for e in entries)

    def test_list_with_limit(self, catalog: ModelCatalog) -> None:
        """list_models respects limit."""
        entries = catalog.list_models(limit=3)
        assert len(entries) <= 3

    def test_search_exact_match(self, catalog: ModelCatalog) -> None:
        """Exact model ID search returns high score."""
        results = catalog.search("claude-sonnet-4")
        assert len(results) > 0
        entry, score = results[0]
        assert "claude" in entry.model_id.lower()
        assert "sonnet" in entry.model_id.lower()
        assert score > 0.5

    def test_search_fuzzy_match(self, catalog: ModelCatalog) -> None:
        """Fuzzy search works with partial queries."""
        results = catalog.search("opus")
        assert len(results) > 0
        # Should find claude-opus
        model_ids = [e.model_id for e, _ in results]
        assert any("opus" in mid.lower() for mid in model_ids)

    def test_search_no_results(self, catalog: ModelCatalog) -> None:
        """Searching for nonsense returns empty."""
        results = catalog.search("xyznonexistent12345")
        assert len(results) == 0

    def test_search_with_provider_filter(self, catalog: ModelCatalog) -> None:
        """Search respects provider filter."""
        results = catalog.search("gpt", provider="openai")
        for entry, _ in results:
            assert entry.provider == "openai"

    def test_get_existing_model(self, catalog: ModelCatalog) -> None:
        """get returns entry for known model."""
        # Use a model from PROVIDER_MODEL_OPTIONS
        entry = catalog.get("claude-sonnet-4-20250514")
        assert entry is not None
        assert entry.provider == "anthropic"

    def test_get_nonexistent_model(self, catalog: ModelCatalog) -> None:
        """get returns None for unknown model."""
        entry = catalog.get("nonexistent-model-xyz")
        assert entry is None

    def test_refresh_reloads(self, catalog: ModelCatalog) -> None:
        """refresh reloads the catalog."""
        count_before = catalog.count
        catalog.refresh()
        # Should have same or more models after refresh
        assert catalog.count >= count_before

    def test_catalog_entry_price_display(self) -> None:
        """CatalogEntry formats pricing correctly."""
        entry = CatalogEntry(
            model_id="test",
            provider="test",
            pricing=ModelPricing(input_per_million=3.0, output_per_million=15.0),
        )
        assert entry.price_display == "$3.00/$15.00"

    def test_catalog_entry_free_price(self) -> None:
        """CatalogEntry shows free for zero pricing."""
        entry = CatalogEntry(model_id="test", provider="test")
        assert entry.price_display == "free/unknown"


class TestFormatModelTable:
    """Tests for format_model_table."""

    def test_format_entries(self) -> None:
        """Formats entries as table."""
        entries = [
            CatalogEntry(
                model_id="claude-sonnet-4",
                provider="anthropic",
                context_window=200_000,
                pricing=ModelPricing(input_per_million=3.0, output_per_million=15.0),
            ),
        ]
        table = format_model_table(entries)
        assert "claude-sonnet-4" in table
        assert "anthropic" in table
        assert "200K" in table

    def test_format_with_current_marker(self) -> None:
        """Current model gets asterisk marker."""
        entries = [
            CatalogEntry(model_id="my-model", provider="test"),
        ]
        table = format_model_table(entries, current_model="my-model")
        assert "* my-model" in table

    def test_format_empty(self) -> None:
        """Empty list returns message."""
        table = format_model_table([])
        assert "No models found" in table

    def test_format_scored_results(self) -> None:
        """Scored results show score column."""
        entries = [
            (CatalogEntry(model_id="test", provider="test"), 0.85),
        ]
        table = format_model_table(entries, show_score=True)
        assert "0.85" in table
