/**
 * Protocol Bridge Tests
 *
 * Comprehensive tests for the ProtocolBridge:
 * - Start/stop lifecycle
 * - Operation handling and dispatch
 * - Event emission with correlation
 * - Error handling
 * - Graceful shutdown
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ProtocolBridge, createProtocolBridge } from '../../../src/core/protocol/bridge.js';
import { SubmissionQueue } from '../../../src/core/queues/submission-queue.js';
import { EventQueue } from '../../../src/core/queues/event-queue.js';
import type { Operation, Submission, AgentEvent, EventEnvelope } from '../../../src/core/protocol/types.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

/**
 * Creates a test operation.
 */
function createTestOperation(content = 'test message'): Operation {
  return {
    type: 'user_turn',
    content,
  };
}

/**
 * Creates a test event.
 */
function createTestEvent(content = 'agent response', done = true): AgentEvent {
  return {
    type: 'agent_message',
    content,
    done,
  };
}

/**
 * Waits for a condition to be true.
 */
async function waitFor(
  condition: () => boolean,
  timeout = 1000,
  interval = 10
): Promise<void> {
  const start = Date.now();
  while (!condition()) {
    if (Date.now() - start > timeout) {
      throw new Error('Timeout waiting for condition');
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

// =============================================================================
// PROTOCOL BRIDGE TESTS
// =============================================================================

describe('ProtocolBridge', () => {
  let bridge: ProtocolBridge;
  let submissionQueue: SubmissionQueue;
  let eventQueue: EventQueue;

  beforeEach(() => {
    bridge = new ProtocolBridge();
    submissionQueue = new SubmissionQueue({ maxSize: 64, timeout: 1000 });
    eventQueue = new EventQueue({ maxRecentEvents: 100 });
  });

  afterEach(async () => {
    // Clean up - stop bridge and close queue
    if (bridge.isRunning()) {
      bridge.stop();
    }
    submissionQueue.close();
    // Wait a bit for async cleanup
    await new Promise((resolve) => setTimeout(resolve, 10));
  });

  // ===========================================================================
  // LIFECYCLE TESTS
  // ===========================================================================

  describe('lifecycle', () => {
    it('starts in not-running state', () => {
      expect(bridge.isRunning()).toBe(false);
    });

    it('start() sets running state', () => {
      bridge.start(submissionQueue, eventQueue);
      expect(bridge.isRunning()).toBe(true);
    });

    it('stop() clears running state', () => {
      bridge.start(submissionQueue, eventQueue);
      bridge.stop();
      expect(bridge.isRunning()).toBe(false);
    });

    it('throws when starting already running bridge', () => {
      bridge.start(submissionQueue, eventQueue);
      expect(() => bridge.start(submissionQueue, eventQueue)).toThrow(
        'ProtocolBridge is already running'
      );
    });

    it('can be restarted after stopping', async () => {
      bridge.start(submissionQueue, eventQueue);
      bridge.stop();
      // Close queue to unblock the consume loop
      submissionQueue.close();
      await bridge.waitForStop();

      // Create new queues for restart
      const newSubmissionQueue = new SubmissionQueue({ maxSize: 64, timeout: 1000 });
      const newEventQueue = new EventQueue();

      expect(() => bridge.start(newSubmissionQueue, newEventQueue)).not.toThrow();
      expect(bridge.isRunning()).toBe(true);

      bridge.stop();
      newSubmissionQueue.close();
    });

    it('stops when queue is closed', async () => {
      bridge.start(submissionQueue, eventQueue);
      submissionQueue.close();
      await bridge.waitForStop();
      expect(bridge.isRunning()).toBe(false);
    });
  });

  // ===========================================================================
  // OPERATION HANDLING TESTS
  // ===========================================================================

  describe('operation handling', () => {
    it('calls registered handler for each submission', async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      // Submit an operation
      await submissionQueue.submit(createTestOperation('message 1'));

      // Wait for handler to be called
      await waitFor(() => handler.mock.calls.length >= 1);

      expect(handler).toHaveBeenCalledTimes(1);
      expect(handler.mock.calls[0][0]).toMatchObject({
        op: { type: 'user_turn', content: 'message 1' },
      });
    });

    it('handles multiple operations in order', async () => {
      const receivedOperations: Submission[] = [];
      const handler = vi.fn().mockImplementation(async (sub: Submission) => {
        receivedOperations.push(sub);
      });

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      // Submit multiple operations
      await submissionQueue.submit(createTestOperation('first'));
      await submissionQueue.submit(createTestOperation('second'));
      await submissionQueue.submit(createTestOperation('third'));

      // Wait for all handlers to be called
      await waitFor(() => handler.mock.calls.length >= 3);

      expect(handler).toHaveBeenCalledTimes(3);
      expect(receivedOperations[0].op).toMatchObject({ content: 'first' });
      expect(receivedOperations[1].op).toMatchObject({ content: 'second' });
      expect(receivedOperations[2].op).toMatchObject({ content: 'third' });
    });

    it('ignores operations when no handler is registered', async () => {
      bridge.start(submissionQueue, eventQueue);

      // Submit an operation without registering a handler
      await submissionQueue.submit(createTestOperation());

      // Give it time to process
      await new Promise((resolve) => setTimeout(resolve, 50));

      // Bridge should still be running (no crash)
      expect(bridge.isRunning()).toBe(true);
    });

    it('replaces previous handler when registering new one', async () => {
      const handler1 = vi.fn().mockResolvedValue(undefined);
      const handler2 = vi.fn().mockResolvedValue(undefined);

      bridge.onOperation(handler1);
      bridge.onOperation(handler2); // Should replace handler1
      bridge.start(submissionQueue, eventQueue);

      await submissionQueue.submit(createTestOperation());
      await waitFor(() => handler2.mock.calls.length >= 1);

      expect(handler1).not.toHaveBeenCalled();
      expect(handler2).toHaveBeenCalledTimes(1);
    });

    it('provides submission with id, timestamp, and correlationId', async () => {
      let receivedSubmission: Submission | null = null;
      const handler = vi.fn().mockImplementation(async (sub: Submission) => {
        receivedSubmission = sub;
      });

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      await submissionQueue.submit(createTestOperation(), 'my-correlation-id');
      await waitFor(() => receivedSubmission !== null);

      expect(receivedSubmission).not.toBeNull();
      expect(receivedSubmission!.id).toBeDefined();
      expect(receivedSubmission!.id).toMatch(/^sub-/);
      expect(receivedSubmission!.timestamp).toBeDefined();
      expect(typeof receivedSubmission!.timestamp).toBe('number');
      expect(receivedSubmission!.correlationId).toBe('my-correlation-id');
    });
  });

  // ===========================================================================
  // EVENT EMISSION TESTS
  // ===========================================================================

  describe('event emission', () => {
    it('throws when emitting without starting', () => {
      expect(() => bridge.emit('sub-0', createTestEvent())).toThrow(
        'ProtocolBridge not started - cannot emit events'
      );
    });

    it('emits events to the event queue', async () => {
      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      bridge.emit('sub-123', createTestEvent('hello'));

      // Wait for async dispatch
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(receivedEvents.length).toBe(1);
      expect(receivedEvents[0].submissionId).toBe('sub-123');
      expect(receivedEvents[0].event).toMatchObject({
        type: 'agent_message',
        content: 'hello',
        done: true,
      });
    });

    it('correlates events with submission ID', async () => {
      let capturedSubmissionId: string | null = null;

      bridge.onOperation(async (sub) => {
        capturedSubmissionId = sub.id;
        // Emit an event correlated with this submission
        bridge.emit(sub.id, createTestEvent('response'));
      });

      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      await submissionQueue.submit(createTestOperation());
      await waitFor(() => receivedEvents.length >= 1);

      expect(receivedEvents[0].submissionId).toBe(capturedSubmissionId);
    });

    it('emits multiple events for one submission', async () => {
      bridge.onOperation(async (sub) => {
        // Emit streaming events
        bridge.emit(sub.id, createTestEvent('part 1', false));
        bridge.emit(sub.id, createTestEvent('part 2', false));
        bridge.emit(sub.id, createTestEvent('done', true));
      });

      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      const subId = await submissionQueue.submit(createTestOperation());
      await waitFor(() => receivedEvents.length >= 3);

      expect(receivedEvents.length).toBe(3);
      expect(receivedEvents.every((e) => e.submissionId === subId)).toBe(true);
    });
  });

  // ===========================================================================
  // ERROR HANDLING TESTS
  // ===========================================================================

  describe('error handling', () => {
    it('continues processing after handler error', async () => {
      let callCount = 0;
      const handler = vi.fn().mockImplementation(async () => {
        callCount++;
        if (callCount === 1) {
          throw new Error('Handler error');
        }
      });

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      // Submit two operations - first will fail, second should still be processed
      await submissionQueue.submit(createTestOperation('first'));
      await submissionQueue.submit(createTestOperation('second'));

      await waitFor(() => handler.mock.calls.length >= 2);

      expect(handler).toHaveBeenCalledTimes(2);
      expect(bridge.isRunning()).toBe(true);
    });

    it('emits error event when handler throws', async () => {
      const handler = vi.fn().mockRejectedValue(new Error('Handler exploded'));

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      const subId = await submissionQueue.submit(createTestOperation());
      await waitFor(() => receivedEvents.length >= 1);

      expect(receivedEvents.length).toBe(1);
      expect(receivedEvents[0].submissionId).toBe(subId);
      expect(receivedEvents[0].event.type).toBe('error');
      expect((receivedEvents[0].event as any).code).toBe('OPERATION_HANDLER_ERROR');
      expect((receivedEvents[0].event as any).message).toContain('Handler exploded');
      expect((receivedEvents[0].event as any).recoverable).toBe(true);
    });

    it('includes stack trace in error event', async () => {
      const testError = new Error('Test error with stack');
      const handler = vi.fn().mockRejectedValue(testError);

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      await submissionQueue.submit(createTestOperation());
      await waitFor(() => receivedEvents.length >= 1);

      const errorEvent = receivedEvents[0].event as any;
      expect(errorEvent.stack).toBeDefined();
      expect(errorEvent.stack).toContain('Test error with stack');
    });

    it('handles non-Error throws gracefully', async () => {
      const handler = vi.fn().mockRejectedValue('string error');

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      const receivedEvents: EventEnvelope[] = [];
      eventQueue.subscribe((envelope) => {
        receivedEvents.push(envelope);
      });

      await submissionQueue.submit(createTestOperation());
      await waitFor(() => receivedEvents.length >= 1);

      const errorEvent = receivedEvents[0].event as any;
      expect(errorEvent.message).toContain('string error');
      expect(errorEvent.stack).toBeUndefined();
    });
  });

  // ===========================================================================
  // GRACEFUL SHUTDOWN TESTS
  // ===========================================================================

  describe('graceful shutdown', () => {
    it('completes current operation before stopping', async () => {
      let operationCompleted = false;

      bridge.onOperation(async () => {
        // Simulate long-running operation
        await new Promise((resolve) => setTimeout(resolve, 50));
        operationCompleted = true;
      });

      bridge.start(submissionQueue, eventQueue);
      await submissionQueue.submit(createTestOperation());

      // Give the handler time to start
      await new Promise((resolve) => setTimeout(resolve, 10));

      // Stop while operation is in progress
      bridge.stop();

      // Operation should complete
      await waitFor(() => operationCompleted, 200);
      expect(operationCompleted).toBe(true);
    });

    it('waitForStop() resolves when bridge stops', async () => {
      bridge.start(submissionQueue, eventQueue);

      const stopPromise = bridge.waitForStop();

      submissionQueue.close();

      await expect(stopPromise).resolves.toBeUndefined();
    });

    it('does not process new operations after stop', async () => {
      const handler = vi.fn().mockResolvedValue(undefined);

      bridge.onOperation(handler);
      bridge.start(submissionQueue, eventQueue);

      bridge.stop();
      // Close queue to unblock the consume loop that's waiting on take()
      submissionQueue.close();
      await bridge.waitForStop();

      // Create a new queue and try to submit - bridge won't consume from it
      const newQueue = new SubmissionQueue({ maxSize: 64 });
      await newQueue.submit(createTestOperation());

      // Give it time to potentially be processed (should not be)
      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(handler).not.toHaveBeenCalled();
      newQueue.close();
    });
  });

  // ===========================================================================
  // FACTORY FUNCTION TESTS
  // ===========================================================================

  describe('createProtocolBridge', () => {
    it('creates a new ProtocolBridge instance', () => {
      const bridge = createProtocolBridge();
      expect(bridge).toBeInstanceOf(ProtocolBridge);
      expect(bridge.isRunning()).toBe(false);
    });
  });
});
