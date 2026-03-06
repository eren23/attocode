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

from attocode.providers.base import BUILTIN_MODELS, KNOWN_PRICING, MODEL_CONTEXT_WINDOWS, ModelPricing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_pricing_cache: dict[str, ModelPricing] = {}
_context_cache: dict[str, int] = {}
_capabilities_cache: dict[str, set[str]] = {}
_cache_timestamp: float = 0.0
_CACHE_TTL: float = 3600.0  # 1 hour

# Models known to support vision even without dynamic cache data
_KNOWN_VISION_MODELS: set[str] = {
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
    "claude-sonnet-4-20250514", "claude-opus-4-20250514",
    "claude-haiku-4-20250414", "claude-haiku-3-5-20241022",
    "google/gemini-2.0-flash", "google/gemini-2.5-pro-preview",
    "glm-4.6v", "glm-4.5v",  # ZAI vision models
}


# ---------------------------------------------------------------------------
# Async init (called once at startup)
# ---------------------------------------------------------------------------

async def init_model_cache() -> None:
    """Fetch model data from OpenRouter and populate caches.

    Safe to call multiple times — skips if the cache is still fresh.
    Fails silently when the request errors out so the agent can fall
    back to built-in data.  The OpenRouter ``/api/v1/models`` endpoint
    works without authentication; ``OPENROUTER_API_KEY`` is sent when
    available (helps with rate limits) but is not required.
    """
    global _pricing_cache, _context_cache, _capabilities_cache, _cache_timestamp  # noqa: PLW0603

    now = time.monotonic()
    if _pricing_cache and now - _cache_timestamp < _CACHE_TTL:
        return  # cache still fresh

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers=headers,
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
    capabilities: dict[str, set[str]] = {}

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

        # Extract capabilities from architecture.input_modalities
        arch = model.get("architecture") or {}
        input_mods = arch.get("input_modalities") or []
        caps: set[str] = set()
        if "image" in input_mods:
            caps.add("vision")
        if "audio" in input_mods:
            caps.add("audio")
        if caps:
            capabilities[model_id] = caps

    if pricing:
        _pricing_cache = pricing
        _context_cache = context
        _capabilities_cache = capabilities
        _cache_timestamp = now
        logger.debug("Loaded %d models from OpenRouter", len(pricing))
        _reconcile_builtin_models()


# ---------------------------------------------------------------------------
# Reconciliation — keep BUILTIN_MODELS in sync with live data
# ---------------------------------------------------------------------------

def _reconcile_builtin_models() -> None:
    """Update stale ``BUILTIN_MODELS`` entries from the dynamic cache.

    Called automatically after a successful cache fetch.  For each builtin
    model, if the dynamic cache has a different context window or pricing,
    the builtin entry is patched in-place and a warning is logged so
    developers know the hardcoded value drifted.
    """
    for model_id, info in BUILTIN_MODELS.items():
        # Context window
        ctx_key = _fuzzy_lookup(model_id, _context_cache)
        if ctx_key is not None:
            live_ctx = _context_cache[ctx_key]
            # Sanity guard: skip if the live value is suspiciously small,
            # which would indicate bad/anomalous API data from OpenRouter.
            if live_ctx < 1024:
                logger.warning(
                    "%s: skipping anomalous context_length %d from OpenRouter",
                    model_id,
                    live_ctx,
                )
                continue
            if live_ctx != info.max_context_tokens:
                logger.warning(
                    "%s: builtin context %d → %d (synced from OpenRouter)",
                    model_id,
                    info.max_context_tokens,
                    live_ctx,
                )
                info.max_context_tokens = live_ctx
                MODEL_CONTEXT_WINDOWS[model_id] = live_ctx

        # Pricing
        price_key = _fuzzy_lookup(model_id, _pricing_cache)
        if price_key is not None:
            live_price = _pricing_cache[price_key]
            if (
                live_price.input_per_million != info.pricing.input_per_million
                or live_price.output_per_million != info.pricing.output_per_million
            ):
                logger.warning(
                    "%s: builtin pricing in=%.2f/out=%.2f → in=%.2f/out=%.2f (synced from OpenRouter)",
                    model_id,
                    info.pricing.input_per_million,
                    info.pricing.output_per_million,
                    live_price.input_per_million,
                    live_price.output_per_million,
                )
                info.pricing = live_price
                KNOWN_PRICING[model_id] = live_price

        # Vision capability
        cap_key = _fuzzy_lookup(model_id, _capabilities_cache)
        if cap_key is not None and "vision" in _capabilities_cache[cap_key]:
            from attocode.providers.base import ProviderCapability
            if ProviderCapability.VISION not in info.capabilities:
                info.capabilities.add(ProviderCapability.VISION)
                logger.debug("%s: added VISION capability from OpenRouter", model_id)


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


def get_cached_capabilities(model_id: str) -> set[str] | None:
    """Return capabilities from the dynamic cache, or ``None``."""
    key = _fuzzy_lookup(model_id, _capabilities_cache)
    if key is not None:
        return _capabilities_cache[key]
    return None


def is_vision_capable(model_id: str) -> bool:
    """Check if a model supports vision input.

    Checks the dynamic cache first, then falls back to a known set.
    """
    caps = get_cached_capabilities(model_id)
    if caps is not None:
        return "vision" in caps
    # Fall back to known vision models
    short_id = model_id.rsplit("/", 1)[-1]
    return model_id in _KNOWN_VISION_MODELS or short_id in _KNOWN_VISION_MODELS


def is_cache_initialized() -> bool:
    """Return whether the dynamic cache has been populated."""
    return len(_pricing_cache) > 0


def clear_cache() -> None:
    """Reset all caches — for test isolation."""
    global _pricing_cache, _context_cache, _capabilities_cache, _cache_timestamp  # noqa: PLW0603
    _pricing_cache = {}
    _context_cache = {}
    _capabilities_cache = {}
    _cache_timestamp = 0.0
