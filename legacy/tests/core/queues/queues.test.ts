/**
 * Queue System Tests
 *
 * Comprehensive tests for the queue infrastructure:
 * - AtomicCounter: Unique ID generation
 * - SubmissionQueue: Bounded async queue with backpressure
 * - EventQueue: Pub/sub event emitter
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  AtomicCounter,
  globalCounter,
  SubmissionQueue,
  QueueTimeoutError,
  QueueClosedError,
  EventQueue,
  EventTimeoutError,
} from '../../../src/core/queues/index.js';
import type { Operation, AgentEvent, EventAgentMessage } from '../../../src/core/protocol/types.js';

// =============================================================================
// ATOMIC COUNTER TESTS
// =============================================================================

describe('AtomicCounter', () => {
  let counter: AtomicCounter;

  beforeEach(() => {
    counter = new AtomicCounter();
  });

  describe('unique ID generation', () => {
    it('generates unique IDs across 1000 iterations', () => {
      const ids = new Set<string>();

      for (let i = 0; i < 1000; i++) {
        const id = counter.next();
        expect(ids.has(id)).toBe(false);
        ids.add(id);
      }

      expect(ids.size).toBe(1000);
    });

    it('generates IDs with correct prefix', () => {
      const id = counter.next();
      expect(id.startsWith('sub-')).toBe(true);
    });
  });

  describe('monotonically increasing', () => {
    it('generates monotonically increasing IDs', () => {
      const ids: string[] = [];

      for (let i = 0; i < 100; i++) {
        ids.push(counter.next());
      }

      // Parse the base36 number from each ID and verify order
      for (let i = 1; i < ids.length; i++) {
        const prev = parseInt(ids[i - 1].replace('sub-', ''), 36);
        const curr = parseInt(ids[i].replace('sub-', ''), 36);
        expect(curr).toBeGreaterThan(prev);
      }
    });

    it('starts from 0', () => {
      const first = counter.next();
      expect(first).toBe('sub-0');
    });

    it('increments correctly', () => {
      expect(counter.next()).toBe('sub-0');
      expect(counter.next()).toBe('sub-1');
      expect(counter.next()).toBe('sub-2');
    });
  });

  describe('reset', () => {
    it('reset() returns counter to 0', () => {
      // Generate some IDs
      counter.next();
      counter.next();
      counter.next();

      // Reset
      counter.reset();

      // Should start from 0 again
      expect(counter.next()).toBe('sub-0');
    });

    it('reset() accepts custom value', () => {
      counter.reset(100n);
      expect(counter.next()).toBe('sub-2s'); // 100 in base36
    });

    it('current() returns current value without incrementing', () => {
      counter.next();
      counter.next();
      expect(counter.current()).toBe(2n);
      expect(counter.current()).toBe(2n); // Still 2, not incremented
    });
  });

  describe('globalCounter', () => {
    it('globalCounter is an AtomicCounter instance', () => {
      expect(globalCounter).toBeInstanceOf(AtomicCounter);
    });

    it('globalCounter generates unique IDs', () => {
      // Reset to avoid interference from other tests
      globalCounter.reset();
      const id1 = globalCounter.next();
      const id2 = globalCounter.next();
      expect(id1).not.toBe(id2);
    });
  });
});

// =============================================================================
// SUBMISSION QUEUE TESTS
// =============================================================================

describe('SubmissionQueue', () => {
  let queue: SubmissionQueue;

  // Helper to create a test operation
  const createOp = (content: string): Operation => ({
    type: 'user_turn',
    content,
  });

  beforeEach(() => {
    queue = new SubmissionQueue({ maxSize: 10, timeout: 100 });
  });

  describe('submit and take', () => {
    it('submit() and take() work correctly', async () => {
      const op = createOp('test message');
      const submissionId = await queue.submit(op);

      expect(submissionId).toMatch(/^sub-/);

      const submission = await queue.take();
      expect(submission).not.toBeNull();
      expect(submission!.op).toEqual(op);
      expect(submission!.id).toBe(submissionId);
    });

    it('maintains FIFO order', async () => {
      await queue.submit(createOp('first'));
      await queue.submit(createOp('second'));
      await queue.submit(createOp('third'));

      const first = await queue.take();
      const second = await queue.take();
      const third = await queue.take();

      expect((first!.op as { content: string }).content).toBe('first');
      expect((second!.op as { content: string }).content).toBe('second');
      expect((third!.op as { content: string }).content).toBe('third');
    });

    it('stores timestamp in submission', async () => {
      const before = Date.now();
      await queue.submit(createOp('test'));
      const after = Date.now();

      const submission = await queue.take();
      expect(submission!.timestamp).toBeGreaterThanOrEqual(before);
      expect(submission!.timestamp).toBeLessThanOrEqual(after);
    });

    it('stores correlationId when provided', async () => {
      await queue.submit(createOp('test'), 'correlation-123');
      const submission = await queue.take();
      expect(submission!.correlationId).toBe('correlation-123');
    });
  });

  describe('queue size limit', () => {
    it('isFull() returns true after maxSize items', async () => {
      const smallQueue = new SubmissionQueue({ maxSize: 3, timeout: 100 });

      expect(smallQueue.isFull()).toBe(false);

      await smallQueue.submit(createOp('1'));
      await smallQueue.submit(createOp('2'));
      await smallQueue.submit(createOp('3'));

      expect(smallQueue.isFull()).toBe(true);
      expect(smallQueue.size()).toBe(3);
    });

    it('size() returns correct count', async () => {
      expect(queue.size()).toBe(0);

      await queue.submit(createOp('1'));
      expect(queue.size()).toBe(1);

      await queue.submit(createOp('2'));
      expect(queue.size()).toBe(2);

      await queue.take();
      expect(queue.size()).toBe(1);
    });

    it('isEmpty() returns correct value', async () => {
      expect(queue.isEmpty()).toBe(true);

      await queue.submit(createOp('test'));
      expect(queue.isEmpty()).toBe(false);

      await queue.take();
      expect(queue.isEmpty()).toBe(true);
    });
  });

  describe('tryTake', () => {
    it('tryTake() returns null when empty', () => {
      const result = queue.tryTake();
      expect(result).toBeNull();
    });

    it('tryTake() returns item when available', async () => {
      await queue.submit(createOp('test'));

      const result = queue.tryTake();
      expect(result).not.toBeNull();
      expect((result!.op as { content: string }).content).toBe('test');
    });

    it('tryTake() does not block', async () => {
      // Should return immediately
      const start = Date.now();
      queue.tryTake();
      const elapsed = Date.now() - start;

      expect(elapsed).toBeLessThan(10);
    });
  });

  describe('async iterator', () => {
    it('async iterator consumes all items', async () => {
      await queue.submit(createOp('1'));
      await queue.submit(createOp('2'));
      await queue.submit(createOp('3'));

      // Close queue after items are submitted
      queue.close();

      const items: string[] = [];
      for await (const submission of queue) {
        items.push((submission.op as { content: string }).content);
      }

      expect(items).toEqual(['1', '2', '3']);
    });

    it('async iterator stops when queue is closed and empty', async () => {
      await queue.submit(createOp('only'));
      queue.close();

      const items: string[] = [];
      for await (const submission of queue) {
        items.push((submission.op as { content: string }).content);
      }

      expect(items).toEqual(['only']);
    });

    it('async iterator handles immediate close', async () => {
      queue.close();

      const items: string[] = [];
      for await (const submission of queue) {
        items.push((submission.op as { content: string }).content);
      }

      expect(items).toEqual([]);
    });
  });

  describe('backpressure', () => {
    it('submit blocks when queue is full', async () => {
      const smallQueue = new SubmissionQueue({ maxSize: 2, timeout: 1000 });

      // Fill the queue
      await smallQueue.submit(createOp('1'));
      await smallQueue.submit(createOp('2'));

      // This submit should block
      let submitResolved = false;
      const submitPromise = smallQueue.submit(createOp('3')).then(() => {
        submitResolved = true;
      });

      // Give it a moment - should still be blocked
      await new Promise((resolve) => setTimeout(resolve, 10));
      expect(submitResolved).toBe(false);

      // Take an item - should unblock submit
      await smallQueue.take();
      await submitPromise;
      expect(submitResolved).toBe(true);
    });

    it('throws QueueTimeoutError when backpressure times out', async () => {
      const smallQueue = new SubmissionQueue({ maxSize: 1, timeout: 50 });

      await smallQueue.submit(createOp('1'));

      // This should timeout
      await expect(smallQueue.submit(createOp('2'))).rejects.toThrow(
        QueueTimeoutError
      );
    });
  });

  describe('close behavior', () => {
    it('throws QueueClosedError when submitting to closed queue', async () => {
      queue.close();

      await expect(queue.submit(createOp('test'))).rejects.toThrow(
        QueueClosedError
      );
    });

    it('take() returns null on closed empty queue', async () => {
      queue.close();

      const result = await queue.take();
      expect(result).toBeNull();
    });

    it('isClosed() returns correct value', () => {
      expect(queue.isClosed()).toBe(false);
      queue.close();
      expect(queue.isClosed()).toBe(true);
    });

    it('close() can be called multiple times safely', () => {
      queue.close();
      queue.close();
      queue.close();
      expect(queue.isClosed()).toBe(true);
    });

    it('pending take() resolves with null when queue closes', async () => {
      // Start a take that will block
      const takePromise = queue.take();

      // Close the queue
      queue.close();

      // Should resolve with null
      const result = await takePromise;
      expect(result).toBeNull();
    });
  });
});

// =============================================================================
// EVENT QUEUE TESTS
// =============================================================================

describe('EventQueue', () => {
  let eventQueue: EventQueue;

  // Helper to create a test event
  const createMessageEvent = (content: string, done = false): EventAgentMessage => ({
    type: 'agent_message',
    content,
    done,
  });

  const createErrorEvent = (): AgentEvent => ({
    type: 'error',
    code: 'TEST_ERROR',
    message: 'Test error message',
    recoverable: true,
  });

  beforeEach(() => {
    eventQueue = new EventQueue({ maxRecentEvents: 10 });
  });

  describe('emit and subscribe', () => {
    it('emit() notifies subscribers', async () => {
      const received: AgentEvent[] = [];

      eventQueue.subscribe((envelope) => {
        received.push(envelope.event);
      });

      eventQueue.emit('sub-1', createMessageEvent('hello'));

      // Wait for async dispatch
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received).toHaveLength(1);
      expect((received[0] as EventAgentMessage).content).toBe('hello');
    });

    it('emit() includes submissionId in envelope', async () => {
      let capturedSubmissionId: string | undefined;

      eventQueue.subscribe((envelope) => {
        capturedSubmissionId = envelope.submissionId;
      });

      eventQueue.emit('sub-123', createMessageEvent('test'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(capturedSubmissionId).toBe('sub-123');
    });

    it('emit() includes timestamp in envelope', async () => {
      let capturedTimestamp: number | undefined;

      const before = Date.now();
      eventQueue.subscribe((envelope) => {
        capturedTimestamp = envelope.timestamp;
      });

      eventQueue.emit('sub-1', createMessageEvent('test'));

      await new Promise((resolve) => setTimeout(resolve, 10));
      const after = Date.now();

      expect(capturedTimestamp).toBeGreaterThanOrEqual(before);
      expect(capturedTimestamp).toBeLessThanOrEqual(after);
    });

    it('multiple subscribers receive the same event', async () => {
      const received1: AgentEvent[] = [];
      const received2: AgentEvent[] = [];

      eventQueue.subscribe((envelope) => received1.push(envelope.event));
      eventQueue.subscribe((envelope) => received2.push(envelope.event));

      eventQueue.emit('sub-1', createMessageEvent('shared'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received1).toHaveLength(1);
      expect(received2).toHaveLength(1);
    });
  });

  describe('typed listeners', () => {
    it('typed listeners receive only matching event types', async () => {
      const messageEvents: EventAgentMessage[] = [];
      const allEvents: AgentEvent[] = [];

      // Typed listener for agent_message only
      eventQueue.on<EventAgentMessage>('agent_message', (envelope) => {
        messageEvents.push(envelope.event);
      });

      // Global listener for all events
      eventQueue.subscribe((envelope) => {
        allEvents.push(envelope.event);
      });

      // Emit different event types
      eventQueue.emit('sub-1', createMessageEvent('msg1'));
      eventQueue.emit('sub-2', createErrorEvent());
      eventQueue.emit('sub-3', createMessageEvent('msg2'));

      await new Promise((resolve) => setTimeout(resolve, 20));

      // Typed listener should only have messages
      expect(messageEvents).toHaveLength(2);
      expect(messageEvents[0].content).toBe('msg1');
      expect(messageEvents[1].content).toBe('msg2');

      // Global listener should have all events
      expect(allEvents).toHaveLength(3);
    });

    it('on() returns unsubscribe function', async () => {
      const received: EventAgentMessage[] = [];

      const unsubscribe = eventQueue.on<EventAgentMessage>('agent_message', (envelope) => {
        received.push(envelope.event);
      });

      eventQueue.emit('sub-1', createMessageEvent('before'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      unsubscribe();

      eventQueue.emit('sub-2', createMessageEvent('after'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received).toHaveLength(1);
      expect(received[0].content).toBe('before');
    });
  });

  describe('once', () => {
    it('once() resolves with first matching event', async () => {
      const promise = eventQueue.once<EventAgentMessage>('agent_message');

      eventQueue.emit('sub-1', createMessageEvent('first'));
      eventQueue.emit('sub-2', createMessageEvent('second'));

      const result = await promise;

      expect(result.event.content).toBe('first');
      expect(result.submissionId).toBe('sub-1');
    });

    it('once() ignores non-matching events', async () => {
      const promise = eventQueue.once<EventAgentMessage>('agent_message');

      eventQueue.emit('sub-1', createErrorEvent());
      eventQueue.emit('sub-2', createMessageEvent('target'));

      const result = await promise;

      expect(result.event.type).toBe('agent_message');
      expect(result.event.content).toBe('target');
    });

    it('once() with timeout rejects when no event arrives', async () => {
      const promise = eventQueue.once<EventAgentMessage>('agent_message', 50);

      await expect(promise).rejects.toThrow(EventTimeoutError);
    });

    it('once() with timeout resolves if event arrives in time', async () => {
      const promise = eventQueue.once<EventAgentMessage>('agent_message', 1000);

      setTimeout(() => {
        eventQueue.emit('sub-1', createMessageEvent('in time'));
      }, 10);

      const result = await promise;
      expect(result.event.content).toBe('in time');
    });
  });

  describe('getRecentEvents', () => {
    it('getRecentEvents() returns stored events', () => {
      eventQueue.emit('sub-1', createMessageEvent('event1'));
      eventQueue.emit('sub-2', createMessageEvent('event2'));
      eventQueue.emit('sub-3', createMessageEvent('event3'));

      const recent = eventQueue.getRecentEvents();

      expect(recent).toHaveLength(3);
      expect((recent[0].event as EventAgentMessage).content).toBe('event1');
      expect((recent[2].event as EventAgentMessage).content).toBe('event3');
    });

    it('getRecentEvents() respects maxRecentEvents limit', () => {
      const smallQueue = new EventQueue({ maxRecentEvents: 3 });

      for (let i = 0; i < 5; i++) {
        smallQueue.emit(`sub-${i}`, createMessageEvent(`event${i}`));
      }

      const recent = smallQueue.getRecentEvents();

      expect(recent).toHaveLength(3);
      // Should have the last 3 events
      expect((recent[0].event as EventAgentMessage).content).toBe('event2');
      expect((recent[1].event as EventAgentMessage).content).toBe('event3');
      expect((recent[2].event as EventAgentMessage).content).toBe('event4');
    });

    it('getRecentEvents(since) filters by timestamp', async () => {
      eventQueue.emit('sub-1', createMessageEvent('before'));

      // Wait a bit so timestamps differ
      await new Promise((resolve) => setTimeout(resolve, 20));
      const midpoint = Date.now();
      await new Promise((resolve) => setTimeout(resolve, 20));

      eventQueue.emit('sub-2', createMessageEvent('after'));

      const recent = eventQueue.getRecentEvents(midpoint);

      expect(recent).toHaveLength(1);
      expect((recent[0].event as EventAgentMessage).content).toBe('after');
    });

    it('getEventsForSubmission() filters by submissionId', () => {
      eventQueue.emit('sub-1', createMessageEvent('s1-e1'));
      eventQueue.emit('sub-2', createMessageEvent('s2-e1'));
      eventQueue.emit('sub-1', createMessageEvent('s1-e2'));
      eventQueue.emit('sub-2', createMessageEvent('s2-e2'));

      const sub1Events = eventQueue.getEventsForSubmission('sub-1');

      expect(sub1Events).toHaveLength(2);
      expect((sub1Events[0].event as EventAgentMessage).content).toBe('s1-e1');
      expect((sub1Events[1].event as EventAgentMessage).content).toBe('s1-e2');
    });
  });

  describe('unsubscribe', () => {
    it('unsubscribe from global listener works correctly', async () => {
      const received: AgentEvent[] = [];

      const unsubscribe = eventQueue.subscribe((envelope) => {
        received.push(envelope.event);
      });

      eventQueue.emit('sub-1', createMessageEvent('before'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received).toHaveLength(1);

      unsubscribe();

      eventQueue.emit('sub-2', createMessageEvent('after'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received).toHaveLength(1); // Still 1, not 2
    });

    it('unsubscribe from typed listener works correctly', async () => {
      const received: EventAgentMessage[] = [];

      const unsubscribe = eventQueue.on<EventAgentMessage>('agent_message', (envelope) => {
        received.push(envelope.event);
      });

      eventQueue.emit('sub-1', createMessageEvent('before'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      unsubscribe();

      eventQueue.emit('sub-2', createMessageEvent('after'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(received).toHaveLength(1);
    });
  });

  describe('clear and stats', () => {
    it('clear() removes all listeners and recent events', async () => {
      const received: AgentEvent[] = [];

      eventQueue.subscribe((envelope) => received.push(envelope.event));
      eventQueue.emit('sub-1', createMessageEvent('test'));
      eventQueue.emit('sub-2', createMessageEvent('test2'));

      // Wait for events to be processed
      await new Promise((resolve) => setTimeout(resolve, 10));
      expect(received).toHaveLength(2);
      expect(eventQueue.getRecentEvents()).toHaveLength(2);

      // Clear should remove listeners and stored events
      eventQueue.clear();

      // Recent events should now be empty
      expect(eventQueue.getRecentEvents()).toHaveLength(0);

      // New events should not be received by old listeners (they were removed)
      eventQueue.emit('sub-3', createMessageEvent('after clear'));
      await new Promise((resolve) => setTimeout(resolve, 10));

      // Received count should still be 2 (no new events received - listeners cleared)
      expect(received).toHaveLength(2);

      // But new events are still stored in recent events buffer
      expect(eventQueue.getRecentEvents()).toHaveLength(1);
    });

    it('stats() returns correct statistics', () => {
      eventQueue.subscribe(() => {});
      eventQueue.subscribe(() => {});
      eventQueue.on('agent_message', () => {});
      eventQueue.on('error', () => {});
      eventQueue.on('error', () => {});
      eventQueue.emit('sub-1', createMessageEvent('test'));

      const stats = eventQueue.stats();

      expect(stats.globalListeners).toBe(2);
      expect(stats.typedListeners).toEqual({
        agent_message: 1,
        error: 2,
      });
      expect(stats.recentEventsCount).toBe(1);
    });
  });

  describe('error handling', () => {
    it('listener errors do not affect other listeners', async () => {
      const received: string[] = [];

      eventQueue.subscribe(() => {
        throw new Error('Listener error');
      });

      eventQueue.subscribe((envelope) => {
        received.push((envelope.event as EventAgentMessage).content);
      });

      eventQueue.emit('sub-1', createMessageEvent('test'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Second listener should still receive the event
      expect(received).toEqual(['test']);
    });
  });
});
