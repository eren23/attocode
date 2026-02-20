"""Response handler - dispatches LLM calls with retry and error handling."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from attocode.errors import LLMError, ProviderError
from attocode.types.events import EventType
from attocode.types.messages import ChatOptions, ChatResponse, ToolDefinition


if __name__ != "__main__":
    from attocode.agent.context import AgentContext


# Default retry config
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 30.0


async def call_llm(
    ctx: AgentContext,
    *,
    max_retries: int = MAX_RETRIES,
    retry_base_delay: float = RETRY_BASE_DELAY,
) -> ChatResponse:
    """Call the LLM provider with retry logic.

    Builds ChatOptions from context config and tool definitions,
    then dispatches to the provider with exponential backoff on
    retryable errors.
    """
    # Build options
    options = ChatOptions(
        model=ctx.config.model,
        max_tokens=ctx.config.max_tokens,
        temperature=ctx.config.temperature,
        tools=ctx.registry.get_definitions() or None,
    )

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        if ctx.is_cancelled:
            raise asyncio.CancelledError("Agent cancelled during LLM call")

        ctx.emit_simple(
            EventType.LLM_START,
            iteration=ctx.iteration,
            metadata={"attempt": attempt + 1},
        )
        start = time.monotonic()

        try:
            response = await ctx.provider.chat(ctx.messages, options)
            duration = time.monotonic() - start

            # Record usage
            if response.usage:
                ctx.metrics.add_usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost=response.usage.cost,
                )

            ctx.emit_simple(
                EventType.LLM_COMPLETE,
                iteration=ctx.iteration,
                tokens=(response.usage.total_tokens if response.usage else 0),
                cost=(response.usage.cost if response.usage else 0),
                metadata={"duration_ms": duration * 1000},
            )

            return response

        except ProviderError as e:
            duration = time.monotonic() - start
            last_error = e
            ctx.emit_simple(
                EventType.LLM_ERROR,
                error=str(e),
                iteration=ctx.iteration,
                metadata={
                    "attempt": attempt + 1,
                    "retryable": e.retryable,
                    "status_code": e.status_code,
                    "duration_ms": duration * 1000,
                },
            )

            if not e.retryable or attempt >= max_retries:
                raise

            # Exponential backoff
            delay = min(retry_base_delay * (2 ** attempt), RETRY_MAX_DELAY)
            await asyncio.sleep(delay)

        except Exception as e:
            duration = time.monotonic() - start
            ctx.emit_simple(
                EventType.LLM_ERROR,
                error=str(e),
                iteration=ctx.iteration,
                metadata={"duration_ms": duration * 1000},
            )
            raise LLMError(f"Unexpected error during LLM call: {str(e) or repr(e) or type(e).__name__}") from e

    # Should not reach here, but just in case
    raise last_error or LLMError("LLM call failed after all retries")


async def call_llm_streaming(
    ctx: AgentContext,
    *,
    max_retries: int = MAX_RETRIES,
    retry_base_delay: float = RETRY_BASE_DELAY,
) -> ChatResponse:
    """Call the LLM provider with streaming, falling back to non-streaming.

    If the provider supports streaming (has ``chat_stream``), uses it and
    emits LLM_STREAM_START / LLM_STREAM_CHUNK / LLM_STREAM_END events.
    Otherwise falls back to the regular ``call_llm()``.
    """
    from attocode.providers.base import StreamingProvider
    from attocode.integrations.streaming.handler import StreamHandler

    if not isinstance(ctx.provider, StreamingProvider):
        return await call_llm(ctx, max_retries=max_retries, retry_base_delay=retry_base_delay)

    # Build options
    options = ChatOptions(
        model=ctx.config.model,
        max_tokens=ctx.config.max_tokens,
        temperature=ctx.config.temperature,
        tools=ctx.registry.get_definitions() or None,
    )

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        if ctx.is_cancelled:
            raise asyncio.CancelledError("Agent cancelled during LLM call")

        ctx.emit_simple(
            EventType.LLM_STREAM_START,
            iteration=ctx.iteration,
            metadata={"attempt": attempt + 1},
        )
        start = time.monotonic()

        try:
            stream = ctx.provider.chat_stream(ctx.messages, options)
            handler = StreamHandler()

            def _on_chunk(chunk: Any) -> None:
                from attocode.types.messages import StreamChunkType
                if chunk.type in (StreamChunkType.TEXT, StreamChunkType.THINKING):
                    ctx.emit_simple(
                        EventType.LLM_STREAM_CHUNK,
                        metadata={
                            "chunk_type": chunk.type.value,
                            "content": chunk.content or "",
                        },
                    )

            response = await handler.process_stream(stream, on_chunk=_on_chunk)
            duration = time.monotonic() - start

            # Record usage
            if response.usage:
                ctx.metrics.add_usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost=response.usage.cost,
                )

            ctx.emit_simple(
                EventType.LLM_STREAM_END,
                iteration=ctx.iteration,
                tokens=(response.usage.total_tokens if response.usage else 0),
                cost=(response.usage.cost if response.usage else 0),
                metadata={"duration_ms": duration * 1000},
            )

            return response

        except ProviderError as e:
            duration = time.monotonic() - start
            last_error = e
            ctx.emit_simple(
                EventType.LLM_ERROR,
                error=str(e),
                iteration=ctx.iteration,
                metadata={
                    "attempt": attempt + 1,
                    "retryable": e.retryable,
                    "status_code": e.status_code,
                    "duration_ms": duration * 1000,
                },
            )

            if not e.retryable or attempt >= max_retries:
                raise

            delay = min(retry_base_delay * (2 ** attempt), RETRY_MAX_DELAY)
            await asyncio.sleep(delay)

        except Exception as e:
            duration = time.monotonic() - start
            ctx.emit_simple(
                EventType.LLM_ERROR,
                error=str(e),
                iteration=ctx.iteration,
                metadata={"duration_ms": duration * 1000},
            )
            raise LLMError(f"Unexpected error during streaming LLM call: {str(e) or repr(e) or type(e).__name__}") from e

    raise last_error or LLMError("Streaming LLM call failed after all retries")
