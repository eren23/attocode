"""Unified model catalog with fuzzy search.

Merges static model lists (config.py, models.yaml) with dynamic
OpenRouter cache into a single searchable catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from attocode.config import PROVIDER_MODEL_OPTIONS
from attocode.providers.base import (
    BUILTIN_MODELS,
    ModelPricing,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CatalogEntry:
    """A model entry in the catalog."""

    model_id: str
    provider: str
    display_name: str = ""
    context_window: int = 0
    pricing: ModelPricing = field(default_factory=ModelPricing)
    source: str = ""  # "builtin", "openrouter", "static"

    @property
    def price_display(self) -> str:
        """Format pricing as $/M tokens string."""
        if self.pricing.input_per_million == 0 and self.pricing.output_per_million == 0:
            return "free/unknown"
        return f"${self.pricing.input_per_million:.2f}/${self.pricing.output_per_million:.2f}"


class ModelCatalog:
    """Unified model catalog with fuzzy search.

    Merges models from:
    1. BUILTIN_MODELS (models.yaml) — static fallback
    2. PROVIDER_MODEL_OPTIONS (config.py) — curated per-provider lists
    3. OpenRouter dynamic cache — 2000+ models when available
    """

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        self._loaded = False

    def load(self) -> None:
        """Load models from all sources."""
        self._entries.clear()

        # 1. Static provider model options (curated lists)
        for provider, models in PROVIDER_MODEL_OPTIONS.items():
            for model_id in models:
                self._entries[model_id] = CatalogEntry(
                    model_id=model_id,
                    provider=provider,
                    display_name=model_id.rsplit("/", 1)[-1],
                    source="static",
                )

        # 2. Built-in models (from models.yaml — has pricing & context)
        for model_id, info in BUILTIN_MODELS.items():
            if model_id in self._entries:
                # Enrich existing entry
                entry = self._entries[model_id]
                entry.context_window = info.max_context_tokens
                entry.pricing = info.pricing
                entry.source = "builtin"
            else:
                self._entries[model_id] = CatalogEntry(
                    model_id=model_id,
                    provider=info.provider,
                    display_name=info.display_name or model_id,
                    context_window=info.max_context_tokens,
                    pricing=info.pricing,
                    source="builtin",
                )

        # 3. Dynamic OpenRouter cache (if available)
        self._load_openrouter_cache()

        self._loaded = True
        logger.debug("Model catalog loaded: %d models", len(self._entries))

    def _load_openrouter_cache(self) -> None:
        """Merge in models from the OpenRouter dynamic cache."""
        from attocode.providers.model_cache import (
            _context_cache,
            _pricing_cache,
            is_cache_initialized,
        )

        if not is_cache_initialized():
            return

        for model_id, pricing in _pricing_cache.items():
            ctx_len = _context_cache.get(model_id, 0)
            # Determine provider from model_id prefix
            provider = model_id.split("/")[0] if "/" in model_id else "unknown"

            if model_id in self._entries:
                # Enrich existing entry with live data
                entry = self._entries[model_id]
                if ctx_len:
                    entry.context_window = ctx_len
                entry.pricing = pricing
            else:
                self._entries[model_id] = CatalogEntry(
                    model_id=model_id,
                    provider=provider,
                    display_name=model_id.rsplit("/", 1)[-1],
                    context_window=ctx_len,
                    pricing=pricing,
                    source="openrouter",
                )

    def refresh(self) -> None:
        """Reload catalog (e.g., after OpenRouter cache is refreshed)."""
        self.load()

    def list_models(
        self,
        *,
        provider: str | None = None,
        limit: int = 0,
    ) -> list[CatalogEntry]:
        """List all models, optionally filtered by provider."""
        if not self._loaded:
            self.load()

        entries = list(self._entries.values())
        if provider:
            entries = [e for e in entries if e.provider == provider]

        # Sort: builtin first, then by provider/model_id
        entries.sort(key=lambda e: (e.source != "builtin", e.provider, e.model_id))

        if limit > 0:
            entries = entries[:limit]
        return entries

    def search(
        self,
        query: str,
        *,
        provider: str | None = None,
        limit: int = 20,
    ) -> list[tuple[CatalogEntry, float]]:
        """Fuzzy search models by query string.

        Returns list of (entry, score) sorted by relevance.
        """
        if not self._loaded:
            self.load()

        from attocode.tui.widgets.command_palette import fuzzy_match

        results: list[tuple[CatalogEntry, float]] = []
        for entry in self._entries.values():
            if provider and entry.provider != provider:
                continue

            # Match against model_id and display_name
            id_score = fuzzy_match(query, entry.model_id)
            name_score = fuzzy_match(query, entry.display_name) * 0.9
            provider_bonus = fuzzy_match(query, entry.provider) * 0.3
            score = max(id_score, name_score) + provider_bonus * 0.1

            if score > 0.15:
                results.append((entry, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get(self, model_id: str) -> CatalogEntry | None:
        """Get a specific model by ID."""
        if not self._loaded:
            self.load()
        return self._entries.get(model_id)

    @property
    def count(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._entries)


# Module-level singleton
_catalog: ModelCatalog | None = None


def get_catalog() -> ModelCatalog:
    """Get the global model catalog (lazy-loaded)."""
    global _catalog  # noqa: PLW0603
    if _catalog is None:
        _catalog = ModelCatalog()
        _catalog.load()
    return _catalog


def format_model_table(
    entries: list[CatalogEntry] | list[tuple[CatalogEntry, float]],
    *,
    show_score: bool = False,
    current_model: str = "",
) -> str:
    """Format model entries as a table string."""
    if not entries:
        return "No models found."

    lines: list[str] = []
    header = f"  {'Model':<45} {'Provider':<12} {'Context':<10} {'Price (in/out $/M)':<20}"
    if show_score:
        header += f" {'Score':<6}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for item in entries:
        if isinstance(item, tuple):
            entry, score = item
        else:
            entry = item
            score = 0.0

        marker = "* " if entry.model_id == current_model else "  "
        ctx = f"{entry.context_window // 1000}K" if entry.context_window else "?"

        line = f"{marker}{entry.model_id:<45} {entry.provider:<12} {ctx:<10} {entry.price_display:<20}"
        if show_score:
            line += f" {score:.2f}"
        lines.append(line)

    return "\n".join(lines)
