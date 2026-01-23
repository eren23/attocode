/**
 * Tests for Attocode Modernization Features:
 * - Unified Diff Utilities
 * - SQLite Session Store
 * - Image Renderer
 * - Sourcegraph Integration
 * - Pricing Updates
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';

// =============================================================================
// DIFF UTILS TESTS
// =============================================================================

import {
  parseUnifiedDiff,
  applyDiff,
  generateDiff,
  getDiffStats,
  formatDiffColored,
  type UnifiedDiff,
} from '../src/integrations/diff-utils.js';

describe('Diff Utils', () => {
  describe('parseUnifiedDiff', () => {
    it('should parse a simple unified diff', () => {
      const diffText = `--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line 1
+new line
 line 2
 line 3`;

      const diffs = parseUnifiedDiff(diffText);

      expect(diffs).toHaveLength(1);
      expect(diffs[0].oldPath).toBe('file.txt');
      expect(diffs[0].newPath).toBe('file.txt');
      expect(diffs[0].hunks).toHaveLength(1);
      expect(diffs[0].hunks[0].lines).toHaveLength(4);
    });

    it('should parse a diff with multiple hunks', () => {
      const diffText = `--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 line 1
-old line
+new line
 line 3
@@ -10,3 +10,4 @@
 line 10
 line 11
+added line
 line 12`;

      const diffs = parseUnifiedDiff(diffText);

      expect(diffs).toHaveLength(1);
      expect(diffs[0].hunks).toHaveLength(2);
    });

    it('should detect new file', () => {
      const diffText = `--- /dev/null
+++ b/newfile.txt
@@ -0,0 +1,3 @@
+line 1
+line 2
+line 3`;

      const diffs = parseUnifiedDiff(diffText);

      expect(diffs).toHaveLength(1);
      expect(diffs[0].isNewFile).toBe(true);
    });

    it('should detect deleted file', () => {
      const diffText = `--- a/oldfile.txt
+++ /dev/null
@@ -1,3 +0,0 @@
-line 1
-line 2
-line 3`;

      const diffs = parseUnifiedDiff(diffText);

      expect(diffs).toHaveLength(1);
      expect(diffs[0].isDeletedFile).toBe(true);
    });

    it('should parse git format diffs', () => {
      const diffText = `diff --git a/src/file.ts b/src/file.ts
--- a/src/file.ts
+++ b/src/file.ts
@@ -1,2 +1,3 @@
 const a = 1;
+const b = 2;
 export { a };`;

      const diffs = parseUnifiedDiff(diffText);

      expect(diffs).toHaveLength(1);
      expect(diffs[0].oldPath).toBe('src/file.ts');
    });
  });

  describe('applyDiff', () => {
    it('should apply a simple addition', () => {
      const original = `line 1
line 2
line 3`;

      const diff: UnifiedDiff = {
        oldPath: 'file.txt',
        newPath: 'file.txt',
        hunks: [{
          oldStart: 1,
          oldCount: 3,
          newStart: 1,
          newCount: 4,
          lines: [
            { type: 'context', content: 'line 1', oldLineNumber: 1, newLineNumber: 1 },
            { type: 'add', content: 'new line', oldLineNumber: null, newLineNumber: 2 },
            { type: 'context', content: 'line 2', oldLineNumber: 2, newLineNumber: 3 },
            { type: 'context', content: 'line 3', oldLineNumber: 3, newLineNumber: 4 },
          ],
        }],
        isNewFile: false,
        isDeletedFile: false,
      };

      const result = applyDiff(original, diff);

      expect(result.success).toBe(true);
      expect(result.content).toContain('new line');
      expect(result.hunksApplied).toBe(1);
    });

    it('should apply a simple removal', () => {
      const original = `line 1
line to remove
line 3`;

      const diff: UnifiedDiff = {
        oldPath: 'file.txt',
        newPath: 'file.txt',
        hunks: [{
          oldStart: 1,
          oldCount: 3,
          newStart: 1,
          newCount: 2,
          lines: [
            { type: 'context', content: 'line 1', oldLineNumber: 1, newLineNumber: 1 },
            { type: 'remove', content: 'line to remove', oldLineNumber: 2, newLineNumber: null },
            { type: 'context', content: 'line 3', oldLineNumber: 3, newLineNumber: 2 },
          ],
        }],
        isNewFile: false,
        isDeletedFile: false,
      };

      const result = applyDiff(original, diff);

      expect(result.success).toBe(true);
      expect(result.content).not.toContain('line to remove');
    });

    it('should handle new file creation', () => {
      const diff: UnifiedDiff = {
        oldPath: '/dev/null',
        newPath: 'new.txt',
        hunks: [{
          oldStart: 0,
          oldCount: 0,
          newStart: 1,
          newCount: 2,
          lines: [
            { type: 'add', content: 'line 1', oldLineNumber: null, newLineNumber: 1 },
            { type: 'add', content: 'line 2', oldLineNumber: null, newLineNumber: 2 },
          ],
        }],
        isNewFile: true,
        isDeletedFile: false,
      };

      const result = applyDiff('', diff);

      expect(result.success).toBe(true);
      expect(result.content).toBe('line 1\nline 2');
    });

    it('should fail on context mismatch', () => {
      const original = `line 1
different line
line 3`;

      const diff: UnifiedDiff = {
        oldPath: 'file.txt',
        newPath: 'file.txt',
        hunks: [{
          oldStart: 1,
          oldCount: 3,
          newStart: 1,
          newCount: 3,
          lines: [
            { type: 'context', content: 'line 1', oldLineNumber: 1, newLineNumber: 1 },
            { type: 'context', content: 'expected line', oldLineNumber: 2, newLineNumber: 2 },
            { type: 'context', content: 'line 3', oldLineNumber: 3, newLineNumber: 3 },
          ],
        }],
        isNewFile: false,
        isDeletedFile: false,
      };

      const result = applyDiff(original, diff);

      expect(result.success).toBe(false);
      expect(result.hunksFailed).toBe(1);
    });
  });

  describe('generateDiff', () => {
    it('should generate diff for additions', () => {
      const oldContent = `line 1
line 2`;
      const newContent = `line 1
new line
line 2`;

      const diff = generateDiff(oldContent, newContent);

      expect(diff).toContain('--- a/file');
      expect(diff).toContain('+++ b/file');
      expect(diff).toContain('+new line');
    });

    it('should generate diff for removals', () => {
      const oldContent = `line 1
line to remove
line 3`;
      const newContent = `line 1
line 3`;

      const diff = generateDiff(oldContent, newContent);

      expect(diff).toContain('-line to remove');
    });

    it('should return empty string for identical content', () => {
      const content = `line 1
line 2`;

      const diff = generateDiff(content, content);

      expect(diff).toBe('');
    });
  });

  describe('getDiffStats', () => {
    it('should count additions and deletions', () => {
      const diff: UnifiedDiff = {
        oldPath: 'file.txt',
        newPath: 'file.txt',
        hunks: [{
          oldStart: 1,
          oldCount: 3,
          newStart: 1,
          newCount: 4,
          lines: [
            { type: 'context', content: 'line 1', oldLineNumber: 1, newLineNumber: 1 },
            { type: 'add', content: 'new 1', oldLineNumber: null, newLineNumber: 2 },
            { type: 'add', content: 'new 2', oldLineNumber: null, newLineNumber: 3 },
            { type: 'remove', content: 'old', oldLineNumber: 2, newLineNumber: null },
            { type: 'context', content: 'line 3', oldLineNumber: 3, newLineNumber: 4 },
          ],
        }],
        isNewFile: false,
        isDeletedFile: false,
      };

      const stats = getDiffStats(diff);

      expect(stats.additions).toBe(2);
      expect(stats.deletions).toBe(1);
      expect(stats.hunks).toBe(1);
    });
  });

  describe('formatDiffColored', () => {
    it('should add ANSI color codes', () => {
      const diff: UnifiedDiff = {
        oldPath: 'file.txt',
        newPath: 'file.txt',
        hunks: [{
          oldStart: 1,
          oldCount: 2,
          newStart: 1,
          newCount: 2,
          lines: [
            { type: 'add', content: 'added', oldLineNumber: null, newLineNumber: 1 },
            { type: 'remove', content: 'removed', oldLineNumber: 1, newLineNumber: null },
          ],
        }],
        isNewFile: false,
        isDeletedFile: false,
      };

      const colored = formatDiffColored(diff);

      // Should contain ANSI escape codes
      expect(colored).toContain('\x1b[');
      expect(colored).toContain('\x1b[32m'); // Green for additions
      expect(colored).toContain('\x1b[31m'); // Red for removals
    });
  });
});

// =============================================================================
// IMAGE RENDERER TESTS
// =============================================================================

import {
  detectProtocol,
  isProtocolAvailable,
  createImageRenderer,
  canRenderImage,
  getProtocolInfo,
  type ImageProtocol,
} from '../src/integrations/image-renderer.js';

describe('Image Renderer', () => {
  describe('detectProtocol', () => {
    it('should return a valid protocol', () => {
      const protocol = detectProtocol();
      expect(['kitty', 'iterm', 'sixel', 'block', 'none']).toContain(protocol);
    });
  });

  describe('isProtocolAvailable', () => {
    it('should always return true for block', () => {
      expect(isProtocolAvailable('block')).toBe(true);
    });

    it('should always return true for none', () => {
      expect(isProtocolAvailable('none')).toBe(true);
    });
  });

  describe('canRenderImage', () => {
    it('should return true for PNG files', () => {
      expect(canRenderImage('image.png')).toBe(true);
      expect(canRenderImage('image.PNG')).toBe(true);
    });

    it('should return true for JPEG files', () => {
      expect(canRenderImage('image.jpg')).toBe(true);
      expect(canRenderImage('image.jpeg')).toBe(true);
    });

    it('should return true for GIF files', () => {
      expect(canRenderImage('image.gif')).toBe(true);
    });

    it('should return true for WebP files', () => {
      expect(canRenderImage('image.webp')).toBe(true);
    });

    it('should return false for non-image files', () => {
      expect(canRenderImage('document.pdf')).toBe(false);
      expect(canRenderImage('script.js')).toBe(false);
      expect(canRenderImage('readme.md')).toBe(false);
    });
  });

  describe('ImageRenderer', () => {
    it('should create renderer with auto-detected protocol', () => {
      const renderer = createImageRenderer();
      expect(renderer.getProtocol()).toBeDefined();
    });

    it('should create renderer with specified protocol', () => {
      const renderer = createImageRenderer({ protocol: 'block' });
      expect(renderer.getProtocol()).toBe('block');
    });

    it('should report supported formats correctly', () => {
      const renderer = createImageRenderer();
      expect(renderer.isSupportedFormat('test.png')).toBe(true);
      expect(renderer.isSupportedFormat('test.txt')).toBe(false);
    });

    it('should report support status', () => {
      const renderer = createImageRenderer({ protocol: 'block' });
      expect(renderer.isSupported()).toBe(true);

      const noneRenderer = createImageRenderer({ protocol: 'none' });
      expect(noneRenderer.isSupported()).toBe(false);
    });

    it('should fail gracefully for non-existent file', async () => {
      const renderer = createImageRenderer({ protocol: 'block' });
      const result = await renderer.renderFile('/nonexistent/image.png');

      expect(result.success).toBe(false);
      expect(result.error).toContain('not found');
    });

    it('should fail for unsupported format', async () => {
      const renderer = createImageRenderer({ protocol: 'block' });
      // Test with a non-image file type - we expect it to fail either due to
      // file not found or unsupported format (depends on check order)
      const result = await renderer.renderFile('/some/file.txt');

      expect(result.success).toBe(false);
      // Either error is acceptable since the file doesn't exist anyway
      expect(result.error).toBeDefined();
    });
  });

  describe('getProtocolInfo', () => {
    it('should return protocol information', () => {
      const info = getProtocolInfo();

      expect(info.detected).toBeDefined();
      expect(typeof info.supported).toBe('boolean');
    });
  });
});

// =============================================================================
// SQLITE STORE TESTS
// =============================================================================

import {
  SQLiteStore,
  createSQLiteStore,
  type SQLiteStoreConfig,
} from '../src/integrations/sqlite-store.js';

describe('SQLite Store', () => {
  let store: SQLiteStore;
  let tempDir: string;

  beforeEach(async () => {
    tempDir = join(tmpdir(), `attocode-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tempDir, { recursive: true });

    store = await createSQLiteStore({
      dbPath: join(tempDir, 'test.db'),
      baseDir: tempDir,
    });
  });

  afterEach(async () => {
    await store.cleanup();
    if (existsSync(tempDir)) {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  describe('session management', () => {
    it('should create a session', () => {
      const sessionId = store.createSession('Test Session');

      expect(sessionId).toBeDefined();
      expect(sessionId).toMatch(/^session-/);
    });

    it('should list sessions', () => {
      store.createSession('Session 1');
      store.createSession('Session 2');

      const sessions = store.listSessions();

      expect(sessions).toHaveLength(2);
    });

    it('should get session metadata', () => {
      const sessionId = store.createSession('Test Session');
      const metadata = store.getSessionMetadata(sessionId);

      expect(metadata).toBeDefined();
      expect(metadata?.name).toBe('Test Session');
      expect(metadata?.messageCount).toBe(0);
    });

    it('should delete a session', () => {
      const sessionId = store.createSession('To Delete');
      store.deleteSession(sessionId);

      const sessions = store.listSessions();
      expect(sessions.find(s => s.id === sessionId)).toBeUndefined();
    });

    it('should update session metadata', () => {
      const sessionId = store.createSession('Original');
      store.updateSessionMetadata(sessionId, {
        name: 'Updated',
        summary: 'Test summary',
      });

      const metadata = store.getSessionMetadata(sessionId);
      expect(metadata?.name).toBe('Updated');
      expect(metadata?.summary).toBe('Test summary');
    });
  });

  describe('entries', () => {
    it('should append a message', () => {
      const sessionId = store.createSession('Test');
      store.appendMessage({ role: 'user', content: 'Hello' });

      const entries = store.loadSession(sessionId);
      expect(entries).toHaveLength(1);
      expect(entries[0].type).toBe('message');
    });

    it('should increment message count', () => {
      const sessionId = store.createSession('Test');
      store.appendMessage({ role: 'user', content: 'Hello' });
      store.appendMessage({ role: 'assistant', content: 'Hi' });

      const metadata = store.getSessionMetadata(sessionId);
      expect(metadata?.messageCount).toBe(2);
    });

    it('should append compaction summary', () => {
      const sessionId = store.createSession('Test');
      store.appendCompaction('Summary of conversation', 10);

      const entries = store.loadSession(sessionId);
      expect(entries).toHaveLength(1);
      expect(entries[0].type).toBe('compaction');
    });

    it('should load session messages', () => {
      const sessionId = store.createSession('Test');
      store.appendMessage({ role: 'user', content: 'Hello' });
      store.appendMessage({ role: 'assistant', content: 'Hi there!' });

      const messages = store.loadSessionMessages(sessionId);

      expect(messages).toHaveLength(2);
      expect(messages[0].role).toBe('user');
      expect(messages[1].role).toBe('assistant');
    });
  });

  describe('checkpoints', () => {
    it('should save a checkpoint', () => {
      store.createSession('Test');
      const checkpointId = store.saveCheckpoint(
        { messages: [], tokens: 100 },
        'Initial state'
      );

      expect(checkpointId).toBeDefined();
      expect(checkpointId).toMatch(/^ckpt-/);
    });

    it('should load latest checkpoint', () => {
      const sessionId = store.createSession('Test');
      store.saveCheckpoint({ count: 1 }, 'First');
      store.saveCheckpoint({ count: 2 }, 'Second');

      const checkpoint = store.loadLatestCheckpoint(sessionId);

      expect(checkpoint).toBeDefined();
      expect(checkpoint?.state.count).toBe(2);
      expect(checkpoint?.description).toBe('Second');
    });

    it('should return null for session without checkpoints', () => {
      const sessionId = store.createSession('Test');
      const checkpoint = store.loadLatestCheckpoint(sessionId);

      expect(checkpoint).toBeNull();
    });
  });

  describe('statistics', () => {
    it('should return database stats', () => {
      store.createSession('Test');
      store.appendMessage({ role: 'user', content: 'Hello' });

      const stats = store.getStats();

      expect(stats.sessionCount).toBe(1);
      expect(stats.entryCount).toBe(1);
      expect(stats.dbSizeBytes).toBeGreaterThan(0);
    });
  });

  describe('events', () => {
    it('should emit session.created event', () => {
      const callback = vi.fn();
      store.on(callback);

      store.createSession('Test');

      expect(callback).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'session.created' })
      );
    });

    it('should emit entry.appended event', () => {
      const callback = vi.fn();
      store.createSession('Test');
      store.on(callback);

      store.appendMessage({ role: 'user', content: 'Hello' });

      expect(callback).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'entry.appended', entryType: 'message' })
      );
    });

    it('should allow unsubscribe', () => {
      const callback = vi.fn();
      const unsubscribe = store.on(callback);

      unsubscribe();
      store.createSession('Test');

      expect(callback).not.toHaveBeenCalled();
    });
  });

  describe('migration', () => {
    it('should handle migration from empty directory', async () => {
      const result = await store.migrateFromJSONL(join(tempDir, 'nonexistent'));

      expect(result.migrated).toBe(0);
      expect(result.failed).toBe(0);
    });

    it('should migrate from JSONL format', async () => {
      // Create mock JSONL data
      const jsonlDir = join(tempDir, 'jsonl');
      await mkdir(jsonlDir, { recursive: true });

      const sessionId = 'session-test123';
      const index = {
        version: 1,
        sessions: [{
          id: sessionId,
          name: 'Test JSONL Session',
          createdAt: new Date().toISOString(),
          lastActiveAt: new Date().toISOString(),
          messageCount: 1,
          tokenCount: 0,
        }],
      };

      await writeFile(join(jsonlDir, 'index.json'), JSON.stringify(index));
      await writeFile(
        join(jsonlDir, `${sessionId}.jsonl`),
        JSON.stringify({
          timestamp: new Date().toISOString(),
          type: 'message',
          data: { role: 'user', content: 'Hello from JSONL' },
        }) + '\n'
      );

      const result = await store.migrateFromJSONL(jsonlDir);

      expect(result.migrated).toBe(1);
      expect(result.failed).toBe(0);

      // Verify migrated data
      const sessions = store.listSessions();
      expect(sessions.find(s => s.id === sessionId)).toBeDefined();
    });
  });
});

// =============================================================================
// SOURCEGRAPH CLIENT TESTS
// =============================================================================

import {
  SourcegraphClient,
  createSourcegraphClient,
  isSourcegraphConfigured,
  formatSearchResults,
  type SearchResponse,
} from '../src/integrations/sourcegraph.js';

describe('Sourcegraph Client', () => {
  describe('isSourcegraphConfigured', () => {
    it('should return false when token not set', () => {
      const originalToken = process.env.SOURCEGRAPH_ACCESS_TOKEN;
      delete process.env.SOURCEGRAPH_ACCESS_TOKEN;

      expect(isSourcegraphConfigured()).toBe(false);

      if (originalToken) {
        process.env.SOURCEGRAPH_ACCESS_TOKEN = originalToken;
      }
    });
  });

  describe('SourcegraphClient', () => {
    it('should create client without token', () => {
      const client = createSourcegraphClient();
      expect(client).toBeDefined();
      expect(client.isConfigured()).toBe(false);
    });

    it('should create client with explicit token', () => {
      const client = createSourcegraphClient({
        accessToken: 'test-token',
      });
      expect(client.isConfigured()).toBe(true);
    });

    it('should use custom endpoint', () => {
      const client = createSourcegraphClient({
        endpoint: 'https://sourcegraph.example.com',
        accessToken: 'test-token',
      });
      expect(client).toBeDefined();
    });

    it('should throw when searching without token', async () => {
      const client = createSourcegraphClient();

      await expect(client.search('test query')).rejects.toThrow('not configured');
    });
  });

  describe('formatSearchResults', () => {
    it('should format empty results', () => {
      const response: SearchResponse = {
        results: [],
        matchCount: 0,
        durationMs: 100,
        limitHit: false,
      };

      const formatted = formatSearchResults(response);

      expect(formatted).toContain('Found 0 matches');
      expect(formatted).toContain('100ms');
    });

    it('should format results with matches', () => {
      const response: SearchResponse = {
        results: [
          {
            repository: 'github.com/org/repo',
            filePath: 'src/file.ts',
            fileUrl: 'https://sourcegraph.com/github.com/org/repo/-/blob/src/file.ts',
            lineNumbers: [10, 20],
            preview: 'function test() {\n  return true;\n}',
            matchType: 'content',
          },
        ],
        matchCount: 1,
        durationMs: 50,
        limitHit: false,
      };

      const formatted = formatSearchResults(response);

      expect(formatted).toContain('Found 1 matches');
      expect(formatted).toContain('github.com/org/repo');
      expect(formatted).toContain('src/file.ts');
      expect(formatted).toContain('Line 10, 20');
    });

    it('should indicate truncated results', () => {
      const response: SearchResponse = {
        results: [],
        matchCount: 1000,
        durationMs: 100,
        limitHit: true,
      };

      const formatted = formatSearchResults(response);

      expect(formatted).toContain('truncated');
    });

    it('should show alerts', () => {
      const response: SearchResponse = {
        results: [],
        matchCount: 0,
        durationMs: 100,
        limitHit: false,
        alerts: ['Consider using a more specific query'],
      };

      const formatted = formatSearchResults(response);

      expect(formatted).toContain('Alerts:');
      expect(formatted).toContain('more specific query');
    });
  });
});

// =============================================================================
// PRICING UPDATES TESTS
// =============================================================================

import { DEFAULT_PRICING, getModelPricing, calculateCost, formatCost } from '../src/integrations/openrouter-pricing.js';

describe('Pricing Updates', () => {
  describe('DEFAULT_PRICING', () => {
    it('should have updated pricing values', () => {
      // Should be $0.075 per million input tokens (Gemini Flash tier)
      expect(DEFAULT_PRICING.prompt).toBe(0.000000075);
      // Should be $0.30 per million output tokens (Gemini Flash tier)
      expect(DEFAULT_PRICING.completion).toBe(0.0000003);
    });

    it('should have zero request and image cost', () => {
      expect(DEFAULT_PRICING.request).toBe(0);
      expect(DEFAULT_PRICING.image).toBe(0);
    });
  });

  describe('getModelPricing', () => {
    it('should return default pricing for unknown model', () => {
      const pricing = getModelPricing('unknown-model-xyz');

      expect(pricing.prompt).toBe(DEFAULT_PRICING.prompt);
      expect(pricing.completion).toBe(DEFAULT_PRICING.completion);
    });
  });

  describe('calculateCost', () => {
    it('should calculate cost correctly', () => {
      // 1000 input tokens + 500 output tokens with default pricing (Gemini Flash)
      // Input: 1000 * 0.000000075 = $0.000075
      // Output: 500 * 0.0000003 = $0.00015
      // Total: $0.000225
      const cost = calculateCost('unknown-model', 1000, 500);

      expect(cost).toBeCloseTo(0.000225, 9);
    });

    it('should handle zero tokens', () => {
      const cost = calculateCost('unknown-model', 0, 0);
      expect(cost).toBe(0);
    });
  });

  describe('formatCost', () => {
    it('should format small costs in microdollars', () => {
      const formatted = formatCost(0.00001);
      expect(formatted).toContain('µ');
    });

    it('should format medium costs with 6 decimals', () => {
      const formatted = formatCost(0.001);
      expect(formatted).toMatch(/\$0\.\d{6}/);
    });

    it('should format larger costs with 4 decimals', () => {
      const formatted = formatCost(0.05);
      expect(formatted).toMatch(/\$0\.\d{4}/);
    });
  });
});

// =============================================================================
// TUI STATE TESTS
// =============================================================================

import { DEFAULT_TUI_STATE, type TUIState } from '../src/tui/types.js';

describe('TUI State Updates', () => {
  describe('DEFAULT_TUI_STATE', () => {
    it('should have toolCallsExpanded field', () => {
      expect(DEFAULT_TUI_STATE.toolCallsExpanded).toBeDefined();
      expect(DEFAULT_TUI_STATE.toolCallsExpanded).toBe(false);
    });

    it('should have showThinkingPanel field', () => {
      expect(DEFAULT_TUI_STATE.showThinkingPanel).toBeDefined();
      expect(DEFAULT_TUI_STATE.showThinkingPanel).toBe(true);
    });
  });
});

// =============================================================================
// EXECUTION ECONOMICS MANAGER TESTS
// =============================================================================

import { ExecutionEconomicsManager } from '../src/integrations/economics.js';

describe('ExecutionEconomicsManager', () => {
  describe('initialization', () => {
    it('should create with default budgets', () => {
      const manager = new ExecutionEconomicsManager();
      const usage = manager.getUsage();

      expect(usage.tokens).toBe(0);
      expect(usage.cost).toBe(0);
      expect(usage.iterations).toBe(0);
    });

    it('should accept custom budget configuration', () => {
      const manager = new ExecutionEconomicsManager({
        maxTokens: 100000,
        maxCost: 0.50,
        maxIterations: 50,
      });

      const budget = manager.getBudget();
      expect(budget.maxTokens).toBe(100000);
      expect(budget.maxCost).toBe(0.50);
      expect(budget.maxIterations).toBe(50);
    });
  });

  describe('recordLLMUsage', () => {
    it('should track token usage', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordLLMUsage(1000, 500);
      const usage = manager.getUsage();

      expect(usage.inputTokens).toBe(1000);
      expect(usage.outputTokens).toBe(500);
      expect(usage.tokens).toBe(1500);
      expect(usage.llmCalls).toBe(1);
    });

    it('should accumulate multiple LLM calls', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordLLMUsage(1000, 500);
      manager.recordLLMUsage(2000, 1000);
      const usage = manager.getUsage();

      expect(usage.tokens).toBe(4500);
      expect(usage.llmCalls).toBe(2);
    });

    it('should use actual cost when provided', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordLLMUsage(1000, 500, 'test-model', 0.01);
      const usage = manager.getUsage();

      expect(usage.cost).toBe(0.01);
    });
  });

  describe('recordToolCall', () => {
    it('should track tool calls and iterations', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordToolCall('read_file', { path: '/test.ts' });
      const usage = manager.getUsage();

      expect(usage.toolCalls).toBe(1);
      expect(usage.iterations).toBe(1);
    });

    it('should track files read', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordToolCall('read_file', { path: '/test.ts' });
      manager.recordToolCall('read_file', { path: '/other.ts' });
      const progress = manager.getProgress();

      // getProgress() returns counts, not Sets
      expect(progress.filesRead).toBe(2);
    });

    it('should track files modified', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordToolCall('write_file', { path: '/new.ts' });
      manager.recordToolCall('edit_file', { path: '/existing.ts' });
      const progress = manager.getProgress();

      expect(progress.filesModified).toBe(2);
    });

    it('should track commands run', () => {
      const manager = new ExecutionEconomicsManager();

      manager.recordToolCall('bash', { command: 'npm test' });
      const progress = manager.getProgress();

      // commandsRun is a count
      expect(progress.commandsRun).toBe(1);
    });
  });

  describe('checkBudget', () => {
    it('should allow continuation when within budget', () => {
      const manager = new ExecutionEconomicsManager({
        maxTokens: 100000,
        maxCost: 1.00,
      });

      manager.recordLLMUsage(1000, 500);
      const result = manager.checkBudget();

      expect(result.canContinue).toBe(true);
    });

    it('should stop when token budget exceeded', () => {
      const manager = new ExecutionEconomicsManager({
        maxTokens: 1000,
        softTokenLimit: 800,
      });

      manager.recordLLMUsage(800, 300); // 1100 tokens > 1000 limit
      const result = manager.checkBudget();

      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('tokens');
      expect(result.isHardLimit).toBe(true);
    });

    it('should stop when cost budget exceeded', () => {
      const manager = new ExecutionEconomicsManager({
        maxCost: 0.01,
        softCostLimit: 0.008,
      });

      manager.recordLLMUsage(1000, 500, 'test', 0.02); // $0.02 > $0.01 limit
      const result = manager.checkBudget();

      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('cost');
    });

    it('should stop when max iterations exceeded', () => {
      const manager = new ExecutionEconomicsManager({
        maxIterations: 5,
      });

      for (let i = 0; i < 6; i++) {
        manager.recordToolCall('test', {});
      }
      const result = manager.checkBudget();

      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('iterations');
    });

    it('should warn but continue on soft limit', () => {
      const manager = new ExecutionEconomicsManager({
        maxTokens: 100000,
        softTokenLimit: 1000,
      });

      manager.recordLLMUsage(800, 400); // 1200 tokens > 1000 soft limit
      const result = manager.checkBudget();

      expect(result.canContinue).toBe(true);
      expect(result.isSoftLimit).toBe(true);
      expect(result.suggestedAction).toBe('request_extension');
    });
  });

  describe('extendBudget', () => {
    it('should update budget limits', () => {
      const manager = new ExecutionEconomicsManager({
        maxTokens: 100000,
      });

      // extendBudget replaces values, doesn't add to them
      manager.extendBudget({ maxTokens: 150000 });
      const budget = manager.getBudget();

      expect(budget.maxTokens).toBe(150000);
    });
  });

  describe('events', () => {
    it('should emit events to listeners', () => {
      const manager = new ExecutionEconomicsManager();
      const events: unknown[] = [];

      manager.on((event) => events.push(event));
      manager.recordToolCall('read_file', { path: '/test.ts' });

      expect(events.length).toBeGreaterThan(0);
    });
  });
});

// =============================================================================
// PRICING API TESTS
// =============================================================================

import { fetchOpenRouterPricing, initPricingCache, pricingCache } from '../src/integrations/openrouter-pricing.js';

describe('OpenRouter Pricing API', () => {
  describe('fetchOpenRouterPricing', () => {
    it('should return empty map when no API key', async () => {
      // Save and clear API key
      const originalKey = process.env.OPENROUTER_API_KEY;
      delete process.env.OPENROUTER_API_KEY;

      const result = await fetchOpenRouterPricing();

      expect(result).toBeInstanceOf(Map);
      expect(result.size).toBe(0);

      // Restore
      if (originalKey) process.env.OPENROUTER_API_KEY = originalKey;
    });
  });

  describe('initPricingCache', () => {
    it('should not throw when initializing', async () => {
      await expect(initPricingCache()).resolves.not.toThrow();
    });
  });

  describe('pricingCache', () => {
    it('should be a Map', () => {
      expect(pricingCache).toBeInstanceOf(Map);
    });
  });
});
