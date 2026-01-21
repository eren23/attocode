/**
 * Lesson 5: Error Classifier
 * 
 * Classifies errors by type and determines if they're recoverable.
 */

import type { ClassifiedError, ErrorCategory } from './types.js';

// =============================================================================
// ERROR PATTERNS
// =============================================================================

/**
 * Patterns for identifying error categories.
 */
interface ErrorPattern {
  pattern: RegExp;
  category: ErrorCategory;
  recoverable: boolean;
}

const ERROR_PATTERNS: ErrorPattern[] = [
  // Network errors
  { pattern: /ECONNREFUSED/i, category: 'network', recoverable: true },
  { pattern: /ECONNRESET/i, category: 'network', recoverable: true },
  { pattern: /ENOTFOUND/i, category: 'network', recoverable: true },
  { pattern: /ETIMEDOUT/i, category: 'timeout', recoverable: true },
  { pattern: /socket hang up/i, category: 'network', recoverable: true },
  { pattern: /network\s*(error|failure)/i, category: 'network', recoverable: true },
  
  // Timeout
  { pattern: /timeout/i, category: 'timeout', recoverable: true },
  { pattern: /timed?\s*out/i, category: 'timeout', recoverable: true },
  { pattern: /deadline\s*exceeded/i, category: 'timeout', recoverable: true },
  
  // Rate limiting
  { pattern: /rate\s*limit/i, category: 'rate_limit', recoverable: true },
  { pattern: /too\s*many\s*requests/i, category: 'rate_limit', recoverable: true },
  { pattern: /throttl/i, category: 'rate_limit', recoverable: true },
  { pattern: /quota\s*exceeded/i, category: 'rate_limit', recoverable: true },
  
  // Context/token limits
  { pattern: /context.*length/i, category: 'context_limit', recoverable: false },
  { pattern: /token.*limit/i, category: 'context_limit', recoverable: false },
  { pattern: /maximum.*tokens/i, category: 'context_limit', recoverable: false },
  
  // Authentication
  { pattern: /unauthorized/i, category: 'auth', recoverable: false },
  { pattern: /authentication\s*(failed|error)/i, category: 'auth', recoverable: false },
  { pattern: /invalid.*api.*key/i, category: 'auth', recoverable: false },
  { pattern: /forbidden/i, category: 'auth', recoverable: false },
  
  // Validation
  { pattern: /invalid.*request/i, category: 'validation', recoverable: false },
  { pattern: /validation\s*(error|failed)/i, category: 'validation', recoverable: false },
  { pattern: /malformed/i, category: 'validation', recoverable: false },
];

// =============================================================================
// HTTP STATUS CLASSIFICATION
// =============================================================================

/**
 * Classify based on HTTP status code.
 */
function classifyStatusCode(status: number): { category: ErrorCategory; recoverable: boolean } {
  if (status === 429) {
    return { category: 'rate_limit', recoverable: true };
  }
  if (status === 401 || status === 403) {
    return { category: 'auth', recoverable: false };
  }
  if (status === 400 || status === 422) {
    return { category: 'validation', recoverable: false };
  }
  if (status >= 500 && status < 600) {
    return { category: 'server_error', recoverable: true };
  }
  if (status >= 400 && status < 500) {
    return { category: 'client_error', recoverable: false };
  }
  return { category: 'unknown', recoverable: false };
}

// =============================================================================
// MAIN CLASSIFIER
// =============================================================================

/**
 * Classify an error.
 */
export function classifyError(error: Error): ClassifiedError {
  const errorMessage = error.message.toLowerCase();
  const errorName = error.name.toLowerCase();
  const combined = `${errorMessage} ${errorName}`;

  // Check for HTTP status code in error
  const statusMatch = combined.match(/(\d{3})/);
  const statusCode = statusMatch ? parseInt(statusMatch[1], 10) : undefined;

  // If we have a status code, use it for classification
  if (statusCode && statusCode >= 400) {
    const statusClass = classifyStatusCode(statusCode);
    return {
      original: error,
      category: statusClass.category,
      recoverable: statusClass.recoverable,
      statusCode,
      suggestedDelay: getSuggestedDelay(statusClass.category, statusCode),
      reason: `HTTP status ${statusCode}`,
    };
  }

  // Match against patterns
  for (const { pattern, category, recoverable } of ERROR_PATTERNS) {
    if (pattern.test(combined)) {
      return {
        original: error,
        category,
        recoverable,
        suggestedDelay: getSuggestedDelay(category),
        reason: `Matched pattern: ${pattern.source}`,
      };
    }
  }

  // Default: unknown, not recoverable
  return {
    original: error,
    category: 'unknown',
    recoverable: false,
    reason: 'No matching pattern found',
  };
}

/**
 * Get suggested delay based on error category.
 */
function getSuggestedDelay(category: ErrorCategory, statusCode?: number): number | undefined {
  switch (category) {
    case 'rate_limit':
      // Rate limits often have retry-after headers, but default to 60s
      return 60000;
    case 'server_error':
      return 5000;
    case 'timeout':
      return 1000;
    case 'network':
      return 2000;
    default:
      return undefined;
  }
}

/**
 * Check if an error is recoverable.
 */
export function isRecoverable(error: Error): boolean {
  const classified = classifyError(error);
  return classified.recoverable;
}

/**
 * Check if an error is a specific category.
 */
export function isErrorCategory(error: Error, category: ErrorCategory): boolean {
  const classified = classifyError(error);
  return classified.category === category;
}

// =============================================================================
// RETRY-AFTER PARSING
// =============================================================================

/**
 * Parse Retry-After header value.
 * Can be a number (seconds) or a date string.
 */
export function parseRetryAfter(value: string | undefined): number | undefined {
  if (!value) return undefined;

  // Try as number (seconds)
  const seconds = parseInt(value, 10);
  if (!isNaN(seconds)) {
    return seconds * 1000; // Convert to ms
  }

  // Try as date
  const date = new Date(value);
  if (!isNaN(date.getTime())) {
    const delay = date.getTime() - Date.now();
    return delay > 0 ? delay : undefined;
  }

  return undefined;
}
