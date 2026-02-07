/**
 * Swarm Request Throttle
 *
 * Token bucket + minimum spacing + FIFO queue to prevent 429 rate limiting
 * across all swarm workers. Since all subagents share the parent's provider
 * by reference (agent.ts:4398), wrapping the provider here automatically
 * throttles ALL downstream LLM calls.
 */

import type { LLMProvider, Message, ChatOptions, ChatResponse, MessageWithContent } from '../../providers/types.js';

// ─── Configuration ──────────────────────────────────────────────────────────

export interface ThrottleConfig {
  /** Burst capacity — max concurrent in-flight requests (default: 2) */
  maxConcurrent: number;
  /** Token refill rate per second (default: 0.5 → 30 req/min) */
  refillRatePerSecond: number;
  /** Floor between consecutive request starts in ms (default: 2000) */
  minSpacingMs: number;
}

export const FREE_TIER_THROTTLE: ThrottleConfig = {
  maxConcurrent: 2,
  refillRatePerSecond: 0.5,
  minSpacingMs: 1500,
};

export const PAID_TIER_THROTTLE: ThrottleConfig = {
  maxConcurrent: 5,
  refillRatePerSecond: 2.0,
  minSpacingMs: 200,
};

// ─── Throttle Stats ─────────────────────────────────────────────────────────

export interface ThrottleStats {
  pendingCount: number;
  availableTokens: number;
  totalAcquired: number;
  backoffLevel: number;
  currentMaxConcurrent: number;
  currentMinSpacingMs: number;
}

// ─── SwarmThrottle ──────────────────────────────────────────────────────────

/**
 * Async semaphore with token bucket rate limiting and minimum spacing.
 *
 * - `acquire()` waits in FIFO order, then consumes a token once available.
 * - Tokens refill passively based on elapsed wall-clock time.
 * - No explicit `release()` — long LLM calls naturally allow refill.
 */
export class SwarmThrottle {
  private tokens: number;
  private lastAcquireTime = 0;
  private lastRefillTime: number;
  private queue: Array<() => void> = [];
  private totalAcquired = 0;
  private refillTimer: ReturnType<typeof setInterval> | null = null;

  // Adaptive backoff state
  private originalConfig: Readonly<ThrottleConfig>;
  private _backoffLevel = 0;
  private lastBackoffTime = 0;
  private static readonly MAX_BACKOFF_LEVEL = 3;
  private static readonly RECOVER_COOLDOWN_MS = 10_000;

  constructor(private config: ThrottleConfig) {
    this.tokens = config.maxConcurrent;
    this.lastRefillTime = Date.now();
    this.originalConfig = { ...config };
  }

  /**
   * Wait for a token to become available (FIFO).
   * Enforces minSpacing between consecutive acquisitions.
   */
  async acquire(): Promise<void> {
    // FIFO: wait in queue if there are already waiters or no tokens
    if (this.queue.length > 0 || this.refill() < 1) {
      await new Promise<void>(resolve => {
        this.queue.push(resolve);
        this.ensureRefillTimer();
      });
    }

    // Enforce minimum spacing
    const now = Date.now();
    const elapsed = now - this.lastAcquireTime;
    if (elapsed < this.config.minSpacingMs && this.lastAcquireTime > 0) {
      const waitMs = this.config.minSpacingMs - elapsed;
      await sleep(waitMs);
    }

    // Consume token (refill first after possible wait)
    this.refill();
    this.tokens = Math.max(0, this.tokens - 1);
    this.lastAcquireTime = Date.now();
    this.totalAcquired++;
  }

  /**
   * Get current throttle stats for observability.
   */
  getStats(): ThrottleStats {
    this.refill();
    return {
      pendingCount: this.queue.length,
      availableTokens: Math.floor(this.tokens),
      totalAcquired: this.totalAcquired,
      backoffLevel: this._backoffLevel,
      currentMaxConcurrent: this.config.maxConcurrent,
      currentMinSpacingMs: this.config.minSpacingMs,
    };
  }

  /** Current backoff level (0 = normal, max = 3). */
  get backoffLevel(): number {
    return this._backoffLevel;
  }

  /**
   * Increase backoff: halve maxConcurrent (min 1), double minSpacingMs (max 5000),
   * halve refillRate (min 0.1). Caps at level 3.
   */
  backoff(): void {
    if (this._backoffLevel >= SwarmThrottle.MAX_BACKOFF_LEVEL) return;
    this._backoffLevel++;
    this.lastBackoffTime = Date.now();

    this.config = {
      maxConcurrent: Math.max(1, Math.floor(this.config.maxConcurrent / 2)),
      minSpacingMs: Math.min(5000, this.config.minSpacingMs * 2),
      refillRatePerSecond: Math.max(0.1, this.config.refillRatePerSecond / 2),
    };

    // Clamp tokens to new maxConcurrent
    this.tokens = Math.min(this.tokens, this.config.maxConcurrent);
  }

  /**
   * Step back toward original config after sustained success.
   * Only recovers if 10s+ have passed since last backoff.
   */
  recover(): void {
    if (this._backoffLevel <= 0) return;
    if (Date.now() - this.lastBackoffTime < SwarmThrottle.RECOVER_COOLDOWN_MS) return;

    this._backoffLevel--;

    // Interpolate back toward original config
    const ratio = this._backoffLevel / SwarmThrottle.MAX_BACKOFF_LEVEL;
    this.config = {
      maxConcurrent: Math.max(1, Math.round(
        this.originalConfig.maxConcurrent * (1 - ratio * 0.5),
      )),
      minSpacingMs: Math.round(
        this.originalConfig.minSpacingMs * (1 + ratio),
      ),
      refillRatePerSecond: this.originalConfig.refillRatePerSecond * (1 - ratio * 0.5),
    };
  }

  /**
   * Feed rate limit info from response headers to proactively adjust throttle.
   * If remaining requests or tokens are low, preemptively back off.
   */
  feedRateLimitInfo(info: { remainingRequests?: number; remainingTokens?: number; resetSeconds?: number }): void {
    // Proactive backoff: if < 5 remaining requests, increase spacing
    if (info.remainingRequests !== undefined && info.remainingRequests < 5) {
      if (this._backoffLevel < SwarmThrottle.MAX_BACKOFF_LEVEL) {
        this.backoff();
      }
    }
    // If reset is imminent (< 2s), briefly pause
    if (info.resetSeconds !== undefined && info.resetSeconds < 2 && info.remainingRequests !== undefined && info.remainingRequests <= 1) {
      this.config = {
        ...this.config,
        minSpacingMs: Math.max(this.config.minSpacingMs, info.resetSeconds * 1000),
      };
    }
  }

  /**
   * Refill tokens based on elapsed time. Returns current token count.
   */
  private refill(): number {
    const now = Date.now();
    const elapsedSec = (now - this.lastRefillTime) / 1000;
    if (elapsedSec > 0) {
      this.tokens = Math.min(
        this.config.maxConcurrent,
        this.tokens + elapsedSec * this.config.refillRatePerSecond,
      );
      this.lastRefillTime = now;
    }
    return this.tokens;
  }

  /**
   * Start a timer to periodically check for token refills and wake waiters.
   * Automatically stops when the queue is empty.
   */
  private ensureRefillTimer(): void {
    if (this.refillTimer !== null) return;

    // Check every ~50ms or minSpacingMs, whichever is smaller
    const intervalMs = Math.min(50, this.config.minSpacingMs || 50);
    this.refillTimer = setInterval(() => {
      this.refill();
      // Wake queued waiters if tokens available
      while (this.queue.length > 0 && this.tokens >= 1) {
        const resolve = this.queue.shift();
        if (resolve) resolve();
      }
      // Stop timer when queue is drained
      if (this.queue.length === 0 && this.refillTimer !== null) {
        clearInterval(this.refillTimer);
        this.refillTimer = null;
      }
    }, intervalMs);
  }
}

// ─── ThrottledProvider ──────────────────────────────────────────────────────

/**
 * Wraps an LLMProvider with throttle.acquire() before each chat call.
 * Delegates name, defaultModel, isConfigured() to inner provider.
 */
export class ThrottledProvider implements LLMProvider {
  constructor(
    private inner: LLMProvider,
    private throttle: SwarmThrottle,
  ) {}

  get name(): string {
    return this.inner.name;
  }

  get defaultModel(): string {
    return this.inner.defaultModel;
  }

  isConfigured(): boolean {
    return this.inner.isConfigured();
  }

  async chat(messages: (Message | MessageWithContent)[], options?: ChatOptions): Promise<ChatResponse> {
    await this.throttle.acquire();
    try {
      const result = await this.inner.chat(messages, options);
      // V3: Feed rate limit info from response headers for proactive throttle
      if (result.rateLimitInfo) {
        this.throttle.feedRateLimitInfo(result.rateLimitInfo);
      }
      this.throttle.recover();
      return result;
    } catch (error) {
      if (isRateLimitError(error)) {
        this.throttle.backoff();
      }
      throw error;
    }
  }

  /**
   * Forward chatWithTools if the inner provider supports it.
   */
  async chatWithTools(...args: unknown[]): Promise<unknown> {
    await this.throttle.acquire();
    const inner = this.inner as unknown as Record<string, (...a: unknown[]) => unknown>;
    if (typeof inner.chatWithTools === 'function') {
      try {
        const result = await inner.chatWithTools(...args);
        this.throttle.recover();
        return result;
      } catch (error) {
        if (isRateLimitError(error)) {
          this.throttle.backoff();
        }
        throw error;
      }
    }
    throw new Error('Inner provider does not support chatWithTools');
  }

  /** Get the underlying throttle for stats/inspection. */
  getThrottle(): SwarmThrottle {
    return this.throttle;
  }
}

// ─── Factory ────────────────────────────────────────────────────────────────

/**
 * Create a throttled wrapper around an LLM provider.
 */
export function createThrottledProvider(
  provider: LLMProvider,
  config: ThrottleConfig = FREE_TIER_THROTTLE,
): ThrottledProvider {
  const throttle = new SwarmThrottle(config);
  return new ThrottledProvider(provider, throttle);
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/** Check if an error is a rate limit (429) or spend limit (402) error. */
function isRateLimitError(error: unknown): boolean {
  const msg = String(error instanceof Error ? error.message : error).toLowerCase();
  return msg.includes('429') || msg.includes('rate') || msg.includes('too many') || msg.includes('402');
}
