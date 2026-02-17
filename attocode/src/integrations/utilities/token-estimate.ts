/**
 * Shared token estimation utility.
 *
 * Uses ~3.5 chars/token as a balanced heuristic for mixed code/text content.
 * This centralizes the estimation so all subsystems agree on context fullness.
 */

const CHARS_PER_TOKEN = 3.5;

/**
 * Estimate token count from a string.
 */
export function estimateTokenCount(text: string): number {
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}
