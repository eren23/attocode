/**
 * Lesson 4: SSE Parser
 * 
 * Parses Server-Sent Events from streaming API responses.
 */

import type { SSEEvent, AnthropicSSEEvent } from './types.js';

// =============================================================================
// SSE PARSER
// =============================================================================

/**
 * Parse SSE events from a ReadableStream.
 * 
 * SSE format:
 * ```
 * event: message_start
 * data: {"type":"message_start",...}
 * 
 * event: content_block_delta
 * data: {"type":"content_block_delta",...}
 * ```
 */
export async function* parseSSE(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<AnthropicSSEEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  
  let buffer = '';
  let currentEvent: Partial<SSEEvent> = {};

  try {
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        // Process any remaining data
        if (buffer.trim()) {
          const event = parseEventBlock(buffer, currentEvent);
          if (event) yield event;
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      // Process complete events (separated by double newlines)
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? ''; // Keep incomplete part in buffer

      for (const part of parts) {
        if (!part.trim()) continue;

        const event = parseEventBlock(part, currentEvent);
        if (event) {
          yield event;
          currentEvent = {};
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parse a single SSE event block.
 */
function parseEventBlock(
  block: string,
  current: Partial<SSEEvent>
): AnthropicSSEEvent | null {
  const lines = block.split('\n');

  for (const line of lines) {
    if (line.startsWith('event:')) {
      current.event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      const data = line.slice(5).trim();
      
      // Handle [DONE] marker
      if (data === '[DONE]') {
        return { type: 'message_stop' };
      }

      current.data = data;
    } else if (line.startsWith('id:')) {
      current.id = line.slice(3).trim();
    } else if (line.startsWith('retry:')) {
      current.retry = parseInt(line.slice(6).trim(), 10);
    }
  }

  if (current.data) {
    try {
      return JSON.parse(current.data) as AnthropicSSEEvent;
    } catch {
      // Invalid JSON, skip
      return null;
    }
  }

  return null;
}

// =============================================================================
// TOOL CALL PARSER
// =============================================================================

/**
 * Try to parse a tool call from accumulated text.
 * Returns null if the text doesn't contain a complete tool call.
 */
export function tryParseToolCall(
  text: string
): { tool: string; input: Record<string, unknown>; endIndex: number } | null {
  // Look for JSON code blocks
  const patterns = [
    /```json\s*(\{[\s\S]*?\})\s*```/,
    /```\s*(\{[\s\S]*?\})\s*```/,
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      try {
        const parsed = JSON.parse(match[1]);
        if (parsed.tool && typeof parsed.tool === 'string') {
          return {
            tool: parsed.tool,
            input: parsed.input || {},
            endIndex: match.index! + match[0].length,
          };
        }
      } catch {
        // JSON incomplete or invalid, continue
      }
    }
  }

  return null;
}

/**
 * Incrementally parse JSON from streaming text.
 * Returns partial results and whether parsing is complete.
 */
export function incrementalJsonParse(
  buffer: string
): { complete: boolean; value?: unknown; remaining: string } {
  // Find potential JSON start
  const jsonStart = buffer.indexOf('{');
  if (jsonStart === -1) {
    return { complete: false, remaining: buffer };
  }

  // Try to parse from the start
  let depth = 0;
  let inString = false;
  let escape = false;

  for (let i = jsonStart; i < buffer.length; i++) {
    const char = buffer[i];

    if (escape) {
      escape = false;
      continue;
    }

    if (char === '\\' && inString) {
      escape = true;
      continue;
    }

    if (char === '"') {
      inString = !inString;
      continue;
    }

    if (!inString) {
      if (char === '{') depth++;
      if (char === '}') depth--;

      if (depth === 0) {
        // Found complete JSON object
        const jsonStr = buffer.slice(jsonStart, i + 1);
        try {
          const value = JSON.parse(jsonStr);
          return {
            complete: true,
            value,
            remaining: buffer.slice(i + 1),
          };
        } catch {
          // Invalid JSON structure
          return { complete: false, remaining: buffer.slice(jsonStart) };
        }
      }
    }
  }

  // Incomplete JSON
  return { complete: false, remaining: buffer.slice(jsonStart) };
}
