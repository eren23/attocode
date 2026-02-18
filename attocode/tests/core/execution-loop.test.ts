/**
 * Tests for Execution Loop helper functions (Phase 2.1)
 *
 * Tests pure utility functions exported from execution-loop.ts:
 * estimateContextTokens, compactToolOutputs, extractRequestedArtifact,
 * isRequestedArtifactMissing, detectIncompleteActionResponse.
 */

import { describe, it, expect } from 'vitest';
import {
  estimateContextTokens,
  compactToolOutputs,
  extractRequestedArtifact,
  isRequestedArtifactMissing,
  detectIncompleteActionResponse,
} from '../../src/core/execution-loop.js';

import type { Message } from '../../src/types.js';

// =============================================================================
// estimateContextTokens
// =============================================================================

describe('estimateContextTokens', () => {
  it('returns 0 for empty array', () => {
    expect(estimateContextTokens([])).toBe(0);
  });

  it('estimates tokens from text content', () => {
    const messages: Message[] = [
      { role: 'user', content: 'Hello world!' }, // 12 chars → ceil(12/3.5) = 4
    ];
    expect(estimateContextTokens(messages)).toBe(4);
  });

  it('includes tool call name and arguments in estimate', () => {
    const messages: Message[] = [
      {
        role: 'assistant',
        content: '',
        toolCalls: [
          { id: 'tc1', name: 'read_file', arguments: { path: '/foo/bar.ts' } },
        ],
      },
    ];
    const result = estimateContextTokens(messages);
    // name: 'read_file' (9 chars) + JSON.stringify({path:'/foo/bar.ts'}) chars
    expect(result).toBeGreaterThan(0);
  });

  it('handles mixed messages with content and tool calls', () => {
    const messages: Message[] = [
      { role: 'user', content: 'Do something' },
      {
        role: 'assistant',
        content: 'Sure, let me read the file.',
        toolCalls: [
          { id: 'tc1', name: 'read_file', arguments: { path: '/src/main.ts' } },
        ],
      },
      { role: 'tool', content: 'file contents here...', toolCallId: 'tc1' },
    ];
    const result = estimateContextTokens(messages);
    expect(result).toBeGreaterThan(10);
  });

  it('handles messages with no content', () => {
    const messages: Message[] = [
      { role: 'assistant', content: undefined as unknown as string },
    ];
    expect(estimateContextTokens(messages)).toBe(0);
  });
});

// =============================================================================
// compactToolOutputs
// =============================================================================

describe('compactToolOutputs', () => {
  it('compacts long tool outputs', () => {
    const longContent = 'x'.repeat(500);
    const messages: Message[] = [
      { role: 'tool', content: longContent, toolCallId: 'tc1' },
    ];
    compactToolOutputs(messages);
    expect(messages[0].content!.length).toBeLessThan(longContent.length);
    expect(messages[0].content).toContain('compacted');
  });

  it('preserves short tool outputs', () => {
    const shortContent = 'short output';
    const messages: Message[] = [
      { role: 'tool', content: shortContent, toolCallId: 'tc1' },
    ];
    compactToolOutputs(messages);
    expect(messages[0].content).toBe(shortContent);
  });

  it('respects preserveFromCompaction metadata flag', () => {
    const longContent = 'x'.repeat(500);
    const messages: Message[] = [
      {
        role: 'tool',
        content: longContent,
        toolCallId: 'tc1',
        metadata: { preserveFromCompaction: true },
      },
    ];
    compactToolOutputs(messages);
    expect(messages[0].content).toBe(longContent);
  });

  it('caps preserved expensive results at 6', () => {
    const longContent = 'x'.repeat(500);
    const messages: Message[] = [];
    // Create 8 preserved tool messages
    for (let i = 0; i < 8; i++) {
      messages.push({
        role: 'tool',
        content: longContent,
        toolCallId: `tc${i}`,
        metadata: { preserveFromCompaction: true },
      });
    }
    compactToolOutputs(messages);
    // First 2 should be compacted (oldest beyond limit of 6)
    const compactedCount = messages.filter(m => m.content!.includes('compacted')).length;
    expect(compactedCount).toBe(2);
  });

  it('does not compact non-tool messages', () => {
    const longContent = 'x'.repeat(500);
    const messages: Message[] = [
      { role: 'user', content: longContent },
      { role: 'assistant', content: longContent },
    ];
    compactToolOutputs(messages);
    expect(messages[0].content).toBe(longContent);
    expect(messages[1].content).toBe(longContent);
  });
});

// =============================================================================
// extractRequestedArtifact
// =============================================================================

describe('extractRequestedArtifact', () => {
  it('extracts .md filename from "write X.md" pattern', () => {
    expect(extractRequestedArtifact('write the report to findings.md')).toBe('findings.md');
  });

  it('extracts .md filename from "save X.md" pattern', () => {
    expect(extractRequestedArtifact('save your analysis to report.md')).toBe('report.md');
  });

  it('extracts .md filename from "create X.md" pattern', () => {
    expect(extractRequestedArtifact('create a file called README.md in docs')).toBe('README.md');
  });

  it('returns null for non-matching strings', () => {
    expect(extractRequestedArtifact('fix the bug in main.ts')).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(extractRequestedArtifact('')).toBeNull();
  });

  it('handles case insensitivity', () => {
    expect(extractRequestedArtifact('Write output to RESULTS.md')).toBe('RESULTS.md');
  });
});

// =============================================================================
// isRequestedArtifactMissing
// =============================================================================

describe('isRequestedArtifactMissing', () => {
  it('returns false for null artifact', () => {
    expect(isRequestedArtifactMissing(null, new Set())).toBe(false);
  });

  it('returns true when no write tools executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['read_file', 'grep']))).toBe(true);
  });

  it('returns false when write_file was executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['write_file']))).toBe(false);
  });

  it('returns false when edit_file was executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['edit_file']))).toBe(false);
  });

  it('returns false when apply_patch was executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['apply_patch']))).toBe(false);
  });

  it('returns false when append_file was executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['append_file']))).toBe(false);
  });

  it('returns true when only read-only tools executed', () => {
    expect(isRequestedArtifactMissing('output.md', new Set(['read_file', 'glob', 'search']))).toBe(true);
  });
});

// =============================================================================
// detectIncompleteActionResponse
// =============================================================================

describe('detectIncompleteActionResponse', () => {
  it('returns false for empty string', () => {
    expect(detectIncompleteActionResponse('')).toBe(false);
  });

  it('returns false for whitespace-only string', () => {
    expect(detectIncompleteActionResponse('   ')).toBe(false);
  });

  it('detects "I will create" as future intent', () => {
    expect(detectIncompleteActionResponse('I will create the file now')).toBe(true);
  });

  it('detects "Let me write" as future intent', () => {
    expect(detectIncompleteActionResponse('Let me write the configuration')).toBe(true);
  });

  it('detects "I\'ll create" as future intent', () => {
    expect(detectIncompleteActionResponse("I'll create the component")).toBe(true);
  });

  it('detects "Now I will" as future intent', () => {
    expect(detectIncompleteActionResponse('Now I will save the file')).toBe(true);
  });

  it('passes completed responses', () => {
    expect(detectIncompleteActionResponse('I have completed the task. Here is the result.')).toBe(false);
  });

  it('passes response with "done" signal', () => {
    expect(detectIncompleteActionResponse("I will create the summary. Done")).toBe(false);
  });

  it('passes regular text without future intent', () => {
    expect(detectIncompleteActionResponse('The function calculates the sum of two numbers.')).toBe(false);
  });

  it('passes response with "created" signal despite future-intent start', () => {
    expect(detectIncompleteActionResponse("I will note that I've already created the file.")).toBe(false);
  });
});
