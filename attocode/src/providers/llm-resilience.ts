/**
 * LLM Resilience Utility
 *
 * Provides semantic-level resilience for LLM calls:
 * - Empty response detection and retry
 * - max_tokens truncation handling with continuation
 * - Malformed response recovery
 * - Graceful degradation with informative errors
 *
 * This complements resilient-fetch.ts (network level) with application-level resilience.
 */

import type { ChatResponse, Message } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for LLM resilience.
 */
export interface LLMResilienceConfig {
  /** Maximum retries for empty responses (default: 2) */
  maxEmptyRetries?: number;
  /** Maximum continuation attempts for max_tokens (default: 3) */
  maxContinuations?: number;
  /** Whether to auto-continue on max_tokens (default: true) */
  autoContinue?: boolean;
  /** Minimum acceptable content length (default: 1) */
  minContentLength?: number;
  /** Callback for resilience events */
  onEvent?: (event: LLMResilienceEvent) => void;

  // Exponential backoff configuration (Codex-inspired)
  /** Initial backoff delay in ms (default: 1000) */
  initialBackoffMs?: number;
  /** Maximum backoff delay in ms (default: 60000) */
  maxBackoffMs?: number;
  /** Backoff multiplier (default: 2) */
  backoffMultiplier?: number;
  /** Add jitter to prevent thundering herd (default: true) */
  useJitter?: boolean;
}

/**
 * Events emitted during resilience handling.
 */
export type LLMResilienceEvent =
  | { type: 'empty_response'; attempt: number; maxAttempts: number }
  | { type: 'empty_response_recovered'; attempt: number }
  | { type: 'empty_response_failed'; attempts: number }
  | { type: 'max_tokens_truncated'; continuation: number; maxContinuations: number }
  | { type: 'max_tokens_continued'; continuation: number; totalContent: number }
  | { type: 'max_tokens_completed'; continuations: number; totalContent: number }
  | { type: 'max_tokens_limit_reached'; continuations: number }
  | { type: 'response_validated'; contentLength: number; hasToolCalls: boolean };

/**
 * Result of resilient LLM call.
 */
export interface ResilientLLMResult {
  /** The validated response */
  response: ChatResponse;
  /** Number of empty response retries used */
  emptyRetries: number;
  /** Number of max_tokens continuations used */
  continuations: number;
  /** Whether response was modified by resilience layer */
  wasRecovered: boolean;
}

/**
 * Function type for making LLM calls.
 */
export type LLMCallFn = (messages: Message[]) => Promise<ChatResponse>;

// =============================================================================
// DEFAULT CONFIG
// =============================================================================

const DEFAULT_CONFIG: Required<Omit<LLMResilienceConfig, 'onEvent'>> = {
  maxEmptyRetries: 2,
  maxContinuations: 3,
  autoContinue: true,
  minContentLength: 1,
  // Exponential backoff defaults (Codex-inspired: 1s→60s + jitter)
  initialBackoffMs: 1000,
  maxBackoffMs: 60000,
  backoffMultiplier: 2,
  useJitter: true,
};

/**
 * Calculate exponential backoff delay with optional jitter.
 * Inspired by Codex's retry strategy.
 *
 * @param attempt - The current attempt number (1-indexed)
 * @param config - Backoff configuration
 * @returns Delay in milliseconds
 */
function calculateBackoff(
  attempt: number,
  config: {
    initialBackoffMs: number;
    maxBackoffMs: number;
    backoffMultiplier: number;
    useJitter: boolean;
  }
): number {
  const baseDelay = config.initialBackoffMs * Math.pow(config.backoffMultiplier, attempt - 1);
  const cappedDelay = Math.min(baseDelay, config.maxBackoffMs);

  if (config.useJitter) {
    // Add up to 25% jitter to prevent thundering herd
    return cappedDelay * (0.75 + Math.random() * 0.5);
  }
  return cappedDelay;
}

/**
 * Sleep for a specified duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// =============================================================================
// RESILIENT LLM CALL
// =============================================================================

/**
 * Wrap an LLM call with semantic resilience.
 *
 * Handles:
 * 1. Empty responses - retries with slight prompt modification
 * 2. max_tokens truncation - auto-continues to get complete response
 * 3. Response validation - ensures response meets minimum quality bar
 *
 * @example
 * ```typescript
 * const result = await resilientLLMCall(
 *   messages,
 *   (msgs) => provider.chat(msgs, options),
 *   { onEvent: (e) => console.log('Resilience:', e) }
 * );
 * ```
 */
export async function resilientLLMCall(
  messages: Message[],
  callFn: LLMCallFn,
  config: LLMResilienceConfig = {}
): Promise<ResilientLLMResult> {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  const onEvent = config.onEvent || (() => {});

  let emptyRetries = 0;
  let continuations = 0;
  let wasRecovered = false;

  // Clone messages to avoid mutation
  let currentMessages = [...messages];

  // ==========================================================================
  // PHASE 1: Handle empty responses
  // ==========================================================================
  let response: ChatResponse | null = null;

  for (let attempt = 1; attempt <= cfg.maxEmptyRetries + 1; attempt++) {
    response = await callFn(currentMessages);

    const hasContent = response.content && response.content.length >= cfg.minContentLength;
    const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;

    // Valid response - has content or tool calls
    if (hasContent || hasToolCalls) {
      if (attempt > 1) {
        onEvent({ type: 'empty_response_recovered', attempt: attempt - 1 });
        wasRecovered = true;
      }
      break;
    }

    // Empty response - retry with nudge
    if (attempt <= cfg.maxEmptyRetries) {
      emptyRetries++;
      onEvent({ type: 'empty_response', attempt, maxAttempts: cfg.maxEmptyRetries + 1 });

      // Apply exponential backoff before retry (Codex-inspired)
      const backoffMs = calculateBackoff(attempt, cfg);
      await sleep(backoffMs);

      // Add a gentle nudge to encourage response
      currentMessages = [
        ...messages,
        {
          role: 'user' as const,
          content: '[System: Your previous response was empty. Please provide a response.]',
        },
      ];
    } else {
      // Failed after all retries
      onEvent({ type: 'empty_response_failed', attempts: attempt });

      // Return what we have, but mark as potentially problematic
      // Don't throw - let the agent decide what to do
      break;
    }
  }

  if (!response) {
    throw new LLMResilienceError('No response received from LLM after retries', {
      emptyRetries,
      continuations: 0,
    });
  }

  // ==========================================================================
  // PHASE 2: Handle max_tokens truncation
  // ==========================================================================
  if (cfg.autoContinue && response.stopReason === 'max_tokens' && !response.toolCalls?.length) {
    let accumulatedContent = response.content || '';
    let accumulatedInputTokens = response.usage?.inputTokens || 0;
    let accumulatedOutputTokens = response.usage?.outputTokens || 0;
    let accumulatedCacheRead = response.usage?.cacheReadTokens || 0;
    let accumulatedCacheWrite = response.usage?.cacheWriteTokens || 0;
    let accumulatedCost = response.usage?.cost || 0;

    while (continuations < cfg.maxContinuations) {
      continuations++;
      onEvent({
        type: 'max_tokens_truncated',
        continuation: continuations,
        maxContinuations: cfg.maxContinuations,
      });

      // Apply exponential backoff before continuation (prevents rate limiting)
      if (continuations > 1) {
        const backoffMs = calculateBackoff(continuations, cfg);
        await sleep(backoffMs);
      }

      // Create continuation request
      const continuationMessages: Message[] = [
        ...messages,
        {
          role: 'assistant' as const,
          content: accumulatedContent,
        },
        {
          role: 'user' as const,
          content: '[System: Please continue from where you left off. Do not repeat what you already said.]',
        },
      ];

      const continuationResponse = await callFn(continuationMessages);
      wasRecovered = true;

      // Accumulate content
      if (continuationResponse.content) {
        accumulatedContent += continuationResponse.content;
      }

      // Accumulate usage
      if (continuationResponse.usage) {
        accumulatedInputTokens += continuationResponse.usage.inputTokens || 0;
        accumulatedOutputTokens += continuationResponse.usage.outputTokens || 0;
        accumulatedCacheRead += continuationResponse.usage.cacheReadTokens || 0;
        accumulatedCacheWrite += continuationResponse.usage.cacheWriteTokens || 0;
        accumulatedCost += continuationResponse.usage.cost || 0;
      }

      onEvent({
        type: 'max_tokens_continued',
        continuation: continuations,
        totalContent: accumulatedContent.length,
      });

      // Check if we're done
      if (continuationResponse.stopReason !== 'max_tokens') {
        onEvent({
          type: 'max_tokens_completed',
          continuations,
          totalContent: accumulatedContent.length,
        });

        // Return combined response
        response = {
          ...continuationResponse,
          content: accumulatedContent,
          usage: {
            inputTokens: accumulatedInputTokens,
            outputTokens: accumulatedOutputTokens,
            totalTokens: accumulatedInputTokens + accumulatedOutputTokens,
            cacheReadTokens: accumulatedCacheRead,
            cacheWriteTokens: accumulatedCacheWrite,
            cost: accumulatedCost,
          },
        };
        break;
      }
    }

    // Hit continuation limit
    if (continuations >= cfg.maxContinuations && response.stopReason === 'max_tokens') {
      onEvent({ type: 'max_tokens_limit_reached', continuations });
      // Still return what we have
      response = {
        ...response,
        content: accumulatedContent,
        usage: {
          inputTokens: accumulatedInputTokens,
          outputTokens: accumulatedOutputTokens,
          totalTokens: accumulatedInputTokens + accumulatedOutputTokens,
          cacheReadTokens: accumulatedCacheRead,
          cacheWriteTokens: accumulatedCacheWrite,
          cost: accumulatedCost,
        },
      };
    }
  }

  // ==========================================================================
  // PHASE 3: Final validation
  // ==========================================================================
  // At this point response is guaranteed non-null (we threw or broke with a value)
  const finalResponse = response as ChatResponse;

  onEvent({
    type: 'response_validated',
    contentLength: finalResponse.content?.length || 0,
    hasToolCalls: (finalResponse.toolCalls?.length || 0) > 0,
  });

  return {
    response: finalResponse,
    emptyRetries,
    continuations,
    wasRecovered,
  };
}

// =============================================================================
// ERROR TYPES
// =============================================================================

/**
 * Error thrown when LLM resilience cannot recover.
 */
export class LLMResilienceError extends Error {
  constructor(
    message: string,
    public readonly details: {
      emptyRetries: number;
      continuations: number;
    }
  ) {
    super(message);
    this.name = 'LLMResilienceError';
  }
}

/**
 * Check if an error is an LLM resilience error.
 */
export function isLLMResilienceError(error: unknown): error is LLMResilienceError {
  return error instanceof LLMResilienceError;
}

// =============================================================================
// VALIDATION UTILITIES
// =============================================================================

/**
 * Validate that a response meets minimum quality criteria.
 */
export function validateResponse(
  response: ChatResponse,
  options: { minContentLength?: number } = {}
): { valid: boolean; issues: string[] } {
  const issues: string[] = [];
  const minLength = options.minContentLength ?? 1;

  // Check for content or tool calls
  const hasContent = response.content && response.content.length >= minLength;
  const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;

  if (!hasContent && !hasToolCalls) {
    issues.push('Response has no content and no tool calls');
  }

  // Check for truncation
  if (response.stopReason === 'max_tokens') {
    issues.push('Response was truncated due to max_tokens');
  }

  return {
    valid: issues.length === 0,
    issues,
  };
}

/**
 * Create a response summary for logging/debugging.
 */
export function summarizeResponse(response: ChatResponse): string {
  const parts: string[] = [];

  if (response.content) {
    const preview = response.content.slice(0, 100);
    parts.push(`content: ${preview}${response.content.length > 100 ? '...' : ''}`);
  }

  if (response.toolCalls?.length) {
    const toolNames = response.toolCalls.map(tc => tc.name).join(', ');
    parts.push(`tools: [${toolNames}]`);
  }

  parts.push(`stop: ${response.stopReason}`);

  if (response.usage) {
    parts.push(`tokens: ${response.usage.inputTokens}/${response.usage.outputTokens}`);
  }

  return parts.join(' | ');
}
