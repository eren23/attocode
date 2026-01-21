/**
 * Trick P: KV-Cache Aware Context
 *
 * Optimizes context structure for LLM KV-cache efficiency.
 * Cached input tokens cost ~10x less than uncached ones.
 *
 * Key principles:
 * 1. Keep system prompt PREFIX stable (no timestamps, session IDs at start)
 * 2. Use deterministic JSON serialization (sorted keys)
 * 3. Mark explicit cache breakpoints
 * 4. Append-only message history (never modify past messages)
 *
 * @example
 * ```typescript
 * import { createCacheAwareContext, stableStringify } from './kv-cache-context';
 *
 * const context = createCacheAwareContext({
 *   staticPrefix: 'You are a helpful coding assistant.',
 *   cacheBreakpoints: ['system_end', 'tools_end'],
 * });
 *
 * // Build system prompt with stable prefix
 * const systemPrompt = context.buildSystemPrompt({
 *   rules: rulesContent,
 *   sessionId: 'abc123',  // Goes at END, not beginning
 * });
 *
 * // Serialize tool calls deterministically
 * const serialized = stableStringify(toolCall.arguments);
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for cache-aware context.
 */
export interface CacheAwareConfig {
  /** Static prefix that never changes (maximizes cache hits) */
  staticPrefix: string;

  /** Points where cache can be safely broken */
  cacheBreakpoints?: CacheBreakpoint[];

  /** Whether to use deterministic JSON serialization */
  deterministicJson?: boolean;

  /** Whether to validate append-only constraint */
  enforceAppendOnly?: boolean;
}

/**
 * Cache breakpoint markers.
 */
export type CacheBreakpoint =
  | 'system_end'      // After system prompt
  | 'tools_end'       // After tool definitions
  | 'rules_end'       // After rules content
  | 'memory_end'      // After memory context
  | 'custom';         // Custom breakpoint

/**
 * Dynamic content that goes at the END of system prompt.
 */
export interface DynamicContent {
  /** Current session ID */
  sessionId?: string;
  /** Current timestamp */
  timestamp?: string;
  /** Current mode */
  mode?: string;
  /** Any other dynamic values */
  [key: string]: string | undefined;
}

/**
 * Cache statistics.
 */
export interface CacheStats {
  /** Estimated cacheable tokens */
  cacheableTokens: number;
  /** Estimated non-cacheable tokens */
  nonCacheableTokens: number;
  /** Cache efficiency ratio */
  cacheRatio: number;
  /** Estimated cost savings (0-1) */
  estimatedSavings: number;
}

/**
 * Message for context building.
 */
export interface ContextMessage {
  id?: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  timestamp?: string;
}

/**
 * Events emitted by cache-aware context.
 */
export type CacheEvent =
  | { type: 'cache.breakpoint'; breakpoint: CacheBreakpoint; position: number }
  | { type: 'cache.violation'; reason: string; details: string }
  | { type: 'cache.stats'; stats: CacheStats };

export type CacheEventListener = (event: CacheEvent) => void;

// =============================================================================
// DETERMINISTIC JSON SERIALIZATION
// =============================================================================

/**
 * Stringify JSON with sorted keys for deterministic output.
 * This ensures the same object always produces the same string,
 * which is critical for KV-cache efficiency.
 *
 * @example
 * ```typescript
 * // Standard JSON.stringify - key order not guaranteed
 * JSON.stringify({ b: 1, a: 2 }); // Could be '{"b":1,"a":2}' or '{"a":2,"b":1}'
 *
 * // stableStringify - always same order
 * stableStringify({ b: 1, a: 2 }); // Always '{"a":2,"b":1}'
 * ```
 */
export function stableStringify(obj: unknown, indent?: number): string {
  return JSON.stringify(obj, sortedReplacer, indent);
}

/**
 * JSON replacer that sorts object keys.
 */
function sortedReplacer(_key: string, value: unknown): unknown {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return value;
  }

  // Sort keys and create new object
  const sorted: Record<string, unknown> = {};
  const keys = Object.keys(value as Record<string, unknown>).sort();

  for (const k of keys) {
    sorted[k] = (value as Record<string, unknown>)[k];
  }

  return sorted;
}

/**
 * Parse JSON and re-serialize deterministically.
 * Useful for normalizing JSON strings from external sources.
 */
export function normalizeJson(jsonString: string): string {
  try {
    const parsed = JSON.parse(jsonString);
    return stableStringify(parsed);
  } catch {
    return jsonString; // Return as-is if not valid JSON
  }
}

// =============================================================================
// CACHE-AWARE CONTEXT MANAGER
// =============================================================================

/**
 * Manages context in a KV-cache-friendly way.
 */
export class CacheAwareContext {
  private config: Required<CacheAwareConfig>;
  private messageHashes: Map<number, string> = new Map();
  private listeners: CacheEventListener[] = [];
  private breakpointPositions: Map<CacheBreakpoint, number> = new Map();

  constructor(config: CacheAwareConfig) {
    this.config = {
      staticPrefix: config.staticPrefix,
      cacheBreakpoints: config.cacheBreakpoints ?? ['system_end'],
      deterministicJson: config.deterministicJson ?? true,
      enforceAppendOnly: config.enforceAppendOnly ?? true,
    };
  }

  /**
   * Build system prompt with stable prefix and dynamic content at END.
   *
   * @example
   * ```typescript
   * const prompt = context.buildSystemPrompt({
   *   rules: 'Follow these rules...',
   *   tools: toolDescriptions,
   *   dynamic: { sessionId: 'abc', mode: 'build' },
   * });
   * // Result:
   * // "You are a helpful assistant.  <- STABLE (cached)
   * //
   * //  ## Rules
   * //  Follow these rules...         <- Semi-stable (cached if unchanged)
   * //
   * //  ## Tools
   * //  [tool descriptions]           <- Semi-stable
   * //
   * //  ---
   * //  Session: abc | Mode: build"   <- DYNAMIC (not cached)
   * ```
   */
  buildSystemPrompt(options: {
    rules?: string;
    tools?: string;
    memory?: string;
    dynamic?: DynamicContent;
  }): string {
    const parts: string[] = [];
    let position = 0;

    // 1. Static prefix (ALWAYS first, never changes)
    parts.push(this.config.staticPrefix);
    position += this.config.staticPrefix.length;

    // Mark system_end breakpoint after static prefix
    if (this.config.cacheBreakpoints.includes('system_end')) {
      this.markBreakpoint('system_end', position);
    }

    // 2. Rules content (semi-stable)
    if (options.rules) {
      parts.push('\n\n## Rules\n' + options.rules);
      position += options.rules.length + 12;

      if (this.config.cacheBreakpoints.includes('rules_end')) {
        this.markBreakpoint('rules_end', position);
      }
    }

    // 3. Tool descriptions (semi-stable)
    if (options.tools) {
      parts.push('\n\n## Available Tools\n' + options.tools);
      position += options.tools.length + 22;

      if (this.config.cacheBreakpoints.includes('tools_end')) {
        this.markBreakpoint('tools_end', position);
      }
    }

    // 4. Memory context (changes more frequently)
    if (options.memory) {
      parts.push('\n\n## Relevant Context\n' + options.memory);
      position += options.memory.length + 22;

      if (this.config.cacheBreakpoints.includes('memory_end')) {
        this.markBreakpoint('memory_end', position);
      }
    }

    // 5. Dynamic content at END (changes every request)
    if (options.dynamic && Object.keys(options.dynamic).length > 0) {
      const dynamicParts: string[] = [];

      if (options.dynamic.sessionId) {
        dynamicParts.push(`Session: ${options.dynamic.sessionId}`);
      }
      if (options.dynamic.mode) {
        dynamicParts.push(`Mode: ${options.dynamic.mode}`);
      }
      if (options.dynamic.timestamp) {
        dynamicParts.push(`Time: ${options.dynamic.timestamp}`);
      }

      // Add any custom dynamic values
      for (const [key, value] of Object.entries(options.dynamic)) {
        if (!['sessionId', 'mode', 'timestamp'].includes(key) && value) {
          dynamicParts.push(`${key}: ${value}`);
        }
      }

      if (dynamicParts.length > 0) {
        parts.push('\n\n---\n' + dynamicParts.join(' | '));
      }
    }

    return parts.join('');
  }

  /**
   * Validate that messages follow append-only constraint.
   * Returns violations if any past messages were modified.
   */
  validateAppendOnly(messages: ContextMessage[]): string[] {
    if (!this.config.enforceAppendOnly) {
      return [];
    }

    const violations: string[] = [];

    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      const currentHash = this.hashMessage(msg);
      const previousHash = this.messageHashes.get(i);

      if (previousHash !== undefined && previousHash !== currentHash) {
        violations.push(
          `Message at index ${i} was modified (role: ${msg.role})`
        );
        this.emit({
          type: 'cache.violation',
          reason: 'message_modified',
          details: `Index ${i}, role ${msg.role}`,
        });
      }

      // Update hash for this position
      this.messageHashes.set(i, currentHash);
    }

    return violations;
  }

  /**
   * Serialize a message in a cache-friendly way.
   */
  serializeMessage(message: ContextMessage): string {
    if (this.config.deterministicJson) {
      return stableStringify(message);
    }
    return JSON.stringify(message);
  }

  /**
   * Serialize tool arguments deterministically.
   */
  serializeToolArgs(args: Record<string, unknown>): string {
    if (this.config.deterministicJson) {
      return stableStringify(args);
    }
    return JSON.stringify(args);
  }

  /**
   * Calculate cache statistics for a context.
   */
  calculateCacheStats(options: {
    systemPrompt: string;
    messages: ContextMessage[];
    dynamicContentLength?: number;
  }): CacheStats {
    const { systemPrompt, messages, dynamicContentLength = 0 } = options;

    // Estimate tokens (~4 chars per token)
    const totalChars = systemPrompt.length +
      messages.reduce((sum, m) => sum + m.content.length, 0);
    const totalTokens = Math.ceil(totalChars / 4);

    // Cacheable = everything except dynamic content at end
    const cacheableChars = totalChars - dynamicContentLength;
    const cacheableTokens = Math.ceil(cacheableChars / 4);
    const nonCacheableTokens = totalTokens - cacheableTokens;

    const cacheRatio = cacheableTokens / totalTokens;

    // Cost savings: cached tokens are ~10x cheaper
    // If 80% is cached, savings = 0.8 * 0.9 = 0.72 (72% savings)
    const estimatedSavings = cacheRatio * 0.9;

    const stats: CacheStats = {
      cacheableTokens,
      nonCacheableTokens,
      cacheRatio,
      estimatedSavings,
    };

    this.emit({ type: 'cache.stats', stats });

    return stats;
  }

  /**
   * Get breakpoint positions.
   */
  getBreakpointPositions(): Map<CacheBreakpoint, number> {
    return new Map(this.breakpointPositions);
  }

  /**
   * Subscribe to cache events.
   */
  on(listener: CacheEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Reset message hashes (call when starting new session).
   */
  reset(): void {
    this.messageHashes.clear();
    this.breakpointPositions.clear();
  }

  // Internal methods

  private hashMessage(message: ContextMessage): string {
    // Simple hash for change detection
    const content = `${message.role}:${message.content}`;
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return hash.toString(16);
  }

  private markBreakpoint(breakpoint: CacheBreakpoint, position: number): void {
    this.breakpointPositions.set(breakpoint, position);
    this.emit({ type: 'cache.breakpoint', breakpoint, position });
  }

  private emit(event: CacheEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a cache-aware context manager.
 *
 * @example
 * ```typescript
 * const context = createCacheAwareContext({
 *   staticPrefix: `You are a coding assistant.
 *
 * You help users write, debug, and understand code.
 * Always explain your reasoning.`,
 *   cacheBreakpoints: ['system_end', 'tools_end'],
 *   deterministicJson: true,
 * });
 * ```
 */
export function createCacheAwareContext(
  config: CacheAwareConfig
): CacheAwareContext {
  return new CacheAwareContext(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Check if a system prompt has timestamps/dynamic content at the start.
 * Returns warnings about cache-unfriendly patterns.
 */
export function analyzeCacheEfficiency(systemPrompt: string): {
  warnings: string[];
  suggestions: string[];
} {
  const warnings: string[] = [];
  const suggestions: string[] = [];

  // Check for timestamps at start
  const timestampPatterns = [
    /^\[?\d{4}-\d{2}-\d{2}/,  // ISO date
    /^\[?\d{1,2}\/\d{1,2}\/\d{4}/,  // US date
    /^Current time:/i,
    /^Timestamp:/i,
    /^Date:/i,
  ];

  for (const pattern of timestampPatterns) {
    if (pattern.test(systemPrompt)) {
      warnings.push('Timestamp/date at start of prompt will invalidate cache');
      suggestions.push('Move timestamps to END of system prompt');
      break;
    }
  }

  // Check for session IDs at start
  if (/^Session( ID)?:/i.test(systemPrompt)) {
    warnings.push('Session ID at start will invalidate cache');
    suggestions.push('Move session ID to END of system prompt');
  }

  // Check for random/dynamic content at start
  if (/^(Random|Dynamic|Generated):/i.test(systemPrompt)) {
    warnings.push('Dynamic content at start will invalidate cache');
    suggestions.push('Move dynamic content to END of system prompt');
  }

  return { warnings, suggestions };
}

/**
 * Format cache stats for display.
 */
export function formatCacheStats(stats: CacheStats): string {
  const cachePercent = Math.round(stats.cacheRatio * 100);
  const savingsPercent = Math.round(stats.estimatedSavings * 100);

  return `KV-Cache Statistics:
  Cacheable tokens:     ${stats.cacheableTokens.toLocaleString()}
  Non-cacheable tokens: ${stats.nonCacheableTokens.toLocaleString()}
  Cache ratio:          ${cachePercent}%
  Estimated savings:    ${savingsPercent}% cost reduction`;
}

/**
 * Create a cache-friendly timestamp that goes at the end.
 */
export function createEndTimestamp(): string {
  return `[Context generated at ${new Date().toISOString()}]`;
}
