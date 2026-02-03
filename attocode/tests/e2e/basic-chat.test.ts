/**
 * E2E: Basic Chat Tests
 *
 * Tests basic conversation functionality with the agent.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  setupE2ETest,
  teardownE2ETest,
  E2ETestContext,
  ControllableMockProvider,
} from './setup.js';

describe('E2E: Controllable Mock Provider', () => {
  let ctx: E2ETestContext;

  beforeEach(async () => {
    ctx = await setupE2ETest();
  });

  afterEach(async () => {
    await teardownE2ETest(ctx);
  });

  describe('response queuing', () => {
    it('should return queued text responses in order', async () => {
      const { provider } = ctx;

      provider.setResponse('First response');
      provider.setResponse('Second response');

      const response1 = await provider.chat([{ role: 'user', content: 'Hello' }]);
      const response2 = await provider.chat([{ role: 'user', content: 'Hi again' }]);

      expect(response1.content).toBe('First response');
      expect(response2.content).toBe('Second response');
    });

    it('should return default response when queue is empty', async () => {
      const { provider } = ctx;

      const response = await provider.chat([{ role: 'user', content: 'Hello' }]);

      expect(response.content).toContain('No response queued');
    });

    it('should track call history', async () => {
      const { provider } = ctx;

      provider.setResponse('Response 1');
      await provider.chat([{ role: 'user', content: 'Message 1' }]);
      await provider.chat([{ role: 'user', content: 'Message 2' }]);

      const history = provider.getCallHistory();
      expect(history).toHaveLength(2);
      expect(history[0].messages[0].content).toBe('Message 1');
      expect(history[1].messages[0].content).toBe('Message 2');
    });

    it('should return last user message', async () => {
      const { provider } = ctx;

      provider.setResponse('Response');
      await provider.chat([
        { role: 'system', content: 'System prompt' },
        { role: 'user', content: 'User message' },
      ]);

      expect(provider.getLastUserMessage()).toBe('User message');
    });
  });

  describe('tool call responses', () => {
    it('should return queued tool calls', async () => {
      const { provider } = ctx;

      provider.setToolCall('read_file', { path: '/test.txt' });

      const response = await provider.chat([{ role: 'user', content: 'Read file' }]);

      expect(response.toolCalls).toHaveLength(1);
      expect(response.toolCalls![0].name).toBe('read_file');
      expect(response.toolCalls![0].arguments).toEqual({ path: '/test.txt' });
      expect(response.stopReason).toBe('tool_use');
    });

    it('should return multiple tool calls', async () => {
      const { provider } = ctx;

      provider.setToolCalls([
        { name: 'read_file', args: { path: 'a.txt' } },
        { name: 'read_file', args: { path: 'b.txt' } },
      ]);

      const response = await provider.chat([{ role: 'user', content: 'Read files' }]);

      expect(response.toolCalls).toHaveLength(2);
    });
  });

  describe('thinking responses', () => {
    it('should include thinking in response', async () => {
      const { provider } = ctx;

      provider.setThinkingResponse('Let me think...', 'Here is my answer.');

      const response = await provider.chat([{ role: 'user', content: 'Question' }]);

      expect(response.thinking).toBe('Let me think...');
      expect(response.content).toBe('Here is my answer.');
    });
  });

  describe('reset', () => {
    it('should clear queue and history on reset', async () => {
      const { provider } = ctx;

      provider.setResponse('Response');
      await provider.chat([{ role: 'user', content: 'Message' }]);

      provider.reset();

      expect(provider.getCallHistory()).toHaveLength(0);

      // Should get default response since queue is empty
      const response = await provider.chat([{ role: 'user', content: 'New message' }]);
      expect(response.content).toContain('No response queued');
    });
  });
});

describe('E2E: Test Context Helpers', () => {
  let ctx: E2ETestContext;

  beforeEach(async () => {
    ctx = await setupE2ETest();
  });

  afterEach(async () => {
    await teardownE2ETest(ctx);
  });

  describe('file operations', () => {
    it('should create and read files', async () => {
      const filePath = await ctx.createFile('test.txt', 'Hello World');

      expect(filePath).toContain('test.txt');

      const content = await ctx.readFile('test.txt');
      expect(content).toBe('Hello World');
    });

    it('should create files in subdirectories', async () => {
      await ctx.createFile('subdir/deep/file.txt', 'Nested content');

      const content = await ctx.readFile('subdir/deep/file.txt');
      expect(content).toBe('Nested content');
    });

    it('should check file existence', async () => {
      expect(await ctx.fileExists('nonexistent.txt')).toBe(false);

      await ctx.createFile('exists.txt', 'content');

      expect(await ctx.fileExists('exists.txt')).toBe(true);
    });
  });

  describe('temp directory', () => {
    it('should provide unique temp directory', async () => {
      const ctx2 = await setupE2ETest();

      expect(ctx.tempDir).not.toBe(ctx2.tempDir);

      await teardownE2ETest(ctx2);
    });

    it('should clean up temp directory on teardown', async () => {
      const tempCtx = await setupE2ETest();
      await tempCtx.createFile('test.txt', 'content');
      const tempDir = tempCtx.tempDir;

      await teardownE2ETest(tempCtx);

      // Directory should be gone
      const { existsSync } = await import('node:fs');
      expect(existsSync(tempDir)).toBe(false);
    });
  });
});
