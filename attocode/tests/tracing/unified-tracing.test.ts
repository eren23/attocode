/**
 * Unified Tracing Tests
 *
 * Tests for the unified session tracing with subagent hierarchy feature.
 * Verifies that:
 * 1. Subagent views are created with correct context
 * 2. Events are tagged with subagent context
 * 3. Aggregation calculates correct totals
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, rm, readFile } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  TraceCollector,
  createTraceCollector,
} from '../../src/tracing/trace-collector.js';

// =============================================================================
// TEST SETUP
// =============================================================================

describe('Unified Tracing', () => {
  let tempDir: string;
  let collector: TraceCollector;

  beforeEach(async () => {
    // Create temp directory for trace files
    tempDir = join(tmpdir(), `trace-test-${Date.now()}`);
    await mkdir(tempDir, { recursive: true });

    // Create trace collector with temp output dir
    collector = createTraceCollector({
      enabled: true,
      outputDir: tempDir,
      captureMessageContent: true,
      captureToolResults: true,
    });
  });

  afterEach(async () => {
    // Clean up temp directory
    try {
      await rm(tempDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  // ===========================================================================
  // SUBAGENT VIEW CREATION
  // ===========================================================================

  describe('Subagent View Creation', () => {
    it('should create a subagent view with correct context', async () => {
      // Start a session first
      await collector.startSession('parent-session-123', 'Test task', 'claude-3-sonnet', {});

      // Create a subagent view
      const subagentView = collector.createSubagentView({
        parentSessionId: 'parent-session-123',
        agentType: 'researcher',
        spawnedAtIteration: 3,
      });

      // Verify the view has correct context
      expect(subagentView.isSubagentView()).toBe(true);
      expect(subagentView.getSubagentContext()).toEqual({
        parentSessionId: 'parent-session-123',
        agentType: 'researcher',
        spawnedAtIteration: 3,
        subagentId: 'researcher-3',
      });

      // Verify it shares the same session ID and output path
      expect(subagentView.getSessionId()).toBe('parent-session-123');
      expect(subagentView.getOutputPath()).toBe(collector.getOutputPath());

      await collector.endSession({ success: true });
    });

    it('should generate unique subagent IDs based on type and iteration', async () => {
      await collector.startSession('parent-session-456', 'Test task', 'claude-3-sonnet', {});

      const view1 = collector.createSubagentView({
        parentSessionId: 'parent-session-456',
        agentType: 'researcher',
        spawnedAtIteration: 1,
      });

      const view2 = collector.createSubagentView({
        parentSessionId: 'parent-session-456',
        agentType: 'researcher',
        spawnedAtIteration: 5,
      });

      const view3 = collector.createSubagentView({
        parentSessionId: 'parent-session-456',
        agentType: 'coder',
        spawnedAtIteration: 5,
      });

      expect(view1.getSubagentContext()?.subagentId).toBe('researcher-1');
      expect(view2.getSubagentContext()?.subagentId).toBe('researcher-5');
      expect(view3.getSubagentContext()?.subagentId).toBe('coder-5');

      await collector.endSession({ success: true });
    });
  });

  // ===========================================================================
  // EVENT TAGGING
  // ===========================================================================

  describe('Event Tagging', () => {
    it('should tag subagent events with subagent context in JSONL', async () => {
      await collector.startSession('test-session', 'Test task', 'claude-3-sonnet', {});

      // Create a subagent view
      const subagentView = collector.createSubagentView({
        parentSessionId: 'test-session',
        agentType: 'researcher',
        spawnedAtIteration: 2,
      });

      // Record an event from the subagent
      await subagentView.record({
        type: 'llm.request',
        data: {
          requestId: 'req-sub-1',
          model: 'claude-3-sonnet',
          provider: 'anthropic',
          messages: [{ role: 'user', content: 'test' }],
          parameters: {},
        },
      });

      // Flush and read the trace file
      await subagentView.flush();
      await collector.flush();

      const outputPath = collector.getOutputPath();
      expect(outputPath).not.toBeNull();

      const content = await readFile(outputPath!, 'utf-8');
      const lines = content.trim().split('\n');

      // Find the LLM request entry from subagent
      const subagentEntry = lines
        .map(line => JSON.parse(line))
        .find(entry => entry._type === 'llm.request' && entry.requestId === 'req-sub-1');

      expect(subagentEntry).toBeDefined();
      expect(subagentEntry.subagentId).toBe('researcher-2');
      expect(subagentEntry.subagentType).toBe('researcher');
      expect(subagentEntry.parentSessionId).toBe('test-session');
      expect(subagentEntry.spawnedAtIteration).toBe(2);

      await collector.endSession({ success: true });
    });

    it('should NOT tag main agent events with subagent context', async () => {
      await collector.startSession('test-session-main', 'Test task', 'claude-3-sonnet', {});

      // Record an event from the main agent
      await collector.record({
        type: 'llm.request',
        data: {
          requestId: 'req-main-1',
          model: 'claude-3-sonnet',
          provider: 'anthropic',
          messages: [{ role: 'user', content: 'test' }],
          parameters: {},
        },
      });

      await collector.flush();

      const outputPath = collector.getOutputPath();
      const content = await readFile(outputPath!, 'utf-8');
      const lines = content.trim().split('\n');

      // Find the LLM request entry from main agent
      const mainEntry = lines
        .map(line => JSON.parse(line))
        .find(entry => entry._type === 'llm.request' && entry.requestId === 'req-main-1');

      expect(mainEntry).toBeDefined();
      expect(mainEntry.subagentId).toBeUndefined();
      expect(mainEntry.subagentType).toBeUndefined();
      expect(mainEntry.parentSessionId).toBeUndefined();
      expect(mainEntry.spawnedAtIteration).toBeUndefined();

      await collector.endSession({ success: true });
    });
  });

  // ===========================================================================
  // HIERARCHY AGGREGATION
  // ===========================================================================

  describe('Hierarchy Aggregation', () => {
    it('should aggregate metrics across main agent and subagents', async () => {
      await collector.startSession('agg-test-session', 'Aggregation test', 'claude-3-sonnet', {});

      // Record some main agent activity
      await collector.record({
        type: 'llm.request',
        data: {
          requestId: 'main-req-1',
          model: 'claude-3-sonnet',
          provider: 'anthropic',
          messages: [{ role: 'user', content: 'test' }],
          parameters: {},
        },
      });
      await collector.record({
        type: 'llm.response',
        data: {
          requestId: 'main-req-1',
          content: 'response',
          stopReason: 'end_turn' as const,
          usage: { inputTokens: 100, outputTokens: 50 },
          durationMs: 1000,
        },
      });
      await collector.record({
        type: 'tool.start',
        data: {
          executionId: 'main-tool-1',
          toolName: 'read_file',
          arguments: { path: '/test' },
        },
      });
      await collector.record({
        type: 'tool.end',
        data: {
          executionId: 'main-tool-1',
          status: 'success' as const,
          result: 'file content',
          durationMs: 100,
        },
      });

      // Create a subagent view and record activity
      const subagentView = collector.createSubagentView({
        parentSessionId: 'agg-test-session',
        agentType: 'researcher',
        spawnedAtIteration: 1,
      });

      await subagentView.record({
        type: 'llm.request',
        data: {
          requestId: 'sub-req-1',
          model: 'claude-3-sonnet',
          provider: 'anthropic',
          messages: [{ role: 'user', content: 'sub test' }],
          parameters: {},
        },
      });
      await subagentView.record({
        type: 'llm.response',
        data: {
          requestId: 'sub-req-1',
          content: 'sub response',
          stopReason: 'end_turn' as const,
          usage: { inputTokens: 200, outputTokens: 100 },
          durationMs: 2000,
        },
      });
      await subagentView.record({
        type: 'tool.start',
        data: {
          executionId: 'sub-tool-1',
          toolName: 'glob',
          arguments: { pattern: '*.ts' },
        },
      });
      await subagentView.record({
        type: 'tool.end',
        data: {
          executionId: 'sub-tool-1',
          status: 'success' as const,
          result: ['a.ts', 'b.ts'],
          durationMs: 50,
        },
      });
      await subagentView.record({
        type: 'tool.start',
        data: {
          executionId: 'sub-tool-2',
          toolName: 'read_file',
          arguments: { path: '/other' },
        },
      });
      await subagentView.record({
        type: 'tool.end',
        data: {
          executionId: 'sub-tool-2',
          status: 'success' as const,
          result: 'other content',
          durationMs: 75,
        },
      });

      await collector.flush();
      await subagentView.flush();

      // Get the hierarchy
      const hierarchy = await collector.getSubagentHierarchy();

      expect(hierarchy).not.toBeNull();
      expect(hierarchy!.sessionId).toBe('agg-test-session');

      // Main agent metrics
      expect(hierarchy!.mainAgent.inputTokens).toBe(100);
      expect(hierarchy!.mainAgent.outputTokens).toBe(50);
      expect(hierarchy!.mainAgent.toolCalls).toBe(1);
      expect(hierarchy!.mainAgent.llmCalls).toBe(1);

      // Subagent metrics
      expect(hierarchy!.subagents).toHaveLength(1);
      const sub = hierarchy!.subagents[0];
      expect(sub.agentId).toBe('researcher-1');
      expect(sub.agentType).toBe('researcher');
      expect(sub.inputTokens).toBe(200);
      expect(sub.outputTokens).toBe(100);
      expect(sub.toolCalls).toBe(2);
      expect(sub.llmCalls).toBe(1);
      expect(sub.spawnedAtIteration).toBe(1);

      // Total metrics
      expect(hierarchy!.totals.inputTokens).toBe(300); // 100 + 200
      expect(hierarchy!.totals.outputTokens).toBe(150); // 50 + 100
      expect(hierarchy!.totals.toolCalls).toBe(3); // 1 + 2
      expect(hierarchy!.totals.llmCalls).toBe(2); // 1 + 1

      await collector.endSession({ success: true });
    });

    it('should handle multiple subagents in hierarchy', async () => {
      await collector.startSession('multi-sub-session', 'Multiple subagents', 'claude-3-sonnet', {});

      // Create multiple subagent views
      const researcher = collector.createSubagentView({
        parentSessionId: 'multi-sub-session',
        agentType: 'researcher',
        spawnedAtIteration: 1,
      });

      const coder = collector.createSubagentView({
        parentSessionId: 'multi-sub-session',
        agentType: 'coder',
        spawnedAtIteration: 3,
      });

      const reviewer = collector.createSubagentView({
        parentSessionId: 'multi-sub-session',
        agentType: 'reviewer',
        spawnedAtIteration: 5,
      });

      // Record tool activity for each (simpler than LLM request/response pairs)
      let toolIndex = 0;
      for (const [view, name] of [[researcher, 'researcher'], [coder, 'coder'], [reviewer, 'reviewer']] as const) {
        const execId = `${name}-tool-${++toolIndex}`;
        await view.record({
          type: 'tool.start',
          data: {
            executionId: execId,
            toolName: 'read_file',
            arguments: { path: `/${name}/file.ts` },
          },
        });
        await view.record({
          type: 'tool.end',
          data: {
            executionId: execId,
            status: 'success' as const,
            result: 'file content',
            durationMs: 100,
          },
        });
      }

      await researcher.flush();
      await coder.flush();
      await reviewer.flush();
      await collector.flush();

      const hierarchy = await collector.getSubagentHierarchy();

      expect(hierarchy).not.toBeNull();
      expect(hierarchy!.subagents).toHaveLength(3);

      const types = hierarchy!.subagents.map(s => s.agentType);
      expect(types).toContain('researcher');
      expect(types).toContain('coder');
      expect(types).toContain('reviewer');

      // Total tool calls should aggregate all subagents
      expect(hierarchy!.totals.toolCalls).toBe(3);

      await collector.endSession({ success: true });
    });

    it('should return null hierarchy when no trace file exists', async () => {
      // Create collector without starting session (no output file)
      const emptyCollector = createTraceCollector({
        enabled: true,
        outputDir: tempDir,
      });

      const hierarchy = await emptyCollector.getSubagentHierarchy();
      expect(hierarchy).toBeNull();
    });
  });

  // ===========================================================================
  // EDGE CASES
  // ===========================================================================

  describe('Edge Cases', () => {
    it('should handle subagent without parent trace collector', () => {
      // Creating a subagent view without active session should still work
      // (the view will be created but won't write anywhere useful)
      const orphanView = collector.createSubagentView({
        parentSessionId: 'orphan-parent',
        agentType: 'orphan',
        spawnedAtIteration: 1,
      });

      expect(orphanView.isSubagentView()).toBe(true);
      expect(orphanView.getSessionId()).toBeNull(); // No session started
    });

    it('should handle empty trace file gracefully', async () => {
      // Start session but don't record any events
      await collector.startSession('empty-session', 'Empty', 'claude-3-sonnet', {});
      await collector.flush();

      const hierarchy = await collector.getSubagentHierarchy();

      // Should still return a valid hierarchy with zeros
      expect(hierarchy).not.toBeNull();
      expect(hierarchy!.mainAgent.inputTokens).toBe(0);
      expect(hierarchy!.subagents).toHaveLength(0);
      expect(hierarchy!.totals.inputTokens).toBe(0);

      await collector.endSession({ success: true });
    });
  });
});
