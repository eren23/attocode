/**
 * Integration Tests: Core + Persistence
 *
 * Verifies that all core infrastructure modules work together:
 * - Protocol Layer (Op/Event types)
 * - Queue System (SubmissionQueue, EventQueue)
 * - Persistence (SQLiteStore, Migrations)
 * - Costs (ModelRegistry, cost calculation)
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import Database from 'better-sqlite3';

// Import from core modules
import { createSQLiteStore, SQLiteStore, type UsageLog } from '../../src/integrations/persistence/sqlite-store.js';
import { SubmissionQueue, EventQueue } from '../../src/core/queues/index.js';
import { modelRegistry, type UsageRecord } from '../../src/costs/index.js';
import { getSchemaVersion, loadMigrations } from '../../src/persistence/migrator.js';
import type {
  OpUserTurn,
  EventAgentMessage,
  EventTaskComplete,
  EventEnvelope,
} from '../../src/core/protocol/types.js';

describe('Core + Persistence Integration', () => {
  let store: SQLiteStore;
  let tempDir: string;

  beforeEach(async () => {
    tempDir = await mkdtemp(join(tmpdir(), 'attocode-test-'));
    store = await createSQLiteStore({ dbPath: join(tempDir, 'test.db') });
  });

  afterEach(async () => {
    store.close();
    await rm(tempDir, { recursive: true, force: true });
  });

  // ===========================================================================
  // Session with Cost Tracking
  // ===========================================================================

  describe('Session with Cost Tracking', () => {
    it('should create session and track usage costs', async () => {
      // Create a session
      const sessionId = store.createSession('Test Session');
      expect(sessionId).toBeDefined();
      expect(sessionId).toMatch(/^session-/);

      // Initial usage should be zero
      const initialUsage = store.getSessionUsage(sessionId);
      expect(initialUsage.promptTokens).toBe(0);
      expect(initialUsage.completionTokens).toBe(0);
      expect(initialUsage.costUsd).toBe(0);

      // Log some usage
      const usageLog: UsageLog = {
        sessionId,
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 1000,
        completionTokens: 500,
        costUsd: 0.0195,
        timestamp: new Date().toISOString(),
      };
      store.logUsage(usageLog);

      // Verify getSessionUsage() returns correct totals
      const usage = store.getSessionUsage(sessionId);
      expect(usage.promptTokens).toBe(1000);
      expect(usage.completionTokens).toBe(500);
      expect(usage.costUsd).toBe(0.0195);
    });

    it('should accumulate multiple usage logs', async () => {
      const sessionId = store.createSession('Multi-Usage Session');

      // Log first usage
      store.logUsage({
        sessionId,
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 1000,
        completionTokens: 500,
        costUsd: 0.0195,
        timestamp: new Date().toISOString(),
      });

      // Log second usage
      store.logUsage({
        sessionId,
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 2000,
        completionTokens: 1000,
        costUsd: 0.039,
        timestamp: new Date().toISOString(),
      });

      // Verify accumulated totals
      const usage = store.getSessionUsage(sessionId);
      expect(usage.promptTokens).toBe(3000);
      expect(usage.completionTokens).toBe(1500);
      expect(usage.costUsd).toBeCloseTo(0.0585, 4);
    });

    it('should calculate cost via ModelRegistry matching logged costs', async () => {
      const sessionId = store.createSession('Cost Calculation Session');

      // Create a usage record for cost calculation
      const usageRecord: UsageRecord = {
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 1000,
        completionTokens: 500,
      };

      // Calculate cost via ModelRegistry
      const costBreakdown = modelRegistry.calculateCost(usageRecord);

      // Log the same usage to the store
      store.logUsage({
        sessionId,
        modelId: usageRecord.modelId,
        promptTokens: usageRecord.promptTokens,
        completionTokens: usageRecord.completionTokens,
        costUsd: costBreakdown.totalCost,
        timestamp: new Date().toISOString(),
      });

      // Verify costs match
      const sessionUsage = store.getSessionUsage(sessionId);
      expect(sessionUsage.costUsd).toBeCloseTo(costBreakdown.totalCost, 6);

      // Verify cost breakdown is reasonable
      // Claude 3.5 Sonnet: $3/M prompt, $15/M completion
      // 1000 prompt tokens = $0.003, 500 completion = $0.0075, total = $0.0105
      expect(costBreakdown.promptCost).toBeCloseTo(0.003, 6);
      expect(costBreakdown.completionCost).toBeCloseTo(0.0075, 6);
      expect(costBreakdown.totalCost).toBeCloseTo(0.0105, 6);
    });

    it('should include cost info in session metadata', async () => {
      const sessionId = store.createSession('Metadata Cost Session');

      // Log usage
      store.logUsage({
        sessionId,
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 5000,
        completionTokens: 2500,
        costUsd: 0.0525, // $0.015 + $0.0375
        timestamp: new Date().toISOString(),
      });

      // Get session metadata
      const metadata = store.getSessionMetadata(sessionId);
      expect(metadata).toBeDefined();
      expect(metadata!.promptTokens).toBe(5000);
      expect(metadata!.completionTokens).toBe(2500);
      expect(metadata!.costUsd).toBeCloseTo(0.0525, 4);
    });
  });

  // ===========================================================================
  // Parent-Child Session Hierarchy
  // ===========================================================================

  describe('Parent-Child Session Hierarchy', () => {
    it('should create child sessions linked to parent', async () => {
      // Create main session
      const mainSessionId = store.createSession('Main Session');
      expect(mainSessionId).toBeDefined();

      // Create child sessions
      const child1Id = store.createChildSession(mainSessionId, 'Child 1', 'subagent');
      const child2Id = store.createChildSession(mainSessionId, 'Child 2', 'branch');

      expect(child1Id).toBeDefined();
      expect(child2Id).toBeDefined();
      expect(child1Id).not.toBe(child2Id);

      // Verify child metadata
      const child1Meta = store.getSessionMetadata(child1Id);
      expect(child1Meta).toBeDefined();
      expect(child1Meta!.parentSessionId).toBe(mainSessionId);
      expect(child1Meta!.sessionType).toBe('subagent');
      expect(child1Meta!.name).toBe('Child 1');

      const child2Meta = store.getSessionMetadata(child2Id);
      expect(child2Meta).toBeDefined();
      expect(child2Meta!.parentSessionId).toBe(mainSessionId);
      expect(child2Meta!.sessionType).toBe('branch');
    });

    it('should return children via getChildSessions()', async () => {
      const mainSessionId = store.createSession('Parent Session');

      // Create multiple children
      const childIds = [
        store.createChildSession(mainSessionId, 'Task 1', 'subagent'),
        store.createChildSession(mainSessionId, 'Task 2', 'subagent'),
        store.createChildSession(mainSessionId, 'Task 3', 'subagent'),
      ];

      // Get children
      const children = store.getChildSessions(mainSessionId);
      expect(children).toHaveLength(3);

      // Verify all child IDs are present
      const returnedIds = children.map(c => c.id);
      for (const childId of childIds) {
        expect(returnedIds).toContain(childId);
      }

      // Verify children are sorted by creation time (ascending)
      for (let i = 1; i < children.length; i++) {
        expect(new Date(children[i].createdAt).getTime())
          .toBeGreaterThanOrEqual(new Date(children[i - 1].createdAt).getTime());
      }
    });

    it('should return empty array for session with no children', async () => {
      const sessionId = store.createSession('Leaf Session');
      const children = store.getChildSessions(sessionId);
      expect(children).toEqual([]);
    });

    it('should return full hierarchy via getSessionTree()', async () => {
      // Create a multi-level hierarchy
      //   main
      //   ├── child1
      //   │   ├── grandchild1
      //   │   └── grandchild2
      //   └── child2

      const mainId = store.createSession('Root');
      const child1Id = store.createChildSession(mainId, 'Child 1', 'subagent');
      const child2Id = store.createChildSession(mainId, 'Child 2', 'branch');
      const grandchild1Id = store.createChildSession(child1Id, 'Grandchild 1', 'subagent');
      const grandchild2Id = store.createChildSession(child1Id, 'Grandchild 2', 'subagent');

      // Get full tree from root
      const tree = store.getSessionTree(mainId);

      // Should include all 5 sessions
      expect(tree).toHaveLength(5);

      // Verify all session IDs are present
      const treeIds = tree.map(s => s.id);
      expect(treeIds).toContain(mainId);
      expect(treeIds).toContain(child1Id);
      expect(treeIds).toContain(child2Id);
      expect(treeIds).toContain(grandchild1Id);
      expect(treeIds).toContain(grandchild2Id);

      // Root should be first
      expect(tree[0].id).toBe(mainId);

      // Verify parent relationships
      const child1 = tree.find(s => s.id === child1Id);
      expect(child1!.parentSessionId).toBe(mainId);

      const grandchild1 = tree.find(s => s.id === grandchild1Id);
      expect(grandchild1!.parentSessionId).toBe(child1Id);
    });

    it('should return subtree when starting from non-root', async () => {
      // Create hierarchy
      const mainId = store.createSession('Root');
      const child1Id = store.createChildSession(mainId, 'Child 1', 'subagent');
      store.createChildSession(mainId, 'Child 2', 'branch');
      const grandchildId = store.createChildSession(child1Id, 'Grandchild', 'subagent');

      // Get tree from child1 (not root)
      const subtree = store.getSessionTree(child1Id);

      // Should only include child1 and its descendants
      expect(subtree).toHaveLength(2);

      const subtreeIds = subtree.map(s => s.id);
      expect(subtreeIds).toContain(child1Id);
      expect(subtreeIds).toContain(grandchildId);
      expect(subtreeIds).not.toContain(mainId);
    });
  });

  // ===========================================================================
  // Event Queue Flow with Submissions
  // ===========================================================================

  describe('Event Queue Flow with Submissions', () => {
    let submissionQueue: SubmissionQueue;
    let eventQueue: EventQueue;

    beforeEach(() => {
      submissionQueue = new SubmissionQueue({ maxSize: 10 });
      eventQueue = new EventQueue({ maxRecentEvents: 50 });
    });

    afterEach(() => {
      submissionQueue.close();
      eventQueue.clear();
    });

    it('should submit operation and receive via take()', async () => {
      const op: OpUserTurn = {
        type: 'user_turn',
        content: 'Hello, world!',
      };

      // Submit operation
      const submissionId = await submissionQueue.submit(op);
      expect(submissionId).toBeDefined();

      // Take submission
      const submission = await submissionQueue.take();
      expect(submission).not.toBeNull();
      expect(submission!.id).toBe(submissionId);
      expect(submission!.op).toEqual(op);
      expect(submission!.timestamp).toBeDefined();
    });

    it('should emit events and notify listeners', async () => {
      const receivedEnvelopes: EventEnvelope[] = [];

      // Subscribe to all events
      const unsubscribe = eventQueue.subscribe((envelope) => {
        receivedEnvelopes.push(envelope);
      });

      // Emit events
      const submissionId = 'test-submission-1';
      const messageEvent: EventAgentMessage = {
        type: 'agent_message',
        content: 'Hello from agent',
        done: false,
      };
      eventQueue.emit(submissionId, messageEvent);

      const completeEvent: EventTaskComplete = {
        type: 'task_complete',
        usage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
        status: 'success',
        durationMs: 1000,
      };
      eventQueue.emit(submissionId, completeEvent);

      // Wait for async dispatch
      await new Promise(resolve => setTimeout(resolve, 10));

      // Verify listeners received events
      expect(receivedEnvelopes).toHaveLength(2);
      expect(receivedEnvelopes[0].event.type).toBe('agent_message');
      expect(receivedEnvelopes[0].submissionId).toBe(submissionId);
      expect(receivedEnvelopes[1].event.type).toBe('task_complete');

      unsubscribe();
    });

    it('should allow typed event subscriptions', async () => {
      const messageEvents: EventEnvelope[] = [];
      const completeEvents: EventEnvelope[] = [];

      // Subscribe to specific event types
      const unsub1 = eventQueue.on<EventAgentMessage>('agent_message', (envelope) => {
        messageEvents.push(envelope);
      });
      const unsub2 = eventQueue.on<EventTaskComplete>('task_complete', (envelope) => {
        completeEvents.push(envelope);
      });

      // Emit mixed events
      eventQueue.emit('sub-1', { type: 'agent_message', content: 'First', done: false });
      eventQueue.emit('sub-1', { type: 'task_complete', usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 }, status: 'success', durationMs: 100 });
      eventQueue.emit('sub-1', { type: 'agent_message', content: 'Second', done: true });

      await new Promise(resolve => setTimeout(resolve, 10));

      // Verify typed listeners only got their events
      expect(messageEvents).toHaveLength(2);
      expect(completeEvents).toHaveLength(1);

      unsub1();
      unsub2();
    });

    it('should store recent events for replay', async () => {
      const submissionId = 'replay-test';

      // Emit several events
      for (let i = 0; i < 5; i++) {
        eventQueue.emit(submissionId, {
          type: 'agent_message',
          content: `Message ${i}`,
          done: i === 4,
        });
      }

      // Get recent events
      const recentEvents = eventQueue.getRecentEvents();
      expect(recentEvents).toHaveLength(5);

      // Verify events are in order
      for (let i = 0; i < 5; i++) {
        const event = recentEvents[i].event as EventAgentMessage;
        expect(event.content).toBe(`Message ${i}`);
      }
    });

    it('should filter events by submission ID', async () => {
      // Emit events for different submissions
      eventQueue.emit('sub-A', { type: 'agent_message', content: 'A1', done: false });
      eventQueue.emit('sub-B', { type: 'agent_message', content: 'B1', done: false });
      eventQueue.emit('sub-A', { type: 'agent_message', content: 'A2', done: true });
      eventQueue.emit('sub-B', { type: 'agent_message', content: 'B2', done: true });

      // Get events for specific submission
      const subAEvents = eventQueue.getEventsForSubmission('sub-A');
      expect(subAEvents).toHaveLength(2);
      expect((subAEvents[0].event as EventAgentMessage).content).toBe('A1');
      expect((subAEvents[1].event as EventAgentMessage).content).toBe('A2');

      const subBEvents = eventQueue.getEventsForSubmission('sub-B');
      expect(subBEvents).toHaveLength(2);
    });

    it('should integrate full submission-event flow', async () => {
      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => receivedEvents.push(envelope));

      // Submit a user turn
      const op: OpUserTurn = { type: 'user_turn', content: 'Calculate 2+2' };
      const submissionId = await submissionQueue.submit(op);

      // Take and process the submission
      const submission = await submissionQueue.take();
      expect(submission).not.toBeNull();

      // Simulate agent response - emit events for this submission
      eventQueue.emit(submission!.id, {
        type: 'agent_message',
        content: 'The answer is 4',
        done: true,
      });

      eventQueue.emit(submission!.id, {
        type: 'task_complete',
        usage: { inputTokens: 50, outputTokens: 10, totalTokens: 60 },
        status: 'success',
        durationMs: 500,
      });

      await new Promise(resolve => setTimeout(resolve, 10));

      // Verify flow
      expect(receivedEvents).toHaveLength(2);
      expect(receivedEvents[0].submissionId).toBe(submissionId);
      expect(receivedEvents[1].submissionId).toBe(submissionId);

      // Verify events can be retrieved for this submission
      const submissionEvents = eventQueue.getEventsForSubmission(submissionId);
      expect(submissionEvents).toHaveLength(2);
    });
  });

  // ===========================================================================
  // Migration on Fresh Database
  // ===========================================================================

  describe('Migration on Fresh Database', () => {
    it('should apply all migrations on fresh database', async () => {
      // The store was already initialized with migrations in beforeEach
      // Verify by checking schema version
      const dbPath = join(tempDir, 'test.db');
      const db = new Database(dbPath);

      try {
        const version = getSchemaVersion(db);
        expect(version).toBeGreaterThanOrEqual(3); // We have 3 migrations
      } finally {
        db.close();
      }
    });

    it('should have all required tables after migration', async () => {
      const dbPath = join(tempDir, 'test.db');
      const db = new Database(dbPath);

      try {
        // Query sqlite_master for tables
        const tables = db.prepare(`
          SELECT name FROM sqlite_master
          WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
          ORDER BY name
        `).all() as Array<{ name: string }>;

        const tableNames = tables.map(t => t.name);

        // Verify all expected tables exist
        expect(tableNames).toContain('sessions');
        expect(tableNames).toContain('entries');
        expect(tableNames).toContain('tool_calls');
        expect(tableNames).toContain('checkpoints');
        expect(tableNames).toContain('usage_logs');
      } finally {
        db.close();
      }
    });

    it('should have cost tracking columns in sessions table', async () => {
      const dbPath = join(tempDir, 'test.db');
      const db = new Database(dbPath);

      try {
        // Get column info for sessions table
        const columns = db.prepare('PRAGMA table_info(sessions)').all() as Array<{
          name: string;
          type: string;
        }>;

        const columnNames = columns.map(c => c.name);

        // Verify cost tracking columns from migration 002
        expect(columnNames).toContain('prompt_tokens');
        expect(columnNames).toContain('completion_tokens');
        expect(columnNames).toContain('cost_usd');
      } finally {
        db.close();
      }
    });

    it('should have hierarchy columns in sessions table', async () => {
      const dbPath = join(tempDir, 'test.db');
      const db = new Database(dbPath);

      try {
        // Get column info for sessions table
        const columns = db.prepare('PRAGMA table_info(sessions)').all() as Array<{
          name: string;
          type: string;
        }>;

        const columnNames = columns.map(c => c.name);

        // Verify hierarchy columns from migration 003
        expect(columnNames).toContain('parent_session_id');
        expect(columnNames).toContain('session_type');
      } finally {
        db.close();
      }
    });

    it('should have all required indexes', async () => {
      const dbPath = join(tempDir, 'test.db');
      const db = new Database(dbPath);

      try {
        // Get all indexes
        const indexes = db.prepare(`
          SELECT name FROM sqlite_master
          WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
        `).all() as Array<{ name: string }>;

        const indexNames = indexes.map(i => i.name);

        // Verify key indexes exist
        expect(indexNames).toContain('idx_entries_session');
        expect(indexNames).toContain('idx_tool_calls_session');
        expect(indexNames).toContain('idx_usage_logs_session');
        expect(indexNames).toContain('idx_sessions_parent');
      } finally {
        db.close();
      }
    });

    it('should create fresh database with migrations in new temp location', async () => {
      // Create a completely new store in a different location
      const newTempDir = await mkdtemp(join(tmpdir(), 'attocode-fresh-'));

      try {
        const freshStore = await createSQLiteStore({
          dbPath: join(newTempDir, 'fresh.db'),
        });

        try {
          // Should be able to use all features
          const sessionId = freshStore.createSession('Fresh Session');
          expect(sessionId).toBeDefined();

          // Can create child sessions
          const childId = freshStore.createChildSession(sessionId, 'Child', 'subagent');
          expect(childId).toBeDefined();

          // Can log usage
          freshStore.logUsage({
            sessionId,
            modelId: 'test-model',
            promptTokens: 100,
            completionTokens: 50,
            costUsd: 0.01,
            timestamp: new Date().toISOString(),
          });

          const usage = freshStore.getSessionUsage(sessionId);
          expect(usage.promptTokens).toBe(100);
        } finally {
          freshStore.close();
        }
      } finally {
        await rm(newTempDir, { recursive: true, force: true });
      }
    });

    it('should load migration files from persistence directory', async () => {
      // This test verifies migration files exist and are parseable
      const { dirname } = await import('node:path');
      const { fileURLToPath } = await import('node:url');

      const __dirname = dirname(fileURLToPath(import.meta.url));
      const migrationsDir = join(__dirname, '../../src/persistence/migrations');

      const migrations = loadMigrations(migrationsDir);

      expect(migrations.length).toBeGreaterThanOrEqual(3);

      // Verify migrations are sorted by version
      for (let i = 1; i < migrations.length; i++) {
        expect(migrations[i].version).toBeGreaterThan(migrations[i - 1].version);
      }

      // Verify expected migrations exist
      const versions = migrations.map(m => m.version);
      expect(versions).toContain(1);
      expect(versions).toContain(2);
      expect(versions).toContain(3);
    });
  });

  // ===========================================================================
  // Cross-Module Integration
  // ===========================================================================

  describe('Cross-Module Integration', () => {
    it('should track costs across parent and child sessions', async () => {
      // Create parent session
      const parentId = store.createSession('Parent');

      // Create child sessions and log usage to each
      const childIds = [
        store.createChildSession(parentId, 'Worker 1', 'subagent'),
        store.createChildSession(parentId, 'Worker 2', 'subagent'),
      ];

      // Log usage to parent
      store.logUsage({
        sessionId: parentId,
        modelId: 'claude-3-5-sonnet-20241022',
        promptTokens: 1000,
        completionTokens: 500,
        costUsd: 0.0105,
        timestamp: new Date().toISOString(),
      });

      // Log usage to children
      store.logUsage({
        sessionId: childIds[0],
        modelId: 'claude-3-5-haiku-20241022',
        promptTokens: 2000,
        completionTokens: 1000,
        costUsd: 0.0056,
        timestamp: new Date().toISOString(),
      });

      store.logUsage({
        sessionId: childIds[1],
        modelId: 'claude-3-5-haiku-20241022',
        promptTokens: 3000,
        completionTokens: 1500,
        costUsd: 0.0084,
        timestamp: new Date().toISOString(),
      });

      // Get session tree and verify costs
      const tree = store.getSessionTree(parentId);
      expect(tree).toHaveLength(3);

      // Calculate total tree cost
      let totalCost = 0;
      for (const session of tree) {
        const usage = store.getSessionUsage(session.id);
        totalCost += usage.costUsd;
      }

      expect(totalCost).toBeCloseTo(0.0105 + 0.0056 + 0.0084, 4);
    });

    it('should persist session entries and retrieve them', async () => {
      const sessionId = store.createSession('Entry Test');

      // Append various entries
      store.appendMessage({ role: 'user', content: 'Hello' });
      store.appendMessage({ role: 'assistant', content: 'Hi there!' });
      store.appendToolCall({
        id: 'tool-1',
        name: 'read_file',
        arguments: { path: '/test.txt' },
      });
      store.appendToolResult('tool-1', 'file contents here');

      // Load session and verify entries
      const entries = store.loadSession(sessionId);
      expect(entries.length).toBeGreaterThanOrEqual(4);

      // Find message entries
      const messageEntries = entries.filter(e => e.type === 'message');
      expect(messageEntries).toHaveLength(2);

      // Verify tool call entry
      const toolCallEntry = entries.find(e => e.type === 'tool_call');
      expect(toolCallEntry).toBeDefined();
      expect((toolCallEntry!.data as { name: string }).name).toBe('read_file');

      // Verify tool result entry
      const toolResultEntry = entries.find(e => e.type === 'tool_result');
      expect(toolResultEntry).toBeDefined();
      expect((toolResultEntry!.data as { callId: string }).callId).toBe('tool-1');
    });

    it('should handle checkpoints with session hierarchy', async () => {
      const parentId = store.createSession('Checkpoint Parent');
      store.setCurrentSessionId(parentId);

      // Save checkpoint on parent
      const checkpoint1Id = store.saveCheckpoint(
        { step: 1, data: 'parent state' },
        'Initial state'
      );
      expect(checkpoint1Id).toBeDefined();

      // Create child and save checkpoint there
      const childId = store.createChildSession(parentId, 'Child', 'subagent');
      store.setCurrentSessionId(childId);

      const checkpoint2Id = store.saveCheckpoint(
        { step: 1, data: 'child state' },
        'Child initial'
      );
      expect(checkpoint2Id).toBeDefined();

      // Load checkpoints independently
      const parentCheckpoint = store.loadLatestCheckpoint(parentId);
      expect(parentCheckpoint).toBeDefined();
      expect(parentCheckpoint!.state.data).toBe('parent state');

      const childCheckpoint = store.loadLatestCheckpoint(childId);
      expect(childCheckpoint).toBeDefined();
      expect(childCheckpoint!.state.data).toBe('child state');
    });

    it('should calculate costs for different models correctly', async () => {
      const sessionId = store.createSession('Multi-Model Session');

      // Usage records for different models
      const usageRecords: UsageRecord[] = [
        { modelId: 'claude-3-5-sonnet-20241022', promptTokens: 1000, completionTokens: 500 },
        { modelId: 'claude-3-5-haiku-20241022', promptTokens: 2000, completionTokens: 1000 },
        { modelId: 'gpt-4o', promptTokens: 1000, completionTokens: 500 },
      ];

      let expectedTotalCost = 0;

      for (const usage of usageRecords) {
        const cost = modelRegistry.calculateCost(usage);
        expectedTotalCost += cost.totalCost;

        store.logUsage({
          sessionId,
          modelId: usage.modelId,
          promptTokens: usage.promptTokens,
          completionTokens: usage.completionTokens,
          costUsd: cost.totalCost,
          timestamp: new Date().toISOString(),
        });
      }

      // Verify session total matches sum of individual costs
      const sessionUsage = store.getSessionUsage(sessionId);
      expect(sessionUsage.costUsd).toBeCloseTo(expectedTotalCost, 6);
    });
  });
});
