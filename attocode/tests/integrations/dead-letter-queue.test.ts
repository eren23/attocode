/**
 * Tests for the dead letter queue.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import Database from 'better-sqlite3';
import {
  DeadLetterQueue,
  createDeadLetterQueue,
  formatDeadLetterStats,
} from '../../src/integrations/dead-letter-queue.js';
import { ErrorCategory } from '../../src/errors/index.js';

describe('Dead Letter Queue', () => {
  let db: Database.Database;
  let dlq: DeadLetterQueue;

  beforeEach(() => {
    // Create in-memory database with DLQ schema
    db = new Database(':memory:');
    db.exec(`
      CREATE TABLE dead_letters (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        operation TEXT NOT NULL,
        args TEXT NOT NULL,
        error TEXT NOT NULL,
        category TEXT NOT NULL,
        attempts INTEGER DEFAULT 1,
        max_attempts INTEGER DEFAULT 3,
        last_attempt TEXT NOT NULL,
        next_retry TEXT,
        metadata TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        resolved_at TEXT
      );
      CREATE INDEX idx_dead_letters_status ON dead_letters(status);
    `);

    dlq = createDeadLetterQueue(db);
  });

  afterEach(() => {
    db.close();
  });

  describe('add', () => {
    it('should add a dead letter item', async () => {
      const item = await dlq.add({
        operation: 'tool:bash',
        args: { command: 'npm install' },
        error: new Error('ETIMEDOUT'),
        sessionId: 'session-123',
      });

      expect(item.id).toBeDefined();
      expect(item.operation).toBe('tool:bash');
      expect(item.args).toBe('{"command":"npm install"}');
      expect(item.error).toBe('ETIMEDOUT');
      expect(item.category).toBe(ErrorCategory.TRANSIENT);
      expect(item.attempts).toBe(1);
      expect(item.status).toBe('pending');
    });

    it('should categorize errors correctly', async () => {
      const item = await dlq.add({
        operation: 'api:call',
        args: {},
        error: new Error('Rate limit exceeded'),
      });

      expect(item.category).toBe(ErrorCategory.RATE_LIMITED);
    });

    it('should emit item.added event', async () => {
      const events: string[] = [];
      dlq.on(event => events.push(event.type));

      await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });

      expect(events).toContain('item.added');
    });
  });

  describe('get', () => {
    it('should retrieve an item by ID', async () => {
      const added = await dlq.add({
        operation: 'test',
        args: { key: 'value' },
        error: new Error('test error'),
      });

      const retrieved = dlq.get(added.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved?.id).toBe(added.id);
      expect(retrieved?.operation).toBe('test');
    });

    it('should return null for non-existent ID', () => {
      const result = dlq.get('non-existent');
      expect(result).toBeNull();
    });
  });

  describe('getPending', () => {
    it('should return pending items', async () => {
      await dlq.add({ operation: 'op1', args: {}, error: new Error('e1') });
      await dlq.add({ operation: 'op2', args: {}, error: new Error('e2') });

      const pending = dlq.getPending();

      expect(pending).toHaveLength(2);
      expect(pending.every(p => p.status === 'pending')).toBe(true);
    });

    it('should filter by operation', async () => {
      await dlq.add({ operation: 'tool:bash', args: {}, error: new Error('e1') });
      await dlq.add({ operation: 'tool:read', args: {}, error: new Error('e2') });

      const pending = dlq.getPending({ operation: 'tool:bash' });

      expect(pending).toHaveLength(1);
      expect(pending[0].operation).toBe('tool:bash');
    });

    it('should filter by session', async () => {
      await dlq.add({ operation: 'op1', args: {}, error: new Error('e1'), sessionId: 's1' });
      await dlq.add({ operation: 'op2', args: {}, error: new Error('e2'), sessionId: 's2' });

      const pending = dlq.getPending({ sessionId: 's1' });

      expect(pending).toHaveLength(1);
      expect(pending[0].sessionId).toBe('s1');
    });
  });

  describe('markRetrying', () => {
    it('should update status to retrying', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });

      dlq.markRetrying(item.id);

      const updated = dlq.get(item.id);
      expect(updated?.status).toBe('retrying');
      expect(updated?.attempts).toBe(2);
    });

    it('should emit item.retrying event', async () => {
      const events: string[] = [];
      dlq.on(event => events.push(event.type));

      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });
      dlq.markRetrying(item.id);

      expect(events).toContain('item.retrying');
    });
  });

  describe('resolve', () => {
    it('should mark item as resolved', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });

      dlq.resolve(item.id);

      const updated = dlq.get(item.id);
      expect(updated?.status).toBe('resolved');
      expect(updated?.resolvedAt).toBeDefined();
    });

    it('should emit item.resolved event', async () => {
      const events: string[] = [];
      dlq.on(event => events.push(event.type));

      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });
      dlq.resolve(item.id);

      expect(events).toContain('item.resolved');
    });
  });

  describe('abandon', () => {
    it('should mark item as abandoned', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });

      dlq.abandon(item.id);

      const updated = dlq.get(item.id);
      expect(updated?.status).toBe('abandoned');
    });
  });

  describe('returnToPending', () => {
    it('should return item to pending status', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
        maxAttempts: 3,
      });

      dlq.markRetrying(item.id);
      dlq.returnToPending(item.id);

      const updated = dlq.get(item.id);
      expect(updated?.status).toBe('pending');
    });

    it('should abandon when max attempts reached', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
        maxAttempts: 2,
      });

      // First retry
      dlq.markRetrying(item.id);
      dlq.returnToPending(item.id);

      // Second retry (reaches max)
      dlq.markRetrying(item.id);
      dlq.returnToPending(item.id);

      const updated = dlq.get(item.id);
      expect(updated?.status).toBe('abandoned');
    });
  });

  describe('delete', () => {
    it('should delete an item', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });

      dlq.delete(item.id);

      expect(dlq.get(item.id)).toBeNull();
    });

    it('should emit item.deleted event', async () => {
      const events: string[] = [];
      dlq.on(event => events.push(event.type));

      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });
      dlq.delete(item.id);

      expect(events).toContain('item.deleted');
    });
  });

  describe('getStats', () => {
    it('should return queue statistics', async () => {
      await dlq.add({ operation: 'op1', args: {}, error: new Error('timeout') });
      await dlq.add({ operation: 'op2', args: {}, error: new Error('timeout') });

      const item3 = await dlq.add({ operation: 'op3', args: {}, error: new Error('auth error') });
      dlq.resolve(item3.id);

      const stats = dlq.getStats();

      expect(stats.total).toBe(3);
      expect(stats.pending).toBe(2);
      expect(stats.resolved).toBe(1);
    });

    it('should count by operation', async () => {
      await dlq.add({ operation: 'tool:bash', args: {}, error: new Error('e1') });
      await dlq.add({ operation: 'tool:bash', args: {}, error: new Error('e2') });
      await dlq.add({ operation: 'tool:read', args: {}, error: new Error('e3') });

      const stats = dlq.getStats();

      expect(stats.byOperation['tool:bash']).toBe(2);
      expect(stats.byOperation['tool:read']).toBe(1);
    });
  });

  describe('cleanup', () => {
    it('should delete old resolved items', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });
      dlq.resolve(item.id);

      // Manually set resolved_at to 10 days ago
      db.prepare(`
        UPDATE dead_letters
        SET resolved_at = datetime('now', '-10 days')
        WHERE id = ?
      `).run(item.id);

      const deleted = dlq.cleanup(7);

      expect(deleted).toBe(1);
      expect(dlq.get(item.id)).toBeNull();
    });

    it('should not delete recent resolved items', async () => {
      const item = await dlq.add({
        operation: 'test',
        args: {},
        error: new Error('test'),
      });
      dlq.resolve(item.id);

      const deleted = dlq.cleanup(7);

      expect(deleted).toBe(0);
      expect(dlq.get(item.id)).not.toBeNull();
    });
  });

  describe('formatDeadLetterStats', () => {
    it('should format stats for display', () => {
      const stats = {
        total: 10,
        pending: 5,
        retrying: 2,
        resolved: 2,
        abandoned: 1,
        byOperation: {
          'tool:bash': 5,
          'tool:read': 5,
        },
        byCategory: {
          TRANSIENT: 7,
          PERMANENT: 3,
        },
      };

      const output = formatDeadLetterStats(stats);

      expect(output).toContain('Total: 10');
      expect(output).toContain('Pending: 5');
      expect(output).toContain('tool:bash: 5');
      expect(output).toContain('TRANSIENT: 7');
    });
  });

  describe('isAvailable', () => {
    it('should return true when table exists', () => {
      expect(dlq.isAvailable()).toBe(true);
    });

    it('should return false when table does not exist', () => {
      const emptyDb = new Database(':memory:');
      const unavailableDlq = createDeadLetterQueue(emptyDb);

      expect(unavailableDlq.isAvailable()).toBe(false);

      emptyDb.close();
    });
  });
});
