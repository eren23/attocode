"""Tests for the dynamic model cache (OpenRouter API fetch)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.providers.base import (
    BUILTIN_MODELS,
    DEFAULT_CONTEXT_WINDOW,
    KNOWN_PRICING,
    MODEL_CONTEXT_WINDOWS,
    ModelPricing,
    get_model_context_window,
    get_model_pricing,
)
from attocode.providers.model_cache import (
    clear_cache,
    get_cached_context_length,
    get_cached_pricing,
    init_model_cache,
    is_cache_initialized,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure each test starts with a clean cache."""
    clear_cache()
    yield
    clear_cache()


# Sample OpenRouter API response (minimal)
OPENROUTER_RESPONSE = {
    "data": [
        {
            "id": "anthropic/claude-sonnet-4",
            "name": "Claude Sonnet 4",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
        },
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            "context_length": 128000,
        },
        {
            "id": "zhipu/glm-5",
            "name": "GLM-5",
            "pricing": {"prompt": "0.0000005", "completion": "0.000001"},
            "context_length": 128000,
        },
    ],
}


def _make_mock_client(response_data: dict) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns *response_data* as JSON."""
    # Use MagicMock for the response because httpx Response.json() is sync
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestInitModelCache:
    @pytest.mark.asyncio
    async def test_works_without_api_key(self) -> None:
        """Cache should populate even without OPENROUTER_API_KEY (public endpoint)."""
        mock_client = _make_mock_client(OPENROUTER_RESPONSE)

        with patch.dict("os.environ", {}, clear=True):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()

        assert is_cache_initialized()
        assert get_cached_context_length("anthropic/claude-sonnet-4") == 200_000

    @pytest.mark.asyncio
    async def test_populates_cache_on_success(self) -> None:
        mock_client = _make_mock_client(OPENROUTER_RESPONSE)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()

        assert is_cache_initialized()
        assert get_cached_context_length("anthropic/claude-sonnet-4") == 200_000
        assert get_cached_context_length("openai/gpt-4o") == 128_000

    @pytest.mark.asyncio
    async def test_fails_silently_on_network_error(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()  # should not raise

        assert not is_cache_initialized()

    @pytest.mark.asyncio
    async def test_respects_ttl(self) -> None:
        """Second call within TTL should be a no-op."""
        mock_client = _make_mock_client(OPENROUTER_RESPONSE)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()
                await init_model_cache()  # should skip

        # Only one HTTP call
        assert mock_client.get.call_count == 1


class TestCachedLookups:
    @pytest.fixture(autouse=True)
    async def _populate(self) -> None:
        mock_client = _make_mock_client(OPENROUTER_RESPONSE)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()

    def test_exact_match(self) -> None:
        assert get_cached_context_length("anthropic/claude-sonnet-4") == 200_000

    def test_fuzzy_match_strips_prefix(self) -> None:
        # "claude-sonnet-4" should match "anthropic/claude-sonnet-4"
        result = get_cached_context_length("claude-sonnet-4")
        assert result == 200_000

    def test_pricing_conversion(self) -> None:
        pricing = get_cached_pricing("anthropic/claude-sonnet-4")
        assert pricing is not None
        # 0.000003 per token * 1M = 3.0 per million
        assert abs(pricing.input_per_million - 3.0) < 0.01
        assert abs(pricing.output_per_million - 15.0) < 0.01

    def test_returns_none_for_unknown(self) -> None:
        assert get_cached_context_length("some/unknown-model") is None
        assert get_cached_pricing("some/unknown-model") is None


class TestThreeTierResolution:
    """Test the full resolution chain in get_model_context_window / get_model_pricing."""

    def test_builtin_fallback_without_cache(self) -> None:
        # No cache populated — should fall back to BUILTIN_MODELS
        assert get_model_context_window("claude-sonnet-4-20250514") == 200_000
        assert get_model_context_window("gpt-4o") == 128_000

    def test_default_for_unknown_model(self) -> None:
        assert get_model_context_window("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW

    def test_pricing_fallback_without_cache(self) -> None:
        pricing = get_model_pricing("claude-sonnet-4-20250514")
        assert pricing.input_per_million == 3.0
        assert pricing.output_per_million == 15.0

    def test_zero_pricing_for_unknown(self) -> None:
        pricing = get_model_pricing("totally-unknown-model")
        assert pricing.input_per_million == 0.0
        assert pricing.output_per_million == 0.0

    def test_prefix_match_dated_variant(self) -> None:
        # "claude-opus-4-20260101" should match "claude-opus-4-20250514"
        assert get_model_context_window("claude-opus-4-20260101") == 200_000

    @pytest.mark.asyncio
    async def test_cache_takes_priority(self) -> None:
        """When cache is populated, its values take precedence over builtins."""
        mock_client = _make_mock_client({
            "data": [
                {
                    "id": "anthropic/claude-sonnet-4-20250514",
                    "name": "Claude Sonnet 4",
                    "pricing": {"prompt": "0.000005", "completion": "0.000025"},
                    "context_length": 250_000,  # different from builtin
                },
            ],
        })

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
                await init_model_cache()

        # Dynamic cache value should win over builtin 200_000
        assert get_model_context_window("claude-sonnet-4-20250514") == 250_000

    def test_clear_cache_resets(self) -> None:
        clear_cache()
        assert not is_cache_initialized()


class TestReconciliation:
    """Test that _reconcile_builtin_models() patches stale BUILTIN_MODELS entries."""

    @pytest.fixture(autouse=True)
    def _save_restore_glm5(self):
        """Save and restore glm-5 builtin entry so tests are isolated."""
        original = BUILTIN_MODELS["glm-5"]
        orig_ctx = original.max_context_tokens
        orig_output = original.max_output_tokens
        orig_pricing = original.pricing
        yield
        original.max_context_tokens = orig_ctx
        original.max_output_tokens = orig_output
        original.pricing = orig_pricing
        MODEL_CONTEXT_WINDOWS["glm-5"] = orig_ctx
        KNOWN_PRICING["glm-5"] = orig_pricing

    @pytest.mark.asyncio
    async def test_reconciles_builtin_models(self) -> None:
        """After init, stale BUILTIN_MODELS entries should be updated to match the dynamic cache."""
        response_with_updated_glm5 = {
            "data": [
                {
                    "id": "zhipu/glm-5",
                    "name": "GLM-5",
                    "pricing": {"prompt": "0.00000095", "completion": "0.00000255"},
                    "context_length": 204_800,
                },
            ],
        }
        mock_client = _make_mock_client(response_with_updated_glm5)

        # Force stale values (earlier tests may have already reconciled)
        glm5 = BUILTIN_MODELS["glm-5"]
        glm5.max_context_tokens = 128_000
        glm5.pricing = ModelPricing()
        MODEL_CONTEXT_WINDOWS["glm-5"] = 128_000
        KNOWN_PRICING["glm-5"] = ModelPricing()

        # Verify stale values
        assert BUILTIN_MODELS["glm-5"].max_context_tokens == 128_000
        assert BUILTIN_MODELS["glm-5"].pricing.input_per_million == 0.0

        with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
            await init_model_cache()

        # After reconciliation, builtin should reflect live data
        assert BUILTIN_MODELS["glm-5"].max_context_tokens == 204_800
        assert abs(BUILTIN_MODELS["glm-5"].pricing.input_per_million - 0.95) < 0.01
        assert abs(BUILTIN_MODELS["glm-5"].pricing.output_per_million - 2.55) < 0.01

        # Backward-compat aliases should also be updated
        assert MODEL_CONTEXT_WINDOWS["glm-5"] == 204_800
        assert abs(KNOWN_PRICING["glm-5"].input_per_million - 0.95) < 0.01

    @pytest.mark.asyncio
    async def test_skips_anomalous_context_values(self) -> None:
        """Anomalous context_length values (0, very small) should not corrupt BUILTIN_MODELS."""
        response_with_bad_ctx = {
            "data": [
                {
                    "id": "zhipu/glm-5",
                    "name": "GLM-5",
                    "pricing": {"prompt": "0.0000005", "completion": "0.000001"},
                    "context_length": 0,  # anomalous
                },
            ],
        }
        mock_client = _make_mock_client(response_with_bad_ctx)

        original_ctx = BUILTIN_MODELS["glm-5"].max_context_tokens

        with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
            await init_model_cache()

        # Context should NOT have been overwritten by the anomalous value
        assert BUILTIN_MODELS["glm-5"].max_context_tokens == original_ctx
        assert MODEL_CONTEXT_WINDOWS["glm-5"] == original_ctx

    @pytest.mark.asyncio
    async def test_no_reconciliation_on_fetch_failure(self) -> None:
        """If the API fetch fails, BUILTIN_MODELS should remain unchanged."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        original_ctx = BUILTIN_MODELS["glm-5"].max_context_tokens

        with patch("attocode.providers.model_cache.httpx.AsyncClient", return_value=mock_client):
            await init_model_cache()

        assert BUILTIN_MODELS["glm-5"].max_context_tokens == original_ctx
