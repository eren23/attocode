/**
 * Session Store Tests (JSONL-based)
 *
 * Tests for the JSONL session persistence functionality.
 * Covers session creation, saving, loading, and round-trip integrity.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdir, rm } from 'node:fs/promises';
import { SessionStore, createSessionStore } from '../src/integrations/persistence/session-store.js';

describe('SessionStore (JSONL)', () => {
  let tempDir: string;
  let store: SessionStore;

  beforeEach(async () => {
    tempDir = join(tmpdir(), `session-test-${Date.now()}`);
    await mkdir(tempDir, { recursive: true });
    store = new SessionStore({ baseDir: tempDir });
    await store.initialize();
  });

  afterEach(async () => {
    try {
      await rm(tempDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  describe('initialization', () => {
    it('should create with default config', async () => {
      const defaultStore = new SessionStore();
      expect(defaultStore).toBeDefined();
    });

    it('should create with custom config', async () => {
      const customStore = new SessionStore({
        baseDir: tempDir,
        autoSave: false,
        maxSessions: 10,
      });
      await customStore.initialize();
      expect(customStore).toBeDefined();
    });

    it('should create session directory on initialize', async () => {
      // Store is initialized - it exists and can create sessions
      const sessionId = await store.createSession('Test');
      expect(sessionId).toBeDefined();
    });
  });

  describe('session creation', () => {
    it('should create a new session', async () => {
      const sessionId = await store.createSession();
      expect(sessionId).toBeDefined();
      expect(sessionId).toMatch(/^session-/);
    });

    it('should create session with custom name', async () => {
      const sessionId = await store.createSession('My Test Session');
      expect(sessionId).toBeDefined();

      const sessions = await store.listSessions();
      const session = sessions.find(s => s.id === sessionId);
      expect(session?.name).toBe('My Test Session');
    });

    it('should generate unique session IDs', async () => {
      const id1 = await store.createSession();
      const id2 = await store.createSession();
      expect(id1).not.toBe(id2);
    });
  });

  describe('session listing', () => {
    it('should return empty array when no sessions', async () => {
      const sessions = await store.listSessions();
      expect(sessions).toEqual([]);
    });

    it('should list created sessions', async () => {
      await store.createSession('Session 1');
      await store.createSession('Session 2');

      const sessions = await store.listSessions();
      expect(sessions).toHaveLength(2);
    });

    it('should order sessions by last active time', async () => {
      const id1 = await store.createSession('First');
      // Small delay to ensure different timestamps
      await new Promise(resolve => setTimeout(resolve, 10));
      const id2 = await store.createSession('Second');

      const sessions = await store.listSessions();
      expect(sessions[0].id).toBe(id2); // Most recent first
      expect(sessions[1].id).toBe(id1);
    });
  });

  describe('entry appending', () => {
    let sessionId: string;

    beforeEach(async () => {
      sessionId = await store.createSession('Test Session');
      store.setCurrentSessionId(sessionId);
    });

    it('should append message entries', async () => {
      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'Hello' },
      });

      const entries = await store.loadSession(sessionId);
      expect(entries).toHaveLength(1);
      expect(entries[0].type).toBe('message');
    });

    it('should append multiple entries', async () => {
      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'Hello' },
      });

      await store.appendEntry({
        type: 'message',
        data: { role: 'assistant', content: 'Hi there!' },
      });

      const entries = await store.loadSession(sessionId);
      expect(entries).toHaveLength(2);
    });

    it('should append tool_call entries', async () => {
      await store.appendEntry({
        type: 'tool_call',
        data: {
          id: 'tc_123',
          name: 'read_file',
          arguments: { path: '/test.txt' },
        },
      });

      const entries = await store.loadSession(sessionId);
      expect(entries[0].type).toBe('tool_call');
    });

    it('should append checkpoint entries', async () => {
      await store.appendEntry({
        type: 'checkpoint',
        data: {
          iteration: 5,
          messages: [],
          metrics: { tokensUsed: 1000 },
        },
      });

      const entries = await store.loadSession(sessionId);
      expect(entries[0].type).toBe('checkpoint');
    });
  });

  describe('session loading', () => {
    let sessionId: string;

    beforeEach(async () => {
      sessionId = await store.createSession('Load Test');
      store.setCurrentSessionId(sessionId);

      // Add some entries
      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'Test message 1' },
      });
      await store.appendEntry({
        type: 'message',
        data: { role: 'assistant', content: 'Test response 1' },
      });
    });

    it('should load session entries', async () => {
      const entries = await store.loadSession(sessionId);
      expect(entries).toHaveLength(2);
    });

    it('should preserve entry order', async () => {
      const entries = await store.loadSession(sessionId);
      expect((entries[0].data as any).content).toBe('Test message 1');
      expect((entries[1].data as any).content).toBe('Test response 1');
    });

    it('should throw for non-existent session', async () => {
      await expect(store.loadSession('nonexistent-id')).rejects.toThrow('Session not found');
    });
  });

  describe('round-trip integrity', () => {
    it('should preserve message data through round-trip', async () => {
      const sessionId = await store.createSession('Round Trip');
      store.setCurrentSessionId(sessionId);

      const originalMessage = {
        role: 'user' as const,
        content: 'This is a test with special chars: äöü 日本語 🎉',
        metadata: { source: 'test', timestamp: Date.now() },
      };

      await store.appendEntry({
        type: 'message',
        data: originalMessage,
      });

      // Reload the session
      const entries = await store.loadSession(sessionId);
      const loadedMessage = entries[0].data;

      expect(loadedMessage).toEqual(originalMessage);
    });

    it('should preserve tool call arguments', async () => {
      const sessionId = await store.createSession('Tool Call Round Trip');
      store.setCurrentSessionId(sessionId);

      const originalToolCall = {
        id: 'tc_test_123',
        name: 'complex_tool',
        arguments: {
          nested: { deep: { value: 42 } },
          array: [1, 2, 3],
          special: 'chars\twith\nnewlines',
        },
      };

      await store.appendEntry({
        type: 'tool_call',
        data: originalToolCall,
      });

      const entries = await store.loadSession(sessionId);
      expect(entries[0].data).toEqual(originalToolCall);
    });
  });

  describe('event emission', () => {
    it('should emit session.created event', async () => {
      const listener = vi.fn();
      store.on(listener);

      await store.createSession('Event Test');

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'session.created' })
      );
    });

    it('should emit entry.appended event', async () => {
      const sessionId = await store.createSession('Append Event Test');
      store.setCurrentSessionId(sessionId);

      const listener = vi.fn();
      store.on(listener);

      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'test' },
      });

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'entry.appended',
          entryType: 'message',
        })
      );
    });

    it('should unsubscribe from events', async () => {
      const listener = vi.fn();
      const unsubscribe = store.on(listener);
      unsubscribe();

      await store.createSession('Unsubscribe Test');
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('session deletion', () => {
    it('should delete a session', async () => {
      const sessionId = await store.createSession('To Delete');

      await store.deleteSession(sessionId);

      const sessions = await store.listSessions();
      expect(sessions.find(s => s.id === sessionId)).toBeUndefined();
    });

    it('should handle deleting non-existent session', async () => {
      // Should not throw
      await store.deleteSession('nonexistent-id');
    });
  });

  describe('session metadata', () => {
    it('should update lastActiveAt on append', async () => {
      const sessionId = await store.createSession('Metadata Test');
      store.setCurrentSessionId(sessionId);

      const beforeAppend = await store.listSessions();
      const initialTime = beforeAppend[0].lastActiveAt;

      // Small delay
      await new Promise(resolve => setTimeout(resolve, 10));

      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'test' },
      });

      const afterAppend = await store.listSessions();
      const updatedTime = afterAppend.find(s => s.id === sessionId)?.lastActiveAt;

      expect(updatedTime).not.toBe(initialTime);
    });

    it('should track message count', async () => {
      const sessionId = await store.createSession('Count Test');
      store.setCurrentSessionId(sessionId);

      await store.appendEntry({
        type: 'message',
        data: { role: 'user', content: 'msg1' },
      });
      await store.appendEntry({
        type: 'message',
        data: { role: 'assistant', content: 'msg2' },
      });

      const sessions = await store.listSessions();
      const session = sessions.find(s => s.id === sessionId);
      expect(session?.messageCount).toBe(2);
    });
  });
});

describe('createSessionStore', () => {
  let tempDir: string;

  beforeEach(async () => {
    tempDir = join(tmpdir(), `session-factory-${Date.now()}`);
    await mkdir(tempDir, { recursive: true });
  });

  afterEach(async () => {
    try {
      await rm(tempDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  it('should create and initialize store', async () => {
    const store = await createSessionStore({ baseDir: tempDir });
    expect(store).toBeDefined();

    // Should be ready to use immediately
    const sessions = await store.listSessions();
    expect(sessions).toEqual([]);
  });
});
