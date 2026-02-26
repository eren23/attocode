"""Dynamic model info cache fetched from OpenRouter API.

Port of TS ``openrouter-pricing.ts``.  Module-level cache populated once
at startup via :func:`init_model_cache`, then consumed synchronously by
:func:`get_cached_context_length` and :func:`get_cached_pricing`.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from attocode.providers.base import ModelPricing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_pricing_cache: dict[str, ModelPricing] = {}
_context_cache: dict[str, int] = {}
_cache_timestamp: float = 0.0
_CACHE_TTL: float = 3600.0  # 1 hour


# ---------------------------------------------------------------------------
# Async init (called once at startup)
# ---------------------------------------------------------------------------

async def init_model_cache() -> None:
    """Fetch model data from OpenRouter and populate caches.

    Safe to call multiple times — skips if the cache is still fresh.
    Fails silently when ``OPENROUTER_API_KEY`` is unset or the request
    errors out so the agent can fall back to built-in data.
    """
    global _pricing_cache, _context_cache, _cache_timestamp  # noqa: PLW0603

    now = time.monotonic()
    if _pricing_cache and now - _cache_timestamp < _CACHE_TTL:
        return  # cache still fresh

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.debug("No OPENROUTER_API_KEY — skipping dynamic model cache")
        return

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.debug("Failed to fetch OpenRouter models: %s", exc)
        return

    models = data.get("data", [])
    if not models:
        return

    pricing: dict[str, ModelPricing] = {}
    context: dict[str, int] = {}

    for model in models:
        model_id: str = model.get("id", "")
        if not model_id:
            continue

        raw_pricing = model.get("pricing") or {}
        # OpenRouter returns per-token prices as strings — multiply by 1M
        # to match our ModelPricing (cost per million tokens).
        try:
            prompt_per_token = float(raw_pricing.get("prompt", "0"))
            completion_per_token = float(raw_pricing.get("completion", "0"))
        except (ValueError, TypeError):
            prompt_per_token = 0.0
            completion_per_token = 0.0

        pricing[model_id] = ModelPricing(
            input_per_million=prompt_per_token * 1_000_000,
            output_per_million=completion_per_token * 1_000_000,
        )

        ctx_len = model.get("context_length")
        if ctx_len and isinstance(ctx_len, int):
            context[model_id] = ctx_len

    if pricing:
        _pricing_cache = pricing
        _context_cache = context
        _cache_timestamp = now
        logger.debug("Loaded %d models from OpenRouter", len(pricing))


# ---------------------------------------------------------------------------
# Sync lookups (used at runtime)
# ---------------------------------------------------------------------------

def _fuzzy_lookup(model_id: str, cache: dict[str, object]) -> str | None:
    """Return the cache key that best matches *model_id*, or ``None``.

    Resolution order:
    1. Exact match
    2. ``model_id`` appears as the suffix after ``/`` in a cache key
       (e.g. ``"claude-sonnet-4-20250514"`` → ``"anthropic/claude-sonnet-4-20250514"``)
    3. Cache key suffix (after ``/``) starts with the base of *model_id*
       stripped of its date suffix.
    """
    if model_id in cache:
        return model_id

    # Strip provider prefix from the query for matching
    short_id = model_id.rsplit("/", 1)[-1]

    for key in cache:
        key_short = key.rsplit("/", 1)[-1]
        if key_short == short_id:
            return key
        if key.endswith(short_id) or short_id in key:
            return key

    return None


def get_cached_context_length(model_id: str) -> int | None:
    """Return context window from the dynamic cache, or ``None``."""
    key = _fuzzy_lookup(model_id, _context_cache)
    if key is not None:
        return _context_cache[key]
    return None


def get_cached_pricing(model_id: str) -> ModelPricing | None:
    """Return pricing from the dynamic cache, or ``None``."""
    key = _fuzzy_lookup(model_id, _pricing_cache)
    if key is not None:
        return _pricing_cache[key]
    return None


def is_cache_initialized() -> bool:
    """Return whether the dynamic cache has been populated."""
    return len(_pricing_cache) > 0


def clear_cache() -> None:
    """Reset all caches — for test isolation."""
    global _pricing_cache, _context_cache, _cache_timestamp  # noqa: PLW0603
    _pricing_cache = {}
    _context_cache = {}
    _cache_timestamp = 0.0
