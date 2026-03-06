/**
 * Bounded async queue for operations from UI to Agent.
 * Implements backpressure - when full, producers wait until space is available.
 */

import type { Operation, Submission, SubmissionId } from '../protocol/types.js';
import { AtomicCounter } from './atomic-counter.js';

/**
 * Configuration for the SubmissionQueue.
 */
export interface SubmissionQueueConfig {
  /** Maximum number of items in the queue (default: 64) */
  maxSize?: number;
  /** Timeout in ms for producers waiting for space (default: 30000) */
  timeout?: number;
}

/**
 * Internal representation of a waiter (producer or consumer).
 */
interface Waiter<T> {
  resolve: (value: T) => void;
  reject: (error: Error) => void;
}

/**
 * Error thrown when a queue operation times out.
 */
export class QueueTimeoutError extends Error {
  constructor(message: string = 'Queue operation timed out') {
    super(message);
    this.name = 'QueueTimeoutError';
  }
}

/**
 * Error thrown when attempting to operate on a closed queue.
 */
export class QueueClosedError extends Error {
  constructor(message: string = 'Queue is closed') {
    super(message);
    this.name = 'QueueClosedError';
  }
}

/**
 * A bounded async queue for operations from UI to Agent.
 *
 * Features:
 * - Bounded capacity with backpressure (producers wait when full)
 * - Async iterator support for consumption
 * - Graceful shutdown via close()
 * - Timeout handling for blocked producers
 */
export class SubmissionQueue {
  private readonly maxSize: number;
  private readonly timeout: number;
  private readonly counter: AtomicCounter;
  private readonly queue: Submission[] = [];
  private readonly producerWaiters: Waiter<void>[] = [];
  private readonly consumerWaiters: Waiter<Submission | null>[] = [];
  private closed = false;

  /**
   * Creates a new SubmissionQueue.
   * @param config - Optional configuration
   */
  constructor(config?: SubmissionQueueConfig) {
    this.maxSize = config?.maxSize ?? 64;
    this.timeout = config?.timeout ?? 30000;
    this.counter = new AtomicCounter();
  }

  /**
   * Submits an operation to the queue.
   * Blocks if the queue is full (backpressure).
   *
   * @param op - The operation to submit
   * @param correlationId - Optional correlation ID for request/response tracking
   * @returns The submission ID
   * @throws QueueClosedError if the queue is closed
   * @throws QueueTimeoutError if waiting for space times out
   */
  async submit(op: Operation, correlationId?: string): Promise<SubmissionId> {
    if (this.closed) {
      throw new QueueClosedError('Cannot submit to a closed queue');
    }

    // Wait for space if queue is full
    if (this.queue.length >= this.maxSize) {
      await this.waitForSpace();
    }

    // Re-check closed status after waiting
    if (this.closed) {
      throw new QueueClosedError('Queue closed while waiting for space');
    }

    const id = this.counter.next();
    const submission: Submission = {
      id,
      op,
      timestamp: Date.now(),
      ...(correlationId !== undefined && { correlationId }),
    };

    this.queue.push(submission);

    // Wake up a waiting consumer if any
    this.wakeConsumer(submission);

    return id;
  }

  /**
   * Takes the next submission from the queue.
   * Blocks if the queue is empty.
   *
   * @returns The next submission, or null if the queue is closed and empty
   */
  async take(): Promise<Submission | null> {
    // Return immediately if there's an item
    if (this.queue.length > 0) {
      const submission = this.queue.shift()!;
      this.wakeProducer();
      return submission;
    }

    // If closed and empty, return null
    if (this.closed) {
      return null;
    }

    // Wait for an item
    return new Promise<Submission | null>((resolve, reject) => {
      this.consumerWaiters.push({ resolve, reject });
    });
  }

  /**
   * Non-blocking version of take().
   * @returns The next submission, or null if the queue is empty
   */
  tryTake(): Submission | null {
    if (this.queue.length === 0) {
      return null;
    }

    const submission = this.queue.shift()!;
    this.wakeProducer();
    return submission;
  }

  /**
   * Returns the current queue size.
   */
  size(): number {
    return this.queue.length;
  }

  /**
   * Returns true if the queue is empty.
   */
  isEmpty(): boolean {
    return this.queue.length === 0;
  }

  /**
   * Returns true if the queue is full.
   */
  isFull(): boolean {
    return this.queue.length >= this.maxSize;
  }

  /**
   * Returns true if the queue is closed.
   */
  isClosed(): boolean {
    return this.closed;
  }

  /**
   * Closes the queue.
   * - Rejects all pending producer waiters
   * - Resolves all pending consumer waiters with null
   * - No more submissions are accepted
   */
  close(): void {
    if (this.closed) {
      return;
    }

    this.closed = true;

    // Reject all waiting producers
    const closedError = new QueueClosedError('Queue was closed');
    for (const waiter of this.producerWaiters) {
      waiter.reject(closedError);
    }
    this.producerWaiters.length = 0;

    // Resolve all waiting consumers with null
    for (const waiter of this.consumerWaiters) {
      waiter.resolve(null);
    }
    this.consumerWaiters.length = 0;
  }

  /**
   * Async iterator for consuming submissions.
   * Yields submissions until the queue is closed and empty.
   */
  async *[Symbol.asyncIterator](): AsyncIterableIterator<Submission> {
    while (true) {
      const submission = await this.take();
      if (submission === null) {
        return;
      }
      yield submission;
    }
  }

  /**
   * Waits for space to become available in the queue.
   * @throws QueueTimeoutError if waiting times out
   * @throws QueueClosedError if queue is closed while waiting
   */
  private waitForSpace(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const waiter: Waiter<void> = { resolve, reject };

      // Set up timeout
      const timeoutId = setTimeout(() => {
        const index = this.producerWaiters.indexOf(waiter);
        if (index !== -1) {
          this.producerWaiters.splice(index, 1);
          reject(new QueueTimeoutError(`Timed out waiting for space after ${this.timeout}ms`));
        }
      }, this.timeout);

      // Wrap resolve to clear timeout
      const originalResolve = waiter.resolve;
      waiter.resolve = (value: void) => {
        clearTimeout(timeoutId);
        originalResolve(value);
      };

      // Wrap reject to clear timeout
      const originalReject = waiter.reject;
      waiter.reject = (error: Error) => {
        clearTimeout(timeoutId);
        originalReject(error);
      };

      this.producerWaiters.push(waiter);
    });
  }

  /**
   * Wakes a waiting producer (called when space becomes available).
   */
  private wakeProducer(): void {
    const waiter = this.producerWaiters.shift();
    if (waiter) {
      waiter.resolve();
    }
  }

  /**
   * Wakes a waiting consumer with a submission.
   * If no consumers are waiting, the submission is already in the queue.
   */
  private wakeConsumer(submission: Submission): void {
    const waiter = this.consumerWaiters.shift();
    if (waiter) {
      // Remove from queue since we're giving it directly to consumer
      const index = this.queue.indexOf(submission);
      if (index !== -1) {
        this.queue.splice(index, 1);
      }
      waiter.resolve(submission);
      // Wake a producer since we freed a slot
      this.wakeProducer();
    }
  }
}
